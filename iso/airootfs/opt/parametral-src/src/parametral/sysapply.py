"""sysapply — the only place that may write to the real system (tier 1).

Two processes, one signed hand-off:

  gateway (parametral)                     sysapply (root)
  ─────────────────                     ────────────────
  host.apply ──► pending job file  ──►  verify Ed25519 signature (approver pub)
                                        re-validate against the closed preset list
                                        snapshot
                                        run argv (no shell, no env surprises)
                                        write result file

The gateway cannot sign and sysapply refuses anything unsigned, so "an approved change"
and "these exact argv" cannot drift apart: the approver signs the job it read.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import time

from . import ed25519, hostapply, util

DEFAULT_SPOOL = "/run/parametral/jobs"
DEFAULT_RESULTS = "/run/parametral/results"
STEP_TIMEOUT_S = 1800
OUTPUT_TAIL = 4096


class JobError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _ensure(path: str, mode: int = 0o700) -> str:
    os.makedirs(path, mode=mode, exist_ok=True)
    return path


# --------------------------------------------------------------- job format

def build_payload(request: dict, node_id: str = "local",
                  job_id: str | None = None) -> dict:
    """Canonical, signed payload. `request` is the wire-level host.apply params."""
    normalised = hostapply.validate(request)
    return {
        "job_id": job_id or "job_" + secrets.token_hex(6),
        "node_id": node_id,
        "created_at": util.iso_seconds(),
        "approval_id": normalised["approval_id"],
        "intent": normalised["intent"],
        "snapshot": True,
        "steps": normalised["steps"],
    }


def payload_bytes(payload: dict) -> bytes:
    """Signature is over this exact byte string, not over a re-serialisation."""
    return util.canonical_json(payload)


def sign_job(payload: dict, sk_path: str) -> dict:
    secret = ed25519.load_secret(sk_path)
    public = secret[32:] if len(secret) == 64 else ed25519.public_from_secret(secret)
    signature = ed25519.sign(payload_bytes(payload), secret)
    return {"alg": "ed25519", "key_id": ed25519.key_id(public),
            "sig": "base64:" + ed25519.b64(signature),
            "payload_sha256": util.sha256_tag(payload_bytes(payload))}


def verify_job(payload: dict, record: dict, pub_path: str) -> None:
    if not isinstance(record, dict):
        raise JobError("SIGNATURE_INVALID", "job has no signature record")
    if record.get("alg") != "ed25519":
        raise JobError("SIGNATURE_INVALID", f"unsupported signature algorithm {record.get('alg')!r}")
    expected = util.sha256_tag(payload_bytes(payload))
    if record.get("payload_sha256") != expected:
        raise JobError("SIGNATURE_INVALID",
                       "job payload does not match the signed payload hash")
    try:
        signature = ed25519.unb64(str(record.get("sig", "")))
    except ed25519.CryptoError as exc:
        raise JobError("SIGNATURE_INVALID", f"signature is not decodable: {exc}") from exc
    if not ed25519.verify(payload_bytes(payload), signature, ed25519.load_public(pub_path)):
        raise JobError("SIGNATURE_INVALID",
                       "job signature does not verify against the approver public key")


# ------------------------------------------------------------ gateway side

class JobQueue:
    """What the gateway may do: drop a job, watch for a result. Nothing else."""

    def __init__(self, spool_dir: str = DEFAULT_SPOOL, results_dir: str = DEFAULT_RESULTS,
                 node_id: str = "local"):
        self.spool_dir = _ensure(spool_dir, 0o750)
        self.results_dir = _ensure(results_dir, 0o755)
        self.node_id = node_id

    def submit(self, request: dict) -> dict:
        payload = build_payload(request, self.node_id)
        path = os.path.join(self.spool_dir, f"{payload['job_id']}.pending.json")
        util.write_json(path, payload, mode=0o640)
        return payload

    def signed_jobs(self) -> list[str]:
        out = []
        for name in sorted(os.listdir(self.spool_dir)):
            if name.endswith(".json") and not name.endswith(".pending.json"):
                out.append(name[:-len(".json")])
        return out

    def pending_jobs(self) -> list[str]:
        return [name[:-len(".pending.json")] for name in sorted(os.listdir(self.spool_dir))
                if name.endswith(".pending.json")]

    def read_pending(self, job_id: str) -> dict:
        return util.read_json(os.path.join(self.spool_dir, f"{job_id}.pending.json"))

    def sign_pending(self, job_id: str, sk_path: str) -> dict:
        payload = self.read_pending(job_id)
        record = sign_job(payload, sk_path)
        final = os.path.join(self.spool_dir, f"{job_id}.json")
        util.write_json(final, payload, mode=0o644)
        util.write_json(final + ".sig", record, mode=0o644)
        util.try_unlink(os.path.join(self.spool_dir, f"{job_id}.pending.json"))
        return record

    def result(self, job_id: str) -> dict | None:
        path = os.path.join(self.results_dir, f"{job_id}.json")
        if not os.path.exists(path):
            return None
        return util.read_json(path)

    def wait(self, job_id: str, timeout_s: float = 5.0, interval: float = 0.2) -> dict | None:
        deadline = time.monotonic() + max(0.0, timeout_s)
        while time.monotonic() < deadline:
            found = self.result(job_id)
            if found is not None:
                return found
            time.sleep(interval)
        return self.result(job_id)


# -------------------------------------------------------------- root side

class JobRunner:
    """Executes signed jobs. This is the code that runs as root — keep it boring."""

    def __init__(self, spool_dir: str = DEFAULT_SPOOL, results_dir: str = DEFAULT_RESULTS,
                 approver_pub_path: str = "/etc/parametral/keys/approver.pub",
                 node_id: str = "local", snapshot_fn=None,
                 step_timeout_s: int = STEP_TIMEOUT_S, env: dict | None = None):
        self.queue = JobQueue(spool_dir, results_dir, node_id)
        self.spool_dir = self.queue.spool_dir
        self.results_dir = self.queue.results_dir
        self.approver_pub_path = approver_pub_path
        self.node_id = node_id
        self.snapshot_fn = snapshot_fn
        self.step_timeout_s = step_timeout_s
        self.env = env or {"PATH": "/usr/bin:/usr/sbin:/bin:/sbin", "LC_ALL": "C"}

    # ------------------------------------------------------------ discovery

    def _signed(self) -> list[str]:
        jobs = []
        for name in sorted(os.listdir(self.spool_dir)):
            if not name.endswith(".json") or name.endswith(".pending.json"):
                continue
            job_id = name[:-len(".json")]
            if os.path.exists(os.path.join(self.spool_dir, name + ".sig")):
                jobs.append(job_id)
        return jobs

    def pending(self) -> list[str]:
        return self.queue.pending_jobs()

    # ------------------------------------------------------------- execute

    def run_once(self) -> list[dict]:
        results = []
        for job_id in self._signed():
            results.append(self.run_job(job_id))
        return results

    def run_job(self, job_id: str) -> dict:
        job_path = os.path.join(self.spool_dir, f"{job_id}.json")
        sig_path = job_path + ".sig"
        try:
            payload = util.read_json(job_path)
            record = util.read_json(sig_path)
            verify_job(payload, record, self.approver_pub_path)
            validated = hostapply.validate({**payload, "approval_id": payload.get("approval_id")})
        except (JobError, hostapply.HostApplyError, ed25519.CryptoError,
                OSError, ValueError) as exc:
            code = getattr(exc, "code", "SIGNATURE_INVALID")
            return self._finish(job_id, {"job_id": job_id, "state": "rejected",
                                        "error": str(exc), "parametral_code": code,
                                        "steps": []})

        snapshot_id = None
        if self.snapshot_fn is not None:
            try:
                snapshot_id = self.snapshot_fn()
            except Exception as exc:  # a failed snapshot means the change must not happen
                return self._finish(job_id, {
                    "job_id": job_id, "state": "rejected",
                    "error": f"pre-change snapshot failed: {exc}", "steps": [],
                    "parametral_code": "SNAPSHOT_FAILED"})

        step_results = []
        state = "applied"
        for index, step in enumerate(validated["steps"]):
            started = time.monotonic()
            try:
                proc = subprocess.run(step["argv"], capture_output=True, text=True,
                                      timeout=self.step_timeout_s, env=self.env, cwd="/",
                                      shell=False)
                entry = {"kind": step["kind"], "argv": step["argv"],
                         "exit_code": proc.returncode,
                         "duration_ms": int((time.monotonic() - started) * 1000),
                         "stdout_tail": (proc.stdout or "")[-OUTPUT_TAIL:],
                         "stderr_tail": (proc.stderr or "")[-OUTPUT_TAIL:]}
            except subprocess.TimeoutExpired:
                entry = {"kind": step["kind"], "argv": step["argv"], "exit_code": 124,
                         "timed_out": True, "duration_ms": int((time.monotonic() - started) * 1000),
                         "stdout_tail": "", "stderr_tail": "step timed out"}
            step_results.append(entry)
            if entry["exit_code"] != 0:
                state = "failed"
                break

        return self._finish(job_id, {"job_id": job_id, "state": state,
                                     "approved_by": record.get("key_id"),
                                     "snapshot_id": snapshot_id,
                                     "intent": payload.get("intent"),
                                     "steps": step_results,
                                     "finished_at": util.iso()})

    def _finish(self, job_id: str, result: dict) -> dict:
        util.write_json(os.path.join(self.results_dir, f"{job_id}.json"), result, mode=0o644)
        for suffix in (".json", ".json.sig"):
            util.try_unlink(os.path.join(self.spool_dir, f"{job_id}{suffix}"))
        return result
