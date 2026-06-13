"""
Rainman sync server CLI
=======================

    python -m rainman_server serve --host 0.0.0.0 --port 8787 --db ./rainman-sync.db
    python -m rainman_server token add --user alice --workspace acme-api [--token T]

Mint a token, hand it to a developer; they run `rainman remote add <url>
<workspace> --token <T>` then `rainman sync`.
"""

import argparse
import secrets
import sys

from rainman_server.db import ServerDB
from rainman_server.app import make_server


def main():
    parser = argparse.ArgumentParser(prog="rainman_server")
    sub = parser.add_subparsers(dest="command")

    p_serve = sub.add_parser("serve", help="Run the sync server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8787)
    p_serve.add_argument("--db", default="rainman-sync.db")

    p_token = sub.add_parser("token", help="Token administration")
    token_sub = p_token.add_subparsers(dest="token_command")
    sub.add_parser("genkey", help="Generate a 32-byte encryption-at-rest key (RAINMAN_DB_KEY)")

    p_token_add = token_sub.add_parser("add", help="Mint a per-seat token")
    p_token_add.add_argument("--user", required=True)
    p_token_add.add_argument("--workspace", required=True)
    p_token_add.add_argument("--role", default="contributor",
                             choices=["reader", "contributor", "admin"])
    p_token_add.add_argument("--token", help="Token value (default: random)")
    p_token_add.add_argument("--db", default="rainman-sync.db")

    args = parser.parse_args()

    if args.command == "serve":
        httpd, _ = make_server(args.host, args.port, args.db)
        print(f"Rainman sync server on http://{args.host}:{args.port} (db: {args.db})")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down.")
            httpd.shutdown()
    elif args.command == "genkey":
        from rainman_server.crypto import generate_key
        print(generate_key())
    elif args.command == "token" and args.token_command == "add":
        db = ServerDB(args.db)
        token = args.token or secrets.token_hex(24)
        db.add_token(token, args.user, args.workspace, role=args.role)
        print(f"Token for user={args.user} workspace={args.workspace} role={args.role}:")
        print(token)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
