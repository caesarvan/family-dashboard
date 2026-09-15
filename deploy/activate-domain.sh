#!/bin/sh
# Activate or validate the website ingress without changing application data.
set -eu
cd /opt/family-dashboard
DOMAIN=home.caesarcharles.world
CERTBOT=certbot/certbot@sha256:f70ad0adbb7e117f0fe42a63c553f28ea451edabc0148757b6efcd9735acaa20
if ! dig +time=3 +tries=1 @v0n0.nic.world caesarcharles.world NS +noall +authority +answer | grep -q 'name.com'; then
    echo 'DNS_NOT_READY: domain is not yet publicly resolving to this server.'
    exit 75
fi
if ! dig +time=3 +tries=1 @ns1bcp.name.com "$DOMAIN" A +short | grep -Fxq '96.44.160.28'; then
    echo 'DNS_RECORD_MISMATCH: refusing certificate activation.'
    exit 1
fi
docker run --rm -v /var/lib/family-dashboard/letsencrypt:/etc/letsencrypt -v /var/lib/family-dashboard/acme:/var/www/acme "$CERTBOT" certonly --non-interactive --agree-tos --register-unsafely-without-email --webroot --webroot-path /var/www/acme --cert-name family-dashboard-domain -d "$DOMAIN"
# Validate the candidate in a fresh container; an old bind mount may reference a replaced inode.
cp deploy/nginx.conf deploy/nginx.pre-domain-activation.conf
cp deploy/nginx.domain-ready.conf deploy/nginx.conf
if ! docker compose run --rm --no-deps web nginx -t; then
    cp deploy/nginx.pre-domain-activation.conf deploy/nginx.conf
    echo 'CONFIG_VALIDATION_FAILED: previous configuration restored.'
    exit 1
fi
docker compose up -d --no-deps --force-recreate web
curl --fail --retry 3 --retry-all-errors --retry-delay 1 --resolve "$DOMAIN:443:96.44.160.28" "https://$DOMAIN/healthz"
echo 'DOMAIN_ACTIVATED'
