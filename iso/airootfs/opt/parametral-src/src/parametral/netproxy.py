"""Per-app network permission without giving the sandbox a network stack.

Design: the sandbox keeps `--unshare-net` (no interfaces, no DNS, connect() fails). When the
user approves `net.open` for an app, the gateway starts a **Unix-socket proxy** inside the
sandbox's filesystem view. The app connects to `/run/net/<grant>.sock`; the proxy — which
runs on the host side, outside the namespace — opens the TCP connection *only* to the
allow-listed host:port pairs, and closes everything else.

Why this shape: enforcing a destination allowlist needs no CAP_NET_ADMIN, no veth pair, no
nftables writes from the gateway, and it cannot be bypassed by the app (it has no route to
anywhere else). The nftables rules are a second, kernel-side belt for the target image; this
proxy is the layer that actually enforces the allowlist today.

Every connection attempt is recorded through `on_event`, so `net.open` grants end up in the
audit log with the destination that was actually used.
"""
from __future__ import annotations

import os
import secrets
import socket
import socketserver
import threading
import time

from . import util

MAX_GRANTS = 32
MAX_CONNECTIONS = 64
BUFFER = 65536


class NetGrantError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _normalise_hosts(hosts) -> list[tuple[str, int]]:
    if not isinstance(hosts, list) or not hosts:
        raise NetGrantError("INVALID_PARAMS", "hosts must be a non-empty list of {host, port}")
    out = []
    for entry in hosts:
        if not isinstance(entry, dict):
            raise NetGrantError("INVALID_PARAMS", "each host entry must be an object")
        host = entry.get("host")
        port = entry.get("port")
        if not isinstance(host, str) or not host or len(host) > 253:
            raise NetGrantError("INVALID_PARAMS", f"bad host {host!r}")
        if any(char in host for char in " /\t\n"):
            raise NetGrantError("INVALID_PARAMS", f"bad host {host!r}")
        if not isinstance(port, int) or not (1 <= port <= 65535):
            raise NetGrantError("INVALID_PARAMS", f"bad port {port!r} for {host}")
        out.append((host, port))
    return out


class _ProxyHandler(socketserver.BaseRequestHandler):
    grant: "Grant"

    def handle(self):
        destination = self.server.destination          # type: ignore[attr-defined]
        grant = self.server.grant                      # type: ignore[attr-defined]
        try:
            upstream = socket.create_connection(destination, timeout=10)
        except OSError as exc:
            grant.report("connect_failed", destination, str(exc))
            return
        grant.report("connect", destination)
        grant.open_connection()
        try:
            self._pump(self.request, upstream)
        finally:
            grant.close_connection()
            try:
                upstream.close()
            except OSError:
                pass

    @staticmethod
    def _pump(a: socket.socket, b: socket.socket) -> None:
        """Bidirectional copy with two threads and hard shutdown on either side."""
        def copy(src, dst):
            try:
                while True:
                    chunk = src.recv(BUFFER)
                    if not chunk:
                        break
                    dst.sendall(chunk)
            except OSError:
                pass
            finally:
                for sock in (src, dst):
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass

        thread = threading.Thread(target=copy, args=(b, a), daemon=True)
        thread.start()
        copy(a, b)
        thread.join(timeout=10)


class _UnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, path: str, grant: "Grant", destination: tuple[str, int]):
        util.try_unlink(path)
        super().__init__(path, _ProxyHandler)
        self.grant = grant
        self.destination = destination
        # The dir is only reachable inside the sandbox (host-side parent is 0750 root:parametral)
        # and the allow-list is enforced by the proxy, so the socket itself is 0666.
        os.chmod(path, 0o666)


