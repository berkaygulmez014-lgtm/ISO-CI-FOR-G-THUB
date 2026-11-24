"""Per-sandbox disk quota through btrfs qgroups.

`RLIMIT_FSIZE` caps a single file; a sandbox that writes 10.000 small files still eats the
disk. The real answer is a qgroup limit on the sandbox's subvolume, which needs root.

This module is the *command layer*: it is deliberately dumb (build argv, run, parse) so the
root helper and the gateway agree on exactly what "limit this sandbox to N MiB" means. On a
host without qgroup support it reports why instead of pretending the limit exists.
"""
from __future__ import annotations

import os
import subprocess

from . import util

MI = 1024 * 1024


class QuotaError(RuntimeError):
    def __init__(self, code: str, message: str, detail: dict | None = None):
        super().__init__(message)
        self.code = code
        self.detail = detail or {}


class QuotaManager:
    def __init__(self, btrfs_bin: str | None = None, dry_run: bool = False):
        self.btrfs = btrfs_bin or os.environ.get("PARAMETRAL_BTRFS", "btrfs")
        self.dry_run = dry_run

    # ------------------------------------------------------------- commands

    def argv_enable(self, mountpoint: str = "/") -> list[str]:
        return [self.btrfs, "quota", "enable", mountpoint]

    def argv_limit(self, subvol_path: str, size_mb: int, qgroup_id: str | None = None) -> list[str]:
        if not isinstance(size_mb, int) or size_mb <= 0:
            raise QuotaError("INVALID_PARAMS", f"bad quota size {size_mb!r}")
        return [self.btrfs, "qgroup", "limit", f"{size_mb}M", subvol_path]

    def argv_show(self, subvol_path: str) -> list[str]:
        return [self.btrfs, "qgroup", "show", subvol_path]

    # ---------------------------------------------------------------- apply

    def _run(self, argv: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
        if self.dry_run:
            print("DRY", " ".join(argv))
            return subprocess.CompletedProcess(argv, 0, "", "")
        try:
            return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            raise QuotaError("QUOTA_FAILED", f"cannot run {argv[0]}: {exc}") from exc

    def enable(self, mountpoint: str = "/") -> dict:
        proc = self._run(self.argv_enable(mountpoint))
        if proc.returncode != 0:
            raise QuotaError("QUOTA_UNAVAILABLE",
                             f"quota enable failed: {(proc.stderr or proc.stdout).strip()[:200]}",
                             {"argv": self.argv_enable(mountpoint)})
        return {"enabled": True, "mountpoint": mountpoint}

    def limit(self, subvol_path: str, size_mb: int) -> dict:
        argv = self.argv_limit(subvol_path, size_mb)
        if not self.dry_run and not os.path.isdir(subvol_path):
            raise QuotaError("INVALID_PARAMS", f"not a subvolume path: {subvol_path}")
        proc = self._run(argv)
        if proc.returncode != 0:
            raise QuotaError("QUOTA_UNAVAILABLE",
                             f"qgroup limit failed: {(proc.stderr or proc.stdout).strip()[:200]}",
                             {"argv": argv})
        return {"limited": True, "path": subvol_path, "size_mb": size_mb}

    def usage(self, subvol_path: str) -> dict:
        proc = self._run(self.argv_show(subvol_path))
        if proc.returncode != 0:
            raise QuotaError("QUOTA_UNAVAILABLE",
                             f"qgroup show failed: {(proc.stderr or proc.stdout).strip()[:200]}")
        return {"raw": proc.stdout.strip()[:2000], "path": subvol_path}


def apply_best_effort(manager: QuotaManager, subvol_path: str, size_mb: int) -> str | None:
    """Try to apply a quota; return a note when it could not be applied.

    The caller records the note (and the audit log says the limit is advisory), because a
    silent "quotas are on" would be worse than no quota at all.
    """
    try:
        manager.limit(subvol_path, size_mb)
        return None
    except QuotaError as exc:
        return f"qgroup limit not applied: {exc}"
