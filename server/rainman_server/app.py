"""
Sync server HTTP layer
======================

Stdlib ThreadingHTTPServer. Routes:

    GET  /v1/health
    GET  /v1/workspaces/{ws}/pull?since=N      role: reader+
    POST /v1/workspaces/{ws}/push              role: contributor+
    GET  /v1/admin/users                        role: admin
    POST /v1/admin/tokens   {username, role}    role: admin -> {token}
    POST /v1/admin/revoke   {username}          role: admin -> {revoked}
    GET  /v1/admin/audit?limit=N                role: admin
    GET  /admin                                 minimal web console (HTML)

Auth: ``Authorization: Bearer <token>``; the token carries a workspace + role.
Every push/pull/admin action is written to the centralized audit trail.

Zero external dependencies.
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from rainman_server.db import ServerDB, ROLE_RANK, ROLE_READER, ROLE_CONTRIBUTOR, ROLE_ADMIN
from rainman_server.console import CONSOLE_HTML


def make_handler(db: ServerDB):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        # ── response helpers ──
        def _send_json(self, code: int, obj: dict) -> None:
            self._send(code, "application/json", json.dumps(obj).encode("utf-8"))

        def _send(self, code: int, ctype: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence default stderr logging
            pass

        def _principal(self):
            """Return (username, workspace, role) from the bearer token, or None."""
            header = self.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                return None
            return db.resolve_token(header[7:].strip())

        def _require(self, min_role: str, workspace=None):
            """Authorize the request. Returns principal tuple or sends an error
            and returns None. If workspace is given, the token must match it."""
            p = self._principal()
            if not p:
                self._send_json(401, {"error": "unauthorized"})
                return None
            username, ws, role = p
            if workspace is not None and ws != workspace:
                self._send_json(403, {"error": "wrong workspace"})
                return None
            if ROLE_RANK[role] < ROLE_RANK[min_role]:
                self._send_json(403, {"error": f"requires {min_role} role"})
                return None
            return p

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0) or 0)
            try:
                return json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return {}

        @staticmethod
        def _parts(path: str):
            return path.strip("/").split("/")

        # ── GET ──
        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/v1/health":
                return self._send_json(200, {"status": "ok"})
            if path in ("/admin", "/admin/"):
                return self._send(200, "text/html; charset=utf-8", CONSOLE_HTML.encode("utf-8"))

            parts = self._parts(path)
            # /v1/workspaces/{ws}/pull
            if len(parts) == 4 and parts[:2] == ["v1", "workspaces"] and parts[3] == "pull":
                ws = parts[2]
                p = self._require(ROLE_READER, workspace=ws)
                if not p:
                    return
                since = parse_qs(parsed.query).get("since", ["0"])[0]
                try:
                    since = int(since)
                except ValueError:
                    since = 0
                cursor, changes = db.pull(ws, since)
                db.log_audit(ws, p[0], "pull", f"since={since} -> {len(changes)} changes")
                return self._send_json(200, {"cursor": cursor, "changes": changes})

            # /v1/admin/{users,audit}
            if parts[:2] == ["v1", "admin"]:
                p = self._require(ROLE_ADMIN)
                if not p:
                    return
                ws = p[1]
                if parts[2:] == ["users"]:
                    return self._send_json(200, {"users": db.list_users(ws)})
                if parts[2:] == ["audit"]:
                    limit = parse_qs(parsed.query).get("limit", ["100"])[0]
                    try:
                        limit = max(1, min(1000, int(limit)))
                    except ValueError:
                        limit = 100
                    return self._send_json(200, {"events": db.get_audit(ws, limit)})

            return self._send_json(404, {"error": "not found"})

        # ── POST ──
        def do_POST(self):
            parsed = urlparse(self.path)
            parts = self._parts(parsed.path)

            # /v1/workspaces/{ws}/push
            if len(parts) == 4 and parts[:2] == ["v1", "workspaces"] and parts[3] == "push":
                ws = parts[2]
                p = self._require(ROLE_CONTRIBUTOR, workspace=ws)
                if not p:
                    return
                body = self._body()
                result = db.push(ws, body.get("memories", []), body.get("deletions", []),
                                 author=p[0])
                db.log_audit(ws, p[0], "push", f"accepted={result['accepted']}")
                return self._send_json(200, result)

            # /v1/admin/{tokens,revoke}
            if parts[:2] == ["v1", "admin"]:
                p = self._require(ROLE_ADMIN)
                if not p:
                    return
                ws = p[1]
                body = self._body()
                if parts[2:] == ["tokens"]:
                    username = (body.get("username") or "").strip()
                    role = body.get("role", ROLE_CONTRIBUTOR)
                    if not username or role not in ROLE_RANK:
                        return self._send_json(400, {"error": "username and valid role required"})
                    token = db.create_token(username, ws, role)
                    db.log_audit(ws, p[0], "token_create", f"user={username} role={role}")
                    return self._send_json(200, {"token": token, "username": username, "role": role})
                if parts[2:] == ["revoke"]:
                    username = (body.get("username") or "").strip()
                    if not username:
                        return self._send_json(400, {"error": "username required"})
                    n = db.revoke_user(ws, username)
                    db.log_audit(ws, p[0], "revoke", f"user={username} tokens={n}")
                    return self._send_json(200, {"revoked": n})

            return self._send_json(404, {"error": "not found"})

    return Handler


def make_server(host: str, port: int, db_path: str):
    """Build (httpd, db). Call httpd.serve_forever() to run."""
    db = ServerDB(db_path)
    httpd = ThreadingHTTPServer((host, port), make_handler(db))
    return httpd, db
