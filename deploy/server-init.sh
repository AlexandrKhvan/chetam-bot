#!/usr/bin/env bash
set -euo pipefail

# Setup 1 GB swap (especially helpful on nano/micro instances)
if [ ! -f /swapfile ]; then
  fallocate -l 1G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# Install Docker Engine + Compose plugin + Git
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl gnupg git

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker ubuntu || true

# Clone CheTam repository
mkdir -p /opt/chetam-bot
if [ ! -d /opt/chetam-bot/.git ]; then
  git clone https://github.com/AlexandrKhvan/chetam-bot.git /opt/chetam-bot
fi
chown -R ubuntu:ubuntu /opt/chetam-bot
chmod +x /opt/chetam-bot/deploy/update.sh || true
