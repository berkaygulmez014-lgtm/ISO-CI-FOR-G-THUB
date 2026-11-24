"""Policy engine. Default deny, deny-beats-allow, file-based rules, versioned.

The engine is deliberately small enough to read in one sitting: a request is
described by (operation, scope) and the answer is one of:
  allow / allow-with-approval / deny  (+ the rule that decided, for auditability).
"""
from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass

# Every operation the wire protocol can ask for. A policy referencing an unknown
# operation is a configuration error and refuses to load (fail closed).
OPERATIONS = frozenset({
    "status",
    "sandbox.create", "sandbox.destroy", "sandbox.list", "sandbox.status",
    "exec.run",
    "fs.read", "fs.write", "fs.edit", "fs.delete", "fs.list",
    "app.install", "app.remove", "app.read",
    "net.open", "net.close", "net.list", "service.start",
    "host.apply", "host.nix_profile",
    "snapshot.create", "snapshot.restore", "snapshot.list",
    "audit.read", "approvals.read", "approvals.decide",
})


class PolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class Decision:
    decision: str                      # "allow" | "deny"
    rule_id: str
    requires_approval: bool = False
    reason: str = ""
    max_ttl_s: int | None = None

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"

    def to_dict(self) -> dict:
        return {"decision": self.decision, "rule_id": self.rule_id,
                "requires_approval": self.requires_approval,
                "reason": self.reason, "max_ttl_s": self.max_ttl_s}


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _path_matches(patterns: list[str], paths: list[str]) -> bool:
    if not patterns:
        return True
    if not paths:
        return False
    for path in paths:
        if not any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns):
            return False
    return True


class Policy:
    """Loaded once, reloadable on SIGHUP. Immutable during a request."""

    def __init__(self, path: str):
        self.path = path
        self.version = None
        self.node_id = None
        self.rules: list[dict] = []
        self.limits: dict = {}
        self.reload()

    # ------------------------------------------------------------------ load

    def reload(self) -> None:
        try:
            with open(self.path, "rb") as handle:
                data = json.load(handle)
        except FileNotFoundError as exc:
            raise PolicyError(f"policy file not found: {self.path}") from exc
        except json.JSONDecodeError as exc:
            raise PolicyError(f"policy file is not valid JSON: {exc}") from exc

        if data.get("default") != "deny":
            raise PolicyError("policy.default must be 'deny' (fail-closed requirement)")
        rules = data.get("rules")
        if not isinstance(rules, list) or not rules:
            raise PolicyError("policy.rules must be a non-empty list")

        seen = set()
        for rule in rules:
            rule_id = rule.get("id")
            if not rule_id or not isinstance(rule_id, str):
                raise PolicyError("every rule needs a string id")
            if rule_id in seen:
                raise PolicyError(f"duplicate rule id: {rule_id}")
            seen.add(rule_id)
            if rule.get("effect") not in ("allow", "deny"):
                raise PolicyError(f"rule {rule_id}: effect must be allow|deny")
            operations = rule.get("operations")
            if not isinstance(operations, list) or not operations:
                raise PolicyError(f"rule {rule_id}: operations must be a non-empty list")
            unknown = set(operations) - OPERATIONS
            if unknown:
                raise PolicyError(f"rule {rule_id}: unknown operations {sorted(unknown)}")
            if not isinstance(rule.get("priority", 100), int):
                raise PolicyError(f"rule {rule_id}: priority must be an integer")
            if rule["effect"] == "allow" and "max_ttl_s" in rule and not isinstance(rule["max_ttl_s"], int):
                raise PolicyError(f"rule {rule_id}: max_ttl_s must be an integer")

        self.version = data.get("policy_version")
        self.node_id = data.get("node_id", "local")
        self.limits = data.get("limits", {}) or {}
        self.rules = rules

    # ---------------------------------------------------------------- explain

    @staticmethod
    def _rule_matches(rule: dict, operation: str, scope: dict) -> bool:
        if operation not in rule.get("operations", []):
            return False

        sandbox_ids = _as_list(rule.get("sandbox_ids"))
        if sandbox_ids:
            requested = scope.get("sandbox_id")
            if "*" not in sandbox_ids and requested not in sandbox_ids:
                return False

        commands = _as_list(rule.get("commands"))
        if commands:
            requested_command = scope.get("command")
            if requested_command is None:
                return False
            if "*" not in commands and requested_command not in commands:
                return False

        if not _path_matches(_as_list(rule.get("paths")), _as_list(scope.get("paths"))):
            return False

        allowed_mounts = _as_list(rule.get("allowed_mounts"))
        if allowed_mounts:
            host_paths = _as_list(scope.get("host_paths"))
            if not host_paths:
                return False
            for host_path in host_paths:
                if not any(fnmatch.fnmatchcase(host_path, pattern) for pattern in allowed_mounts):
                    return False

        not_allowed = _as_list(rule.get("not_allowed_mounts"))
        if not_allowed:
            host_paths = _as_list(scope.get("host_paths"))
            if not host_paths:
                return False
            if all(any(fnmatch.fnmatchcase(host_path, pattern) for pattern in not_allowed)
                   for host_path in host_paths):
                return False

        services = _as_list(rule.get("services"))
        if services:
            requested = scope.get("service")
            if requested is None or requested not in services:
                return False

        return True

    def explain(self, operation: str, scope: dict | None = None) -> Decision:
        if operation not in OPERATIONS:
            raise PolicyError(f"unknown operation: {operation}")
        scope = scope or {}

        deny_rules = [r for r in self.rules if r["effect"] == "deny"
                      and self._rule_matches(r, operation, scope)]
        if deny_rules:
            rule = max(deny_rules, key=lambda r: r.get("priority", 100))
            return Decision("deny", rule["id"], False,
                            rule.get("description") or f"denied by rule {rule['id']}", None)

        allow_rules = [r for r in self.rules if r["effect"] == "allow"
                       and self._rule_matches(r, operation, scope)]
        if not allow_rules:
            return Decision("deny", "default-deny", False,
                            f"no allow rule matched operation {operation} for scope {scope}", None)

        rule = max(allow_rules, key=lambda r: r.get("priority", 100))
        requires_approval = bool(rule.get("requires_approval", False))
        reason = rule.get("description") or f"allowed by rule {rule['id']}"
        return Decision("allow", rule["id"], requires_approval, reason,
                        rule.get("max_ttl_s"))

    # ----------------------------------------------------------------- limits

    def limit(self, name: str, default=None):
        return self.limits.get(name, default)

    def clamp_ttl(self, requested_s: int, rule_max: int | None) -> int:
        cap = min(int(self.limit("max_token_ttl_s", 1800)),
                  int(rule_max) if rule_max else int(self.limit("max_token_ttl_s", 1800)))
        return max(1, min(int(requested_s), cap))
