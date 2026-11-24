"""Approval gate: the human checkpoint for dangerous operations.

An approval is a short-lived record ("may I do X on Y, because Z?"). It does not
execute anything by itself; it only lets `permission.request` mint a token.
Decisions come from the approver side (desktop UI / `parametral approvals approve`)
and are signed with the approver key so the AI process cannot forge them.
"""
from __future__ import annotations

import os
import secrets

from . import ed25519, util

PENDING, APPROVED, REJECTED, DEFERRED, EXPIRED = "pending", "approved", "rejected", "deferred", "expired"
OPEN_STATES = (PENDING, DEFERRED)
FINAL_STATES = (APPROVED, REJECTED, EXPIRED)

APPROVAL_TTL_S = 900


class ApprovalError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ApprovalStore:
    def __init__(self, directory: str, approver_pub_path: str, node_id: str = "local",
                 ttl_s: int = APPROVAL_TTL_S, notifier=None,
                 approver_sk_path: str | None = None):
        self.directory = util.ensure_dir(os.path.join(directory, "approvals"))
        # Asymmetric on purpose: the daemon verifies with the public key only, so a
        # compromised gateway uid cannot approve anything (and cannot sign sysapply jobs).
        self.approver_pub_path = approver_pub_path
        self.approver_sk_path = approver_sk_path
        self.node_id = node_id
        self.ttl_s = int(ttl_s)
        self.notifier = notifier          # callable(approval: dict) -> None, best effort
        self._notifier_errors: list[str] = []

    # ------------------------------------------------------------------- key

    def _public(self) -> bytes:
        if not os.path.exists(self.approver_pub_path):
            raise ApprovalError("PEER_REJECTED",
                                f"approver public key missing: {self.approver_pub_path}")
        return ed25519.load_public(self.approver_pub_path)

    def ensure_keys(self) -> tuple[str, str]:
        """Create the approver keypair if absent (run by the approver, never the AI)."""
        if os.path.exists(self.approver_pub_path):
            return (self.approver_sk_path or "", self.approver_pub_path)
        if not self.approver_sk_path:
            raise ApprovalError("PEER_REJECTED",
                                "no approver keypair and no path to create one")
        ed25519.keygen(self.approver_sk_path, self.approver_pub_path)
        return (self.approver_sk_path, self.approver_pub_path)

    def _message(self, approval_id: str, decision: str) -> bytes:
        return f"{approval_id}|{decision}".encode("utf-8")

    def proof(self, approval_id: str, decision: str) -> str:
        """Sign an approval decision (approver side: needs the private key)."""
        if not self.approver_sk_path or not os.path.exists(self.approver_sk_path):
            raise ApprovalError("PEER_REJECTED", "approver private key not available here")
        secret = ed25519.load_secret(self.approver_sk_path)
        return "ed25519:" + ed25519.b64(ed25519.sign(self._message(approval_id, decision),
                                                    secret))

    def verify_proof(self, approval_id: str, decision: str, proof: str) -> bool:
        if not isinstance(proof, str) or not proof:
            return False
        try:
            signature = ed25519.unb64(proof)
        except ed25519.CryptoError:
            return False
        return ed25519.verify(self._message(approval_id, decision), signature, self._public())

    # -------------------------------------------------------------- lifecycle

    def _path(self, approval_id: str) -> str:
        if not approval_id.startswith("apr_") or "/" in approval_id or ".." in approval_id:
            raise ApprovalError("INVALID_PARAMS", f"bad approval id {approval_id!r}")
        return os.path.join(self.directory, f"{approval_id}.json")

    def _load(self, approval_id: str) -> dict:
        path = self._path(approval_id)
        if not os.path.exists(path):
            raise ApprovalError("NOT_FOUND", f"unknown approval {approval_id}")
        approval = util.read_json(path)
        if approval.get("state") == PENDING and util.parse_iso(approval["expires_at"]) <= util.now():
            approval = self._save({**approval, "state": EXPIRED,
                                   "decided_at": util.iso(), "decided_by": "system:ttl"})
        return approval

    def _save(self, approval: dict) -> dict:
        util.write_json(self._path(approval["approval_id"]), approval)
        return approval

    def create(self, *, operation: str, scope: dict, justification: str,
               requested_by: str, ttl_s: int | None = None) -> dict:
        approval = {
            "approval_id": "apr_" + secrets.token_hex(6),
            "node_id": self.node_id,
            "operation": operation,
            "scope": scope or {},
            "justification": str(justification)[:2000],
            "requested_by": requested_by,
            "requested_at": util.iso(),
            "expires_at": util.in_seconds(ttl_s or self.ttl_s),
            "state": PENDING,
            "decided_at": None,
            "decided_by": None,
            "reason": None,
        }
        self._save(approval)
        if self.notifier:
            try:
                self.notifier(approval)
            except Exception as exc:  # notification must never break the gate
                self._notifier_errors.append(f"{type(exc).__name__}: {exc}")
        return approval

    def list(self, state: str | None = None, limit: int = 50) -> list[dict]:
        out = []
        for name in sorted(os.listdir(self.directory)):
            if not name.endswith(".json"):
                continue
            approval = self._load(name[:-5])
            if state and approval.get("state") != state:
                continue
            out.append(approval)
        out.sort(key=lambda item: item.get("requested_at", ""), reverse=True)
        return out[:max(1, min(int(limit), 200))]

    def get(self, approval_id: str) -> dict:
        return self._load(approval_id)

    def usable(self, approval_id: str, operation: str) -> dict:
        """Approval for this operation that is still approved and unexpired."""
        approval = self._load(approval_id)
        if approval.get("state") != APPROVED:
            raise ApprovalError("APPROVAL_PENDING",
                                f"approval {approval_id} is {approval.get('state')}")
        if approval.get("operation") != operation:
            raise ApprovalError("INVALID_PARAMS",
                                f"approval {approval_id} is for {approval.get('operation')}, "
                                f"not {operation}")
        return approval

    def decide(self, approval_id: str, decision: str, *, decided_by: str,
               proof: str | None, reason: str | None = None) -> dict:
        if decision not in (APPROVED, REJECTED, DEFERRED):
            raise ApprovalError("INVALID_PARAMS", "decision must be approve|reject|defer")
        if not self.verify_proof(approval_id, decision, proof or ""):
            raise ApprovalError("PEER_REJECTED", "approver proof is missing or wrong")
        approval = self._load(approval_id)
        if approval.get("state") == EXPIRED:
            raise ApprovalError("APPROVAL_PENDING", f"approval {approval_id} expired")
        return self._save({**approval, "state": decision, "decided_at": util.iso(),
                           "decided_by": decided_by, "reason": (reason or "")[:2000]})

    # --------------------------------------------------------------- notify

    def notifier_errors(self) -> list[str]:
        return list(self._notifier_errors)


def desktop_notifier(summary_prefix: str = "Parametral izin isteği"):
    """Best-effort desktop notification; never required for correctness."""
    import shutil
    import subprocess

    def notify(approval: dict) -> None:
        if not shutil.which("notify-send"):
            return
        body = (f"{approval['operation']}\n{approval['justification']}\n"
                f"id: {approval['approval_id']}  (parametral approvals approve "
                f"{approval['approval_id']})")
        subprocess.run(["notify-send", "-u", "critical", "-a", "Parametral OS",
                        summary_prefix, body], timeout=10, check=False)

    return notify
