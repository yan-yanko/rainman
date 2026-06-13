"""
OIDC single sign-on (IdP-agnostic)
==================================

Lets the sync server accept short-lived **OIDC bearer JWTs** from any standard
provider (Okta, Entra ID, Google Workspace, Keycloak, ...) *in addition to* the
static per-seat tokens. A request authenticates via OIDC when its bearer is a
JWT (``header.payload.signature``); otherwise it falls back to a static token.

Validation uses **PyJWT** (vetted — JWT verification is not hand-rolled):
  * RS256 only — pinning the algorithm prevents "alg":"none" and HS256
    key-confusion attacks.
  * signature verified against the IdP's JWKS (fetched + cached) or a pinned
    public key (no-network / air-gapped deployments),
  * ``iss``, ``aud``, and ``exp`` required and checked.

Verified claims map to the existing ``(username, workspace, role)`` RBAC model
via a config contract, so everything downstream (gating, audit) is unchanged.

Configuration (env, all optional except issuer+audience to enable OIDC):
  RAINMAN_OIDC_ISSUER          required to enable OIDC
  RAINMAN_OIDC_AUDIENCE        required — expected ``aud``
  RAINMAN_OIDC_JWKS_URI        IdP JWKS endpoint (production)
  RAINMAN_OIDC_PUBLIC_KEY      OR a pinned PEM public key (air-gapped)
  RAINMAN_OIDC_USERNAME_CLAIM  claim used as username (default: email)
  RAINMAN_OIDC_WORKSPACE       static workspace for this issuer
  RAINMAN_OIDC_WORKSPACE_CLAIM OR a claim carrying the workspace
  RAINMAN_OIDC_ROLE_CLAIM      claim carrying group/role values (default: groups)
  RAINMAN_OIDC_ROLE_MAP        JSON {claim_value: role}, e.g. {"rainman-admins":"admin"}
  RAINMAN_OIDC_DEFAULT_ROLE    role when no mapping matches (default: reader)

This module is part of the SERVER package, where dependencies are allowed; the
client stays stdlib-only.
"""

import json
import os
from typing import Optional, Tuple

import jwt
from jwt import PyJWKClient

from rainman_server.db import ROLE_RANK, ROLE_READER


class OIDCConfig:
    def __init__(self, issuer: str, audience: str, *,
                 jwks_uri: Optional[str] = None, public_key: Optional[str] = None,
                 username_claim: str = "email",
                 workspace: Optional[str] = None, workspace_claim: Optional[str] = None,
                 role_claim: str = "groups", role_map: Optional[dict] = None,
                 default_role: str = ROLE_READER):
        if not (jwks_uri or public_key):
            raise ValueError("OIDC needs either jwks_uri or public_key")
        if not (workspace or workspace_claim):
            raise ValueError("OIDC needs either workspace or workspace_claim")
        self.issuer = issuer
        self.audience = audience
        self.jwks_uri = jwks_uri
        self.public_key = public_key
        self.username_claim = username_claim
        self.workspace = workspace
        self.workspace_claim = workspace_claim
        self.role_claim = role_claim
        self.role_map = role_map or {}
        self.default_role = default_role

    @classmethod
    def from_env(cls) -> Optional["OIDCConfig"]:
        issuer = os.environ.get("RAINMAN_OIDC_ISSUER", "").strip()
        audience = os.environ.get("RAINMAN_OIDC_AUDIENCE", "").strip()
        if not issuer or not audience:
            return None  # OIDC not configured
        role_map = {}
        raw_map = os.environ.get("RAINMAN_OIDC_ROLE_MAP", "").strip()
        if raw_map:
            try:
                role_map = json.loads(raw_map)
            except ValueError:
                role_map = {}
        return cls(
            issuer=issuer,
            audience=audience,
            jwks_uri=os.environ.get("RAINMAN_OIDC_JWKS_URI") or None,
            public_key=os.environ.get("RAINMAN_OIDC_PUBLIC_KEY") or None,
            username_claim=os.environ.get("RAINMAN_OIDC_USERNAME_CLAIM", "email"),
            workspace=os.environ.get("RAINMAN_OIDC_WORKSPACE") or None,
            workspace_claim=os.environ.get("RAINMAN_OIDC_WORKSPACE_CLAIM") or None,
            role_claim=os.environ.get("RAINMAN_OIDC_ROLE_CLAIM", "groups"),
            role_map=role_map,
            default_role=os.environ.get("RAINMAN_OIDC_DEFAULT_ROLE", ROLE_READER),
        )


class OIDCValidator:
    def __init__(self, config: OIDCConfig):
        self.cfg = config
        self._jwk_client = PyJWKClient(config.jwks_uri) if config.jwks_uri else None

    def authenticate(self, bearer: str) -> Optional[Tuple[str, str, str]]:
        """Validate an OIDC JWT and map it to (username, workspace, role).
        Returns None on any validation failure — never raises into the handler."""
        try:
            if self._jwk_client is not None:
                key = self._jwk_client.get_signing_key_from_jwt(bearer).key
            else:
                key = self.cfg.public_key
            claims = jwt.decode(
                bearer, key,
                algorithms=["RS256"],            # pin alg — no none/HS256 confusion
                audience=self.cfg.audience,
                issuer=self.cfg.issuer,
                options={"require": ["exp", "iss", "aud"]},
            )
        except Exception:
            return None
        return self._map_claims(claims)

    def _map_claims(self, claims: dict) -> Optional[Tuple[str, str, str]]:
        username = claims.get(self.cfg.username_claim)
        if not username:
            return None
        workspace = self.cfg.workspace or claims.get(self.cfg.workspace_claim)
        if not workspace:
            return None
        return (str(username), str(workspace), self._role_from(claims))

    def _role_from(self, claims: dict) -> str:
        values = claims.get(self.cfg.role_claim) or []
        if isinstance(values, str):
            values = [values]
        best = None
        for v in values:
            mapped = self.cfg.role_map.get(v)
            if mapped in ROLE_RANK and (best is None or ROLE_RANK[mapped] > ROLE_RANK[best]):
                best = mapped
        return best or self.cfg.default_role


def validator_from_env() -> Optional[OIDCValidator]:
    cfg = OIDCConfig.from_env()
    return OIDCValidator(cfg) if cfg else None
