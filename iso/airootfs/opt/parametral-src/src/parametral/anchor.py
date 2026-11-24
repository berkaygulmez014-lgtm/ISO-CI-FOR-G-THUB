"""Off-host anchors for the audit chain.

The chain in `audit.py` makes tampering *evident* locally. An anchor makes it evident even
if the whole state directory is replaced: once a day the daemon-side operator writes the
current head (seq + hash) somewhere else — a git repo, object storage, a log collector —
signed with the operator key. Verification then asks two questions:

  1. does each anchor's signature hold (nobody forged an anchor)?
  2. does the local chain still contain a record with exactly that seq and hash
     (did somebody rewrite the local log)?

Anchors are append-only, one JSON object per line, and the file is safe to copy around.
"""
from __future__ import annotations

import json
import os

from . import ed25519, util


class AnchorError(RuntimeError):
    pass


ANCHORS_FILE = "anchors.jsonl"


def _payload(audit_head: dict, node_id: str) -> dict:
    return {"node_id": node_id, "seq": int(audit_head["head_seq"]),
            "head_hash": audit_head["head_hash"], "created_at": util.iso_seconds()}


def write_anchor(audit, out_dir: str, sk_path: str, node_id: str = "local") -> dict:
    """Append a signed head snapshot to `<out_dir>/anchors.jsonl`."""
    if audit.head["head_seq"] < 1:
        raise AnchorError("nothing to anchor yet: the audit log is empty")
    util.ensure_dir(out_dir, 0o750)
    payload = _payload(audit.head, node_id)
    secret = ed25519.load_secret(sk_path)
    body = util.canonical_json(payload)
    record = {"alg": "ed25519",
              "key_id": ed25519.key_id(secret[32:] if len(secret) == 64
                                       else ed25519.public_from_secret(secret)),
              "sig": "base64:" + ed25519.b64(ed25519.sign(body, secret)),
              "payload": payload}
    line = json.dumps(record, sort_keys=True, ensure_ascii=False).encode() + b"\n"
    path = os.path.join(out_dir, ANCHORS_FILE)
    with open(path, "ab") as handle:      # append-only, never rewritten
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    latest = os.path.join(out_dir, "latest-anchor.json")
    util.write_json(latest, record, mode=0o644)
    return record


def read_anchors(out_dir: str) -> list[dict]:
    path = os.path.join(out_dir, ANCHORS_FILE)
    if not os.path.exists(path):
        raise AnchorError(f"no anchors at {path}")
    records = []
    with open(path, "rb") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise AnchorError(f"anchor file is corrupt: {exc}") from exc
    return records


def verify_anchors(audit, out_dir: str, pub_path: str) -> dict:
    """Check signatures and whether the local chain still matches the newest anchor."""
    records = read_anchors(out_dir)
    public = ed25519.load_public(pub_path)
    result = {"anchors": len(records), "signatures_ok": True, "chain_matches": True,
              "chain_verified": True, "first_bad": None, "anchored_seq": None,
              "anchored_hash": None, "reason": None}

    chain = audit.verify()
    result["chain_verified"] = bool(chain["verified"])

    previous_seq = -1
    for index, record in enumerate(records, start=1):
        payload = record.get("payload") or {}
        try:
            signature = ed25519.unb64(str(record.get("sig", "")))
        except ed25519.CryptoError:
            result.update(signatures_ok=False, first_bad=index,
                          reason="anchor signature is not decodable")
            return result
        if not ed25519.verify(util.canonical_json(payload), signature, public):
            result.update(signatures_ok=False, first_bad=index,
                          reason="anchor signature does not verify")
            return result
        seq = payload.get("seq")
        if not isinstance(seq, int) or seq <= previous_seq:
            result.update(signatures_ok=False, first_bad=index,
                          reason="anchors are not in increasing seq order")
            return result
        previous_seq = seq

    newest = records[-1]["payload"]
    result["anchored_seq"] = newest["seq"]
    result["anchored_hash"] = newest["head_hash"]

    local_records = {record["seq"]: record for record in audit._read_records()}
    local = local_records.get(newest["seq"])
    if local is None:
        result.update(chain_matches=False,
                      reason=f"local log has no record #{newest['seq']} (truncated?)")
        return result
    if local.get("hash") != newest["head_hash"]:
        result.update(chain_matches=False,
                      reason=f"local record #{newest['seq']} differs from the anchored hash")
        return result
    if not chain["verified"]:
        result.update(chain_matches=False,
                      reason=f"local chain does not verify: {chain.get('reason')}")
        return result
    result["reason"] = "anchors verify and the local chain matches the newest anchor"
    return result
