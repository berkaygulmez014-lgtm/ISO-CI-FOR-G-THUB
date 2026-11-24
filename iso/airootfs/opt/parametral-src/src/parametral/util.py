"""Shared helpers: paths, canonical JSON, hashing, time, atomic writes.

No third-party dependencies: the OS layer must start on a minimal Debian with
nothing but python3-stdlib, and it must be auditable by reading it.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    dt = dt or now()
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def iso_seconds(dt: datetime | None = None) -> str:
    dt = dt or now()
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def in_seconds(seconds: float) -> str:
    return iso(now() + timedelta(seconds=float(seconds)))


def canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def sha256_tag(data) -> str:
    return "sha256:" + sha256_hex(data)


# ---------------------------------------------------------------- filesystem

def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value else default


def state_dir() -> str:
    """Persistent state: sandboxes, audit, tokens, approvals, snapshots."""
    return os.path.abspath(_env("PARAMETRAL_STATE", os.path.expanduser("~/.local/state/parametral")))


def runtime_dir() -> str:
    """Sockets, pids, ephemeral handshake material."""
    default = os.path.join(_env("XDG_RUNTIME_DIR", "/tmp"), "parametral")
    return os.path.abspath(_env("PARAMETRAL_RUNTIME", default))


def socket_path() -> str:
    """Where the control socket is.

    Order: explicit PARAMETRAL_SOCKET, then the per-user socket if it exists (tests, per-user
    daemons), then the system gateway at /run/parametral/control.sock. Without that last step
    every CLI invocation from a desktop session fails with "connection refused" while a system
    daemon is perfectly healthy — the socket simply lives outside XDG_RUNTIME_DIR.
    """
    explicit = os.environ.get("PARAMETRAL_SOCKET")
    if explicit:
        return os.path.abspath(explicit)

    per_user = os.path.abspath(os.path.join(runtime_dir(), "v1", "control.sock"))
    if os.path.exists(per_user):
        return per_user

    system = "/run/parametral/control.sock"
    if os.path.exists(system):
        return system

    return per_user


def policy_path() -> str:
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "policy", "policy.v1.json")
    return os.path.abspath(_env("PARAMETRAL_POLICY", default))


def ensure_dir(path: str, mode: int = 0o700) -> str:
    os.makedirs(path, mode=mode, exist_ok=True)
    return path


def atomic_write(path: str, data: bytes, mode: int = 0o600) -> None:
    """Write-then-rename, fsync both file and directory. Partial writes never visible."""
    directory = os.path.dirname(path) or "."
    ensure_dir(directory, 0o700)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(directory, os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: str):
    with open(path, "rb") as handle:
        return json.load(handle)


def write_json(path: str, obj, mode: int = 0o600) -> None:
    atomic_write(path, json.dumps(obj, indent=2, sort_keys=True).encode("utf-8") + b"\n", mode)


def try_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def append_only_hint(path: str) -> str | None:
    """Best-effort `chattr +a`. Returns a note when the kernel/fs refuses.

    We never claim this as a guarantee: it needs CAP_LINUX_IMMUTABLE (root) and
    even then the flag is removable. The real integrity story is the hash chain
    in audit.py plus, from phase 5, an off-host anchor.
    """
    try:
        import subprocess

        proc = subprocess.run(["chattr", "+a", path], capture_output=True, text=True, timeout=10)
        if proc.returncode == 0:
            return None
        return (proc.stderr or proc.stdout).strip()[:200] or "chattr failed"
    except FileNotFoundError:
        return "chattr not installed"
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"


def peer_uid(sock) -> int | None:
    """Effective uid of the peer on a connected AF_UNIX socket (SO_PEERCRED)."""
    try:
        creds = sock.getsockopt(1, 17, 12)  # SOL_SOCKET, SO_PEERCRED, struct ucred
    except OSError as exc:
        if exc.errno in (errno.ENOPROTOOPT, errno.EINVAL):
            return None
        raise
    import struct

    _pid, uid, _gid = struct.unpack("3i", creds)
    return uid
