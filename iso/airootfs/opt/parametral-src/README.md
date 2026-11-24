<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/parametral-mark-512.png">
  <source media="(prefers-color-scheme: light)" srcset="assets/parametral-mark-light.svg">
  <img src="assets/parametral-mark-512.png" width="168" alt="Parametral OS">
</picture>

<h1>Parametral OS</h1>

<p><b>An Arch + Nix system an AI can operate — but never own.</b></p>

<p>
  <img alt="tests" src="https://img.shields.io/badge/tests-272%20passing-brightgreen">
  <img alt="api" src="https://img.shields.io/badge/api-v1.2-blue">
  <img alt="sandbox" src="https://img.shields.io/badge/sandbox-bwrap%20%2B%20seccomp%20%2B%20cgroup%20v2-informational">
  <img alt="platform" src="https://img.shields.io/badge/platform-Arch%20%2B%20Nix-1793d1">
</p>

<p><sub>Arch · Nix · bubblewrap · cgroup v2 · btrfs · Ed25519 · Python 3.12+ (stdlib only)</sub></p>

</div>

The AI is treated as untrusted code with good intentions. It gets one JSON-RPC socket, a
short-lived capability token per operation, a sandbox per job, and a human gate for anything
that touches the real machine. A separate deterministic oracle refuses a fixed set of
irreversible operations before policy, tokens or approvals are even consulted. Every accepted,
refused and critical request lands in a hash-chained audit log.

Nothing here is a chatbot feature. This is the part that decides whether an autonomous agent is
allowed to run `rm -rf` on your machine — and it answers "no" from a place the model cannot reach.

## Target vs today

| | target | today |
|---|---|---|
| AI installs an app | Tier 0: sandboxed, no human | pipeline implemented: Nix install → verify → ≤3 attempts → honest report; nix CLI stubbed in tests (real nix lands with the Arch image) |
| AI changes the real system | Tier 1: approval + snapshot, closed preset list | implemented: approver-signed job → `sysapply` (root); tested with a stubbed pacman |
| catastrophic command | Tier 2: deterministic refusal | implemented, Ed25519-signed, fail-closed |
| rollback | one command | sandbox snapshots/restore work (btrfs, unprivileged); host-level needs the root helper |
| distribution image | bootable Arch + Nix ISO | install kit ready (`install/`, UEFI+LUKS+btrfs, both kernels, snapshot hooks, KDE/Hyprland choice); ISO build is roadmap A1 |

## Desktop editions

The installer asks one question: **KDE Plasma** or **Hyprland** (the Parametral session).
Either answer installs the same palette, wallpaper, fonts, user separation and SDDM greeter;
only the compositor and its shell differ.

| | KDE Plasma | Hyprland (Parametral) |
|---|---|---|
| session | stock `plasma.desktop` | `parametral.desktop` → `uwsm` + `start-hyprland` |
| shell | Plasma panel + Kickoff | Noctalia (MIT) with our palette, bar plate and launcher mark |
| config | KConfig under `~/.config` | Lua modules under `/etc/parametral/hypr` |
| best for | familiar full desktop, settings UI | a desktop the AI can read, change and snapshot as text |

`both` is available for VMs and side-by-side review; SDDM preselects the edition you pick.
After install, `parametral-desktop status` shows the answer and `parametral-desktop default
<session>` changes the greeter default. The dispatcher is `install/74-desktop.sh`; the
edition modules are `install/desktop/{kde,hyprland}.sh`.

## Phase status

| phase | contents | state |
|---|---|---|
| 1 | API v1.2, policy engine, tokens, approvals, audit chain, bwrap sandbox, exec/fs, tier-2 oracle, snapshots, `app.install` pipeline, CLI | **done** — 148 tests, isolation proof |
| 2 | `app.install` + `host.apply` — **done**; `host.nix_profile` executor, artifact installs, real-nix run on the Arch image remain | in progress |
| 3 | btrfs qgroup disk quota per sandbox, streaming output limits | planned |
| 4 | host-level snapshots via root helper, off-host audit anchor | planned |
| 5 | microVM profile (`profile:"microvm"`), multi-node (methods reserved, no swarm code) | reserved |

## How a request is decided

```
hard-deny oracle  →  policy (default deny)  →  capability token  →  handler  →  audit
 deterministic          allow / approval        Ed25519 + TTL       sandbox    hash chain
 signed, read-only      no rule → deny          scope + use cap     cgroup     tamper-evident
```

