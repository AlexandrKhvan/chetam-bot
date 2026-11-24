#!/usr/bin/env bash
set -euo pipefail

cd /opt/chetam-bot
git pull --ff-only origin main
docker compose up -d --build
docker compose ps
