"""Capability tokens: HMAC-SHA256, node-scoped, TTL- and use-limited.

The AI never holds ambient authority. It holds a token that names exactly which
operations, on which sandbox, for how long, and for how many uses. Any mismatch
is a hard failure — there is no "close enough" path here.
"""
from __future__ import annotations

import base64
import fnmatch
import fcntl
import hashlib
import hmac
import json
import os
import secrets

from . import util

PREFIX = "u1."
TOKEN_VERSION = 1

# Contract §5.8: one token op covers a family of read/write methods.
OP_IMPLIES = {
    "fs.read": {"fs.list"},
    "fs.list": {"fs.read"},
    "fs.write": {"fs.edit", "fs.delete"},
}


class TokenError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _path_covered(path: str, patterns: list) -> bool:
    """`/work` is inside `/work/**`: the directory root itself counts as covered."""
    for pattern in patterns:
        if fnmatch.fnmatchcase(path, pattern):
            return True
        if pattern.endswith("/**") and path == pattern[:-3]:
            return True
    return False


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


class TokenStore:
    def __init__(self, directory: str, key_path: str, node_id: str = "local",
                 ttl_cap_s: int = 1800, default_max_uses: int = 25):
        self.directory = util.ensure_dir(os.path.join(directory, "tokens"))
        self.key_path = key_path
        self.node_id = node_id
        self.ttl_cap_s = int(ttl_cap_s)
        self.default_max_uses = int(default_max_uses)
        self._key = self._load_or_create_key()

    def _load_or_create_key(self) -> bytes:
        if os.path.exists(self.key_path):
            with open(self.key_path, "rb") as handle:
                key = handle.read()
            if len(key) < 32:
                raise TokenError("KEY_CORRUPT", f"token key at {self.key_path} is too short")
            return key
        key = secrets.token_bytes(32)
        util.atomic_write(self.key_path, key, mode=0o600)
        return key

    # ------------------------------------------------------------------ issue

    def issue(self, *, ops: list[str], scope: dict | None, ttl_s: int,
              max_uses: int | None = None, approval_id: str | None = None) -> tuple[str, dict]:
        scope = scope or {}
        ttl = max(1, min(int(ttl_s), self.ttl_cap_s))
        payload = {
            "v": TOKEN_VERSION,
            "tid": "tok_" + secrets.token_hex(6),
            "node_id": self.node_id,
            "ops": sorted(set(ops)),
            "scope": scope,
            "iat": util.iso_seconds(),
            "exp": util.in_seconds(ttl),
            "max_uses": int(max_uses if max_uses is not None else self.default_max_uses),
            "approval_id": approval_id,
        }
        body = b64url_encode(util.canonical_json(payload))
        signature = b64url_encode(hmac.new(self._key, (PREFIX + body).encode("ascii"),
                                           hashlib.sha256).digest())
        return f"{PREFIX}{body}.{signature}", payload

    # ----------------------------------------------------------------- verify

    def _decode(self, token: str) -> tuple[dict, str]:
        if not isinstance(token, str) or not token.startswith(PREFIX):
            raise TokenError("TOKEN_INVALID", "token is not a u1 token")
        body_and_sig = token[len(PREFIX):]
        if body_and_sig.count(".") != 1:
            raise TokenError("TOKEN_INVALID", "token is malformed")
        body, signature = body_and_sig.split(".", 1)
        expected = b64url_encode(hmac.new(self._key, (PREFIX + body).encode("ascii"),
                                          hashlib.sha256).digest())
        if not hmac.compare_digest(expected, signature):
            raise TokenError("TOKEN_INVALID", "token signature does not verify")
        try:
            payload = json.loads(b64url_decode(body))
        except (ValueError, json.JSONDecodeError) as exc:
            raise TokenError("TOKEN_INVALID", f"token payload is not JSON: {exc}") from exc
        if payload.get("v") != TOKEN_VERSION:
            raise TokenError("TOKEN_INVALID", f"unsupported token version {payload.get('v')!r}")
        return payload, body

    def _uses_path(self, tid: str) -> str:
        return os.path.join(self.directory, f"{tid}.json")

    def used_count(self, tid: str) -> int:
        path = self._uses_path(tid)
        if not os.path.exists(path):
            return 0
        return int(util.read_json(path).get("used", 0))

    def _bump_use(self, payload: dict) -> None:
        path = self._uses_path(payload["tid"])
        used = self.used_count(payload["tid"]) + 1
        util.write_json(path, {"used": used, "exp": payload["exp"], "node_id": self.node_id})

    def _consume_slot(self, payload: dict) -> None:
        """Atomically take one use from the token's budget.

        verify(consume=True) used to read the counter, compare, then write — under a threaded
        server N concurrent callers all passed the check and all wrote, so a max_uses=1 token
        could be spent many times. The check and the bump now happen under an exclusive
        flock, so exactly max_uses calls succeed.
        """
        path = self._uses_path(payload["tid"])
        limit = int(payload.get("max_uses", 0))
        with open(path + ".lock", "a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                used = self.used_count(payload["tid"])
                if used >= limit:
                    raise TokenError("TOKEN_INVALID",
                                     f"token uses exhausted ({used}/{limit})")
                util.write_json(path, {"used": used + 1, "exp": payload["exp"],
                                       "node_id": self.node_id})
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def scope_allows(scope: dict, request_scope: dict) -> bool:
        """Is this request's scope inside the token's granted scope?"""
        sandbox_ids = _as_list(scope.get("sandbox_ids"))
        if sandbox_ids and "*" not in sandbox_ids:
            if request_scope.get("sandbox_id") not in sandbox_ids:
                return False

        commands = _as_list(scope.get("commands"))
        if commands and "*" not in commands:
            if request_scope.get("command") not in commands:
                return False

        paths = _as_list(scope.get("paths"))
        if paths:
            request_paths = _as_list(request_scope.get("paths"))
            if not request_paths:
                return False
            for path in request_paths:
                if not _path_covered(path, paths):
                    return False
        return True

    def verify(self, token: str, operation: str | None = None,
               request_scope: dict | None = None, consume: bool = False) -> dict:
        payload, _ = self._decode(token)
        if payload.get("node_id") != self.node_id:
            raise TokenError("TOKEN_INVALID", "token is scoped to a different node")
        try:
            expired = util.parse_iso(payload["exp"]) <= util.now()
        except (KeyError, ValueError) as exc:
            raise TokenError("TOKEN_INVALID", "token has no usable exp") from exc
        if expired:
            raise TokenError("TOKEN_INVALID", f"token expired at {payload['exp']}")

        if operation is not None:
            granted_ops = set(payload.get("ops", []))
            implied = set()
            for granted in granted_ops:
                implied |= OP_IMPLIES.get(granted, set())
            if operation not in granted_ops and operation not in implied:
                raise TokenError("TOKEN_INVALID",
                                 f"token does not grant operation {operation!r}")
            if request_scope is not None and not self.scope_allows(payload.get("scope", {}),
                                                                   request_scope):
                raise TokenError("TOKEN_INVALID", "request scope is outside the token's scope")

        if consume:
            self._consume_slot(payload)
        else:
            used = self.used_count(payload["tid"])
            if used >= int(payload.get("max_uses", 0)):
                raise TokenError("TOKEN_INVALID",
                                 f"token uses exhausted ({used}/{payload['max_uses']})")
        return payload

    # -------------------------------------------------------------- maintenance

    def sweep(self) -> int:
        """Delete use-counters for expired tokens. Returns how many were removed."""
        removed = 0
        for name in os.listdir(self.directory):
            if not name.endswith(".json"):
                continue
            path = os.path.join(self.directory, name)
            try:
                data = util.read_json(path)
                if util.parse_iso(data["exp"]) <= util.now():
                    util.try_unlink(path)
                    removed += 1
            except (OSError, KeyError, ValueError):
                util.try_unlink(path)
                removed += 1
        return removed
