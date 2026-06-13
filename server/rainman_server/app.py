"""
Sync server HTTP layer
======================

Stdlib ThreadingHTTPServer. Three routes, bearer-token auth scoped to a
workspace:

    GET  /v1/health
    GET  /v1/workspaces/{ws}/pull?since=N
    POST /v1/workspaces/{ws}/push     body: {memories:[...], deletions:[ids]}

Zero external dependencies.
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from rainman_server.db import ServerDB


def make_handler(db: ServerDB):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        # ── helpers ──
        def _send(self, code: int, obj: dict) -> None:
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _auth(self, ws: str):
            header = self.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                return None
            resolved = db.resolve_token(header[7:].strip())
            if not resolved:
                return None
            username, workspace = resolved
            return username if workspace == ws else None

        def log_message(self, *args):  # silence default stderr logging
            pass

        @staticmethod
        def _route(path: str):
            parts = path.strip("/").split("/")
            # ["v1","workspaces",<ws>,<action>]
            if len(parts) == 4 and parts[0] == "v1" and parts[1] == "workspaces":
                return parts[2], parts[3]
            return None, None

        # ── GET ──
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/v1/health":
                return self._send(200, {"status": "ok"})
            ws, action = self._route(parsed.path)
            if action == "pull":
                user = self._auth(ws)
                if not user:
                    return self._send(401, {"error": "unauthorized"})
                since = parse_qs(parsed.query).get("since", ["0"])[0]
                try:
                    since = int(since)
                except ValueError:
                    since = 0
                cursor, changes = db.pull(ws, since)
                return self._send(200, {"cursor": cursor, "changes": changes})
            return self._send(404, {"error": "not found"})

        # ── POST ──
        def do_POST(self):
            parsed = urlparse(self.path)
            ws, action = self._route(parsed.path)
            if action == "push":
                user = self._auth(ws)
                if not user:
                    return self._send(401, {"error": "unauthorized"})
                length = int(self.headers.get("Content-Length", 0) or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    return self._send(400, {"error": "bad json"})
                result = db.push(
                    ws,
                    body.get("memories", []),
                    body.get("deletions", []),
                    author=user,
                )
                return self._send(200, result)
            return self._send(404, {"error": "not found"})

    return Handler


def make_server(host: str, port: int, db_path: str):
    """Build (httpd, db). Call httpd.serve_forever() to run."""
    db = ServerDB(db_path)
    httpd = ThreadingHTTPServer((host, port), make_handler(db))
    return httpd, db
