#!/bin/sh
set -eu
cd /opt/family-dashboard
docker compose exec -T app python < deploy/backup.py
