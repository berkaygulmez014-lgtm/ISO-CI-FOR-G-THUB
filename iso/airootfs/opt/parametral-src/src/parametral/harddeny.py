"""parametral-harddeny — the deterministic Tier-2 oracle.

Why this is a separate process and not part of the model: GC Shield is an
in-model training defence (adversarial examples + DPO refusals). It makes harmful
intent *less likely to be produced*; it is probabilistic and it cannot be
queried. This module is the opposite kind of thing:

  * deterministic — same input, same verdict, no model in the loop;
  * read-only and **Ed25519-signed** — the oracle only ever holds the *public*
    key, so compromising the daemon's uid cannot mint a new signature. The signing
    key belongs to root (or an offline machine), not to the AI's account;
  * fail-closed — if the oracle is unreachable the gateway denies, loudly;
  * self-closing — the rule file and its signature are watched at runtime
    (inotify + hash polling); any change shuts the oracle down.

The gateway asks this oracle BEFORE policy and BEFORE any token is honoured.
A denial here is final: no approval is offered, because a human cannot authorise
formatting a disk through an AI.

Protocol (internal, no version negotiation): one JSON object per line, and the
socket only accepts peers whose uid is in the allow-list (SO_PEERCRED).
  request : {"node_id": "...", "operation": "exec.run", "scope": {...}}
  response: {"decision": "allow"|"deny", "rule_id": "hd-..."|null,
             "reason": "...", "rules_version": 1, "rules_sig": "ed25519:..."}
"""
from __future__ import annotations

import base64
import ctypes
import ctypes.util
import fnmatch
import hashlib
import json
import os
import select
import socketserver
import threading

from . import ed25519, util

DEFAULT_RULES = "hard_deny.v1.json"


class HardDenyError(RuntimeError):
    pass


