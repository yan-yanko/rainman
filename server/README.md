# Rainman Sync Server

Self-hosted, **stdlib-only** sync server for sharing a repo's Rainman memory
across a team. Zero external dependencies; runs anywhere Python 3.10+ runs,
including air-gapped networks.

It syncs the **project layer** of a repo (not personal/global memories) through
a workspace, using a monotonic-cursor delta protocol with tombstones for
deletes. Auth is per-seat bearer tokens with **role-based access control**
(`reader` < `contributor` < `admin`) and a centralized audit trail. SSO/SAML/SCIM
are roadmap (deferred pending a target identity provider).

See [`DEPLOY.md`](DEPLOY.md) for production / air-gapped deployment and
[`../SOC2_READINESS.md`](../SOC2_READINESS.md) for the control mapping.

## Run

```bash
python -m rainman_server serve --host 0.0.0.0 --port 8787 --db ./rainman-sync.db
```

## Mint a token for a developer

```bash
python -m rainman_server token add --user alice --workspace acme-api --role contributor --db ./rainman-sync.db
# prints a token
```

Roles: `reader` (pull only), `contributor` (pull + push), `admin` (manage tokens
+ view audit). Hand the token to the developer. On their machine:

```bash
rainman remote add http://your-server:8787 acme-api --token <TOKEN>
rainman sync
```

## Admin console

Mint an `admin` token and open `http://your-server:8787/admin` in a browser:
paste the token to list users, mint/revoke tokens, and view the audit trail.

## Protocol

| Endpoint | Purpose |
|----------|---------|
| `GET /v1/health` | liveness |
| `GET /v1/workspaces/{ws}/pull?since=N` | reader+ — changes (upserts + tombstones) with `seq > N`, plus new `cursor` |
| `POST /v1/workspaces/{ws}/push` | contributor+ — body `{memories:[...], deletions:[ids]}`; assigns seqs, stamps `author` |
| `GET /v1/admin/users` · `POST /v1/admin/tokens` · `POST /v1/admin/revoke` · `GET /v1/admin/audit` · `GET /v1/admin/audit/verify` | admin only |

Bearer tokens are stored as SHA-256 digests (never cleartext at rest). The
audit log is hash-chained; `GET /v1/admin/audit/verify` returns `{ok, broken_at}`
so tampering with or deleting any past row is detectable.

All authenticated requests require `Authorization: Bearer <token>`; the token is
scoped to a single workspace. Conflicts resolve last-write-to-server-wins by
`seq`; the client's local audit log preserves history.

> Production note: for larger teams, front this with a TLS-terminating reverse
> proxy. The server speaks plain HTTP and trusts the proxy for TLS.
