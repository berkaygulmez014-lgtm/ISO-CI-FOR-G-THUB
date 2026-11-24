"""Isolation proof: run a probe inside a sandbox and show what it can and cannot do.

This is the evidence behind the claim "hello world runs isolated, network is
closed, the host is unreachable". Every line of the report is produced by a real
exit code or errno from inside the sandbox — nothing in here is asserted by hand.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import tempfile

from . import util
from .sandbox import SandboxManager

PROBE = r'''
import ctypes, json, os, socket, sys

checks = {}

def check(name, ok, detail):
    checks[name] = {"ok": bool(ok), "detail": str(detail)[:300]}

print("HELLO FROM SANDBOX")

# --- identity / privileges -------------------------------------------------
status = ""
try:
    status = open("/proc/self/status").read()
except OSError as exc:
    check("proc_self_readable", False, exc)
capeff = "?"
for line in status.splitlines():
    if line.startswith("CapEff"):
        capeff = line.split()[1]
check("no_capabilities", capeff in ("0000000000000000", "0"), "CapEff=%s" % capeff)
check("not_root", os.getuid() != 0, "uid=%s" % os.getuid())
check("no_new_privs", "NoNewPrivs:\t1" in status or "NoNewPrivs: 1" in status,
      [l for l in status.splitlines() if l.startswith("NoNewPrivs")])

# --- network ---------------------------------------------------------------
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(4)
    sock.connect(("1.1.1.1", 80))
    check("network_closed", False, "connected to 1.1.1.1:80")
except OSError as exc:
    check("network_closed", True, "%s" % exc)
check("dns_absent", not os.path.exists("/etc/resolv.conf"),
      "/etc/resolv.conf present" if os.path.exists("/etc/resolv.conf") else "absent")

# --- host filesystem invisible --------------------------------------------
for path in __HIDDEN_PATHS__:
    check("hidden:" + path, not os.path.exists(path),
          "exists!" if os.path.exists(path) else "ENOENT")
check("home_only_sandbox_user", sorted(os.listdir("/home")) == ["user"], os.listdir("/home"))
check("sysfs_absent", not os.path.exists("/sys"), "absent" if not os.path.exists("/sys") else "visible")

# --- host filesystem read-only --------------------------------------------
try:
    with open("/etc/passwd", "ab") as handle:
        handle.write(b"pwned\n")
    check("etc_readonly", False, "wrote to /etc/passwd")
except OSError as exc:
    check("etc_readonly", True, exc)
try:
    with open("/usr/local/bin/probe-write", "wb") as handle:
        handle.write(b"x")
    check("usr_readonly", False, "wrote into /usr")
except OSError as exc:
    check("usr_readonly", True, exc)

# --- kernel attacks blocked by seccomp ------------------------------------
libc = ctypes.CDLL("libc.so.6", use_errno=True)
result = libc.mount(b"/tmp", b"/tmp", b"tmpfs", 0, None)
check("mount_blocked", result == -1 and ctypes.get_errno() == 1,
      "rc=%s errno=%s" % (result, ctypes.get_errno()))
result = libc.ptrace(0, 0, None, None)
check("ptrace_blocked", result == -1 and ctypes.get_errno() == 1,
      "rc=%s errno=%s" % (result, ctypes.get_errno()))
result = libc.sethostname(b"pwned", 5)
check("sethostname_blocked", result == -1, "rc=%s errno=%s" % (result, ctypes.get_errno()))

# --- pid namespace --------------------------------------------------------
pids = sorted(int(entry) for entry in os.listdir("/proc") if entry.isdigit())
check("pid_ns_small", len(pids) <= 5, pids)
# Host PID 1 (systemd/init) must not be reachable from here.
visible = []
for pid in pids:
    try:
        cmdline = open("/proc/%d/cmdline" % pid, "rb").read().decode("utf-8", "replace")
    except OSError:
        continue
    lowered = cmdline.lower()
    if "systemd" in lowered or "/sbin/init" in lowered:
        visible.append(cmdline)
check("host_init_invisible", not visible, visible or "PID 1 of this namespace is our own init")

# --- the sandbox itself is writable --------------------------------------
try:
    with open("/work/probe-write.txt", "w") as handle:
        handle.write("ok\n")
    check("sandbox_writable", True, "/work/probe-write.txt")
except OSError as exc:
    check("sandbox_writable", False, exc)

print("PROBE_JSON " + json.dumps(checks))
'''

REPORT_HEADER = """Parametral OS — sandbox isolation proof
generated: {generated}
host: {host}   kernel: {kernel}
bubblewrap: {bwrap_version}
sandbox: {sandbox_id}  profile={profile}  limits={limits}
command: {command}
quota backend: {quota}