- **GC Shield** is in-model training (adversarial examples + DPO refusals). Soft, probabilistic,
  no socket — nothing in this repo queries it.
- **Oracle** (`parametral-harddeny`) is a separate process: signed read-only rules, public-key verification,
  `SO_PEERCRED`-gated socket, self-closing if its rules change at runtime, fail-closed if absent.
- **Tiers**: 0 = sandbox / rootless Nix profile (no human), 1 = real system write (approval +
  snapshot, reviewed presets only), 2 = hard-deny list (no approval path exists).

## Layout

| path | what |
|---|---|
| `docs/API-v1.md` | the wire contract, frozen v1.2.0 — the AI codes against this |
| `docs/ARCHITECTURE.md` | three layers, three tiers, trust boundaries, honest limitations |
| `docs/ROADMAP.md` | three-actor plan v0.3: Arch base / AI / this layer / OS mind |
| `src/parametral/` | gateway, policy, tokens, approvals, audit, sandbox, oracle, `appinstall`, `sysapply`, `netproxy`, `anchor`, `quota` |
| `src/parametral_guard.c` | in-sandbox seccomp + rlimit guard (compiled to `bin/seccomp_guard`) |
| `policy/policy.v1.json` | allow/approval rules, default deny |
| `policy/hard_deny.v1.json` + `.sig` + `.v1.pub` | tier-2 list, Ed25519-signed |
| `tests/` | 272 unittest cases, no third-party deps |
| `install/` | Arch install kit: disk+LUKS, users, snapshots, boot, desktop edition choice (`74-desktop.sh`), `70-verify.sh` evidence |
| `src/tools/parametral-snapshot` | create / list / boot-entry / promote / prune rollback tool |
| `assets/` | mark: delivered raster (transparent) for dark, flat vector for light |
| `proofs/isolation-proof.txt` | generated isolation evidence (20+ checks) |

## Build and run (fish)

```fish
cd ~/Desktop/Development/parametral-os
make guard                 # static seccomp guard
make test                  # 272 tests, expect "OK"
make proof                 # writes proofs/isolation-proof.txt, expect "RESULT: PASS"
bash scripts/smoke.sh      # two real processes, real sockets, expect "SMOKE OK"
```

Run it for real (two units in production, two terminals here):

```fish
bin/harddeny keygen        # once: Ed25519 keypair; private key stays with the operator
bin/harddeny sign          # sign policy/hard_deny.v1.json
bin/harddeny verify        # verify with the public key only
bin/parametral-harddeny              # terminal 1: tier-2 oracle
bin/parametrald               # terminal 2: gateway

bin/parametral status
bin/parametral sandbox create demo --auto-permission
bin/parametral exec <sandbox_id> --auto-permission -- wipefs -a /dev/sda   # refused, tier 2
bin/parametral audit verify
```

## The API in four lines

```json
{"jsonrpc":"2.0","id":"1","method":"v1.node.hello","params":{"node_id":"local"}}
{"jsonrpc":"2.0","id":"2","method":"v1.sandbox.create","params":{"node_id":"local","name":"demo","capability_token":"u1.…"}}
{"jsonrpc":"2.0","id":"3","method":"v1.exec.run","params":{"node_id":"local","sandbox_id":"sbx_l_…","cmd":["rg","--version"],"capability_token":"u1.…"}}
{"jsonrpc":"2.0","id":"4","method":"v1.fs.write","params":{"node_id":"local","sandbox_id":"sbx_l_…","path":"/work/a.txt","content":"hi","capability_token":"u1.…"}}
```

Every response carries `node_id`-scoped results; errors carry stable `parametral_code` values
(`POLICY_DENIED`, `TOKEN_REQUIRED`, `APPROVAL_REQUIRED`, `HARD_DENY_UNAVAILABLE`, …).

## Invariants that have tests

- A **valid token cannot override a tier-2 rule** (`test_valid_token_cannot_override_hard_deny`).
- **Oracle down ⇒ everything state-changing is refused**, diagnostics still answer (`OracleDownTest`).
- Sandbox: no network, no host home, read-only `/usr`, `CapEff=0`, uid≠0, `mount`/`ptrace` EPERM
  (`tests/test_sandbox_isolation.py`, `proofs/`).
- **Tier-1 has no generic exec path**: interpreters, absolute paths, metacharacters and unknown
  flags are refused (`tests/test_hostapply.py`).
