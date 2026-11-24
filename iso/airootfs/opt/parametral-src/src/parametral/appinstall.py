"""app.install — the "install this" pipeline.

Shape of the thing the AI calls:

    manifest v1 (validated) → pre-install snapshot → sandboxed install attempt
    → verify (real command, real exit code) → retry (max 3) → honest report
    → rollback path (nix generation rollback or snapshot restore)

Hard rules baked into the code, not into a document:

  * no manifest, no verify command → refuse (an install that nobody can check is a guess);
  * the sandbox never gets write access to /nix/store: installs go through the host's
    nix-daemon socket, which is the component allowed to write there;
  * cache-only by default (`builders ''`, signed substituters) so a "cache miss" cannot
    silently become "compile arbitrary code from the network";
  * every attempt is recorded separately with the real stderr tail — a failure is never
    flattened into "install failed";
  * output is capped, so a chatty build cannot exhaust the daemon's memory.
"""
from __future__ import annotations

import os
import re
import secrets
import time

from . import util
from .sandbox import SandboxError, SandboxManager

MAX_ATTEMPTS = 3
INSTALL_TIMEOUT_S = 900
VERIFY_TIMEOUT_S = 120
STDERR_TAIL = 4096

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._+-]{0,63}$")
FLAKE_REF_RE = re.compile(r"^(nixpkgs|github:[A-Za-z0-9_.-]{1,39}/[A-Za-z0-9_.-]{1,39})"
                          r"#[A-Za-z0-9_.+-]{1,64}$")
LOCK_RE = re.compile(r"^(sha256-[A-Za-z0-9+/=]{16,64}|[0-9a-f]{64})$")
SOURCES = ("nix", "artifact")          # artifact is declared, not implemented (phase 2b)
VERIFY_TIMEOUT_MAX_S = 600


class ManifestError(RuntimeError):
    def __init__(self, code: str, message: str, detail=None):
        super().__init__(message)
        self.code = code
        self.detail = detail or {}