"""


def _bwrap_version() -> str:
    try:
        proc = subprocess.run(["bwrap", "--version"], capture_output=True, text=True, timeout=10)
        return (proc.stdout or proc.stderr).strip()
    except (OSError, subprocess.SubprocessError):
        return "not installed"


def run_proof(state_dir: str | None = None, output_path: str | None = None,
              keep_sandbox: bool = False) -> tuple[bool, str, dict]:
    """Run the probe inside a real sandbox. Returns (passed, report_text, raw)."""
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    workdir = state_dir or tempfile.mkdtemp(prefix="parametral-proof-",
                                            dir=os.environ.get("TMPDIR") or None)
    canary_dir = os.path.join(workdir, "host-canary")
    util.ensure_dir(canary_dir, 0o700)
    canary = os.path.join(canary_dir, "canary.txt")
    util.atomic_write(canary, b"HOST-SECRET-CANARY\n", mode=0o600)

    hidden = [os.path.expanduser("~"), "/root", "/etc/shadow", canary, here]
    manager = SandboxManager(workdir, node_id="local", defaults={
        "cpu_cores": 1.0, "memory_mb": 512, "pids": 128, "disk_mb": 64})
    meta = manager.create(name="isolation-proof", profile="strict")
    sandbox_id = meta["sandbox_id"]
    probe_path = os.path.join(meta["root"], "probe.py")
    util.atomic_write(probe_path, PROBE.replace("__HIDDEN_PATHS__", repr(hidden)).encode(), mode=0o644)

    try:
        result = manager.run(sandbox_id, ["python3", "/work/probe.py"], timeout_s=60)
    finally:
        if not keep_sandbox:
            manager.destroy(sandbox_id, purge=True)

    checks: dict = {}
    for line in result["stdout"].splitlines():
        if line.startswith("PROBE_JSON "):
            checks = json.loads(line[len("PROBE_JSON "):])
    if not checks:
        checks = {"probe_executed": {"ok": False,
                                     "detail": (result["stderr"] or "no probe output")[:300]}}

    expected = ["no_capabilities", "not_root", "no_new_privs", "network_closed", "dns_absent",
                "home_only_sandbox_user", "sysfs_absent", "etc_readonly", "usr_readonly",
                "mount_blocked", "ptrace_blocked", "sethostname_blocked", "pid_ns_small",
                "host_init_invisible", "sandbox_writable"]
    hidden_checks = [name for name in checks if name.startswith("hidden:")]
    passed = (all(checks.get(name, {}).get("ok") for name in expected)
              and len(hidden_checks) == len(hidden)
              and all(checks[name]["ok"] for name in hidden_checks))

    lines = [REPORT_HEADER.format(
        generated=util.iso(),
        host=platform.node(),
        kernel=platform.release(),
        bwrap_version=_bwrap_version(),
        sandbox_id=sandbox_id,
        profile=meta["profile"],
        limits=json.dumps(meta["limits"], sort_keys=True),
        command=" ".join(["python3", "/work/probe.py"]),
        quota=result.get("quota_backend", "?"),
    )]
    width = max(len(name) for name in checks) if checks else 10
    for name in sorted(checks):
        item = checks[name]
        lines.append(f"  [{'PASS' if item['ok'] else 'FAIL'}] {name.ljust(width)}  {item['detail']}")

    lines.append("")
    lines.append(f"exit_code={result['exit_code']} duration_ms={result['duration_ms']} "
                 f"timed_out={result['timed_out']} truncated={result['truncated']}")
    lines.append("")
    lines.append("--- probe stdout ---")
    lines.extend(result["stdout"].rstrip().splitlines() or ["(empty)"])
    if result["stderr"].strip():
        lines.append("--- probe stderr ---")
        lines.extend(result["stderr"].rstrip().splitlines())
    lines.append("")
    lines.append("RESULT: " + ("PASS — sandbox is isolated as specified"
                               if passed else "FAIL — see failed checks above"))

    report = "\n".join(lines) + "\n"
    # Default next to the *state*, not next to the installed code: the service runs as an
    # unprivileged user and cannot write into the install tree.
    default_root = os.environ.get("PARAMETRAL_STATE") or os.path.join(
        os.path.expanduser("~"), ".local", "share", "parametral")
    target = output_path or os.path.join(default_root, "proofs", "isolation-proof.txt")
    util.ensure_dir(os.path.dirname(target), 0o755)
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(report)
    raw = {"checks": checks, "result": result, "sandbox": meta, "report_path": target}
    return passed, report, raw
