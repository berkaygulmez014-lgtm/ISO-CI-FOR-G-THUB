#!/usr/bin/env bash
# 78-ai — the AI-facing half of the product: the account the model runs in, and the window
# the human uses to say yes or no.
#
# The model side itself is not in this repo (it is trained separately, with SFT). What the OS
# owes it is: an account with no ambient authority, a socket that refuses root, and a human
# gate that cannot be forged.
set -eu

[ "${1:-}" = "--help" ] && { echo "usage: 78-ai.sh"; exit 0; }

SRC="${SRC:-/opt/parametral-src}"
echo "==> AI hesabı (yetki yok, kendi 0700 evi)"

id ai >/dev/null 2>&1 || useradd -m -s /bin/bash ai
usermod -G "" ai                      # no supplementary groups at all
usermod -s /bin/bash ai
install -d -o ai -g ai -m 0700 /home/ai
chown ai:ai /home/ai 2>/dev/null || true

# the AI may use the store; it may never write to it
if [ -f /etc/nix/nix.conf ]; then
  grep -q '^allowed-users' /etc/nix/nix.conf || echo 'allowed-users = *' >> /etc/nix/nix.conf
fi

echo "==> Onay penceresi"
install -d /usr/share/applications
install -m 0644 "$SRC/branding/apps/parametral-approvals.desktop" \
  /usr/share/applications/parametral-approvals.desktop

for app in parametral-approvals parametral-ai; do
  built="$SRC/apps/$app/target/release/$app"
  if [ -x "$built" ]; then
    install -m 0755 "$built" "/usr/local/bin/$app"
    echo "    $app installed"
  fi
done

install -m 0644 "$SRC/branding/apps/parametral-ai.desktop" /usr/share/applications/

built="$SRC/apps/parametral-approvals/target/release/parametral-approvals"
if [ -x "$built" ]; then
  echo "    approval window installed"
else
  echo "    NOTE: prebuilt binary not in the payload (build it with 'cargo build --release'"
  echo "          in apps/parametral-approvals and re-run; the menu entry is installed anyway)"
fi

# The gate only helps if it is in front of the user when the AI asks. Autostart it for the
# seat account, not for ai itself.
cat > /etc/xdg/autostart/parametral-approvals.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=Parametral onay istekleri
Exec=/usr/local/bin/parametral-approvals
OnlyShowIn=KDE;
NoDisplay=true
X-KDE-autostart-after=panel
EOF

echo "==> done"
