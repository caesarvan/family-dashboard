#!/bin/sh
set -eu
docker run --rm -v /var/lib/family-dashboard/letsencrypt:/etc/letsencrypt -v /var/lib/family-dashboard/acme:/var/www/acme certbot/certbot@sha256:f70ad0adbb7e117f0fe42a63c553f28ea451edabc0148757b6efcd9735acaa20 renew --quiet
cd /opt/family-dashboard
docker compose exec -T web nginx -t
docker compose exec -T web nginx -s reload