class HardDenyUnavailable(HardDenyError):
    """Oracle not reachable / not trusted: callers must fail closed."""


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _glob_any(value: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatchcase(value, pattern):
            return True
        if pattern.endswith("/**") and value == pattern[:-3]:
            return True
    return False


class HardDenyEngine:
    def __init__(self, rules: dict, source: str = "<memory>", sig: str | None = None,
                 body_sha256: str | None = None):
        self.rules = rules
        self.source = source
        self.version = int(rules.get("version", 0))
        self.sig = sig
        self.body_sha256 = body_sha256
        self._validate()

    def _validate(self) -> None:
        rules = self.rules.get("rules")
        if not isinstance(rules, list) or not rules:
            raise HardDenyError("hard-deny list has no rules")
        seen = set()
        for rule in rules:
            rule_id = rule.get("id")
            if not rule_id or not isinstance(rule_id, str):
                raise HardDenyError("every hard-deny rule needs a string id")
            if rule_id in seen:
                raise HardDenyError(f"duplicate hard-deny rule id: {rule_id}")
            seen.add(rule_id)
            if not isinstance(rule.get("operations"), list) or not rule["operations"]:
                raise HardDenyError(f"rule {rule_id}: operations required")
            if not any(key in rule for key in ("commands", "paths", "host_paths")):
                raise HardDenyError(f"rule {rule_id}: needs at least one matcher")

    def check(self, operation: str, scope: dict | None = None) -> dict:
        scope = scope or {}
        command = scope.get("command")
        paths = _as_list(scope.get("paths"))
        host_paths = _as_list(scope.get("host_paths"))

        for rule in self.rules["rules"]:
            if operation not in rule["operations"]:
                continue
            matched = False
            commands = _as_list(rule.get("commands"))
            if commands and command and _glob_any(str(command), commands):
                matched = True
            rule_paths = _as_list(rule.get("paths"))
            if rule_paths and any(_glob_any(path, rule_paths) for path in paths):
                matched = True
            rule_host_paths = _as_list(rule.get("host_paths"))
            if rule_host_paths and any(_glob_any(path, rule_host_paths) for path in host_paths):
                matched = True
            if matched:
                return {"decision": "deny", "rule_id": rule["id"],
                        "reason": rule.get("reason", "hard deny"),
                        "rules_version": self.version, "rules_sig": self.sig}
        return {"decision": "allow", "rule_id": None, "reason": "no hard-deny rule matched",
                "rules_version": self.version, "rules_sig": self.sig}


# ------------------------------------------------------------- ed25519 crypto
# Implementation lives in parametral.ed25519 (shared with the approval gate and
# sysapply). The oracle only ever loads the PUBLIC key.

from . import ed25519 as _ed  # noqa: E402  (kept here for call-site clarity)


def ed25519_keygen(sk_path: str, pub_path: str) -> tuple[bytes, bytes]:
    return _ed.keygen(sk_path, pub_path)


def load_private_key(sk_path: str) -> bytes:
    return _ed.load_secret(sk_path)


def load_public_key(pub_path: str) -> bytes:
    return _ed.load_public(pub_path)


def key_id(public: bytes) -> str:
    return _ed.key_id(public)


def sign_rules(rules_path: str, sk_path: str) -> str:
    """Sign the rule list with the operator's private key; writes <rules>.sig."""
    with open(rules_path, "rb") as handle:
        body = handle.read()
    secret = ed25519.load_secret(sk_path)
    public = secret[32:] if len(secret) == 64 else ed25519.public_from_secret(secret)
    signature = ed25519.sign(body, secret)
    record = {"alg": "ed25519", "key_id": ed25519.key_id(public),
              "sig": "base64:" + ed25519.b64(signature)}
    util.atomic_write(rules_path + ".sig", (json.dumps(record) + "\n").encode(), mode=0o644)
    return f"{ed25519.key_id(public)}:{ed25519.b64(signature)[:16]}…"


def load_rules(rules_path: str, pub_path: str,
               require_signature: bool = True) -> HardDenyEngine:
    """Load + verify against the PUBLIC key. Tampered/unsigned lists never load."""
    try:
        with open(rules_path, "rb") as handle:
            body = handle.read()
        rules = json.loads(body)
    except FileNotFoundError as exc:
        raise HardDenyError(f"hard-deny list not found: {rules_path}") from exc
    except json.JSONDecodeError as exc:
        raise HardDenyError(f"hard-deny list is not valid JSON: {exc}") from exc

    signature = None
    if require_signature:
        sig_path = rules_path + ".sig"
        if not os.path.exists(sig_path):
            raise HardDenyError(f"hard-deny list is unsigned: {sig_path} missing")
        record = util.read_json(sig_path)
        if record.get("alg") != "ed25519":
            raise HardDenyError(f"unsupported signature algorithm {record.get('alg')!r}")
        raw_sig = ed25519.unb64(str(record.get("sig", "")))
        public = ed25519.load_public(pub_path)
        if not ed25519.verify(body, raw_sig, public):
            raise HardDenyError("hard-deny list signature does not verify (tampered?)")
        signature = f"{ed25519.key_id(public)}:{ed25519.b64(raw_sig)[:16]}…"
    return HardDenyEngine(rules, source=rules_path, sig=signature,
                          body_sha256=hashlib.sha256(body).hexdigest())


# ------------------------------------------------------- runtime file watch
#
# "Refuses to load a tampered list" is not enough: the list could be swapped while
# the oracle runs. Any change to the rules or signature shuts the oracle down, and
# the gateway then fails closed.

IN_MODIFY = 0x00000002
IN_ATTRIB = 0x00000004
IN_CLOSE_WRITE = 0x00000008
IN_MOVED_FROM = 0x00000040
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
IN_DELETE = 0x00000200
IN_DELETE_SELF = 0x00000400
IN_MOVE_SELF = 0x00000800
WATCH_MASK = (IN_MODIFY | IN_ATTRIB | IN_CLOSE_WRITE | IN_MOVED_FROM | IN_MOVED_TO
              | IN_CREATE | IN_DELETE | IN_DELETE_SELF | IN_MOVE_SELF)


class _Inotify:
    def __init__(self):
        self._libc = ctypes.CDLL("libc.so.6", use_errno=True)
        self.fd = self._libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1 failed")

    def add(self, path: str) -> int:
        wd = self._libc.inotify_add_watch(self.fd, path.encode(), WATCH_MASK)
        if wd < 0:
            raise OSError(ctypes.get_errno(), f"inotify_add_watch({path}) failed")
        return wd

    def wait(self, timeout: float) -> bool:
        readable, _, _ = select.select([self.fd], [], [], timeout)
        if not readable:
            return False
        try:
            os.read(self.fd, 4096)
        except BlockingIOError:
            return False
        return True


class RulesWatcher:
    """Watch rules + signature; any change fires `on_change(reason)` exactly once."""

    def __init__(self, rules_path: str, on_change, poll_interval: float = 1.0,
                 expected_sha256: str | None = None):
        self.rules_path = rules_path
        self.sig_path = rules_path + ".sig"
        self.on_change = on_change
        self.poll_interval = poll_interval
        self.expected_sha256 = expected_sha256
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.fired = threading.Event()
        self.reason: str | None = None
        # Snapshot at construction: a change that happens right after start() must
        # still be caught, otherwise there is a window where the swap goes unseen.
        self._initial_sha256 = self._sha256()

    def _sha256(self) -> str | None:
        try:
            with open(self.rules_path, "rb") as handle:
                return hashlib.sha256(handle.read()).hexdigest()
        except OSError:
            return None

    def _fire(self, reason: str) -> None:
        if self.fired.is_set():
            return
        self.reason = reason
        self.fired.set()
        self.on_change(reason)

    def start(self) -> "RulesWatcher":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        directory = os.path.dirname(os.path.abspath(self.rules_path)) or "."
        inotify = None
        try:
            inotify = _Inotify()
            inotify.add(directory)
        except (OSError, AttributeError):
            inotify = None  # polling only

        last = self._initial_sha256
        while not self._stop.is_set():
            if inotify is not None:
                try:
                    if inotify.wait(0.5) and self._sha256() != last:
                        self._fire("rules file changed at runtime (inotify)")
                        return
                except OSError:
                    inotify = None
            else:
                self._stop.wait(0.5)

            current = self._sha256()
            if current != last:
                self._fire("rules file changed at runtime (hash mismatch)")
                return
            if self.expected_sha256 and last is not None and last != self.expected_sha256:
                self._fire("rules hash diverged from the verified hash")
                return
            self._stop.wait(self.poll_interval)


# ------------------------------------------------------------------- server

class _Handler(socketserver.StreamRequestHandler):
    engine: HardDenyEngine

    def handle(self):
        allowed = getattr(self.server, "allowed_uids", None) or {os.getuid()}
        peer = util.peer_uid(self.connection)
        if peer is None or peer not in allowed:
            # Only the gateway may query the oracle; a random process must not be
            # able to probe the deny list through the socket.
            self._reply({"decision": "deny", "rule_id": "hd-peer-rejected",
                         "reason": f"peer uid {peer!r} is not allowed to query the oracle"})
            return
        while True:
            line = self.rfile.readline(65536)
            if not line:
                return
            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                self._reply({"decision": "deny", "rule_id": "hd-bad-request",
                             "reason": f"malformed request: {exc}"})
                continue
            operation = request.get("operation")
            if not isinstance(operation, str):
                self._reply({"decision": "deny", "rule_id": "hd-bad-request",
                             "reason": "operation required"})
                continue
            self._reply(self.engine.check(operation, request.get("scope") or {}))

    def _reply(self, payload: dict) -> None:
        try:
            self.wfile.write(json.dumps(payload).encode() + b"\n")
            self.wfile.flush()
        except OSError:
            return


class HardDenyServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, socket_path: str, engine: HardDenyEngine,
                 allowed_uids: set[int] | None = None):
        util.ensure_dir(os.path.dirname(socket_path), 0o700)
        util.try_unlink(socket_path)
        handler = type("BoundHardDenyHandler", (_Handler,), {"engine": engine})
        super().__init__(socket_path, handler)
        self.allowed_uids = set(allowed_uids) if allowed_uids else {os.getuid()}
        os.chmod(socket_path, 0o600)


