"""parametrald — JSON-RPC 2.0 control plane over a Unix socket.

Every request passes through: node check → policy → capability token → handler →
audit. Nothing executes before the token is validated, and nothing is executed
without a policy decision, so "default deny" is the shape of the code, not a
comment in it.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import time
import errno
import json
import os
import re
import socket
import socketserver
import threading
import time
import traceback

from . import appinstall, hostapply, netproxy, sysapply, util
from .approvals import FINAL_STATES, ApprovalError, ApprovalStore, desktop_notifier
from .audit import AuditLog
from .harddeny import HardDenyClient, HardDenyUnavailable
from .policy import OPERATIONS, Policy, PolicyError
from .sandbox import SandboxError, SandboxManager
from .tokens import TokenError, TokenStore

SERVER_VERSION = "0.1.0"
PROTOCOL_VERSIONS = ["v1"]
MAX_LINE = 1024 * 1024

# Methods that take an approval as their own input (never token-gated).
NO_TOKEN_METHODS = {"v1.node.hello", "v1.node.status", "v1.policy.explain",
                    "v1.audit.verify", "v1.sandbox.list", "v1.permission.request",
                    "v1.approvals.list", "v1.approvals.get", "v1.approvals.decide",
                    "v1.sandbox.status"}


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "data": self.data}


CODE_UNSUPPORTED = -32008

# Read-only diagnostics must work even when the oracle is down, so an operator can
# see *why* everything is being refused.
ORACLE_EXEMPT = {"v1.node.hello", "v1.node.status", "v1.policy.explain", "v1.audit.verify"}


def _invalid(message: str, field: str | None = None, **extra) -> RpcError:
    data = {"parametral_code": "INVALID_PARAMS", **(extra or {})}
    if field:
        data["field"] = field
    return RpcError(-32602, message, data)


def _not_found(message: str) -> RpcError:
    return RpcError(-32006, message, {"parametral_code": "NOT_FOUND"})


def _limit(message: str, **extra) -> RpcError:
    return RpcError(-32007, message, {"parametral_code": "LIMIT_EXCEEDED", **extra})


def _unsupported(message: str, milestone: str) -> RpcError:
    return RpcError(CODE_UNSUPPORTED, message,
                    {"parametral_code": "UNSUPPORTED", "milestone": milestone})


def _require(params: dict, field: str, kind=str, max_len: int | None = None):
    value = params.get(field)
    if value is None:
        raise _invalid(f"missing required field {field!r}", field)
    if not isinstance(value, kind):
        raise _invalid(f"field {field!r} must be {kind.__name__}", field)
    if kind is str:
        if not value.strip():
            raise _invalid(f"field {field!r} must not be empty", field)
        if max_len and len(value) > max_len:
            raise _limit(f"field {field!r} longer than {max_len}")
    return value


def _require_id(params: dict, field: str) -> str:
    value = _require(params, field, str, 128)
    if not all(char.isalnum() or char in "_-." for char in value):
        raise _invalid(f"field {field!r} has illegal characters", field)
    return value


class ParametralDaemon:
    def __init__(self, policy_path: str | None = None, state_dir: str | None = None,
                 node_id: str = "local", socket_path: str | None = None,
                 notifier=None, harddeny_socket: str | None = None,
                 harddeny_rules: str | None = None):
        self.node_id = node_id
        self.approver_uids = {
            int(part) for part in os.environ.get("PARAMETRAL_APPROVER_UIDS", "").replace(" ", "").split(",")
            if part.isdigit()
        }
        self.policy_path = policy_path or util.policy_path()
        self.state_dir = util.ensure_dir(state_dir or util.state_dir())
        self.socket_path = socket_path or util.socket_path()
        self.started_at = util.now()
        self.harddeny_socket = harddeny_socket or os.path.join(util.runtime_dir(), "harddeny.sock")
        self.harddeny_rules = harddeny_rules
        self.harddeny = HardDenyClient(self.harddeny_socket)

        self.policy = Policy(self.policy_path)
        self.audit = AuditLog(os.path.join(self.state_dir, "audit"), node_id)
        self.tokens = TokenStore(self.state_dir,
                                 os.path.join(self.state_dir, "token.key"),
                                 node_id,
                                 ttl_cap_s=int(self.policy.limit("max_token_ttl_s", 1800)),
                                 default_max_uses=int(self.policy.limit("default_token_max_uses", 25)))
        self.approvals = ApprovalStore(self.state_dir,
                                       os.path.join(util.runtime_dir(), "approver.pub"),
                                       node_id,
                                       ttl_s=int(self.policy.limit("approval_ttl_s", 900)),
                                       notifier=notifier if notifier is not None else desktop_notifier())
        self.sandboxes = SandboxManager(self.state_dir, node_id, defaults={
            "cpu_cores": 1.0,
            "memory_mb": int(self.policy.limit("max_memory_mb", 512)) // 2,
            "pids": 128,
            "disk_mb": 256,
        })
        self.net_grants = netproxy.GrantRegistry(on_event=self._net_event)
        self.job_queue = sysapply.JobQueue(
            os.environ.get("PARAMETRAL_JOB_SPOOL", os.path.join(util.runtime_dir(), "jobs")),
            os.environ.get("PARAMETRAL_JOB_RESULTS", os.path.join(util.runtime_dir(), "results")),
            node_id)
        self.installer = appinstall.Installer(
            self.sandboxes,
            nix_bin=os.environ.get("PARAMETRAL_NIX_BIN", "nix"),
            state_root=self.state_dir)
        self._idempotency: dict[str, tuple[float, dict]] = {}
        self._idem_lock = threading.Lock()
        self.handlers = {
            "v1.node.hello": self._node_hello,
            "v1.node.status": self._node_status,
            "v1.policy.explain": self._policy_explain,
            "v1.permission.request": self._permission_request,
            "v1.approvals.list": self._approvals_list,
            "v1.approvals.get": self._approvals_get,
            "v1.approvals.decide": self._approvals_decide,
            "v1.sandbox.create": self._sandbox_create,
            "v1.sandbox.list": self._sandbox_list,
            "v1.sandbox.status": self._sandbox_status,
            "v1.sandbox.destroy": self._sandbox_destroy,
            "v1.exec.run": self._exec_run,
            "v1.net.open": self._net_open,
            "v1.net.close": self._net_close,
            "v1.net.list": self._net_list,
            "v1.fs.read": self._fs_read,
            "v1.fs.write": self._fs_write,
            "v1.fs.edit": self._fs_edit,
            "v1.fs.list": self._fs_list,
            "v1.fs.delete": self._fs_delete,
            "v1.audit.query": self._audit_query,
            "v1.audit.verify": self._audit_verify,
            "v1.app.install": self._app_install,
            "v1.app.remove": self._app_remove,
            "v1.app.verify": self._app_verify,
            "v1.snapshot.create": self._snapshot_create,
            "v1.snapshot.list": self._snapshot_list,
            "v1.host.apply": self._host_apply,
            "v1.host.nix_profile": self._host_nix_profile,
            "v1.snapshot.restore": self._snapshot_restore,
            "v1.node.peers": self._not_yet_phase_5,
            "v1.node.dispatch": self._not_yet_phase_5,
            "v1.snapshot.replicate": self._not_yet_phase_5,
        }
        self.operation_of = {
            "v1.permission.request": None,        # the *requested* operation is checked
            "v1.sandbox.create": "sandbox.create",
            "v1.sandbox.destroy": "sandbox.destroy",
            "v1.sandbox.list": "sandbox.list",
            "v1.sandbox.status": "sandbox.status",
            "v1.exec.run": "exec.run",
            "v1.net.open": "net.open",
            "v1.net.close": "net.close",
            "v1.net.list": "net.list",
            "v1.fs.read": "fs.read",
            "v1.fs.write": "fs.write",
            "v1.fs.edit": "fs.write",
            "v1.fs.list": "fs.list",
            "v1.fs.delete": "fs.write",
            "v1.audit.query": "audit.read",
            "v1.audit.verify": "status",
            "v1.approvals.list": "approvals.read",
            "v1.approvals.get": "approvals.read",
            "v1.approvals.decide": "approvals.decide",
            "v1.node.status": "status",
            "v1.policy.explain": "status",
            "v1.app.install": "app.install",
            "v1.app.remove": "app.remove",
            "v1.app.verify": "app.read",
            "v1.snapshot.create": "snapshot.create",
            "v1.snapshot.restore": "snapshot.restore",
            "v1.snapshot.list": "snapshot.list",
            "v1.host.apply": "host.apply",
            "v1.host.nix_profile": "host.nix_profile",
        }

    # ------------------------------------------------------------- dispatch

    def scope_for(self, method: str, params: dict) -> dict:
        """Translate wire params into the policy/token scope vocabulary."""
        scope: dict = {}
        sandbox_id = params.get("sandbox_id")
        if isinstance(sandbox_id, str) and sandbox_id:
            scope["sandbox_id"] = sandbox_id
        if method == "v1.exec.run":
            cmd = params.get("cmd")
            if isinstance(cmd, list) and cmd and isinstance(cmd[0], str):
                scope["command"] = os.path.basename(cmd[0])
        elif method in ("v1.fs.read", "v1.fs.list", "v1.fs.write", "v1.fs.edit",
                        "v1.fs.delete"):
            path = params.get("path")
            if isinstance(path, str) and path:
                scope["paths"] = [path]
        elif method == "v1.sandbox.create":
            mounts = params.get("mounts") or []
            host_paths = [m.get("host_path") for m in mounts
                          if isinstance(m, dict) and isinstance(m.get("host_path"), str)]
            if host_paths:
                scope["host_paths"] = host_paths
        elif method == "v1.permission.request":
            requested = params.get("scope") or {}
            if isinstance(requested, dict):
                if isinstance(requested.get("sandbox_id"), str):
                    scope["sandbox_id"] = requested["sandbox_id"]
                if isinstance(requested.get("paths"), list):
                    scope["paths"] = [p for p in requested["paths"] if isinstance(p, str)]
                if isinstance(requested.get("commands"), list) and requested["commands"]:
                    scope["command"] = requested["commands"][0]
        return scope

    def handle(self, request: dict) -> dict:
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}

        if request.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return self._error_response(request_id, RpcError(-32600, "invalid JSON-RPC request",
                                                             {"parametral_code": "INVALID_REQUEST"}))
        if not isinstance(params, dict):
            return self._error_response(request_id, RpcError(-32600, "params must be an object",
                                                             {"parametral_code": "INVALID_REQUEST",
                                                              "field": "params"}))
        if method not in self.handlers:
            return self._error_response(request_id, RpcError(-32601, f"unknown method {method}",
                                                             {"parametral_code": "METHOD_NOT_FOUND"}))

        node_id = params.get("node_id")
        if node_id is None:
            return self._error_response(request_id, RpcError(
                -32600, "params.node_id is mandatory", {"parametral_code": "INVALID_REQUEST",
                                                        "field": "node_id"}))
        if node_id != self.node_id:
            return self._error_response(request_id, RpcError(
                -32011, f"this node is {self.node_id!r}, request addressed {node_id!r}",
                {"parametral_code": "NODE_MISMATCH"}))

        operation = self.operation_of.get(method)
        oracle_operation = operation
        if method == "v1.permission.request":
            requested = params.get("operation")
            oracle_operation = requested if isinstance(requested, str) else None
        oracle_scope = self.scope_for(method, params)
        token_payload = None
        try:
            # Stage 0: deterministic hard-deny oracle (fail closed). A denial here
            # is final — no approval is offered, no token can override it. It also runs
            # for capability *requests*, so a forbidden command never gets a token.
            if oracle_operation is not None and method not in ORACLE_EXEMPT:
                try:
                    verdict = self.harddeny.check(oracle_operation, oracle_scope, self.node_id)
                except HardDenyUnavailable as exc:
                    self.audit.append(method=method, actor="anonymous", params=params,
                                      result="denied", severity="critical",
                                      detail={"reason": str(exc),
                                              "parametral_code": "HARD_DENY_UNAVAILABLE"})
                    raise RpcError(-32013, "hard-deny oracle is unavailable; refusing "
                                           "the operation (fail closed)",
                                   {"parametral_code": "HARD_DENY_UNAVAILABLE",
                                    "socket": self.harddeny_socket}) from exc
                if verdict.get("decision") != "allow":
                    self.audit.append(method=method, actor="anonymous", params=params,
                                      result="denied", severity="critical",
                                      detail={"hard_deny": verdict,
                                              "parametral_code": "POLICY_DENIED"})
                    raise RpcError(-32001, "operation is on the hard deny list", {
                        "parametral_code": "POLICY_DENIED", "hard_deny": True,
                        "rule_id": verdict.get("rule_id"),
                        "reason": verdict.get("reason"),
                        "approval_possible": False,
                        "hint": "tier-2 rule: no approval can authorise this"})

            if operation is not None:
                decision = self.policy.explain(operation, self.scope_for(method, params))
                if not decision.allowed:
                    self.audit.append(method=method, actor="anonymous", params=params,
                                      result="denied", severity="warning",
                                      detail={"rule_id": decision.rule_id,
                                              "reason": decision.reason})
                    raise RpcError(-32001, "policy denied the operation", {
                        "parametral_code": "POLICY_DENIED", "rule_id": decision.rule_id,
                        "operation": operation, "reason": decision.reason,
                        "hint": "request a capability token via v1.permission.request"})

                if method not in NO_TOKEN_METHODS:
                    token = params.get("capability_token")
                    if not token:
                        self.audit.append(method=method, actor="anonymous", params=params,
                                          result="denied", severity="warning",
                                          detail={"reason": "missing capability token"})
                        raise RpcError(-32002, "operation needs a capability token", {
                            "parametral_code": "TOKEN_REQUIRED", "operation": operation,
                            "hint": f"v1.permission.request for {operation}"})
                    try:
                        token_payload = self.tokens.verify(
                            token, operation, self.scope_for(method, params), consume=True)
                    except TokenError as exc:
                        self.audit.append(method=method, actor="anonymous", params=params,
                                          result="denied", severity="warning",
                                          detail={"reason": str(exc)})
                        raise RpcError(-32003, str(exc), {"parametral_code": "TOKEN_INVALID",
                                                          "operation": operation}) from exc

            idem_key = params.get("idempotency_key")
            cache_key = None
            if idem_key and operation is not None:
                cache_key = f"{operation}:{idem_key}"
                cached = self._idempotent_get(cache_key)
                if cached is not None:
                    return {"jsonrpc": "2.0", "id": request_id, "result": cached}

            result = self.handlers[method](params, token_payload)

            if cache_key:
                self._idempotent_put(cache_key, result)

            self.audit.append(method=method, actor=self._actor(token_payload), params=params,
                              result="ok", token_id=self._tid(token_payload),
                              sandbox_id=params.get("sandbox_id"),
                              exit_code=result.get("exit_code") if isinstance(result, dict) else None,
                              duration_ms=result.get("duration_ms") if isinstance(result, dict) else None)
            return {"jsonrpc": "2.0", "id": request_id, "result": result}

        except RpcError as exc:
            self.audit.append(method=method, actor=self._actor(token_payload), params=params,
                              result="error", severity="warning",
                              token_id=self._tid(token_payload),
                              sandbox_id=params.get("sandbox_id"), detail=exc.data)
            return self._error_response(request_id, exc)
        except (SandboxError, TokenError, ApprovalError) as exc:
            code_map = {
                "NOT_FOUND": (-32006, "NOT_FOUND"),
                "INVALID_PARAMS": (-32602, "INVALID_PARAMS"),
                "LIMIT_EXCEEDED": (-32007, "LIMIT_EXCEEDED"),
                "CONFLICT": (-32012, "CONFLICT"),
                "UNSUPPORTED": (-32008, "UNSUPPORTED"),
                "SANDBOX_UNAVAILABLE": (-32009, "SANDBOX_UNAVAILABLE"),
                "APPROVAL_PENDING": (-32005, "APPROVAL_PENDING"),
                "PEER_REJECTED": (-32010, "PEER_REJECTED"),
                "TOKEN_INVALID": (-32003, "TOKEN_INVALID"),
            }
            code, parametral_code = code_map.get(getattr(exc, "code", ""), (-32603, "INTERNAL"))
            severity = "security" if (getattr(exc, "detail", None) or {}).get("severity") == "security" else "warning"
            self.audit.append(method=method, actor=self._actor(token_payload), params=params,
                              result="error", severity=severity,
                              token_id=self._tid(token_payload),
                              sandbox_id=params.get("sandbox_id"),
                              detail={"message": str(exc), "parametral_code": parametral_code,
                                      "detail": getattr(exc, "detail", None)})
            return self._error_response(request_id, RpcError(
                code, str(exc), {"parametral_code": parametral_code,
                                 **(getattr(exc, "detail", None) or {})}))
        except PolicyError as exc:
            self.audit.append(method=method, actor=self._actor(token_payload), params=params,
                              result="error", detail={"message": str(exc)})
            return self._error_response(request_id, RpcError(
                -32603, f"policy error: {exc}", {"parametral_code": "INTERNAL"}))
        except Exception as exc:  # never swallow: surface + audit
            detail = traceback.format_exc(limit=8)
            self.audit.append(method=method, actor=self._actor(token_payload), params=params,
                              result="error", severity="error",
                              detail={"message": f"{type(exc).__name__}: {exc}",
                                      "traceback": detail})
            return self._error_response(request_id, RpcError(
                -32603, f"{type(exc).__name__}: {exc}", {"parametral_code": "INTERNAL"}))

    # ------------------------------------------------------------ idempotency

    def _idempotent_get(self, key: str) -> dict | None:
        with self._idem_lock:
            entry = self._idempotency.get(key)
            if entry is None:
                return None
            created, result = entry
            if time.monotonic() - created > 600:
                self._idempotency.pop(key, None)
                return None
            return result

    def _idempotent_put(self, key: str, result: dict) -> None:
        with self._idem_lock:
            if len(self._idempotency) > 256:
                self._idempotency.clear()
            self._idempotency[key] = (time.monotonic(), result)

    @staticmethod
    def _actor(payload: dict | None) -> str:
        if payload:
            return f"token:{payload.get('tid')}"
        return "session:local"

    @staticmethod
    def _tid(payload: dict | None) -> str | None:
        return payload.get("tid") if payload else None

    @staticmethod
    def _error_response(request_id, error: RpcError) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "error": error.to_dict()}

    # -------------------------------------------------------------- handlers

    def peer_allowed(self, peer_uid: int) -> bool:
        """Same uid as the daemon, or an explicitly configured approver uid.

        The AI never runs as the daemon's uid: it is a different account by design. The human
        approval window *does* have to reach the daemon, and it lives with the seat user, so
        that one uid is allowed in — configured, never inferred. Everything such a peer may do
        is still gated by role checks and the approver's Ed25519 proof.
        """
        if peer_uid == os.getuid():
            return True
        return peer_uid in self.approver_uids

    def _node_hello(self, params: dict, _token) -> dict:
        offered = params.get("protocol_versions") or PROTOCOL_VERSIONS
        if not isinstance(offered, list) or not set(offered) & set(PROTOCOL_VERSIONS):
            raise _invalid("no common protocol version", "protocol_versions",
                           supported=PROTOCOL_VERSIONS)
        return {
            "node_id": self.node_id,
            "server_version": SERVER_VERSION,
            "protocol_versions": PROTOCOL_VERSIONS,
            "selected": "v1",
            "features": ["sandbox.bwrap", "seccomp.blacklist-v1", "cgroup.v2", "audit.chain",
                         "tokens.hmac", "approvals.desktop", "harddeny.oracle.v1"],
            "policy_version": self.policy.version,
            "started_at": util.iso_seconds(self.started_at),
        }

    def _node_status(self, params: dict, _token) -> dict:
        verify = self.audit.verify()
        return {
            "node_id": self.node_id,
            "server_version": SERVER_VERSION,
            "uptime_s": int((util.now() - self.started_at).total_seconds()),
            "sandboxes": self.sandboxes.list(),
            "policy_version": self.policy.version,
            "policy_path": self.policy_path,
            "quota_backend": "cgroup2" if self.sandboxes._cgroup_root() else "rlimits",
            "limits_default": self.sandboxes.default_limits.to_dict(),
            "audit": {"head_seq": verify["head_seq"], "head_hash": verify["head_hash"],
                      "verified": verify["verified"]},
            "approvals_pending": len(self.approvals.list(state="pending")),
            "harddeny": self._harddeny_status(),
        }

    def _harddeny_status(self) -> dict:
        status = {"socket": self.harddeny_socket, "rules": self.harddeny_rules,
                  "available": False, "rules_version": None, "rules_sig": None}
        try:
            verdict = self.harddeny.check("status", {}, self.node_id)
            status.update({"available": True,
                           "rules_version": verdict.get("rules_version"),
                           "rules_sig": verdict.get("rules_sig")})
        except HardDenyUnavailable as exc:
            status["error"] = str(exc)[:200]
        return status

    def _policy_explain(self, params: dict, _token) -> dict:
        operation = _require(params, "operation", str)
        if operation not in OPERATIONS:
            raise _invalid(f"unknown operation {operation!r}", "operation")
        scope = params.get("scope") or {}
        if not isinstance(scope, dict):
            raise _invalid("scope must be an object", "scope")
        return self.policy.explain(operation, scope).to_dict()

    def _permission_request(self, params: dict, _token) -> dict:
        operation = _require(params, "operation", str)
        if operation not in OPERATIONS:
            raise _invalid(f"unknown operation {operation!r}", "operation")
        scope_in = params.get("scope") or {}
        if not isinstance(scope_in, dict):
            raise _invalid("scope must be an object", "scope")
        justification = _require(params, "justification", str, 2000)
        requested_by = str(params.get("requested_by") or "unknown")

        scope = {}
        sandbox_id = scope_in.get("sandbox_id")
        if isinstance(sandbox_id, str) and sandbox_id:
            self.sandboxes.get(sandbox_id)  # validates existence
            scope["sandbox_ids"] = [sandbox_id]
        if isinstance(scope_in.get("paths"), list):
            scope["paths"] = [str(p) for p in scope_in["paths"] if isinstance(p, str)] or None
        if isinstance(scope_in.get("commands"), list):
            commands = [str(c) for c in scope_in["commands"] if isinstance(c, str)]
            scope["commands"] = commands or None
        scope = {key: value for key, value in scope.items() if value}

        # The requested capability is evaluated per dimension: the sandbox/paths
        # scope *and* every individual command. One command outside policy and the
        # whole request is refused — no smuggling a second command into a token.
        base_scope = {key: value for key, value in scope.items() if key != "commands"}
        decisions = []
        commands = scope.get("commands")
        if commands:
            for command in commands:
                decisions.append(self.policy.explain(operation,
                                                     {**base_scope, "command": command}))
        else:
            decisions.append(self.policy.explain(operation, base_scope))
        denied = [item for item in decisions if not item.allowed]
        if denied:
            raise RpcError(-32001, "policy denied the requested capability", {
                "parametral_code": "POLICY_DENIED", "rule_id": denied[0].rule_id,
                "operation": operation, "reason": denied[0].reason})

        requires_approval = any(item.requires_approval for item in decisions)
        ttls = [item.max_ttl_s for item in decisions if item.max_ttl_s]
        max_ttl_s = min(ttls) if ttls else None

        approval_id = params.get("approval_id")
        if requires_approval:
            if approval_id:
                approval = self.approvals.usable(str(approval_id), operation)
            else:
                approval = self.approvals.create(operation=operation, scope=scope,
                                                 justification=justification,
                                                 requested_by=requested_by)
                raise RpcError(-32004, "operation needs human approval", {
                    "parametral_code": "APPROVAL_REQUIRED",
                    "approval_id": approval["approval_id"],
                    "operation": operation, "expires_at": approval["expires_at"],
                    "how": f"parametral approvals approve {approval['approval_id']}"})
        else:
            approval = None

        ttl_s = params.get("ttl_s", self.policy.limit("default_token_ttl_s", 900))
        try:
            ttl_s = int(ttl_s)
        except (TypeError, ValueError) as exc:
            raise _invalid("ttl_s must be an integer", "ttl_s") from exc
        ttl_s = self.policy.clamp_ttl(ttl_s, max_ttl_s)

        max_uses = params.get("max_uses", self.policy.limit("default_token_max_uses", 25))
        try:
            max_uses = max(1, min(int(max_uses), 1000))
        except (TypeError, ValueError) as exc:
            raise _invalid("max_uses must be an integer", "max_uses") from exc

        token, payload = self.tokens.issue(ops=[operation], scope=scope, ttl_s=ttl_s,
                                           max_uses=max_uses,
                                           approval_id=approval["approval_id"] if approval else None)
        return {
            "capability_token": token,
            "expires_at": payload["exp"],
            "max_uses": payload["max_uses"],
            "ops": payload["ops"],
            "scope": scope,
            "node_id": self.node_id,
            "approval_id": payload["approval_id"],
        }

    # ------------------------------------------------------------- approvals

    def _approvals_list(self, params: dict, _token) -> dict:
        state = params.get("state")
        if state is not None and state not in ("pending", "approved", "rejected",
                                              "deferred", "expired"):
            raise _invalid("bad state filter", "state")
        return {"approvals": self.approvals.list(state=state,
                                                 limit=int(params.get("limit", 50)))}

    def _approvals_get(self, params: dict, _token) -> dict:
        """Fetch one approval; `wait_s` turns this into a long-poll.

        The server is threaded, so a waiting client does not stall other calls, but the wait
        is still capped: a client must not be able to pin a thread indefinitely.
        """
        approval_id = _require_id(params, "approval_id")
        raw_wait = params.get("wait_s", 0)
        try:
            wait_s = float(raw_wait)
        except (TypeError, ValueError) as exc:
            raise _invalid("wait_s must be a number", "wait_s") from exc
        wait_s = max(0.0, min(wait_s, float(self.policy.limit("approval_wait_s", 120))))
        started = time.monotonic()
        approval = self.approvals.get(approval_id)
        while approval.get("state") not in FINAL_STATES and time.monotonic() - started < wait_s:
            time.sleep(0.2)
            approval = self.approvals.get(approval_id)
        return {
            "approval_id": approval["approval_id"],
            "operation": approval.get("operation"),
            "scope": approval.get("scope"),
            "state": approval.get("state"),
            "requested_by": approval.get("requested_by"),
            "justification": approval.get("justification"),
            "expires_at": approval.get("expires_at"),
            "decided_at": approval.get("decided_at"),
            "decided_by": approval.get("decided_by"),
            "reason": approval.get("reason"),
            "waited_s": round(time.monotonic() - started, 3),
        }

    def _approvals_decide(self, params: dict, _token) -> dict:
        approval_id = _require_id(params, "approval_id")
        decision_word = _require(params, "decision", str)
        decision = {"approve": "approved", "reject": "rejected", "defer": "deferred"}.get(decision_word)
        if decision is None:
            raise _invalid("decision must be approve|reject|defer", "decision")
        proof = params.get("approver_proof")
        if not isinstance(proof, str) or not proof:
            raise RpcError(-32010, "approver_proof is required for approval decisions", {
                "parametral_code": "PEER_REJECTED"})
        approval = self.approvals.decide(approval_id, decision,
                                         decided_by=str(params.get("decided_by") or "user:local"),
                                         proof=proof,
                                         reason=params.get("reason"))
        return {"approval_id": approval_id, "state": approval["state"],
                "decided_at": approval["decided_at"]}

    # -------------------------------------------------------------- sandboxes

    def _sandbox_create(self, params: dict, _token) -> dict:
        name = _require(params, "name", str, 63)
        profile = params.get("profile", "strict")
        limits = params.get("limits") or {}
        if not isinstance(limits, dict):
            raise _invalid("limits must be an object", "limits")
        mounts = params.get("mounts") or []
        if not isinstance(mounts, list):
            raise _invalid("mounts must be a list", "mounts")
        env = params.get("env") or {}
        if not isinstance(env, dict):
            raise _invalid("env must be an object", "env")
        meta = self.sandboxes.create(name=name, profile=str(profile), limits=limits,
                                    net=bool(params.get("net", False)), env=env,
                                    mounts=mounts)
        return {"sandbox_id": meta["sandbox_id"], "name": meta["name"],
                "state": meta["state"], "root": meta["root"],
                "limits": meta["limits"], "net": meta["net"],
                "profile": meta["profile"], "created_at": meta["created_at"]}

    def _sandbox_list(self, params: dict, _token) -> dict:
        return {"sandboxes": self.sandboxes.list(), "node_id": self.node_id}

    def _sandbox_status(self, params: dict, _token) -> dict:
        sandbox_id = _require_id(params, "sandbox_id")
        meta = self.sandboxes.get(sandbox_id)
        return {"sandbox_id": sandbox_id, "name": meta["name"], "state": meta["state"],
                "profile": meta["profile"], "net": meta["net"],
                "execs": meta.get("execs", 0), "quota": meta["limits"],
                "usage": self.sandboxes.usage(sandbox_id),
                "created_at": meta["created_at"]}

    def _sandbox_destroy(self, params: dict, _token) -> dict:
        sandbox_id = _require_id(params, "sandbox_id")
        return self.sandboxes.destroy(sandbox_id, purge=bool(params.get("purge", True)))

    def _net_event(self, event: dict) -> None:
        """Every proxy connection attempt lands in the audit log."""
        self.audit.append(method="netproxy." + str(event.get("event")),
                          actor="system:netproxy", params=event,
                          sandbox_id=event.get("sandbox_id"),
                          result="ok" if event.get("event") in ("connect", "grant_created")
                          else "denied",
                          detail=event, severity="info")

    def _net_open(self, params: dict, _token) -> dict:
        sandbox_id = _require_id(params, "sandbox_id")
        meta = self.sandboxes.get(sandbox_id)
        hosts = params.get("hosts")
        ttl_s = params.get("ttl_s", 300)
        try:
            ttl_s = int(ttl_s)
        except (TypeError, ValueError) as exc:
            raise _invalid("ttl_s must be an integer", "ttl_s") from exc
        try:
            grant = self.net_grants.open(sandbox_id, meta["net_dir"], hosts, ttl_s)
        except netproxy.NetGrantError as exc:
            code = -32007 if exc.code == "LIMIT_EXCEEDED" else -32602
            raise RpcError(code, str(exc), {"parametral_code": exc.code}) from exc
        return {"grant_id": grant.grant_id, "sandbox_id": sandbox_id,
                "hosts": [{"host": host, "port": port} for host, port in grant.hosts],
                "socket_dir": "/run/net",
                "sockets": [f"/run/net/{grant.grant_id}-{port}.sock"
                            for _host, port in grant.hosts],
                "expires_in_s": max(0, int(grant.expires_at - time.monotonic())),
                "note": "the sandbox has no network stack; these Unix sockets are the only "
                        "way out and they forward only to the approved destinations"}

    def _net_close(self, params: dict, _token) -> dict:
        grant_id = _require_id(params, "grant_id")
        try:
            self.net_grants.close(grant_id)
        except netproxy.NetGrantError as exc:
            raise RpcError(-32006, str(exc), {"parametral_code": exc.code}) from exc
        return {"grant_id": grant_id, "closed": True}

    def _net_list(self, params: dict, _token) -> dict:
        sandbox_id = params.get("sandbox_id")
        if sandbox_id:
            _require_id(params, "sandbox_id")
        grants = self.net_grants.list()
        if sandbox_id:
            grants = [grant for grant in grants if grant["sandbox_id"] == sandbox_id]
        return {"grants": grants, "sweep_hint": "expired grants are closed automatically"}

    def _exec_run(self, params: dict, _token) -> dict:
        sandbox_id = _require_id(params, "sandbox_id")
        cmd = params.get("cmd")
        if not isinstance(cmd, list) or not cmd:
            raise _invalid("cmd must be a non-empty array", "cmd")
        env = params.get("env") or {}
        if not isinstance(env, dict):
            raise _invalid("env must be an object", "env")
        timeout_s = params.get("timeout_s", self.policy.limit("exec_timeout_s", 30))
        try:
            timeout_s = int(timeout_s)
        except (TypeError, ValueError) as exc:
            raise _invalid("timeout_s must be an integer", "timeout_s") from exc
        meta = self.sandboxes.get(sandbox_id)
        result = self.sandboxes.run(sandbox_id, [str(part) for part in cmd],
                                    cwd=str(params.get("cwd") or "/work"),
                                    env=env, timeout_s=timeout_s,
                                    max_output_bytes=int(params.get("max_output_bytes", 65536)))
        if params.get("verdict") is not None:
            result["verdict"] = self._check_verdict(meta, result, params["verdict"])
        return result

    def _check_verdict(self, meta: dict, result: dict, spec) -> dict:
        """Evaluate a postcondition, so "the command ran" is not mistaken for "it worked".

        Supported: expect_exit (int or list), stdout_contains, stdout_regex,
        stderr_contains, file_exists, file_sha256. Unknown keys are an error rather than a
        silent pass — a typo in the verdict must not turn into a green light.
        """
        if not isinstance(spec, dict):
            raise _invalid("verdict must be an object", "verdict")
        known = {"expect_exit", "stdout_contains", "stdout_regex", "stderr_contains",
                 "file_exists", "file_sha256"}
        unknown = sorted(set(spec) - known)
        if unknown:
            raise _invalid(f"verdict: unknown check(s) {unknown}", "verdict")

        stdout = result.get("stdout") or ""
        stderr = result.get("stderr") or ""
        checks: list[dict] = []

        def record(name: str, ok: bool, detail: str) -> None:
            checks.append({"check": name, "ok": bool(ok), "detail": str(detail)[:300]})

        if "expect_exit" in spec:
            want = spec["expect_exit"]
            wanted = want if isinstance(want, list) else [want]
            try:
                wanted = [int(value) for value in wanted]
            except (TypeError, ValueError) as exc:
                raise _invalid("verdict.expect_exit must be an int or a list of ints",
                               "verdict") from exc
            code = result.get("exit_code")
            record("expect_exit", code in wanted, f"exit={code} want={wanted}")
        if "stdout_contains" in spec:
            needle = str(spec["stdout_contains"])
            record("stdout_contains", needle in stdout, f"{needle!r} in stdout")
        if "stderr_contains" in spec:
            needle = str(spec["stderr_contains"])
            record("stderr_contains", needle in stderr, f"{needle!r} in stderr")
        if "stdout_regex" in spec:
            pattern = str(spec["stdout_regex"])
            try:
                matched = re.search(pattern, stdout, re.MULTILINE) is not None
            except re.error as exc:
                raise _invalid(f"verdict.stdout_regex is not a valid regex: {exc}",
                               "verdict") from exc
            record("stdout_regex", matched, pattern)
        if "file_exists" in spec:
            host = self.sandboxes.host_path(meta, str(spec["file_exists"]))
            record("file_exists", os.path.exists(host), spec["file_exists"])
        if "file_sha256" in spec:
            want = str(spec["file_sha256"])
            host = self.sandboxes.host_path(meta, str(spec.get("file_exists") or ""))
            if not os.path.exists(host):
                record("file_sha256", False, "file missing")
            else:
                with open(host, "rb") as handle:
                    digest = hashlib.sha256(handle.read()).hexdigest()
                record("file_sha256", digest == want.replace("sha256:", ""),
                       f"{digest} want {want}")
        return {"passed": all(item["ok"] for item in checks), "checks": checks}

    # ------------------------------------------------------------ filesystem

    def _fs_paths(self, params: dict) -> tuple[dict, str]:
        sandbox_id = _require_id(params, "sandbox_id")
        meta = self.sandboxes.get(sandbox_id)
        path = _require(params, "path", str, 4096)
        return meta, self.sandboxes.host_path(meta, path)

    def _fs_read(self, params: dict, _token) -> dict:
        meta, host = self._fs_paths(params)
        if not os.path.exists(host):
            raise _not_found(f"no such file: {params.get('path')}")
        if os.path.isdir(host):
            raise _invalid("path is a directory; use v1.fs.list", "path")
        max_bytes = max(1, min(int(params.get("max_bytes", 1024 * 1024)), 8 * 1024 * 1024))
        with open(host, "rb") as handle:
            data = handle.read(max_bytes + 1)
        truncated = len(data) > max_bytes
        data = data[:max_bytes]
        try:
            content = data.decode("utf-8")
            encoding = "utf-8"
            payload = {"content": content}
        except UnicodeDecodeError:
            encoding = "base64"
            payload = {"content_b64": base64.b64encode(data).decode("ascii")}
        return {"path": params["path"], "size": os.path.getsize(host),
                "sha256": util.sha256_tag(data), "encoding": encoding,
                "truncated": truncated, **payload}

    def _fs_write(self, params: dict, _token) -> dict:
        meta, host = self._fs_paths(params)
        if "content_b64" in params and params["content_b64"] is not None:
            try:
                data = base64.b64decode(str(params["content_b64"]), validate=True)
            except (ValueError, TypeError) as exc:
                raise _invalid("content_b64 is not valid base64", "content_b64") from exc
        else:
            content = _require(params, "content", str)
            data = content.encode("utf-8")
        if len(data) > 32 * 1024 * 1024:
            raise _limit("content larger than 32 MiB")
        if params.get("create_parents", True):
            os.makedirs(os.path.dirname(host), exist_ok=True)
        created = not os.path.exists(host)
        mode_text = str(params.get("mode") or "0640")
        try:
            mode = int(mode_text, 8)
        except ValueError as exc:
            raise _invalid("mode must be octal like '0644'", "mode") from exc
        util.atomic_write(host, data, mode=mode)
        return {"path": params["path"], "size": len(data), "sha256": util.sha256_tag(data),
                "created": created}

    def _fs_edit(self, params: dict, _token) -> dict:
        meta, host = self._fs_paths(params)
        if not os.path.exists(host):
            raise _not_found(f"no such file: {params.get('path')}")
        old = _require(params, "old", str)
        new = _require(params, "new", str, 1024 * 1024)
        with open(host, "rb") as handle:
            original = handle.read()
        try:
            text = original.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _invalid("file is not valid UTF-8; use fs.write with base64", "path") from exc
        occurrences = text.count(old)
        if occurrences == 0:
            raise _invalid("old text not found in file", "old")
        expected = int(params.get("count", 1))
        if occurrences != expected:
            raise RpcError(-32012, f"ambiguous match: {occurrences} occurrences, expected {expected}",
                           {"parametral_code": "CONFLICT", "occurrences": occurrences})
        updated = text.replace(old, new, expected)
        util.atomic_write(host, updated.encode("utf-8"), mode=0o640)
        return {"path": params["path"], "replacements": expected,
                "sha256": util.sha256_tag(updated.encode("utf-8"))}

    def _fs_list(self, params: dict, _token) -> dict:
        meta, host = self._fs_paths(params)
        if not os.path.isdir(host):
            raise _invalid("path is not a directory", "path")
        recursive = bool(params.get("recursive", False))
        max_entries = max(1, min(int(params.get("max_entries", 500)), 5000))
        entries = []
        if recursive:
            for root, dirs, files in os.walk(host):
                for name in sorted(dirs) + sorted(files):
                    full = os.path.join(root, name)
                    entries.append(self._entry(full, host))
                    if len(entries) >= max_entries:
                        break
                if len(entries) >= max_entries:
                    break
        else:
            for name in sorted(os.listdir(host)):
                entries.append(self._entry(os.path.join(host, name), host))
                if len(entries) >= max_entries:
                    break
        return {"entries": entries, "truncated": len(entries) >= max_entries}

    @staticmethod
    def _entry(full: str, base: str) -> dict:
        try:
            stat = os.lstat(full)
        except OSError as exc:
            raise _not_found(f"cannot stat {full}: {exc}") from exc
        kind = "dir" if os.path.isdir(full) else ("link" if os.path.islink(full) else "file")
        return {"name": os.path.relpath(full, base), "type": kind, "size": stat.st_size,
                "mode": oct(stat.st_mode & 0o777)[2:].zfill(4),
                "mtime": util.iso_seconds(
                    datetime.datetime.fromtimestamp(stat.st_mtime, datetime.timezone.utc))}

    def _fs_delete(self, params: dict, _token) -> dict:
        meta, host = self._fs_paths(params)
        import shutil

        if not os.path.exists(host):
            raise _not_found(f"no such path: {params.get('path')}")
        if os.path.isdir(host):
            if not params.get("recursive", False) and os.listdir(host):
                raise RpcError(-32012, "directory not empty (pass recursive=true)",
                               {"parametral_code": "CONFLICT"})
            shutil.rmtree(host)
        else:
            os.unlink(host)
        return {"path": params["path"], "deleted": True}

    # ----------------------------------------------------------------- audit

    def _audit_query(self, params: dict, _token) -> dict:
        from_seq = int(params.get("from_seq", 1))
        limit = int(params.get("limit", 50))
        method = params.get("method")
        if method is not None and not isinstance(method, str):
            raise _invalid("method must be a string", "method")
        records = self.audit.query(from_seq=from_seq, limit=limit, method=method)
        return {"records": records,
                "next_seq": (records[-1]["seq"] + 1) if records else from_seq}

    def _audit_verify(self, params: dict, _token) -> dict:
        result = self.audit.verify()
        result["checked_at"] = util.iso()
        return result

    # ------------------------------------------------------- reserved stubs

    # ----------------------------------------------------- app lifecycle

    def _manifest_from(self, params: dict) -> dict:
        manifest = params.get("manifest")
        if not isinstance(manifest, dict):
            raise _invalid("manifest must be an object", "manifest")
        return manifest

    def _app_install(self, params: dict, _token) -> dict:
        sandbox_id = _require_id(params, "sandbox_id")
        manifest = self._manifest_from(params)
        attempt_limit = params.get("attempt_limit")
        try:
            record = self.installer.install(sandbox_id, manifest,
                                           attempt_limit=attempt_limit,
                                           snapshot=bool(params.get("snapshot", True)))
        except appinstall.ManifestError as exc:
            code = -32602
            if exc.code == "UNSUPPORTED":
                code = CODE_UNSUPPORTED
            raise RpcError(code, str(exc), {"parametral_code": exc.code, **exc.detail}) from exc
        return record

    def _app_remove(self, params: dict, _token) -> dict:
        sandbox_id = _require_id(params, "sandbox_id")
        manifest = self._manifest_from(params)
        try:
            return self.installer.remove(sandbox_id, manifest)
        except appinstall.ManifestError as exc:
            raise RpcError(-32602, str(exc), {"parametral_code": exc.code, **exc.detail}) from exc

    def _app_verify(self, params: dict, _token) -> dict:
        sandbox_id = _require_id(params, "sandbox_id")
        manifest = self._manifest_from(params)
        try:
            return self.installer.verify(sandbox_id, manifest)
        except appinstall.ManifestError as exc:
            raise RpcError(-32602, str(exc), {"parametral_code": exc.code, **exc.detail}) from exc

    def _host_apply(self, params: dict, _token) -> dict:
        """Tier-1: queue a signed job for sysapply.

        The gateway can only *ask*: the exact argv is signed by the approver, verified
        and executed by root. Nothing here runs as root, and an unsigned job never runs.
        """
        job_id = params.get("job_id")
        if job_id is not None:
            job_id = _require_id(params, "job_id")
            result = self.job_queue.result(job_id)
            if result is None:
                raise RpcError(-32005, "job is still waiting for the approver's signature", {
                    "parametral_code": "APPROVAL_PENDING", "job_id": job_id,
                    "how": f"parametral host sign {job_id}"})
            return result
        try:
            payload = self.job_queue.submit(params)
        except hostapply.HostApplyError as exc:
            code = -32004 if exc.code == "APPROVAL_REQUIRED" else -32602
            raise RpcError(code, str(exc), {"parametral_code": exc.code}) from exc
        result = self.job_queue.wait(payload["job_id"],
                                     timeout_s=float(params.get("wait_s", 3)))
        if result is not None:
            return result
        raise RpcError(-32005, "change queued: the approver must sign this exact job", {
            "parametral_code": "APPROVAL_PENDING", "job_id": payload["job_id"],
            "steps": [step["kind"] for step in payload["steps"]],
            "how": f"parametral host sign {payload['job_id']}"})

    def _host_nix_profile(self, params: dict, _token) -> dict:
        """Tier-0: rootless, generation-based. Validated now, executed in phase 2."""
        action = params.get("action")
        if action not in ("install", "remove", "list"):
            raise _invalid("action must be install|remove|list", "action")
        packages = params.get("packages") or []
        if not isinstance(packages, list):
            raise _invalid("packages must be a list", "packages")
        if action != "list" and not packages:
            raise _invalid("packages must not be empty", "packages")
        for ref in packages:
            if not isinstance(ref, str) or not hostapply.PATTERNS["flake_refs"].match(ref):
                raise _invalid(f"bad flake reference {ref!r} (want nixpkgs#name)", "packages")
        raise _unsupported("host.nix_profile is contract-only until phase 2; nothing was "
                           "executed", "phase-2")

    def _not_yet_phase_2(self, params: dict, _token) -> dict:
        raise _unsupported(
            "application lifecycle is specified in API v1 but implemented in phase 2; "
            "nothing was executed", "phase-2")

    def _snapshot_create(self, params: dict, _token) -> dict:
        sandbox_id = _require_id(params, "sandbox_id")
        label = params.get("label")
        if label is not None and (not isinstance(label, str) or len(label) > 120):
            raise _invalid("label must be a string <=120 chars", "label")
        record = self.sandboxes.snapshot(sandbox_id, label=label,
                                        reason=str(params.get("reason") or "manual"))
        return {"snapshot_id": record["snapshot_id"], "sandbox_id": sandbox_id,
                "label": record["label"], "created_at": record["created_at"],
                "kind": record["kind"], "parent": record["parent"],
                "read_only": True}

    def _snapshot_list(self, params: dict, _token) -> dict:
        sandbox_id = params.get("sandbox_id")
        if sandbox_id is not None:
            sandbox_id = _require_id(params, "sandbox_id")
            self.sandboxes.get(sandbox_id)
        return {"snapshots": self.sandboxes.list_snapshots(sandbox_id),
                "btrfs_available": self.sandboxes.btrfs_available}

    def _snapshot_restore(self, params: dict, _token) -> dict:
        sandbox_id = _require_id(params, "sandbox_id")
        snapshot_id = _require_id(params, "snapshot_id")
        result = self.sandboxes.restore(sandbox_id, snapshot_id,
                                       confirm=params.get("confirm") is True)
        result["quota_note"] = self.sandboxes.snapshot_notes[-1:] or []
        return result

    def _not_yet_phase_4(self, params: dict, _token) -> dict:
        raise _unsupported(
            "snapshots are specified in API v1 but implemented in phase 4; "
            "no snapshot was taken or restored", "phase-4")

    def _not_yet_phase_5(self, params: dict, _token) -> dict:
        raise _unsupported(
            "multi-node methods are reserved for phase 5; no swarm code exists in v1",
            "phase-5")


# --------------------------------------------------------------------- server

class _Handler(socketserver.StreamRequestHandler):
    daemon: ParametralDaemon

    def handle(self):
        peer = util.peer_uid(self.connection)
        if peer is not None and not self.daemon.peer_allowed(peer):
            try:
                self.connection.sendall(json.dumps({
                    "jsonrpc": "2.0", "id": None,
                    "error": {"code": -32010, "message": "peer uid rejected",
                              "data": {"parametral_code": "PEER_REJECTED"}}}).encode() + b"\n")
            except OSError:
                pass
            return
        while True:
            try:
                line = self.rfile.readline(MAX_LINE + 1)
            except OSError:
                return
            if not line:
                return
            if len(line) > MAX_LINE:
                self._send({"jsonrpc": "2.0", "id": None,
                            "error": {"code": -32600, "message": "request line too large",
                                      "data": {"parametral_code": "INVALID_REQUEST"}}})
                return
            if not line.strip():
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                self._send({"jsonrpc": "2.0", "id": None,
                            "error": {"code": -32700, "message": f"parse error: {exc}",
                                      "data": {"parametral_code": "PARSE_ERROR"}}})
                continue
            if isinstance(request, list):
                self._send({"jsonrpc": "2.0", "id": None,
                            "error": {"code": -32600, "message": "batch requests are not supported",
                                      "data": {"parametral_code": "INVALID_REQUEST"}}})
                continue
            self._send(self.daemon.handle(request))

    def _send(self, payload: dict) -> None:
        try:
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")
            self.wfile.flush()
        except OSError:
            return


class ParametralServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, socket_path: str, daemon: ParametralDaemon):
        util.ensure_dir(os.path.dirname(socket_path), 0o700)
        util.try_unlink(socket_path)
        self.daemon_instance = daemon
        handler = type("BoundHandler", (_Handler,), {"daemon": daemon})
        super().__init__(socket_path, handler)
        os.chmod(socket_path, 0o660)   # 0600 locked out the human approval window


def serve(policy_path: str | None = None, state_dir: str | None = None,
          node_id: str = "local", socket_path: str | None = None) -> None:
    daemon = ParametralDaemon(policy_path=policy_path, state_dir=state_dir,
                           node_id=node_id, socket_path=socket_path)
    server = ParametralServer(daemon.socket_path, daemon)
    print(json.dumps({"event": "listening", "socket": daemon.socket_path,
                      "node_id": node_id, "policy_version": daemon.policy.version,
                      "audit_head": daemon.audit.head}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        util.try_unlink(daemon.socket_path)
