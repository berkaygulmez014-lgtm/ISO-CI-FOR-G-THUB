#!/usr/bin/env bash
# 40-users.sh — the separation that makes the rest of the design meaningful.
#
#   operator  : the human. wheel, can do anything, types the passphrase.
#   parametral   : service user for parametrald + parametral-harddeny. No shell, no sudo.
#   approver  : owns the approval key, runs the approval UI. No sudo, no shell for AI.
#   ai        : where the AI process lives. No groups, no sudo, 0700 home, cannot read
#               /etc/parametral/keys, cannot read the approver key, cannot touch /root.
set -Eeuo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }

# --non-interactive is for throwaway test VMs only: it sets a known operator password
# instead of prompting. A real install must type the password.
NONINTERACTIVE=0
for arg in "$@"; do
  case "$arg" in
    --non-interactive) NONINTERACTIVE=1 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

# The human account defaults to `operator`, the name the rest of the kit documents. The
# installer may pass another name; validate it so it stays a valid useradd/chpasswd token.
HUMAN="${PARAMETRAL_USER:-operator}"
case "$HUMAN" in
  [a-z_]* ) ;;
  *) echo "PARAMETRAL_USER must start with a-z or _ (got: $HUMAN)" >&2; exit 2 ;;
esac
case "$HUMAN" in
  *[!a-z0-9_-]*|"") echo "PARAMETRAL_USER contains unsupported characters (got: $HUMAN)" >&2; exit 2 ;;
esac

# useradd -m writes into /home. If @home is not mounted (easy to miss when chrooting
# by hand), /home/operator lands in the root subvolume and the greeter later fails with
# "chdir(/home/operator) failed" -> the session dies right after authentication.
if ! mountpoint -q /home; then
  echo "WARN: /home is not a separate mountpoint — home directories will land in the root subvolume." >&2
  echo "      mount @home at /home (or /mnt/home before chroot) and re-run 40-users.sh." >&2
fi

echo "==> users"
id "$HUMAN" >/dev/null 2>&1 || useradd -m -G wheel -s /bin/bash "$HUMAN"
id parametral   >/dev/null 2>&1 || useradd -r -d /var/lib/parametral -s /usr/bin/nologin parametral
id approver  >/dev/null 2>&1 || useradd -r -d /var/lib/parametral -s /bin/bash approver
id ai        >/dev/null 2>&1 || useradd -m -s /bin/bash ai

# the AI account is deliberately naked: no supplementary groups, no sudo, no docker,
# no video/audio, no games. If a future step needs a group, that is a design change.
usermod -G "" ai
install -d -o ai -g ai -m 0700 /home/ai
# The human account runs the approval window; it reaches the daemon through the
# parametral group (socket 0660), never through root.
usermod -aG parametral "$HUMAN" 2>/dev/null || true
install -d -o parametral -g parametral -m 0750 /var/lib/parametral
install -d -o approver -g approver -m 0700 /var/lib/parametral
install -d -o root -g root -m 0755 /var/lib/parametral/keys

if [ -n "${PARAMETRAL_PASSWORD:-}" ]; then
  echo "==> passwords: $HUMAN uses the installer password; ai is test-mode only"
  printf '%s:%s\n' "$HUMAN" "$PARAMETRAL_PASSWORD" | chpasswd
  if [ "$NONINTERACTIVE" = "1" ]; then
    printf 'ai:parametral\n' | chpasswd
  else
    passwd ai
  fi
elif [ "$NONINTERACTIVE" = "1" ]; then
  echo "==> passwords: TEST MODE ($HUMAN/ai = 'parametral', service users locked)"
  printf '%s:parametral\nai:parametral\n' "$HUMAN" | chpasswd
else
  echo "==> passwords (interactive: $HUMAN types theirs, service users get none)"
  passwd "$HUMAN"
  passwd ai
fi
usermod -L parametral
usermod -L approver

echo "==> sudo: only wheel, and the AI accounts are explicitly denied"
cat > /etc/sudoers.d/10-parametral <<'EOF'
%wheel ALL=(ALL:ALL) ALL
ai       ALL=(ALL) !ALL
parametral  ALL=(ALL) !ALL
approver ALL=(ALL) !ALL
EOF
chmod 0440 /etc/sudoers.d/10-parametral
visudo -cf /etc/sudoers.d/10-parametral

echo "==> polkit: the AI account cannot authorise privileged actions"
install -d -m 0755 /etc/polkit-1/rules.d
cat > /etc/polkit-1/rules.d/50-parametral-ai.rules <<'EOF'
// Parametral OS: the AI account may never obtain privileges through polkit.
polkit.addRule(function(action, subject) {
    if (subject.user === "ai") {
        return polkit.Result.NO;
    }
});
EOF

echo "==> directory ownership for the OS layer"
install -d -o root -g root -m 0755 /etc/parametral
install -d -o root -g root -m 0755 /etc/parametral/policy
install -d -o root -g root -m 0755 /etc/parametral/keys
install -d -o root -g root -m 0755 /etc/parametral

# public keys must be readable by the service user (the oracle verifies with them);
# anything ending in .sk or .key is the secret half and stays root-only.
find /etc/parametral/keys -type f \( -name '*.sk' -o -name '*.key' \) -exec chmod 0600 {} + 2>/dev/null || true
find /etc/parametral/keys -type f \( -name '*.pub' -o -name '*.sig' \) -exec chmod 0644 {} + 2>/dev/null || true

echo "==> home permissions: other users cannot read each other"
chmod 0700 /home/ai "/home/$HUMAN"

echo "checks:"
printf '  ai groups: %s\n' "$(id -nG ai)"
printf '  ai sudo:   %s\n' "$(sudo -l -U ai 2>&1 | tail -1)"
