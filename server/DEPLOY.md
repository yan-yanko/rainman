# Deploying the Rainman Sync Server

The server is **stdlib-only** — there is no dependency install step, which makes
air-gapped deployment trivial: if Python 3.10+ is present, the server runs.

## Option A — run directly

```bash
python -m rainman_server serve --host 0.0.0.0 --port 8787 --db /var/lib/rainman/sync.db
```

Mint tokens (one per developer, with a role):

```bash
python -m rainman_server token add --user alice --workspace acme-api --role contributor --db /var/lib/rainman/sync.db
python -m rainman_server token add --user lead  --workspace acme-api --role admin       --db /var/lib/rainman/sync.db
```

Roles: `reader` (pull only), `contributor` (pull + push), `admin` (manage
tokens + view audit, via the console at `/admin`).

## Option B — Docker

```bash
docker build -t rainman-server ./server
docker run -d -p 8787:8787 -v rainman-data:/data --name rainman rainman-server
docker exec rainman python -m rainman_server token add \
    --user alice --workspace acme-api --role contributor --db /data/rainman-sync.db
```

## Air-gapped install

There is nothing to fetch from the internet at runtime — the server makes **zero
outbound connections** (verify with `ss -tunp` / egress firewall: you'll see
only the inbound listener). For a fully offline pipeline:

1. On a connected host, pre-pull the base image and export it:
   `docker pull python:3.12-slim && docker save python:3.12-slim -o python-base.tar`
2. Transfer `python-base.tar` + this repo's `server/` directory across the gap.
3. `docker load -i python-base.tar`, then `docker build` / `docker run` as above.

Or skip Docker entirely: copy `server/rainman_server/` to the air-gapped host
and run it with the system Python. No wheels, no PyPI.

## SSO (OIDC) — optional

Set these to accept OIDC bearer JWTs in addition to static tokens (unset = static
tokens only). MFA is handled by your IdP.

| Env var | Purpose |
|---|---|
| `RAINMAN_OIDC_ISSUER` | IdP issuer URL (required to enable OIDC) |
| `RAINMAN_OIDC_AUDIENCE` | expected `aud` claim (required) |
| `RAINMAN_OIDC_JWKS_URI` | IdP JWKS endpoint (production) |
| `RAINMAN_OIDC_PUBLIC_KEY` | *or* a pinned PEM public key (air-gapped, no JWKS fetch) |
| `RAINMAN_OIDC_USERNAME_CLAIM` | claim used as username (default `email`) |
| `RAINMAN_OIDC_WORKSPACE` / `..._WORKSPACE_CLAIM` | static workspace, or a claim carrying it |
| `RAINMAN_OIDC_ROLE_CLAIM` | claim with group/role values (default `groups`) |
| `RAINMAN_OIDC_ROLE_MAP` | JSON `{claim_value: role}`, e.g. `{"rainman-admins":"admin"}` |
| `RAINMAN_OIDC_DEFAULT_ROLE` | role when no mapping matches (default `reader`) |

Air-gapped note: use `RAINMAN_OIDC_PUBLIC_KEY` to pin the IdP signing key so the
server never needs to fetch a JWKS over the network.

## TLS

The server speaks **plain HTTP** and is designed to sit behind a TLS-terminating
reverse proxy (nginx/Caddy/Traefik). Example nginx:

```nginx
server {
  listen 443 ssl;
  server_name rainman.internal;
  ssl_certificate     /etc/ssl/rainman.crt;
  ssl_certificate_key /etc/ssl/rainman.key;
  location / { proxy_pass http://127.0.0.1:8787; proxy_set_header Host $host; }
}
```

Bind the server to `127.0.0.1` when a proxy is co-located so it is never exposed
directly.

## Backups

All state — synced memories, tokens, and the audit trail — lives in the single
SQLite file (`--db`). Back it up with a consistent copy:

```bash
sqlite3 /var/lib/rainman/sync.db ".backup '/backups/rainman-$(date +%F).db'"
```

WAL mode is enabled; the `.backup` command captures a consistent snapshot
without stopping the server.

## Hardening checklist

- [ ] Run behind TLS (reverse proxy); bind app to localhost.
- [ ] Run as a non-root user; mount the data volume with least privilege.
- [ ] Restrict inbound to the developer network / VPN.
- [ ] Rotate tokens periodically (`token add` re-issues; revoke via the console).
- [ ] Back up the SQLite file; consider full-disk / filesystem encryption for
      encryption-at-rest (the DB itself is not encrypted — see SOC2_READINESS).
- [ ] Tune `RAINMAN_MAX_BODY_BYTES` (default 10 MiB) to your largest expected
      push; the server rejects larger request bodies with 413 before reading them.
