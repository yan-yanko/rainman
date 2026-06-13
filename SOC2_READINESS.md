# SOC 2 Readiness

> SOC 2 is an **audit**, not a feature — it requires an independent auditor and
> an observation period. This document is not a certification. It maps Rainman's
> *existing technical controls* to the SOC 2 Trust Services Criteria (TSC) so a
> prospective customer's security team can assess the product, and so the gaps
> to a real audit are explicit.

Scope below: the **self-hosted** deployment (client + sync server run on
customer infrastructure). A managed/hosted offering would add organizational
controls (personnel, vendor management, physical security) out of scope here.

## Control mapping

### CC6 — Logical & Physical Access Controls

| Control | Status | Where |
|---|---|---|
| Authentication on all data access | ✅ | Per-seat bearer tokens; every sync/admin request requires `Authorization: Bearer` (`server/rainman_server/app.py`) |
| Role-based authorization (least privilege) | ✅ | `reader < contributor < admin`; pull=reader+, push=contributor+, admin API=admin (`db.py`, `app.py`) |
| Workspace isolation | ✅ | Tokens are scoped to one workspace; cross-workspace access is rejected (403) |
| Deprovisioning | ✅ | `revoke` removes all of a user's tokens immediately (admin console / `/v1/admin/revoke`) |
| Secrets not stored in source control | ✅ | Client token kept in `~/.rainman/sync_credentials.json` or env, never the committable `.rainman/` |
| MFA / SSO | ⛔ Gap | Deferred (Phase 3 SSO/SAML/SCIM). Today: pre-shared tokens. Compensating: short-lived rotated tokens behind VPN. |

### CC7 — System Operations / Monitoring

| Control | Status | Where |
|---|---|---|
| Centralized, append-only audit trail | ✅ | Server logs push / pull / token_create / revoke with actor + timestamp (`db.audit`, viewable in console) |
| Client-side action audit | ✅ | Opt-in append-only JSONL of store/recall/forget (`rainman/core/audit.py`) |
| Tamper-evidence of the audit log | ⚠️ Partial | Append-only by construction; no cryptographic chaining yet (potential enhancement) |

### CC8 — Change Management

| Control | Status | Where |
|---|---|---|
| Version control + peer-reviewable history | ✅ | Git; CI runs lint + 215 tests on every push/PR (`.github/workflows/ci.yml`) |
| Release integrity | ✅ | Sigstore-signed artifacts + CycloneDX SBOM (`.github/workflows/release.yml`) |
| Automated testing gate | ✅ | `pytest -m unit` + `ruff` in CI |

### Confidentiality & Data Residency

| Control | Status | Where |
|---|---|---|
| No third-party data egress | ✅ | Client and server make zero external calls; self-hosted. Verifiable via egress monitoring. |
| Secret redaction before storage | ✅ | `rainman/core/redact.py` (+ org-policy mandatory patterns/denylists) |
| Memory-poisoning controls | ✅ | Trust gating + quarantine + provenance (`THREAT_MODEL.md`) |
| Encryption in transit | ✅ (deployment) | TLS terminated at a reverse proxy (`server/DEPLOY.md`) |
| Encryption at rest | ⛔ Gap | SQLite DB is unencrypted; rely on full-disk / filesystem encryption on the host. SQLCipher is a future option. |
| Org-managed policy / retention | ✅ | Policy control plane: retention TTL, non-overridable `enforce` mandates (`rainman/core/config.py`) |

## Gaps to a real SOC 2 (work to close)

1. **SSO / MFA** — replace pre-shared tokens with OIDC/SAML + SCIM provisioning (Phase 3, deferred pending a target IdP).
2. **Encryption at rest** — host-level disk encryption today; evaluate SQLCipher for the server DB.
3. **Audit tamper-evidence** — optional hash-chaining of audit rows.
4. **Organizational controls** — access reviews, incident response runbook, vendor management, security training — required for the audit regardless of code.
5. **Formal policies** — data retention, access control, and change management policies documented and approved.

## Summary for a security reviewer

The product's architecture is **privacy- and access-control-first**: self-hosted,
zero egress, per-seat RBAC, workspace isolation, immediate deprovisioning, and a
centralized audit trail — the technical backbone several TSC criteria require is
in place. The principal gaps before a SOC 2 Type II are **SSO/MFA**,
**encryption at rest**, and the **organizational/process controls** that an audit
demands independent of the codebase.
