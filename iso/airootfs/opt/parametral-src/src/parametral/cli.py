"""`parametral` command line: operator/approver surface + smoke-test tooling.

The AI talks JSON-RPC (client.py). This CLI exists for the human side: approve
or reject a request, verify the audit chain, inspect a sandbox, run the proof.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import shutil
import subprocess
import sys

from . import util
from . import anchor as anchor_mod
from . import harddeny as hd
from . import sysapply
from .approvals import ApprovalStore
from .client import Client, ClientError
from .daemon import SERVER_VERSION, ParametralDaemon
from .sandbox import SandboxManager


def _print(payload) -> None:
    if isinstance(payload, str):
        print(payload)
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))


def _client(args) -> Client:
    return Client(socket_path=args.socket, node_id=args.node_id)


def _token(args) -> str:
    token = getattr(args, "token", None) or os.environ.get("PARAMETRAL_TOKEN")
    if not token:
        raise SystemExit("this command needs --token or PARAMETRAL_TOKEN "
                         "(get one with `parametral perm request ...`)")
    return token


def _auto_token(args, client: Client, operation: str, scope: dict, justification: str) -> str:
    granted = client.request_permission(operation, scope, justification,
                                        ttl_s=getattr(args, "ttl", 600))
    return granted["capability_token"]


# --------------------------------------------------------------------- commands

def cmd_serve(args) -> int:
    daemon = ParametralDaemon(policy_path=args.policy, state_dir=args.state,
                           node_id=args.node_id, socket_path=args.socket,
                           harddeny_socket=args.harddeny_socket,
                           harddeny_rules=args.harddeny_rules)
    from .daemon import ParametralServer

    server = ParametralServer(daemon.socket_path, daemon)
    print(json.dumps({"event": "listening", "socket": daemon.socket_path,
                      "node_id": daemon.node_id, "policy_version": daemon.policy.version,
                      "audit_head": daemon.audit.head}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        util.try_unlink(daemon.socket_path)
    return 0


def _harddeny_paths(args):
    rules_path = args.rules or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "policy", hd.DEFAULT_RULES)
    sk_path = args.key or os.path.join(util.state_dir(), "keys", "hard_deny.ed25519.sk")
    pub_path = args.pub or os.path.join(os.path.dirname(rules_path), "hard_deny.v1.pub")
    socket_path = args.socket or os.path.join(util.runtime_dir(), "harddeny.sock")
    return rules_path, sk_path, pub_path, socket_path


def cmd_harddeny(args) -> int:
    rules_path, sk_path, pub_path, socket_path = _harddeny_paths(args)

    if args.action == "keygen":
        _secret, public = hd.ed25519_keygen(sk_path, pub_path)
        print(json.dumps({"secret_key": sk_path, "public_key": pub_path,
                          "key_id": hd.key_id(public),
                          "note": "signing key is root-owned in production; the oracle "
                                  "only ever reads the public key"}))
        return 0
    if args.action == "sign":
        print(f"signed {rules_path}\n{hd.sign_rules(rules_path, sk_path)}")
        return 0
    if args.action == "verify":
        engine = hd.load_rules(rules_path, pub_path)
        print(json.dumps({"verified": True, "rules": rules_path, "version": engine.version,
                          "signature": engine.sig, "body_sha256": engine.body_sha256,
                          "public_key": pub_path,
                          "rules_count": len(engine.rules["rules"])}))
        return 0
    if args.action == "check":
        scope = json.loads(args.scope) if args.scope else {}
        client = hd.HardDenyClient(socket_path)
        try:
            print(json.dumps(client.check(args.operation, scope), indent=2))
        except hd.HardDenyUnavailable as exc:
            print(json.dumps({"decision": "deny", "reason": str(exc),
                              "note": "fail-closed: oracle unreachable"}), file=sys.stderr)
            return 2
        return 0
    if args.action == "serve":
        allowed = {int(uid) for uid in (args.allow_uid or [os.getuid()])}
        return hd.serve(rules_path, pub_path, socket_path, allowed_uids=allowed)
    raise SystemExit(f"unknown harddeny action {args.action}")


def cmd_host(args) -> int:
    spool = args.spool or os.path.join(util.runtime_dir(), "jobs")
    results = args.results or os.path.join(util.runtime_dir(), "results")
    pub = args.approver_pub or os.path.join(util.runtime_dir(), "approver.pub")
    sk = args.key or os.path.join(util.runtime_dir(), "approver.sk")
    queue = sysapply.JobQueue(spool, results)

    if args.action == "pending":
        pending = queue.pending_jobs()
        _print({"pending": [queue.read_pending(job) for job in pending]})
        return 0
    if args.action == "sign":
        if not args.job_id:
            raise SystemExit("host sign needs a job id (see `parametral host pending`)")
        _print({"signed": args.job_id, **queue.sign_pending(args.job_id, sk)})
        return 0
    if args.action == "result":
        if not args.job_id:
            raise SystemExit("host result needs a job id")
        _print(queue.result(args.job_id) or {"state": "unknown", "job_id": args.job_id})
        return 0
    if args.action in ("run-once", "serve"):
        runner = sysapply.JobRunner(spool, results, approver_pub_path=pub)
        if args.action == "run-once":
            _print({"results": runner.run_once()})
            return 0
        print(json.dumps({"event": "sysapply-listening", "spool": spool,
                          "results": results, "approver_pub": pub}), flush=True)
        try:
            while True:
                for result in runner.run_once():
                    print(json.dumps({"event": "job", **result}), flush=True)
                time.sleep(1)
        except KeyboardInterrupt:
            return 0
    raise SystemExit(f"unknown host action {args.action}")


def cmd_status(args) -> int:
    with _client(args) as client:
        _print(client.status())
    return 0


def cmd_hello(args) -> int:
    with _client(args) as client:
        _print(client.hello())
    return 0


def cmd_sandbox_create(args) -> int:
    limits = {"cpu_cores": args.cpu, "memory_mb": args.mem, "pids": args.pids,
              "disk_mb": args.disk}
    scope = {"sandbox_id": None}
    with _client(args) as client:
        token = args.token or os.environ.get("PARAMETRAL_TOKEN")
        if not token or args.auto_permission:
            token = _auto_token(args, client, "sandbox.create", {}, "create sandbox")
        result = client.call("v1.sandbox.create", name=args.name, limits=limits,
                             profile=args.profile, net=args.net,
                             capability_token=token)
        _print(result)
    return 0


def cmd_sandbox_list(args) -> int:
    with _client(args) as client:
        _print(client.call("v1.sandbox.list"))
    return 0


def cmd_sandbox_status(args) -> int:
    with _client(args) as client:
        _print(client.call("v1.sandbox.status", sandbox_id=args.sandbox_id))
    return 0


def cmd_sandbox_destroy(args) -> int:
    with _client(args) as client:
        token = args.token or os.environ.get("PARAMETRAL_TOKEN")
        if not token or args.auto_permission:
            token = _auto_token(args, client, "sandbox.destroy",
                                {"sandbox_id": args.sandbox_id}, "destroy sandbox")
        _print(client.call("v1.sandbox.destroy", sandbox_id=args.sandbox_id,
                           purge=not args.keep, capability_token=token))
    return 0


def cmd_exec(args) -> int:
    command = args.command[1:] if args.command and args.command[0] == "--" else args.command
    if not command:
        raise SystemExit("exec needs a command: parametral exec <sandbox> -- cmd ...")
    with _client(args) as client:
        token = args.token or os.environ.get("PARAMETRAL_TOKEN")
        if not token or args.auto_permission:
            token = _auto_token(args, client, "exec.run",
                                {"sandbox_id": args.sandbox_id,
                                 "commands": [os.path.basename(command[0])]},
                                "run %s" % command[0])
        result = client.call("v1.exec.run", sandbox_id=args.sandbox_id, cmd=command,
                             timeout_s=args.timeout, capability_token=token,
                             cwd=args.cwd)
        if args.json:
            _print(result)
        else:
            sys.stdout.write(result["stdout"])
            sys.stderr.write(result["stderr"])
            if result["timed_out"]:
                print("[timed out]", file=sys.stderr)
            print(f"[exit={result['exit_code']} {result['duration_ms']}ms "
                  f"quota={result['quota_backend']}]", file=sys.stderr)
        return 0 if result["exit_code"] == 0 else 1


def cmd_fs(args) -> int:
    with _client(args) as client:
        token = args.token or os.environ.get("PARAMETRAL_TOKEN")
        if not token or args.auto_permission:
            operation = "fs.read" if args.action in ("read", "ls") else "fs.write"
            token = _auto_token(args, client, operation,
                                {"sandbox_id": args.sandbox_id, "paths": [args.path]},
                                f"fs {args.action}")
        if args.action == "read":
            _print(client.call("v1.fs.read", sandbox_id=args.sandbox_id, path=args.path,
                               capability_token=token))
        elif args.action == "ls":
            _print(client.call("v1.fs.list", sandbox_id=args.sandbox_id, path=args.path,
                               capability_token=token))
        else:
            content = sys.stdin.read() if args.path_or_content is None else args.path_or_content
            _print(client.call("v1.fs.write", sandbox_id=args.sandbox_id, path=args.path,
                               content=content, capability_token=token))
    return 0


def cmd_policy_explain(args) -> int:
    scope = json.loads(args.scope) if args.scope else {}
    with _client(args) as client:
        _print(client.call("v1.policy.explain", operation=args.operation, scope=scope))
    return 0


def cmd_perm_request(args) -> int:
    scope = {}
    if args.sandbox_id:
        scope["sandbox_id"] = args.sandbox_id
    if args.commands:
        scope["commands"] = args.commands
    if args.paths:
        scope["paths"] = args.paths
    with _client(args) as client:
        result = client.request_permission(args.operation, scope,
                                           args.justification, ttl_s=args.ttl,
                                           approval_id=args.approval_id)
        _print(result)
    return 0


def cmd_approvals(args) -> int:
    state_dir = util.state_dir() if not args.state else args.state
    store = ApprovalStore(state_dir, os.path.join(util.runtime_dir(), "approver.pub"),
                          node_id=args.node_id,
                          approver_sk_path=os.path.join(util.runtime_dir(), "approver.sk"))
    if args.action == "keygen":
        from . import ed25519 as _ed

        sk = args.key or os.path.join(util.runtime_dir(), "approver.sk")
        pub = args.pub or os.path.join(util.runtime_dir(), "approver.pub")
        _secret, public = _ed.keygen(sk, pub)
        _print({"signing_key": sk, "public_key": pub, "key_id": _ed.key_id(public)})
        return 0
    if args.action == "list":
        _print({"approvals": store.list(state=args.state_filter)})
        return 0
    if args.action == "get":
        _print(store.get(args.approval_id))
        return 0
    decision_word = {"approve": "approved", "reject": "rejected", "defer": "deferred"}[args.action]
    with _client(args) as client:
        proof = store.proof(args.approval_id, decision_word)
        _print(client.call("v1.approvals.decide", approval_id=args.approval_id,
                           decision=args.action, approver_proof=proof,
                           decided_by=args.decided_by, reason=args.reason))
    return 0


def cmd_audit(args) -> int:
    if args.action in ("anchor", "anchor-verify"):
        from .audit import AuditLog

        state = args.state or util.state_dir()
        out = args.out or os.path.join(state, "anchors")
        sk = args.key or os.path.join(state, "keys", "anchor.ed25519.sk")
        pub = args.pub or os.path.join(state, "keys", "anchor.ed25519.pub")
        audit = AuditLog(os.path.join(state, "audit"), node_id=args.node_id)
        try:
            if args.action == "anchor":
                record = anchor_mod.write_anchor(audit, out, sk, node_id=args.node_id)
                _print({"anchored": True, "seq": record["payload"]["seq"],
                        "head_hash": record["payload"]["head_hash"],
                        "key_id": record["key_id"], "out": out})
                return 0
            result = anchor_mod.verify_anchors(audit, out, pub)
            _print(result)
            return 0 if (result["signatures_ok"] and result["chain_matches"]) else 1
        except (anchor_mod.AnchorError, Exception) as exc:  # surfaced, never swallowed
            print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
            return 2
    with _client(args) as client:
        if args.action == "verify":
            _print(client.call("v1.audit.verify"))
        else:
            token = args.token or os.environ.get("PARAMETRAL_TOKEN")
            if not token or args.auto_permission:
                token = _auto_token(args, client, "audit.read", {}, "read audit log")
            _print(client.call("v1.audit.query", from_seq=args.from_seq, limit=args.limit,
                               capability_token=token))
    return 0


def cmd_proof(args) -> int:
    from .proof import run_proof

    passed, report, raw = run_proof(output_path=args.output, keep_sandbox=args.keep)
    print(report)
    print(f"[proof written to {raw['report_path']}]")
    return 0 if passed else 1


def cmd_doctor(args) -> int:
    checks = {}
    checks["bwrap"] = shutil.which("bwrap") or "MISSING"
    checks["python"] = sys.version.split()[0]
    checks["seccomp_guard"] = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "bin", "seccomp_guard")
    checks["seccomp_guard_built"] = os.access(checks["seccomp_guard"], os.X_OK)
    checks["cgroup_v2"] = os.path.exists("/sys/fs/cgroup/cgroup.controllers")
    manager = SandboxManager(util.state_dir(), defaults={})
    root = manager._cgroup_root()
    checks["cgroup_delegated"] = bool(root)
    checks["cgroup_base"] = root
    checks["policy"] = util.policy_path()
    checks["policy_loads"] = True
    try:
        from .policy import Policy

        policy = Policy(util.policy_path())
        checks["policy_version"] = policy.version
        checks["policy_rules"] = len(policy.rules)
    except Exception as exc:  # doctor reports, never hides
        checks["policy_loads"] = f"{type(exc).__name__}: {exc}"
    checks["root_fs"] = subprocess.run(["findmnt", "-no", "FSTYPE", "/"],
                                       capture_output=True, text=True).stdout.strip()
    checks["userns_available"] = os.path.exists("/proc/sys/kernel/unprivileged_userns_clone")
    _print(checks)
    ok = checks["seccomp_guard_built"] and checks["cgroup_v2"] and checks["policy_loads"] is True
    return 0 if ok else 1


# ----------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="parametral", description="Parametral OS control CLI")
    parser.add_argument("--socket", default=None, help="control socket path")
    parser.add_argument("--state", default=None, help="state directory")
    parser.add_argument("--node-id", default="local")
    parser.add_argument("--version", action="version", version=f"parametral {SERVER_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the daemon in the foreground")
    serve.add_argument("--policy", default=None)
    serve.add_argument("--harddeny-socket", default=None,
                       help="tier-2 oracle socket (default: $XDG_RUNTIME_DIR/parametral/harddeny.sock)")
    serve.add_argument("--harddeny-rules", default=None)
    serve.set_defaults(func=cmd_serve)

    sub.add_parser("status", help="node status").set_defaults(func=cmd_status)
    sub.add_parser("hello", help="handshake").set_defaults(func=cmd_hello)
    sub.add_parser("doctor", help="environment diagnostics").set_defaults(func=cmd_doctor)

    host = sub.add_parser("host", help="tier-1 signed-job executor (sysapply)")
    host.add_argument("action", choices=["pending", "sign", "result", "run-once", "serve"])
    host.add_argument("job_id", nargs="?", default=None)
    host.add_argument("--spool", default=None)
    host.add_argument("--results", default=None)
    host.add_argument("--approver-pub", default=None)
    host.add_argument("--key", default=None, help="approver private key (sign only)")
    host.set_defaults(func=cmd_host)

    hard = sub.add_parser("harddeny", help="tier-2 deterministic deny oracle")
    hard.add_argument("action", choices=["serve", "check", "keygen", "sign", "verify"])
    hard.add_argument("operation", nargs="?", default=None)
    hard.add_argument("--scope", default=None, help="JSON scope for check")
    hard.add_argument("--rules", default=None)
    hard.add_argument("--key", default=None, help="Ed25519 signing key (private)")
    hard.add_argument("--pub", default=None, help="Ed25519 public key (oracle side)")
    hard.add_argument("--socket", default=None)
    hard.add_argument("--allow-uid", action="append", default=None, type=int,
                      help="uid allowed to query the oracle (repeatable; default: self)")
    hard.set_defaults(func=cmd_harddeny)

    sandbox = sub.add_parser("sandbox", help="sandbox lifecycle")
    sandbox_sub = sandbox.add_subparsers(dest="action", required=True)
    create = sandbox_sub.add_parser("create")
    create.add_argument("name")
    create.add_argument("--cpu", type=float, default=1.0)
    create.add_argument("--mem", type=int, default=512)
    create.add_argument("--pids", type=int, default=128)
    create.add_argument("--disk", type=int, default=256)
    create.add_argument("--profile", default="strict")
    create.add_argument("--net", action="store_true")
    create.add_argument("--token")
    create.add_argument("--ttl", type=int, default=600)
    create.add_argument("--auto-permission", action="store_true")
    create.set_defaults(func=cmd_sandbox_create)
    sandbox_sub.add_parser("list").set_defaults(func=cmd_sandbox_list)
    status = sandbox_sub.add_parser("status")
    status.add_argument("sandbox_id")
    status.set_defaults(func=cmd_sandbox_status)
    destroy = sandbox_sub.add_parser("destroy")
    destroy.add_argument("sandbox_id")
    destroy.add_argument("--keep", action="store_true")
    destroy.add_argument("--token")
    destroy.add_argument("--ttl", type=int, default=600)
    destroy.add_argument("--auto-permission", action="store_true")
    destroy.set_defaults(func=cmd_sandbox_destroy)

    exec_parser = sub.add_parser("exec", help="run a command inside a sandbox")
    exec_parser.add_argument("sandbox_id")
    exec_parser.add_argument("--cwd", default="/work")
    exec_parser.add_argument("--timeout", type=int, default=30)
    exec_parser.add_argument("--token")
    exec_parser.add_argument("--ttl", type=int, default=600)
    exec_parser.add_argument("--auto-permission", action="store_true")
    exec_parser.add_argument("--json", action="store_true")
    exec_parser.add_argument("command", nargs=argparse.REMAINDER)
    exec_parser.set_defaults(func=cmd_exec)

    fs = sub.add_parser("fs", help="sandbox file operations")
    fs_sub = fs.add_subparsers(dest="action", required=True)
    for action in ("read", "ls"):
        item = fs_sub.add_parser(action)
        item.add_argument("sandbox_id")
        item.add_argument("path")
        item.add_argument("--token")
        item.add_argument("--ttl", type=int, default=600)
        item.add_argument("--auto-permission", action="store_true")
        item.set_defaults(func=cmd_fs)
    write = fs_sub.add_parser("write")
    write.add_argument("sandbox_id")
    write.add_argument("path")
    write.add_argument("path_or_content", nargs="?", default=None)
    write.add_argument("--token")
    write.add_argument("--ttl", type=int, default=600)
    write.add_argument("--auto-permission", action="store_true")
    write.set_defaults(func=cmd_fs)

    policy = sub.add_parser("policy", help="policy inspection")
    policy_sub = policy.add_subparsers(dest="action", required=True)
    explain = policy_sub.add_parser("explain")
    explain.add_argument("operation")
    explain.add_argument("--scope", default=None, help="JSON scope")
    explain.set_defaults(func=cmd_policy_explain)

    perm = sub.add_parser("perm", help="capability requests")
    perm_sub = perm.add_subparsers(dest="action", required=True)
    request = perm_sub.add_parser("request")
    request.add_argument("operation")
    request.add_argument("--sandbox-id", default=None)
    request.add_argument("--command", dest="commands", action="append", default=None)
    request.add_argument("--path", dest="paths", action="append", default=None)
    request.add_argument("--ttl", type=int, default=600)
    request.add_argument("--justification", default="operator request")
    request.add_argument("--approval-id", default=None)
    request.set_defaults(func=cmd_perm_request)

    approvals = sub.add_parser("approvals", help="human approval gate")
    approvals_sub = approvals.add_subparsers(dest="action", required=True)
    keygen = approvals_sub.add_parser("keygen", help="create the approver Ed25519 keypair")
    keygen.add_argument("--key", default=None)
    keygen.add_argument("--pub", default=None)
    keygen.set_defaults(func=cmd_approvals)
    listing = approvals_sub.add_parser("list")
    listing.add_argument("--state-filter", default=None)
    listing.set_defaults(func=cmd_approvals)
    get = approvals_sub.add_parser("get")
    get.add_argument("approval_id")
    get.set_defaults(func=cmd_approvals)
    for action in ("approve", "reject", "defer"):
        item = approvals_sub.add_parser(action)
        item.add_argument("approval_id")
        item.add_argument("--reason", default=None)
        item.add_argument("--decided-by", default="user:" + os.environ.get("USER", "local"))
        item.set_defaults(func=cmd_approvals)

    audit = sub.add_parser("audit", help="audit trail")
    audit_sub = audit.add_subparsers(dest="action", required=True)
    audit_sub.add_parser("verify").set_defaults(func=cmd_audit)
    for action in ("anchor", "anchor-verify"):
        item = audit_sub.add_parser(action)
        item.add_argument("--out", default=None, help="anchor directory (off-host target)")
        item.add_argument("--key", default=None)
        item.add_argument("--pub", default=None)
        item.set_defaults(func=cmd_audit)
    tail = audit_sub.add_parser("tail")
    tail.add_argument("--from-seq", type=int, default=1)
    tail.add_argument("--limit", type=int, default=20)
    tail.add_argument("--token")
    tail.add_argument("--ttl", type=int, default=600)
    tail.add_argument("--auto-permission", action="store_true")
    tail.set_defaults(func=cmd_audit)

    proof = sub.add_parser("proof", help="run the isolation proof")
    proof.add_argument("--output", default=None)
    proof.add_argument("--keep", action="store_true")
    proof.set_defaults(func=cmd_proof)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ClientError as exc:
        print(json.dumps({"error": {"code": exc.code, "message": exc.message,
                                    "data": exc.data}}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
