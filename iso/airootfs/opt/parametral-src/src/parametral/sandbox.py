"""Sandbox manager: bubblewrap namespaces, seccomp guard, cgroup v2 quotas.

One sandbox = one directory (root + home) + one cgroup + a fixed bwrap profile.
Nothing here ever touches the host filesystem outside `<state>/sandboxes/<id>`.
Network is off unless the profile reserved it *and* a `net.open` token was used.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field

from . import quota as quota_mod
from . import util

GUARD_NAME = "seccomp_guard"
SECCOMP_PROFILE = "blacklist-v1"
PROFILES = ("strict", "net-client", "microvm")
MI = 1024 * 1024
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")

ETC_RO_FILES = ("ld.so.cache", "ld.so.conf", "ld.so.conf.d", "alternatives",
                "localtime", "nsswitch.conf", "ssl", "ca-certificates.conf")


class SandboxError(RuntimeError):
    def __init__(self, code: str, message: str, detail=None):
        super().__init__(message)
        self.code = code
        self.detail = detail


@dataclass
class Limits:
    cpu_cores: float = 1.0
    memory_mb: int = 512
    pids: int = 128
    disk_mb: int = 256

    @classmethod
    def from_dict(cls, data: dict | None, defaults: "Limits" | None = None) -> "Limits":
        base = defaults or cls()
        data = data or {}
        try:
            limits = cls(
                cpu_cores=float(data.get("cpu_cores", base.cpu_cores)),
                memory_mb=int(data.get("memory_mb", base.memory_mb)),
                pids=int(data.get("pids", base.pids)),
                disk_mb=int(data.get("disk_mb", base.disk_mb)),
            )
        except (TypeError, ValueError) as exc:
            raise SandboxError("INVALID_PARAMS", f"limits must be numeric: {exc}") from exc
        if not (0.05 <= limits.cpu_cores <= 64):
            raise SandboxError("INVALID_PARAMS", "limits.cpu_cores out of range")
        if not (16 <= limits.memory_mb <= 65536):
            raise SandboxError("INVALID_PARAMS", "limits.memory_mb out of range")
        if not (4 <= limits.pids <= 4096):
            raise SandboxError("INVALID_PARAMS", "limits.pids out of range")
        if not (1 <= limits.disk_mb <= 1024 * 1024):
            raise SandboxError("INVALID_PARAMS", "limits.disk_mb out of range")
        return limits

    def to_dict(self) -> dict:
        return {"cpu_cores": self.cpu_cores, "memory_mb": self.memory_mb,
                "pids": self.pids, "disk_mb": self.disk_mb}


def resolve_sandbox_uid(current_uid: int | None = None) -> int:
    """The uid a sandbox must run as.

    A root daemon (CI, early images, someone running `sudo parametrald`) must never hand
    the AI a root sandbox. We map to PARAMETRAL_SANDBOX_UID (default 1000) instead; the
    writable trees are chowned to it in create().
    """
    uid = os.getuid() if current_uid is None else current_uid
    if uid != 0:
        return uid
    target = int(os.environ.get("PARAMETRAL_SANDBOX_UID", "1000"))
    if target == 0:
        raise SandboxError("INVALID_PARAMS",
                           "PARAMETRAL_SANDBOX_UID=0 would create a root sandbox")
    return target


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


def _write(path: str, value: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(value)


class SandboxManager:
    def __init__(self, state_root: str, node_id: str = "local",
                 guard_path: str | None = None, defaults: dict | None = None):
        self.node_id = node_id
        self.state_root = os.path.abspath(state_root)
        self.directory = util.ensure_dir(os.path.join(self.state_root, "sandboxes"))
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.guard_path = guard_path or os.path.join(here, "bin", GUARD_NAME)
        self.default_limits = Limits.from_dict(defaults)
        self._lock = threading.Lock()
        self.quota_notes: list[str] = []
        self.snapshots_dir = util.ensure_dir(os.path.join(self.state_root, "snapshots"))
        self.snapshot_notes: list[str] = []
        self.trash_dir = util.ensure_dir(os.path.join(self.state_root, "trash"))
        # A root daemon (CI, early images) must not produce a root sandbox: the sandbox
        # runs as this uid instead, and its writable trees are chowned to it.
        self.sandbox_uid = resolve_sandbox_uid()
        self.btrfs_delete_ok = False
        self.btrfs_available = self._probe_btrfs()

    # --------------------------------------------------------------- helpers

    def _node_short(self) -> str:
        short = re.sub(r"[^a-z0-9]", "", self.node_id.lower())[:3] or "lcl"
        return short

    def _dir(self, sandbox_id: str) -> str:
        if not re.fullmatch(r"sbx_[a-z0-9]{1,6}_[0-9a-f]{12}", sandbox_id or ""):
            raise SandboxError("INVALID_PARAMS", f"bad sandbox id {sandbox_id!r}")
        return os.path.join(self.directory, sandbox_id)

    def _meta_path(self, sandbox_id: str) -> str:
        return os.path.join(self._dir(sandbox_id), "meta.json")

    def _save(self, meta: dict) -> dict:
        util.write_json(self._meta_path(meta["sandbox_id"]), meta, mode=0o600)
        return meta

    def get(self, sandbox_id: str) -> dict:
        path = self._meta_path(sandbox_id)
        if not os.path.exists(path):
            raise SandboxError("NOT_FOUND", f"unknown sandbox {sandbox_id}")
        return util.read_json(path)

    def list(self) -> list[dict]:
        out = []
        for name in sorted(os.listdir(self.directory)):
            meta_path = os.path.join(self.directory, name, "meta.json")
            if os.path.exists(meta_path):
                meta = util.read_json(meta_path)
                out.append({"sandbox_id": meta["sandbox_id"], "name": meta["name"],
                            "state": meta["state"], "profile": meta["profile"],
                            "net": meta["net"], "execs": meta.get("execs", 0),
                            "created_at": meta["created_at"]})
        return out

    # ----------------------------------------------------------------- btrfs

    def _btrfs(self, *args: str) -> subprocess.CompletedProcess:
        if not shutil.which("btrfs"):
            raise SandboxError("SANDBOX_UNAVAILABLE", "btrfs-progs not installed")
        try:
            return subprocess.run(["btrfs", *args], capture_output=True, text=True, timeout=60)
        except subprocess.SubprocessError as exc:
            raise SandboxError("SANDBOX_UNAVAILABLE", f"btrfs failed: {exc}") from exc

    def _btrfs_run(self, *args: str) -> None:
        proc = self._btrfs(*args)
        if proc.returncode != 0:
            raise SandboxError("CONFLICT",
                               f"btrfs {' '.join(args[:2])} failed: "
                               f"{(proc.stderr or proc.stdout).strip()[:200]}")

    def _btrfs_delete(self, path: str, attempts: int = 3) -> bool:
        """Delete a subvolume. Transient failures retry; a hard EPERM flips the flag
        so we stop paying the retry cost on every teardown."""
        for _ in range(attempts):
            proc = self._btrfs("subvolume", "delete", path)
            if proc.returncode == 0:
                return True
            if "Operation not permitted" in (proc.stderr or ""):
                self.btrfs_delete_ok = False
                return False
            time.sleep(0.15)
        return False

    def _probe_btrfs(self) -> bool:
        """Can this user create and snapshot subvolumes here? Probed, not assumed."""
        probe = os.path.join(self.state_root, ".btrfs-probe")
        try:
            self._btrfs_run("subvolume", "create", probe)
            self._btrfs_run("subvolume", "snapshot", probe, probe + "-snap")
        except SandboxError:
            return False
        # Unprivileged delete needs CAP_SYS_ADMIN or `user_subvol_rm_allowed`. We can
        # still snapshot/restore without it (rename + snapshot); only space reclaim
        # needs root, so record the capability instead of pretending it is unavailable.
        self.btrfs_delete_ok = self._btrfs_delete(probe + "-snap")
        if not self.btrfs_delete_ok:
            self.snapshot_notes.append(
                "btrfs delete refused (no CAP_SYS_ADMIN / user_subvol_rm_allowed): "
                "old subvolumes are parked in <state>/trash for root to reclaim")
        self._btrfs_delete(probe)
        return True

    def _make_dir(self, path: str) -> None:
        """Subvolume when possible (so it can be snapshotted), plain dir otherwise."""
        if self.btrfs_available:
            try:
                self._btrfs_run("subvolume", "create", path)
                return
            except SandboxError as exc:
                self.snapshot_notes.append(f"subvolume create failed for {path}: {exc}")
        os.makedirs(path, mode=0o700, exist_ok=True)

    def _remove_tree(self, path: str) -> None:
        """Remove a dir or subvolume; never leave the daemon stuck on EPERM."""
        if not os.path.exists(path):
            return
        if self.btrfs_available and self.btrfs_delete_ok and self._btrfs_delete(path):
            return
        if self.btrfs_available:
            # Unprivileged delete refused: park it in trash (root can reclaim later).
            target = os.path.join(self.trash_dir, f"{os.path.basename(path)}-{int(time.time() * 1000)}")
            try:
                os.rename(path, target)
                self.snapshot_notes.append(f"parked subvolume in trash: {target}")
                return
            except OSError as exc:
                self.snapshot_notes.append(f"could not park {path}: {exc}")
        shutil.rmtree(path, ignore_errors=False)

    # ---------------------------------------------------------------- create

    def create(self, *, name: str, profile: str = "strict", limits: dict | None = None,
               net: bool = False, env: dict | None = None, mounts: list | None = None,
               sandbox_id: str | None = None, nix: bool = False) -> dict:
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise SandboxError("INVALID_PARAMS",
                               "name must match [a-z0-9][a-z0-9._-]{0,62}")
        if profile not in PROFILES:
            raise SandboxError("INVALID_PARAMS", f"profile must be one of {PROFILES}")
        if profile == "microvm":
            raise SandboxError("UNSUPPORTED", "microvm profile is not implemented",
                               {"milestone": "phase-5"})
        if profile == "net-client" and not net:
            net = True  # reserves the netns; still closed until a net.open token is used
        if profile == "strict" and net:
            raise SandboxError("INVALID_PARAMS", "profile 'strict' cannot request net")
        if nix and not os.path.isdir("/nix/store"):
            raise SandboxError("SANDBOX_UNAVAILABLE",
                               "nix requested but this host has no /nix/store "
                               "(install nix first)", {"field": "nix"})

        with self._lock:
            for existing in self.list():
                if existing["name"] == name:
                    raise SandboxError("CONFLICT", f"sandbox name {name!r} already exists")

            effective = Limits.from_dict(limits, self.default_limits)
            sid = sandbox_id or f"sbx_{self._node_short()}_{os.urandom(6).hex()}"
            base = self._dir(sid)
            os.makedirs(base, mode=0o700, exist_ok=False)
            os.makedirs(os.path.join(base, "meta/etc"), mode=0o700, exist_ok=True)
            self._make_dir(os.path.join(base, "root"))
            self._make_dir(os.path.join(base, "home"))

            uid, gid = os.getuid(), os.getgid()
            util.atomic_write(os.path.join(base, "meta/etc/passwd"),
                              f"user:x:{uid}:{gid}:Parametral sandbox:/home/user:/bin/sh\nroot:x:0:0:root:/root:/bin/sh\n".encode(),
                              mode=0o644)
            util.atomic_write(os.path.join(base, "meta/etc/group"),
                              f"user:x:{gid}:\nroot:x:0:\n".encode(), mode=0o644)
            util.atomic_write(os.path.join(base, "meta/etc/hosts"),
                              b"127.0.0.1 localhost\n::1 localhost\n", mode=0o644)
            if net:
                util.atomic_write(os.path.join(base, "meta/etc/resolv.conf"),
                                  b"nameserver 10.0.2.3\n", mode=0o644)

            net_dir = os.path.join(base, "net")
            # AF_UNIX paths are limited to 108 bytes; fall back to a short, private
            # per-sandbox dir when the state tree is nested deeply (tests, containers).
            if len(os.path.join(net_dir, "net_0123456789-65535.sock")) > 100:
                net_dir = os.path.join(tempfile.gettempdir(), f"parametral-net-{sid}")
            os.makedirs(net_dir, mode=0o700, exist_ok=True)
            if os.getuid() == 0:
                for path in (os.path.join(base, "root"), os.path.join(base, "home"),
                             net_dir, os.path.join(base, "meta")):
                    try:
                        os.chown(path, self.sandbox_uid, self.sandbox_uid)
                    except OSError as exc:
                        self.snapshot_notes.append(f"chown failed for {path}: {exc}")
            meta = {
                "sandbox_id": sid,
                "node_id": self.node_id,
                "name": name,
                "profile": profile,
                "state": "created",
                "created_at": util.iso(),
                "net": bool(net),
                "nix": bool(nix),
                "limits": effective.to_dict(),
                "env": {str(k): str(v) for k, v in (env or {}).items()},
                "mounts": mounts or [],
                "execs": 0,
                "root": os.path.join(base, "root"),
                "home": os.path.join(base, "home"),
                "net_dir": net_dir,
            }
            note = None
            if self.btrfs_available:
                note = quota_mod.apply_best_effort(quota_mod.QuotaManager(),
                                                   os.path.join(base, "root"),
                                                   effective.disk_mb)
            meta["quota_note"] = note
            if note:
                self.snapshot_notes.append(note)
            return self._save(meta)

    # --------------------------------------------------------------- destroy

    def destroy(self, sandbox_id: str, purge: bool = True) -> dict:
        meta = self.get(sandbox_id)
        base = self._dir(sandbox_id)
        self._cgroup_kill(sandbox_id)
        self._cgroup_remove(sandbox_id)
        meta["state"] = "destroyed"
        meta["destroyed_at"] = util.iso()
        net_dir = meta.get("net_dir")
        if net_dir and not net_dir.startswith(base):
            shutil.rmtree(net_dir, ignore_errors=True)
        if purge:
            self._remove_tree(base)
            return {"sandbox_id": sandbox_id, "state": "destroyed", "purged": True}
        self._save(meta)
        return {"sandbox_id": sandbox_id, "state": "destroyed", "purged": False}

    # ------------------------------------------------------------- snapshots

    def _btrfs_ready(self) -> None:
        if not self.btrfs_available:
            raise SandboxError("UNSUPPORTED",
                               "snapshots need btrfs; this state dir cannot make subvolumes",
                               {"milestone": "phase-4"})

    def snapshot(self, sandbox_id: str, label: str | None = None,
                 reason: str | None = None) -> dict:
        """Read-only btrfs snapshot of the sandbox (root + home). No root needed."""
        self._btrfs_ready()
        meta = self.get(sandbox_id)
        for name in ("root", "home"):
            path = os.path.join(self._dir(sandbox_id), name)
            if not os.path.isdir(path):
                raise SandboxError("CONFLICT", f"sandbox {sandbox_id} has no {name} to snapshot")
            if not self._is_subvolume(path):
                raise SandboxError("UNSUPPORTED",
                                   f"{path} is not a btrfs subvolume; snapshot impossible",
                                   {"milestone": "phase-4"})

        snapshot_id = "snap_%s_%s" % (time.strftime("%Y%m%dT%H%M%S", time.gmtime()),
                                      os.urandom(3).hex())
        target = os.path.join(self.snapshots_dir, snapshot_id)
        os.makedirs(target, mode=0o700, exist_ok=True)
        created = []
        try:
            for name in ("root", "home"):
                source = os.path.join(self._dir(sandbox_id), name)
                destination = os.path.join(target, name)
                self._btrfs_run("subvolume", "snapshot", "-r", source, destination)
                created.append(destination)
            record = {
                "snapshot_id": snapshot_id,
                "node_id": self.node_id,
                "sandbox_id": sandbox_id,
                "label": label,
                "reason": reason,
                "created_at": util.iso(),
                "kind": "btrfs",
                "paths": {"root": os.path.join(target, "root"),
                          "home": os.path.join(target, "home")},
                "parent": self._latest_snapshot_id(sandbox_id),
            }
            util.write_json(os.path.join(self.snapshots_dir, f"{snapshot_id}.json"), record)
            return record
        except SandboxError:
            for path in created:
                self._btrfs_delete(path)
            raise

    @staticmethod
    def _is_subvolume(path: str) -> bool:
        """btrfs gives every subvolume its own synthetic st_dev (no root needed)."""
        try:
            return os.stat(path).st_dev != os.stat(os.path.dirname(path)).st_dev
        except OSError:
            return False

    def _latest_snapshot_id(self, sandbox_id: str) -> str | None:
        records = [record for record in self.list_snapshots(sandbox_id)]
        return records[0]["snapshot_id"] if records else None

    def list_snapshots(self, sandbox_id: str | None = None) -> list[dict]:
        records = []
        for name in os.listdir(self.snapshots_dir):
            if not name.endswith(".json"):
                continue
            try:
                record = util.read_json(os.path.join(self.snapshots_dir, name))
            except (OSError, ValueError):
                continue
            if sandbox_id and record.get("sandbox_id") != sandbox_id:
                continue
            records.append(record)
        records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return records

    def restore(self, sandbox_id: str, snapshot_id: str, confirm: bool = False) -> dict:
        """Swap the sandbox back to a snapshot. Destructive → confirm:true required."""
        self._btrfs_ready()
        if confirm is not True:
            raise SandboxError("INVALID_PARAMS", "snapshot.restore requires confirm:true")
        record = util.read_json(os.path.join(self.snapshots_dir, f"{snapshot_id}.json"))
        if record.get("sandbox_id") != sandbox_id:
            raise SandboxError("INVALID_PARAMS",
                               f"snapshot {snapshot_id} belongs to "
                               f"{record.get('sandbox_id')}, not {sandbox_id}")
        for name in ("root", "home"):
            if not os.path.isdir(record["paths"][name]):
                raise SandboxError("NOT_FOUND", f"snapshot data for {name} is missing")

        pre_restore = self.snapshot(sandbox_id, label=f"pre-restore-{snapshot_id}",
                                   reason="snapshot.restore safety net")
        self._cgroup_kill(sandbox_id)
        self._cgroup_remove(sandbox_id)

        base = self._dir(sandbox_id)
        stamp = int(time.time() * 1000)
        old_paths = []
        for name in ("root", "home"):
            current = os.path.join(base, name)
            parked = os.path.join(self.trash_dir, f"{sandbox_id}-{name}-{stamp}")
            if os.path.exists(current):
                os.rename(current, parked)
                old_paths.append(parked)
            self._btrfs_run("subvolume", "snapshot", record["paths"][name], current)

        for path in old_paths:
            if not self._btrfs_delete(path):
                self.snapshot_notes.append(f"restore: parked {path} (root must reclaim)")

        meta = self.get(sandbox_id)
        meta["last_restore"] = {"snapshot_id": snapshot_id, "at": util.iso(),
                                "pre_restore_snapshot": pre_restore["snapshot_id"]}
        self._save(meta)
        return {"restored": True, "from": snapshot_id, "sandbox_id": sandbox_id,
                "pre_restore_snapshot": pre_restore["snapshot_id"],
                "reboot_required": False,
                "space_reclaim_needs_root": not self.btrfs_delete_ok}

    # ------------------------------------------------------------------- run

    def _system_env(self, meta: dict, extra_path: list[str] | None = None) -> dict:
        path_parts = list(extra_path or []) + ["/usr/local/bin", "/usr/bin", "/bin"]
        env = {
            "PATH": ":".join(path_parts),
            "HOME": "/home/user",
            "TERM": "dumb",
            "LANG": "C.UTF-8",
            "TMPDIR": "/tmp",
        }
        forbidden = {"PATH", "HOME", "LD_PRELOAD", "LD_LIBRARY_PATH", "TMPDIR"}
        for key, value in meta.get("env", {}).items():
            if key in forbidden or key.startswith("PARAMETRAL_") or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", key):
                continue
            env[key] = value
        return env

    def _bwrap_argv(self, meta: dict, cmd: list[str], cwd: str, env: dict,
                    rlimits: dict) -> list[str]:
        base = self._dir(meta["sandbox_id"])
        # nix runtime: the store is READ-ONLY inside the sandbox; every write goes through
        # the host's nix-daemon socket, which is bind-mounted for exactly that reason.
        if meta.get("nix"):
            if os.path.isdir("/nix/store"):
                argv_nix = ["--ro-bind", "/nix/store", "/nix/store"]
            else:
                argv_nix = []
            daemon_socket = "/nix/var/nix/daemon-socket"
            if os.path.exists(daemon_socket):
                argv_nix += ["--ro-bind", daemon_socket, daemon_socket]
                env["NIX_REMOTE"] = "daemon"
            env.setdefault("NIX_CONFIG", "builders = \nrequire-sigs = true")
            argv_nix_prefix = argv_nix
        else:
            argv_nix_prefix = []
        argv = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session"]
        if os.getuid() == 0:
            argv += ["--uid", str(self.sandbox_uid), "--gid", str(self.sandbox_uid)]
        argv += [
                "--ro-bind", "/usr", "/usr",
                "--symlink", "usr/lib", "/lib",
                "--symlink", "usr/lib64", "/lib64",
                "--symlink", "usr/bin", "/bin",
                "--symlink", "usr/sbin", "/sbin",
                "--tmpfs", "/etc"]

        for name in ("passwd", "group", "hosts", "resolv.conf"):
            candidate = os.path.join(base, "meta/etc", name)
            if os.path.exists(candidate):
                argv += ["--ro-bind", candidate, f"/etc/{name}"]
        for name in ETC_RO_FILES:
            host_path = f"/etc/{name}"
            if os.path.exists(host_path):
                argv += ["--ro-bind-try", host_path, host_path]

        # approved destinations are reachable only through these Unix sockets
        net_dir = meta.get("net_dir")
        if net_dir and os.path.isdir(net_dir):
            argv += ["--ro-bind", net_dir, "/run/net"]
            env.setdefault("PARAMETRAL_NET_DIR", "/run/net")
        argv += argv_nix_prefix
        argv += ["--proc", "/proc", "--dev", "/dev",
                 "--size", str(64 * MI), "--tmpfs", "/tmp",
                 "--bind", meta["root"], "/work",
                 "--bind", meta["home"], "/home/user"]

        for mount in meta.get("mounts", []):
            host_path = mount.get("host_path")
            sandbox_path = mount.get("sandbox_path")
            if not host_path or not sandbox_path:
                raise SandboxError("INVALID_PARAMS", "mounts need host_path and sandbox_path")
            flag = "--ro-bind" if mount.get("mode", "ro") != "rw" else "--bind"
            argv += [flag, host_path, sandbox_path]

        argv += ["--ro-bind", os.path.abspath(self.guard_path), "/run/parametral/guard"]
        argv += ["--chdir", cwd, "--clearenv"]
        for key, value in env.items():
            argv += ["--setenv", key, value]
        argv += ["--setenv", "PARAMETRAL_RLIMIT_AS_BYTES", str(rlimits["as"])]
        argv += ["--setenv", "PARAMETRAL_RLIMIT_CPU_SECONDS", str(rlimits["cpu"])]
        argv += ["--setenv", "PARAMETRAL_RLIMIT_FSIZE_BYTES", str(rlimits["fsize"])]
        argv += ["--", "/run/parametral/guard", *cmd]
        return argv

    def run(self, sandbox_id: str, cmd: list[str], *, cwd: str = "/work",
            env: dict | None = None, timeout_s: int = 30,
            max_output_bytes: int = 65536, extra_path: list[str] | None = None) -> dict:
        meta = self.get(sandbox_id)
        if meta.get("state") != "created":
            raise SandboxError("CONFLICT", f"sandbox {sandbox_id} is {meta.get('state')}")
        if (not isinstance(cmd, list) or not cmd
                or not all(isinstance(part, str) for part in cmd)
                or not cmd[0]):
            # Empty *arguments* are legitimate (`--option builders ""`); an empty
            # argv[0] is not.
            raise SandboxError("INVALID_PARAMS", "cmd must be a non-empty array of strings")
        if not os.path.exists(self.guard_path):
            raise SandboxError("SANDBOX_UNAVAILABLE",
                               f"seccomp guard missing: {self.guard_path} (run `make`)")
        if not os.access("/usr/bin/bwrap", os.X_OK):
            raise SandboxError("SANDBOX_UNAVAILABLE", "bubblewrap (bwrap) not installed")

        safe_cwd = self._validate_path(cwd)
        timeout_s = max(1, min(int(timeout_s), 3600))
        max_output_bytes = max(1024, min(int(max_output_bytes), 4 * MI))
        limits = Limits.from_dict(meta["limits"])

        rlimits = {"as": limits.memory_mb * MI,
                   "cpu": timeout_s + 5,
                   "fsize": limits.disk_mb * MI}
        run_env = self._system_env(meta, extra_path)
        run_env.update({str(k): str(v) for k, v in (env or {}).items()
                        if re.fullmatch(r"[A-Z_][A-Z0-9_]*", str(k))
                        and str(k) not in ("PATH", "HOME", "LD_PRELOAD", "LD_LIBRARY_PATH")})
        argv = self._bwrap_argv(meta, cmd, safe_cwd, run_env, rlimits)

        cgroup_dir, quota_note = self._cgroup_create(meta)
        started = time.monotonic()
        try:
            proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    stdin=subprocess.DEVNULL, close_fds=True,
                                    start_new_session=True,
                                    env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
        except OSError as exc:
            self._cgroup_remove(sandbox_id)
            raise SandboxError("SANDBOX_UNAVAILABLE", f"cannot start bwrap: {exc}",
                               {"errno": exc.errno}) from exc

        if cgroup_dir:
            self._cgroup_adopt(cgroup_dir, proc.pid)

        stdout_box: list[tuple[bytes, bool]] = []
        stderr_box: list[tuple[bytes, bool]] = []

        def drain(pipe, box):
            box.append(self._drain(pipe, max_output_bytes))

        threads = [threading.Thread(target=drain, args=(proc.stdout, stdout_box), daemon=True),
                   threading.Thread(target=drain, args=(proc.stderr, stderr_box), daemon=True)]
        for thread in threads:
            thread.start()

        timed_out = False
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._cgroup_kill(sandbox_id)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=10)
        for pipe in (proc.stdout, proc.stderr):
            try:
                pipe.close()
            except OSError:
                pass
        duration_ms = int((time.monotonic() - started) * 1000)

        stdout, stdout_truncated = stdout_box[0] if stdout_box else (b"", False)
        stderr, stderr_truncated = stderr_box[0] if stderr_box else (b"", False)
        returncode = proc.returncode

        with self._lock:
            meta = self.get(sandbox_id)
            meta["execs"] = int(meta.get("execs", 0)) + 1
            self._save(meta)

        self._cgroup_remove(sandbox_id)
        signaled = returncode is not None and returncode < 0
        return {
            "sandbox_id": sandbox_id,
            "exit_code": 124 if timed_out else (128 - returncode if signaled else returncode),
            "stdout": stdout.decode("utf-8", "replace"),
            "stderr": stderr.decode("utf-8", "replace"),
            "duration_ms": duration_ms,
            "truncated": stdout_truncated or stderr_truncated,
            "timed_out": timed_out,
            "signaled": bool(signaled),
            "seccomp_profile": SECCOMP_PROFILE,
            "quota_backend": "cgroup2" if cgroup_dir else "rlimits",
            "quota_note": quota_note,
        }

    @staticmethod
    def _drain(pipe, cap: int) -> tuple[bytes, bool]:
        chunks: list[bytes] = []
        total = 0
        truncated = False
        while True:
            chunk = pipe.read(65536)
            if not chunk:
                break
            if total < cap:
                keep = chunk[: cap - total]
                chunks.append(keep)
                total += len(keep)
                if len(keep) < len(chunk):
                    truncated = True
            else:
                truncated = True
        return b"".join(chunks), truncated

    # --------------------------------------------------------------- paths

    def _validate_path(self, path: str) -> str:
        """Sandbox-internal absolute path; only /work and /home/user are legal."""
        if not isinstance(path, str) or not path.startswith("/"):
            raise SandboxError("INVALID_PARAMS", f"path must be absolute: {path!r}")
        if "\x00" in path or ".." in path.split("/"):
            raise SandboxError("LIMIT_EXCEEDED", f"path traversal refused: {path!r}",
                               {"severity": "security"})
        normalised = os.path.normpath(path)
        if not (normalised == "/work" or normalised.startswith("/work/")
                or normalised == "/home/user" or normalised.startswith("/home/user/")):
            raise SandboxError("LIMIT_EXCEEDED", f"path outside sandbox scope: {path!r}",
                               {"severity": "security"})
        return normalised

    def host_path(self, meta: dict, sandbox_path: str) -> str:
        normalised = self._validate_path(sandbox_path)
        if normalised == "/work" or normalised.startswith("/work/"):
            relative = normalised[len("/work"):].lstrip("/")
            base, resolved = meta["root"], os.path.join(meta["root"], relative)
        else:
            relative = normalised[len("/home/user"):].lstrip("/")
            base, resolved = meta["home"], os.path.join(meta["home"], relative)
        if not os.path.realpath(resolved).startswith(os.path.realpath(base) + os.sep) \
                and os.path.realpath(resolved) != os.path.realpath(base):
            raise SandboxError("LIMIT_EXCEEDED",
                               f"symlink escape refused: {sandbox_path!r}",
                               {"severity": "security"})
        return resolved

    # -------------------------------------------------------------- cgroups

    def _cgroup_root(self) -> str | None:
        cgroup = _read("/proc/self/cgroup").strip()
        current = None
        for line in cgroup.splitlines():
            parts = line.split(":", 2)
            if len(parts) == 3 and parts[0] == "0":
                current = parts[2]
                break
        if not current:
            return None
        candidate = os.path.join("/sys/fs/cgroup", current.lstrip("/"))
        for _ in range(8):
            parent = os.path.dirname(candidate)
            if parent in ("/sys/fs/cgroup", "/"):
                return None
            controllers = _read(os.path.join(parent, "cgroup.subtree_control")).strip()
            processes = _read(os.path.join(parent, "cgroup.procs")).strip()
            if controllers and not processes and os.access(parent, os.W_OK):
                return parent
            candidate = parent
        return None

    def _cgroup_create(self, meta: dict) -> tuple[str | None, str | None]:
        root = self._cgroup_root()
        if root is None:
            return None, "no delegated cgroup ancestor with controllers (using rlimits only)"
        path = os.path.join(root, f"parametral-{meta['sandbox_id']}")
        limits = Limits.from_dict(meta["limits"])
        try:
            os.makedirs(path, mode=0o755, exist_ok=True)
            _write(os.path.join(path, "memory.max"), str(limits.memory_mb * MI))
            if os.path.exists(os.path.join(path, "memory.swap.max")):
                _write(os.path.join(path, "memory.swap.max"), "0")
            _write(os.path.join(path, "cpu.max"), f"{int(limits.cpu_cores * 100000)} 100000")
            _write(os.path.join(path, "pids.max"), str(limits.pids))
        except OSError as exc:
            self.quota_notes.append(f"cgroup setup failed for {meta['sandbox_id']}: {exc}")
            return None, f"cgroup setup failed ({exc.strerror or exc}); rlimits only"
        return path, None

    def _cgroup_adopt(self, cgroup_dir: str, pid: int) -> None:
        try:
            _write(os.path.join(cgroup_dir, "cgroup.procs"), str(pid))
        except OSError as exc:
            self.quota_notes.append(f"cannot move pid {pid} into cgroup: {exc}")

    def _cgroup_dir(self, sandbox_id: str) -> str | None:
        root = self._cgroup_root()
        if root is None:
            return None
        path = os.path.join(root, f"parametral-{sandbox_id}")
        return path if os.path.isdir(path) else None

    def _cgroup_kill(self, sandbox_id: str) -> None:
        path = self._cgroup_dir(sandbox_id)
        if not path:
            return
        kill_path = os.path.join(path, "cgroup.kill")
        if os.path.exists(kill_path):
            try:
                _write(kill_path, "1")
                return
            except OSError:
                pass
        for pid in _read(os.path.join(path, "cgroup.procs")).split():
            try:
                os.kill(int(pid), 9)
            except (ProcessLookupError, PermissionError, ValueError):
                continue

    def _cgroup_remove(self, sandbox_id: str) -> None:
        path = self._cgroup_dir(sandbox_id)
        if not path:
            return
        for _ in range(10):
            try:
                os.rmdir(path)
                return
            except OSError:
                time.sleep(0.05)

    def usage(self, sandbox_id: str) -> dict:
        path = self._cgroup_dir(sandbox_id)
        if not path:
            return {"available": False}
        usage = {"available": True}
        for line in _read(os.path.join(path, "cpu.stat")).splitlines():
            if line.startswith("usage_usec"):
                usage["cpu_ns"] = int(line.split()[1]) * 1000
        for key, filename in (("memory_peak_bytes", "memory.peak"),
                              ("memory_current_bytes", "memory.current"),
                              ("pids_current", "pids.current")):
            raw = _read(os.path.join(path, filename)).strip()
            if raw and raw != "max":
                usage[key] = int(raw)
        return usage
