"""Append-only, hash-chained audit log.

Guarantee: any modification, deletion or reordering of records is *detectable*
by verify(). The chain cannot be silently rewritten by an attacker who has only
the daemon's own privileges and does not know the recorded head hash — and from
phase 5 the head is anchored off-host.

This module never swallows errors: a failed write raises, and the caller
(daemon) turns that into a refused operation, because "no audit record" must
mean "the action did not happen".
"""
from __future__ import annotations

import json
import os
import threading

from . import util

GENESIS = "sha256:" + "0" * 64


class AuditError(RuntimeError):
    pass


class AuditLog:
    def __init__(self, directory: str, node_id: str = "local"):
        self.directory = util.ensure_dir(directory)
        self.path = os.path.join(self.directory, "audit.jsonl")
        self.head_path = os.path.join(self.directory, "head.json")
        self.node_id = node_id
        self._lock = threading.Lock()
        self._seq, self._head = self._load_head()

    # ------------------------------------------------------------------ state

    def _load_head(self) -> tuple[int, str]:
        if os.path.exists(self.head_path):
            head = util.read_json(self.head_path)
            if head.get("node_id") != self.node_id:
                raise AuditError(
                    f"audit head belongs to node {head.get('node_id')!r}, daemon is {self.node_id!r}")
            return int(head["seq"]), str(head["hash"])
        if not os.path.exists(self.path):
            return 0, GENESIS
        seq, head = 0, GENESIS
        with open(self.path, "rb") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                seq, head = int(record["seq"]), str(record["hash"])
        return seq, head

    def _write_head(self) -> None:
        util.write_json(self.head_path, {"node_id": self.node_id, "seq": self._seq, "hash": self._head})

    # ----------------------------------------------------------------- append

    def append(self, *, method: str, actor: str, params=None, result: str = "ok",
               token_id: str | None = None, approval_id: str | None = None,
               sandbox_id: str | None = None, exit_code: int | None = None,
               duration_ms: int | None = None, detail=None,
               severity: str = "info") -> dict:
        params_bytes = util.canonical_json(params if params is not None else {})
        with self._lock:
            seq = self._seq + 1
            record = {
                "seq": seq,
                "ts": util.iso(),
                "node_id": self.node_id,
                "method": method,
                "actor": actor,
                "token_id": token_id,
                "approval_id": approval_id,
                "sandbox_id": sandbox_id,
                "params_sha256": util.sha256_tag(params_bytes),
                "result": result,
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "detail": detail,
                "severity": severity,
                "prev_hash": self._head,
            }
            digest = util.sha256_tag(util.canonical_json(record))
            record["hash"] = digest
            line = json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o640)
            try:
                os.write(fd, line)
                os.fsync(fd)
            finally:
                os.close(fd)
            self._seq, self._head = seq, digest
            self._write_head()
            return record

    # ------------------------------------------------------------ verification

    def _read_records(self) -> list[dict]:
        if not os.path.exists(self.path):
            return []
        records = []
        with open(self.path, "rb") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise AuditError(f"record at line {number} is not valid JSON: {exc}") from exc
        return records

    def verify(self) -> dict:
        try:
            records = self._read_records()
        except AuditError as exc:
            return {"verified": False, "records": 0, "head_seq": self._seq,
                    "head_hash": self._head, "first_broken_seq": None, "reason": str(exc)}

        prev = GENESIS
        for index, record in enumerate(records, start=1):
            expected_seq = index
            if record.get("seq") != expected_seq:
                return {"verified": False, "records": len(records), "head_seq": self._seq,
                        "head_hash": self._head, "first_broken_seq": expected_seq,
                        "reason": f"sequence gap: expected {expected_seq}, found {record.get('seq')}"}
            if record.get("prev_hash") != prev:
                return {"verified": False, "records": len(records), "head_seq": self._seq,
                        "head_hash": self._head, "first_broken_seq": expected_seq,
                        "reason": "prev_hash does not match previous record"}
            claimed = record.get("hash")
            body = {key: value for key, value in record.items() if key != "hash"}
            if util.sha256_tag(util.canonical_json(body)) != claimed:
                return {"verified": False, "records": len(records), "head_seq": self._seq,
                        "head_hash": self._head, "first_broken_seq": expected_seq,
                        "reason": "record hash mismatch (record modified)"}
            prev = claimed

        if len(records) < self._seq:
            return {"verified": False, "records": len(records), "head_seq": self._seq,
                    "head_hash": self._head, "first_broken_seq": len(records) + 1,
                    "reason": f"truncation: head says seq {self._seq}, log ends at {len(records)}"}
        if records and records[-1]["hash"] != self._head:
            return {"verified": False, "records": len(records), "head_seq": self._seq,
                    "head_hash": self._head, "first_broken_seq": len(records),
                    "reason": "head hash does not match last record (append outside daemon?)"}
        return {"verified": True, "records": len(records), "head_seq": self._seq,
                "head_hash": self._head, "first_broken_seq": None, "reason": None}

    # ----------------------------------------------------------------- query

    def query(self, from_seq: int = 1, limit: int = 50, method: str | None = None) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        out = []
        for record in self._read_records():
            if record.get("seq", 0) < from_seq:
                continue
            if method and record.get("method") != method:
                continue
            out.append(record)
            if len(out) >= limit:
                break
        return out

    @property
    def head(self) -> dict:
        return {"head_seq": self._seq, "head_hash": self._head}