class Grant:
    """One approved destination list for one sandbox, with a TTL."""

    def __init__(self, sandbox_id: str, hosts, ttl_s: int, on_event=None):
        self.grant_id = "net_" + secrets.token_hex(5)
        self.sandbox_id = sandbox_id
        self.hosts = _normalise_hosts(hosts)
        self.expires_at = time.monotonic() + max(1, min(int(ttl_s), 3600))
        self.on_event = on_event
        self.created_at = util.iso()
        self.socket_path: str | None = None
        self._servers: list[tuple[_UnixServer, str]] = []
        self._threads: list[threading.Thread] = []
        self._open_connections = 0
        self._lock = threading.Lock()
        self._closed = False

    # ------------------------------------------------------------- lifecycle

    def start(self, directory: str) -> str:
        """Bind one Unix socket per allowed destination inside `directory`."""
        util.ensure_dir(directory, 0o755)
        for host, port in self.hosts:
            name = f"{self.grant_id}-{port}.sock"
            path = os.path.join(directory, name)
            server = _UnixServer(path, self, (host, int(port)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self._servers.append((server, path))
            self._threads.append(thread)
            self.socket_path = path
        self.report("grant_created", None, f"{len(self.hosts)} destination(s)")
        return self.socket_path or ""

    def stop(self) -> None:
        if self._closed:
            return
        self._closed = True
        for server, path in self._servers:
            server.shutdown()
            server.server_close()
            util.try_unlink(path)
        self.report("grant_closed", None, "ttl expired or revoked")

    @property
    def closed(self) -> bool:
        return self._closed or time.monotonic() > self.expires_at

    def allows(self, host: str, port: int) -> bool:
        return (host, int(port)) in self.hosts

    # ------------------------------------------------------------ accounting

    def report(self, event: str, destination, detail: str = "") -> None:
        if self.on_event is None:
            return
        try:
            self.on_event({"event": event, "grant_id": self.grant_id,
                           "sandbox_id": self.sandbox_id,
                           "destination": f"{destination[0]}:{destination[1]}"
                           if isinstance(destination, tuple) else None,
                           "detail": detail[:300], "ts": util.iso()})
        except Exception as exc:  # never let logging break a grant
            self.on_event({"event": "grant_log_error", "grant_id": self.grant_id,
                           "detail": f"{type(exc).__name__}: {exc}", "ts": util.iso()})

    def open_connection(self) -> None:
        with self._lock:
            self._open_connections += 1
            if self._open_connections > MAX_CONNECTIONS:
                self.report("connection_limit", None, str(self._open_connections))

    def close_connection(self) -> None:
        with self._lock:
            self._open_connections = max(0, self._open_connections - 1)


class GrantRegistry:
    """Keeps the grants of every sandbox; sweeps expired ones."""

    def __init__(self, on_event=None):
        self.on_event = on_event
        self._grants: dict[str, Grant] = {}
        self._lock = threading.Lock()

    def open(self, sandbox_id: str, net_dir: str, hosts, ttl_s: int) -> Grant:
        with self._lock:
            if len(self._grants) >= MAX_GRANTS:
                raise NetGrantError("LIMIT_EXCEEDED", "too many open net grants")
            grant = Grant(sandbox_id, hosts, ttl_s, self.on_event)
            grant.start(net_dir)
            self._grants[grant.grant_id] = grant
            return grant

    def close(self, grant_id: str) -> None:
        with self._lock:
            grant = self._grants.pop(grant_id, None)
        if grant is None:
            raise NetGrantError("NOT_FOUND", f"unknown grant {grant_id}")
        grant.stop()

    def for_sandbox(self, sandbox_id: str) -> list[Grant]:
        with self._lock:
            return [grant for grant in self._grants.values()
                    if grant.sandbox_id == sandbox_id and not grant.closed]

    def list(self) -> list[dict]:
        with self._lock:
            return [{"grant_id": grant.grant_id, "sandbox_id": grant.sandbox_id,
                     "hosts": [{"host": host, "port": port} for host, port in grant.hosts],
                     "created_at": grant.created_at,
                     "expires_in_s": max(0, int(grant.expires_at - time.monotonic()))}
                    for grant in self._grants.values() if not grant.closed]

    def sweep(self) -> int:
        with self._lock:
            expired = [gid for gid, grant in self._grants.items() if grant.closed]
            grants = [self._grants.pop(gid) for gid in expired]
        for grant in grants:
            grant.stop()
        return len(grants)
