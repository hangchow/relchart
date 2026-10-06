#!/bin/bash
# Reviewed administrator installation; application updates run unprivileged.
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [[ $EUID != 0 ]]; then
    echo 'Run this installer as root' >&2
    exit 1
fi
getent passwd relchart >/dev/null || useradd --system --home-dir /var/lib/relchart --shell /usr/sbin/nologin relchart
getent passwd relchart-deploy >/dev/null || useradd --system --home-dir /var/lib/relchart-deploy --shell /usr/sbin/nologin relchart-deploy
install -d -o relchart -g relchart -m 0700 /var/lib/relchart /var/lib/relchart/stocks /var/cache/relchart
install -d -o relchart-deploy -g relchart-deploy -m 0755 /opt/relchart /opt/relchart/releases
install -d -o relchart-deploy -g relchart-deploy -m 0700 /var/lib/relchart-deploy
install -d -m 0755 /etc/relchart /usr/local/libexec/relchart
if [[ ! -f /etc/relchart/relchart.env ]]; then
    install -m 0644 relchart.env.example /etc/relchart/relchart.env
fi
if [[ ! -f /etc/relchart/firewall.nft ]]; then
    install -m 0644 relchart-firewall.nft /etc/relchart/firewall.nft
fi
install -m 0755 start.py deploy.py /usr/local/libexec/relchart/
install -m 0644 relchart-web.service relchart-deploy.service relchart-deploy.timer relchart-firewall.service /etc/systemd/system/
cat > /etc/sudoers.d/relchart-deploy <<'SUDOERS'
relchart-deploy ALL=(root) NOPASSWD: /usr/bin/systemctl start relchart-web.service, /usr/bin/systemctl stop relchart-web.service, /usr/bin/systemctl restart relchart-web.service
SUDOERS
chmod 0440 /etc/sudoers.d/relchart-deploy
visudo -cf /etc/sudoers.d/relchart-deploy
nft -c -f /etc/relchart/firewall.nft
systemd-analyze verify /etc/systemd/system/relchart-web.service /etc/systemd/system/relchart-deploy.service /etc/systemd/system/relchart-deploy.timer /etc/systemd/system/relchart-firewall.service
systemctl daemon-reload
systemctl enable --now relchart-firewall.service
nft -f /etc/relchart/firewall.nft
ufw allow in on enp9s0f0np0 from 192.168.10.0/24 to 192.168.10.1 port 80 proto tcp comment 'relchart LAN'
systemctl enable relchart-web.service
echo 'Installed. Run initial deployment, verify it, then enable relchart-deploy.timer.'
