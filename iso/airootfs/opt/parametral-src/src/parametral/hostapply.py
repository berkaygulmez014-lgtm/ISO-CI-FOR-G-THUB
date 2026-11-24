"""Tier-1 execution surface: a *closed* set of reviewed operations.

`v1.host.apply` must never become "run this argv as root". If it did, the AI could
hide a root shell inside an approved change and the root-owned signing key would
not save us. So the request does not carry a free-form command: it carries a
`argv` that has to match one of the presets below — exact prefix, validated
arguments, no shell, no metacharacters, no absolute paths, no flags we did not
enumerate.

The executor itself lands in phase 2; this module is the gate it will have to
pass, and it is tested now so the contract cannot drift into a generic executor.
"""
from __future__ import annotations

import re

MAX_STEPS = 8
MAX_TOKENS = 24


class HostApplyError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# Every token after the prefix must match the argument class of that preset.
PATTERNS = {
    # Arch package names / repo-qualified names ("extra/ripgrep"); no flags, no paths.
    "packages": re.compile(r"^[a-z0-9@][a-z0-9@._+-]{0,63}$"),
    "abs_packages": re.compile(r"^[a-z0-9@][a-z0-9@._+-]{0,63}$"),
    # nix flake refs only: nixpkgs#ripgrep, github:owner/repo#pkg
    "flake_refs": re.compile(r"^(nixpkgs|github:[A-Za-z0-9_.-]{1,39}/[A-Za-z0-9_.-]{1,39})"
                             r"#[A-Za-z0-9_.+-]{1,64}$"),
    "units": re.compile(r"^[A-Za-z0-9@:_.-]{1,64}\.(service|socket|timer|path)$"),
}

PRESETS = (
    {"kind": "pacman-install", "argv": ["pacman", "-S", "--noconfirm"], "args": "packages"},
    {"kind": "pacman-sync", "argv": ["pacman", "-Syu", "--noconfirm"], "args": None},
    {"kind": "pacman-remove", "argv": ["pacman", "-Rns", "--noconfirm"], "args": "packages"},
    {"kind": "nix-profile-install", "argv": ["nix", "profile", "install"], "args": "flake_refs"},
    {"kind": "nix-profile-remove", "argv": ["nix", "profile", "remove"], "args": "flake_refs"},
    {"kind": "home-manager", "argv": ["home-manager", "switch"], "args": None},
    {"kind": "systemd-enable", "argv": ["systemctl", "enable"], "args": "units"},
    {"kind": "systemd-disable", "argv": ["systemctl", "disable"], "args": "units"},
    {"kind": "systemd-start", "argv": ["systemctl", "start"], "args": "units"},
    {"kind": "systemd-stop", "argv": ["systemctl", "stop"], "args": "units"},
    {"kind": "systemd-restart", "argv": ["systemctl", "restart"], "args": "units"},
)

# Belt and braces: no interpreter ever appears in a tier-1 argv.
FORBIDDEN_TOKENS = {"sh", "bash", "zsh", "fish", "dash", "env", "eval", "exec", "source",
                    "-c", "--", "/bin/sh", "/bin/bash", "xargs", "sudo", "su", "doas"}
APPROVAL_RE = re.compile(r"^apr_[0-9a-f]{12}$")


def _match_preset(argv: list[str]):
    for preset in PRESETS:
        prefix = preset["argv"]
        if argv[:len(prefix)] == prefix:
            return preset
    return None


def validate(request: dict) -> dict:
    """Return a normalised request or raise HostApplyError. Never executes anything."""
    if not isinstance(request, dict):
        raise HostApplyError("INVALID_PARAMS", "host.apply request must be an object")

    intent = request.get("intent")
    if not isinstance(intent, str) or not intent.strip():
        raise HostApplyError("INVALID_PARAMS", "intent is required")
    if len(intent) > 200 or "\n" in intent:
        raise HostApplyError("INVALID_PARAMS", "intent must be a single line, <=200 chars")

    if request.get("snapshot") is not True:
        raise HostApplyError("INVALID_PARAMS",
                             "snapshot:true is mandatory for tier-1 changes "
                             "(no snapshot, no change)")

    approval_id = request.get("approval_id")
    if not isinstance(approval_id, str) or not APPROVAL_RE.match(approval_id):
        raise HostApplyError("APPROVAL_REQUIRED",
                             "tier-1 changes require an approved approval_id (apr_...)")

    steps = request.get("steps")
    if not isinstance(steps, list) or not steps:
        raise HostApplyError("INVALID_PARAMS", "steps must be a non-empty list")
    if len(steps) > MAX_STEPS:
        raise HostApplyError("INVALID_PARAMS", f"at most {MAX_STEPS} steps per change")

    normalised = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise HostApplyError("INVALID_PARAMS", f"step {index} must be an object")
        argv = step.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(t, str) for t in argv):
            raise HostApplyError("INVALID_PARAMS", f"step {index}: argv must be a string list")
        if len(argv) > MAX_TOKENS:
            raise HostApplyError("INVALID_PARAMS", f"step {index}: argv too long")
        for token in argv:
            if not token or any(char in token for char in " \t\n;|&$`<>()\\'\"*?[]{}"):
                raise HostApplyError("INVALID_PARAMS",
                                     f"step {index}: illegal character in {token!r}")
            if token in FORBIDDEN_TOKENS:
                raise HostApplyError("INVALID_PARAMS",
                                     f"step {index}: interpreter/shell token {token!r} is "
                                     "never allowed in a tier-1 change")
            if token.startswith("/") or token.startswith("~"):
                raise HostApplyError("INVALID_PARAMS",
                                     f"step {index}: absolute paths are not allowed ({token!r})")

        preset = _match_preset(argv)
        if preset is None:
            raise HostApplyError("INVALID_PARAMS",
                                 f"step {index}: argv {argv[:3]}… is not one of the reviewed "
                                 "operations; tier-1 has no generic exec path")

        arguments = argv[len(preset["argv"]):]
        if preset["args"] is None:
            if arguments:
                raise HostApplyError("INVALID_PARAMS",
                                     f"step {index}: {preset['kind']} takes no arguments")
        else:
            if not arguments:
                raise HostApplyError("INVALID_PARAMS",
                                     f"step {index}: {preset['kind']} needs arguments")
            pattern = PATTERNS[preset["args"]]
            for argument in arguments:
                if not pattern.match(argument):
                    raise HostApplyError("INVALID_PARAMS",
                                         f"step {index}: bad {preset['args']} value "
                                         f"{argument!r}")

        normalised.append({"kind": preset["kind"], "argv": list(argv)})

    return {"intent": intent.strip(), "approval_id": approval_id, "snapshot": True,
            "steps": normalised, "node_id": request.get("node_id")}
