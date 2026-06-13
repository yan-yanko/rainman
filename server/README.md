# Rainman Sync Server

Self-hosted, **stdlib-only** sync server for sharing a repo's Rainman memory
across a team. Zero external dependencies; runs anywhere Python 3.10+ runs,
including air-gapped networks.

It syncs the **project layer** of a repo (not personal/global memories) through
a workspace, using a monotonic-cursor delta protocol with tombstones for
deletes. Auth is per-seat bearer tokens. SSO/SCIM/RBAC are roadmap (Phase 3).

## Run

```bash
python -m rainman_server serve --host 0.0.0.0 --port 8787 --db ./rainman-sync.db
```

## Mint a token for a developer

```bash
python -m rainman_server token add --user alice --workspace acme-api --db ./rainman-sync.db
# prints a token
```

Hand the token to the developer. On their machine:

```bash
rainman remote add http://your-server:8787 acme-api --token <TOKEN>
rainman sync
```

## Protocol

| Endpoint | Purpose |
|----------|---------|
| `GET /v1/health` | liveness |
| `GET /v1/workspaces/{ws}/pull?since=N` | changes (upserts + tombstones) with `seq > N`, plus new `cursor` |
| `POST /v1/workspaces/{ws}/push` | body `{memories:[...], deletions:[ids]}`; assigns seqs, stamps `author` |

All authenticated requests require `Authorization: Bearer <token>`; the token is
scoped to a single workspace. Conflicts resolve last-write-to-server-wins by
`seq`; the client's local audit log preserves history.

> Production note: for larger teams, front this with a TLS-terminating reverse
> proxy. The server speaks plain HTTP and trusts the proxy for TLS.