- Rules that change while the oracle runs stop it (`RuntimeFileWatchTest`); foreign uid on the
  oracle socket is refused (`PeerCredentialTest`).
- Every accepted/denied/critical request appends one audit record; edits, deletions and truncation
  are detected (`tests/test_audit.py`).
- No bare `except:` in `src/` — failures surface, they are not swallowed.

## Roadmap

| line | what | state |
|---|---|---|
| **A** | Arch base: btrfs (`@`/`@home`/`@var`/`@snapshots`), LUKS, both kernels, 4-user separation | install kit done (`install/`), ISO build pending |
| **B** | Nix-first `app.install`: install → verify → ≤3 attempts → honest report; `home-manager` (tier 0) | `app.install` done (stubbed nix in tests); `host.nix_profile` pending |
| **C** | Tier-1: approval → approver-signed job → `sysapply` (root) → snapshot → preset-only run | done and tested; enable as a unit on the image |
| **D** | hardening: per-app network allowlist, btrfs qgroup quota, off-host audit anchor, CI | implemented and tested; nftables belt + CI run land with the image |
| **E** | later: microVM profile, multi-node, 80B cloud model (separate product) | reserved, no code |
| **F** | OS mind: experience-store schema (F0), 10 small expert runtime (F1), expert training (F2) | runtime side is ours, training side is theirs |

Full detail, owners and "done" criteria: [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Scope: the AI is not in this repository

This repo is the **OS half**: gateway, policy, oracle, sandbox, snapshots, audit, tier-1 executor,
install kit. It exposes one contract (`docs/API-v1.md`) and executes nothing the contract does not
name.

The other half — the model family, GC Shield training, the agent loop, the cascade and
the 10 experts' training — lives in a separate project on the AI side. It reaches this system only
through the JSON-RPC socket. GC Shield is **not** an OS component here: it lives in the weights,
it has no socket, and no code in this repo queries it.

Naming: brand is **Parametral OS**; binaries are `parametrald` (gateway),
`parametral-harddeny` (tier-2 oracle), `parametral-sysapply` (tier-1 executor); state and config
live under `/var/lib/parametral` and `/etc/parametral`.

## Limitations (read before trusting it)

1. Audit is tamper-**evident**, not tamper-proof: same-uid (or root) can rewrite the chain.
2. Signing/approver keys are root-owned **in production only**; in this repo they sit in the
   operator's state dir. Until that moves, the oracle stops a jailbroken model, not a compromised
   account.
3. Tier 1 needs a human twice by design: once to approve the operation, once to sign the exact
   argv (`parametral host sign <job_id>`). That is deliberate — approval and payload cannot drift.
   `host.nix_profile` is still contract-only.
4. `app.install` is implemented end-to-end (manifest → snapshot → sandboxed install → verify →
   ≤3 attempts → real stderr report), but the dev host has no `/nix/store`, so the tests run a
   stubbed `nix` CLI; the real-nix path is exercised on the Arch image. `host.apply` and
   `host.nix_profile` are still contract-only (`-32008`), and artifact installs say
   `UNSUPPORTED` instead of pretending.
5. Unprivileged `btrfs subvolume delete` needs `CAP_SYS_ADMIN`; replaced subvolumes are parked in
   `<state>/trash` and `snapshot.restore` reports `space_reclaim_needs_root`.
6. Containers share the kernel: microVM profile is phase 5. No GPU/display/dbus passthrough yet.
7. Network grants are enforced by the allow-listing Unix-socket proxy; the nftables belt for the
   installed image is generated but not yet applied (needs CAP_NET_ADMIN). Disk quotas need
   `btrfs qgroup` privileges on the target; without them the sandbox records
   `quota_note` saying the limit is advisory instead of claiming it is on.

## Brand assets

`assets/parametral-mark-{1024,512,256}.png` — delivered raster, black background converted to
alpha so it sits on any dark surface; the wordmark is deliberately **not** baked in (the README
renders the name as text: crisper, theme-aware, and spelled correctly).

`assets/parametral-mark-light.svg`, `assets/parametral-favicon.svg` — flat vector variants: the
raster's glow dies on a white background, and a 22-tick ring needs a coarser 8/12-tick reduction
at 16 px. Regenerate the raster exports with `python3 scripts/prepare_logo.py <source.png>`.

## License

Deliberately not chosen yet: the repository stays private until the first release, and licensing
lands with that release (code and policy/rules will get separate terms — the policy must stay
auditable and redistributable, the name and mark must not).
