# Security Policy

## Reporting a vulnerability

Please report security issues **privately**. Do not open a public issue for a
suspected vulnerability.

- Use GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
  ("Report a vulnerability" under the repo's **Security** tab), **or**
- Email the maintainer at `yanko1984@gmail.com` with the subject `RAINMAN SECURITY`.

We aim to acknowledge within **3 business days** and to provide a remediation
plan or assessment within **10 business days**.

## Supported versions

Rainman is pre-1.0. Security fixes land on `main` and in the latest release.
Older tags are not back-patched.

## Security posture

Rainman is built local-first, and that is its primary security property:

- **No data leaves the machine.** Zero external API calls, zero telemetry,
  zero network traffic. Storing, scoring, and ranking are local computation.
- **Zero third-party runtime dependencies** (Python stdlib only) — a near-empty
  attack surface and a trivial supply chain to audit. See the SBOM attached to
  each release.
- **Secret redaction before storage.** Auto-learned content (the `post_tool_use`
  and `session_end` hooks) is run through `rainman/core/redact.py`: sensitive
  file paths (`.env`, `*.pem`, `credentials*`, ...) are skipped entirely, and
  secret-shaped content (AWS keys, GitHub tokens, PEM headers, bearer tokens,
  connection strings) is replaced with `[REDACTED]`. Organisations can add
  mandatory patterns and path denylists via policy.
- **Provenance and trust on every memory.** Each memory records its `source`
  and `author`; a derived trust level (`user` > `hook` > `ingest`) gates how it
  is used. See [`THREAT_MODEL.md`](THREAT_MODEL.md).
- **Append-only audit log** (opt-in) records who stored, recalled, and forgot
  what, for incident reconstruction.
- **Org policy control plane** lets a security team distribute mandatory,
  non-overridable settings (`enforce` block) via MDM or git.

## Known trust boundary

`rainman ingest` and the auto-learn hooks bring **third-party content**
(git history, repo files, tool output) into memory, which can later be injected
into an AI agent's context. This is a prompt-injection persistence channel and
is treated as the primary threat — see [`THREAT_MODEL.md`](THREAT_MODEL.md) for
the model, mitigations, and residual risk.

## Release integrity

Release artifacts are built in CI and signed with
[Sigstore](https://www.sigstore.dev/) (keyless, OIDC-based). Each release
includes the `.sigstore` bundles and a CycloneDX SBOM. Verify before installing
from a release artifact:

```bash
python -m pip install sigstore
python -m sigstore verify identity \
  --cert-identity "https://github.com/<owner>/rainman/.github/workflows/release.yml@refs/tags/<tag>" \
  --cert-oidc-issuer "https://token.actions.githubusercontent.com" \
  rainman-<version>-py3-none-any.whl
```