class Installer:
    """Runs installs inside an existing sandbox. No host writes, no root."""

    def __init__(self, sandboxes: SandboxManager, nix_bin: str = "nix",
                 state_root: str | None = None, max_attempts: int = MAX_ATTEMPTS):
        self.sandboxes = sandboxes
        self.nix_bin = nix_bin or os.environ.get("PARAMETRAL_NIX_BIN", "nix")
        self.state_root = state_root or sandboxes.state_root
        self.records_dir = util.ensure_dir(os.path.join(self.state_root, "apps"))
        self.max_attempts = max(1, min(int(max_attempts), MAX_ATTEMPTS))

    # ------------------------------------------------------------- manifest

    @staticmethod
    def validate_manifest(manifest: dict) -> dict:
        if not isinstance(manifest, dict):
            raise ManifestError("INVALID_PARAMS", "manifest must be an object")
        name = manifest.get("name")
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise ManifestError("INVALID_PARAMS",
                                "manifest.name must match [a-z0-9][a-z0-9._+-]{0,63}",
                                {"field": "name"})

        source = manifest.get("source", "nix")
        if source not in SOURCES:
            raise ManifestError("INVALID_PARAMS", f"manifest.source must be one of {SOURCES}",
                                {"field": "source"})
        if source == "artifact":
            raise ManifestError("UNSUPPORTED",
                                "artifact installs are not implemented yet; use source:'nix'",
                                {"milestone": "phase-2b", "field": "source"})

        flake_ref = manifest.get("flake_ref")
        if not isinstance(flake_ref, str) or not FLAKE_REF_RE.match(flake_ref):
            raise ManifestError("INVALID_PARAMS",
                                "manifest.flake_ref must look like nixpkgs#ripgrep",
                                {"field": "flake_ref"})

        versions = manifest.get("version")
        if versions is not None and not isinstance(versions, str):
            raise ManifestError("INVALID_PARAMS", "manifest.version must be a string",
                                {"field": "version"})

        flake_lock = manifest.get("flake_lock")
        if flake_lock is not None and (not isinstance(flake_lock, str)
                                       or not LOCK_RE.match(flake_lock)):
            raise ManifestError("INVALID_PARAMS",
                                "manifest.flake_lock must be the pinned hash "
                                "(sha256-… or 64 hex chars)",
                                {"field": "flake_lock"})

        verify = manifest.get("verify")
        if not isinstance(verify, dict):
            raise ManifestError("INVALID_PARAMS",
                                "manifest.verify is mandatory: an install nobody can check "
                                "is not an install", {"field": "verify"})
        cmd = verify.get("cmd")
        if not isinstance(cmd, list) or not cmd or not all(isinstance(part, str) and part
                                                          for part in cmd):
            raise ManifestError("INVALID_PARAMS",
                                "manifest.verify.cmd must be a non-empty argv array",
                                {"field": "verify.cmd"})
        expect_exit = verify.get("expect_exit", 0)
        if not isinstance(expect_exit, int):
            raise ManifestError("INVALID_PARAMS", "verify.expect_exit must be an integer",
                                {"field": "verify.expect_exit"})
        contains = verify.get("expect_stdout_contains")
        if contains is not None and not isinstance(contains, str):
            raise ManifestError("INVALID_PARAMS",
                                "verify.expect_stdout_contains must be a string",
                                {"field": "verify.expect_stdout_contains"})

        permissions = manifest.get("permissions") or {}
        if not isinstance(permissions, dict):
            raise ManifestError("INVALID_PARAMS", "manifest.permissions must be an object",
                                {"field": "permissions"})
        network = permissions.get("network") or []
        if not isinstance(network, list) or any(not isinstance(entry, str) for entry in network):
            raise ManifestError("INVALID_PARAMS",
                                "permissions.network must be a list of 'host:port'",
                                {"field": "permissions.network"})
        write_dirs = permissions.get("write_dirs") or []
        if not isinstance(write_dirs, list) or any(
                not isinstance(entry, str) or not entry.startswith("/work")
                for entry in write_dirs):
            raise ManifestError("INVALID_PARAMS",
                                "permissions.write_dirs entries must be absolute paths "
                                "inside /work", {"field": "permissions.write_dirs"})
        ipc = permissions.get("ipc") or []
        if not isinstance(ipc, list) or any(not isinstance(entry, str) for entry in ipc):
            raise ManifestError("INVALID_PARAMS", "permissions.ipc must be a list of sandbox ids",
                                {"field": "permissions.ipc"})

        return {"name": name, "version": versions, "source": source,
                "flake_ref": flake_ref, "flake_lock": flake_lock,
                "verify": {"cmd": list(cmd), "expect_exit": expect_exit,
                           "expect_stdout_contains": contains},
                "permissions": {"network": list(network), "write_dirs": list(write_dirs),
                                "ipc": list(ipc)}}

    # ---------------------------------------------------------------- paths

    @staticmethod
    def profile_dir() -> str:
        return "/work/.nix-profile"

    def _nix(self, *args: str) -> list[str]:
        """Cache-only, signature-required nix invocation (inside the sandbox)."""
        return [self.nix_bin, *args,
                "--option", "builders", "",
                "--option", "substituters", "https://cache.nixos.org",
                "--option", "require-sigs", "true"]

    # -------------------------------------------------------------- actions

    def install(self, sandbox_id: str, manifest: dict, attempt_limit: int | None = None,
                snapshot: bool = True) -> dict:
        spec = self.validate_manifest(manifest)
        attempts_allowed = self.max_attempts
        if attempt_limit is not None:
            attempts_allowed = max(1, min(int(attempt_limit), MAX_ATTEMPTS))
        self.sandboxes.get(sandbox_id)

        started = time.monotonic()
        snapshot_id = None
        if snapshot:
            try:
                snapshot_id = self.sandboxes.snapshot(
                    sandbox_id, label=f"pre-install-{spec['name']}",
                    reason="app.install")["snapshot_id"]
            except SandboxError as exc:
                # No snapshot on a non-btrfs state dir is acceptable and reported;
                # a snapshot failure that hides itself would not be.
                snapshot_id = None
                if exc.code not in ("UNSUPPORTED", "SANDBOX_UNAVAILABLE"):
                    raise

        app_id = "app_" + secrets.token_hex(4)
        failures: list[dict] = []
        state = "failed"
        verify_result: dict = {}
        install_result: dict = {}

        for attempt in range(1, attempts_allowed + 1):
            install_result = self.sandboxes.run(
                sandbox_id,
                self._nix("profile", "install", "--profile", self.profile_dir(),
                          spec["flake_ref"]),
                timeout_s=INSTALL_TIMEOUT_S, max_output_bytes=256 * 1024,
                extra_path=[f"{self.profile_dir()}/bin"])
            if install_result["exit_code"] != 0:
                failures.append(self._failure(attempt, "install", install_result))
                continue

            verify_result = self.verify(sandbox_id, spec)
            if verify_result["passed"]:
                state = "installed"
                break
            failures.append(self._failure(attempt, "verify", verify_result, verify=True))

        record = {
            "app_id": app_id,
            "sandbox_id": sandbox_id,
            "name": spec["name"],
            "version": spec["version"],
            "source": spec["source"],
            "flake_ref": spec["flake_ref"],
            "flake_lock": spec["flake_lock"],
            "state": state,
            "attempts": len(failures) if state == "failed" else len(failures) + 1,
            "verify": verify_result,
            "snapshot_id": snapshot_id,
            "permissions": spec["permissions"],
            "duration_ms": int((time.monotonic() - started) * 1000),
            "finished_at": util.iso(),
            "failures": failures,
            "diagnosis": self._diagnose(failures) if state == "failed" else None,
        }
        util.write_json(os.path.join(self.records_dir, f"{app_id}.json"), record)
        return record

    def verify(self, sandbox_id: str, manifest: dict) -> dict:
        """Verify an installed app. Accepts a raw manifest or an already-validated spec."""
        if isinstance(manifest.get("verify"), dict) and "permissions" in manifest:
            spec = manifest
        else:
            spec = self.validate_manifest(manifest)
        verify = spec["verify"]
        result = self.sandboxes.run(
            sandbox_id, verify["cmd"], timeout_s=min(VERIFY_TIMEOUT_S, VERIFY_TIMEOUT_MAX_S),
            max_output_bytes=64 * 1024, extra_path=[f"{self.profile_dir()}/bin"])
        passed = result["exit_code"] == verify["expect_exit"]
        if passed and verify["expect_stdout_contains"]:
            passed = verify["expect_stdout_contains"] in result["stdout"]
        return {"passed": passed, "exit_code": result["exit_code"],
                "stdout_tail": result["stdout"][-STDERR_TAIL:],
                "stderr_tail": result["stderr"][-STDERR_TAIL:],
                "expected_exit": verify["expect_exit"],
                "stdout_contains": verify["expect_stdout_contains"],
                "duration_ms": result["duration_ms"]}

    def remove(self, sandbox_id: str, manifest: dict) -> dict:
        spec = self.validate_manifest(manifest)
        result = self.sandboxes.run(
            sandbox_id,
            self._nix("profile", "remove", "--profile", self.profile_dir(), spec["name"]),
            timeout_s=300, max_output_bytes=64 * 1024,
            extra_path=[f"{self.profile_dir()}/bin"])
        return {"state": "removed" if result["exit_code"] == 0 else "failed",
                "name": spec["name"], "exit_code": result["exit_code"],
                "stdout_tail": result["stdout"][-STDERR_TAIL:],
                "stderr_tail": result["stderr"][-STDERR_TAIL:]}

    def rollback(self, sandbox_id: str) -> dict:
        result = self.sandboxes.run(
            sandbox_id,
            self._nix("profile", "rollback", "--profile", self.profile_dir()),
            timeout_s=300, max_output_bytes=64 * 1024,
            extra_path=[f"{self.profile_dir()}/bin"])
        return {"state": "rolled_back" if result["exit_code"] == 0 else "failed",
                "exit_code": result["exit_code"],
                "stderr_tail": result["stderr"][-STDERR_TAIL:]}

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _failure(attempt: int, stage: str, result: dict, verify: bool = False) -> dict:
        return {"attempt": attempt, "stage": stage,
                "exit_code": result.get("exit_code"),
                "timed_out": result.get("timed_out", False),
                "stderr_tail": (result.get("stderr") or result.get("stderr_tail") or "")[-STDERR_TAIL:],
                "stdout_tail": (result.get("stdout") or result.get("stdout_tail") or "")[-STDERR_TAIL:],
                "verify": verify}

    @staticmethod
    def _diagnose(failures: list[dict]) -> str:
        if not failures:
            return "no attempts were made"
        stages = {failure["stage"] for failure in failures}
        stderr_blob = " ".join(failure.get("stderr_tail", "") for failure in failures).lower()
        if "network" in stderr_blob or "unable to download" in stderr_blob:
            return ("install needs a substituter the sandbox cannot reach; the sandbox network "
                    "is closed by design — the nix-daemon performs downloads, not the sandbox")
        if "not found" in stderr_blob or "does not provide" in stderr_blob:
            return "flake_ref does not resolve to a package (check the attribute name)"
        if "signature" in stderr_blob:
            return "substituter signature rejected; require-sigs is on and the cache is untrusted"
        if stages == {"verify"}:
            return "install command succeeded but the verification command still fails — the " \
                   "manifest's verify step, not the package, is the likely cause"
        return "install did not complete within the attempt limit; see failures[] for stderr"