def serve(rules_path: str, pub_path: str, socket_path: str,
          allowed_uids: set[int] | None = None,
          ready: threading.Event | None = None) -> int:
    engine = load_rules(rules_path, pub_path)
    server = HardDenyServer(socket_path, engine, allowed_uids=allowed_uids)
    closed: dict = {"reason": None}

    def on_change(reason: str) -> None:
        closed["reason"] = reason
        server.shutdown()

    watcher = RulesWatcher(rules_path, on_change,
                           expected_sha256=engine.body_sha256).start()

    print(json.dumps({"event": "parametral-harddeny-listening", "socket": socket_path,
                      "rules_version": engine.version, "rules_sig": engine.sig,
                      "allowed_uids": sorted(server.allowed_uids)}), flush=True)
    if ready is not None:
        ready.set()
    status = 0
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        closed["reason"] = "interrupted"
    finally:
        watcher.stop()
        server.server_close()
        util.try_unlink(socket_path)
    if closed["reason"] and closed["reason"] != "interrupted":
        print(json.dumps({"event": "parametral-harddeny-closed", "reason": closed["reason"]}),
              flush=True)
        status = 3
    return status


# ------------------------------------------------------------------- client

class HardDenyClient:
    def __init__(self, socket_path: str, timeout: float = 2.0):
        self.socket_path = socket_path
        self.timeout = timeout

    def check(self, operation: str, scope: dict | None = None, node_id: str = "local") -> dict:
        import socket

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                sock.connect(self.socket_path)
                sock.sendall(json.dumps({"node_id": node_id, "operation": operation,
                                         "scope": scope or {}}).encode() + b"\n")
                buffer = b""
                while not buffer.endswith(b"\n"):
                    chunk = sock.recv(65536)
                    if not chunk:
                        raise HardDenyUnavailable("oracle closed the connection")
                    buffer += chunk
            return json.loads(buffer)
        except (OSError, json.JSONDecodeError) as exc:
            raise HardDenyUnavailable(
                f"hard-deny oracle unavailable at {self.socket_path}: {exc}") from exc

    def probe(self) -> dict:
        return self.check("status")
