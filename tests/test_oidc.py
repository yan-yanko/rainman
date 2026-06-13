"""
OIDC SSO tests (server)
=======================

A mock RSA issuer (pinned public key, no network) drives the real server:
claim->role mapping, signature/issuer/audience/expiry rejection, alg pinning,
and coexistence with static per-seat tokens.
"""

import json
import threading
import time
import urllib.request
import urllib.error

import pytest

jwt = pytest.importorskip("jwt")
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from rainman_server.app import make_server
from rainman_server.oidc import OIDCConfig, OIDCValidator

ISS = "https://idp.example.com/"
AUD = "rainman-sync"
WS = "acme-api"


def _keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return priv, pub


@pytest.fixture(scope="module")
def keys():
    return _keypair()


def _mint(priv, *, groups=None, email="dev@example.com", iss=ISS, aud=AUD, exp_delta=3600):
    now = int(time.time())
    payload = {"iss": iss, "aud": aud, "iat": now, "exp": now + exp_delta, "email": email}
    if groups is not None:
        payload["groups"] = groups
    return jwt.encode(payload, priv, algorithm="RS256")


@pytest.fixture
def server(keys, tmp_path):
    priv, pub = keys
    cfg = OIDCConfig(
        issuer=ISS, audience=AUD, public_key=pub,
        username_claim="email", workspace=WS, role_claim="groups",
        role_map={"rainman-admins": "admin", "rainman-devs": "contributor"},
        default_role="reader",
    )
    httpd, db = make_server("127.0.0.1", 0, str(tmp_path / "s.db"),
                            oidc=OIDCValidator(cfg))
    db.add_token("static-contrib", "ci-bot", WS, role="contributor")  # coexisting static token
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}", priv
    finally:
        httpd.shutdown()
        t.join(timeout=5)


def _status(method, url, bearer, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": f"Bearer {bearer}"})
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def _pull(url, bearer):
    return _status("GET", f"{url}/v1/workspaces/{WS}/pull?since=0", bearer)


def _push(url, bearer):
    return _status("POST", f"{url}/v1/workspaces/{WS}/push", bearer,
                   body={"memories": [], "deletions": []})


def _admin_users(url, bearer):
    return _status("GET", f"{url}/v1/admin/users", bearer)


@pytest.mark.unit
class TestOIDCAuth:
    def test_valid_contributor_can_push(self, server):
        url, priv = server
        tok = _mint(priv, groups=["rainman-devs"])
        assert _push(url, tok) == 200

    def test_admin_group_maps_to_admin(self, server):
        url, priv = server
        tok = _mint(priv, groups=["rainman-admins"])
        assert _admin_users(url, tok) == 200

    def test_unmapped_group_is_reader(self, server):
        url, priv = server
        tok = _mint(priv, groups=["some-other-team"])
        assert _pull(url, tok) == 200       # reader can pull
        assert _push(url, tok) == 403       # but not push

    def test_no_groups_defaults_reader(self, server):
        url, priv = server
        tok = _mint(priv)  # no groups claim
        assert _pull(url, tok) == 200
        assert _push(url, tok) == 403


@pytest.mark.unit
class TestOIDCRejection:
    def test_expired_rejected(self, server):
        url, priv = server
        tok = _mint(priv, groups=["rainman-devs"], exp_delta=-10)
        assert _pull(url, tok) == 401

    def test_wrong_audience_rejected(self, server):
        url, priv = server
        tok = _mint(priv, groups=["rainman-devs"], aud="some-other-app")
        assert _pull(url, tok) == 401

    def test_wrong_issuer_rejected(self, server):
        url, priv = server
        tok = _mint(priv, groups=["rainman-devs"], iss="https://evil.example.com/")
        assert _pull(url, tok) == 401

    def test_bad_signature_rejected(self, server):
        url, _ = server
        other_priv, _ = _keypair()  # signed by a key the server doesn't trust
        tok = _mint(other_priv, groups=["rainman-admins"])
        assert _pull(url, tok) == 401


@pytest.mark.unit
class TestStaticTokenCoexistence:
    def test_static_token_still_works(self, server):
        url, _ = server
        assert _push(url, "static-contrib") == 200       # static contributor pushes
        assert _admin_users(url, "static-contrib") == 403  # but isn't admin

    def test_unknown_static_token_rejected(self, server):
        url, _ = server
        assert _pull(url, "not-a-real-token") == 401
