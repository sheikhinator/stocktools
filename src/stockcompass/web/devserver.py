"""Serve the screens and the data service to a normal browser (development and automated screen tests).

    python -m stockcompass.web.devserver --db path/to/stockcompass.duckdb --port 8765
    then open http://127.0.0.1:8765/web/index.html
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from stockcompass.db import Database

from .api import Api, dumps

ROOT = Path(__file__).resolve().parent.parent      # the stockcompass package: web/ and assets/


def make_server(db: Database, port: int = 0, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    api = Api(db)
    lock = threading.Lock()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(ROOT), **k)

        def log_message(self, *a):
            pass

        def do_POST(self):
            if "/api/" not in self.path:
                self.send_error(404)
                return
            method = self.path.rsplit("/api/", 1)[1].split("?")[0]
            n = int(self.headers.get("Content-Length") or 0)
            params = json.loads(self.rfile.read(n) or b"{}")
            with lock:
                body = dumps(api.dispatch(method, params)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer((host, port), Handler)
    srv.api = api
    return srv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    srv = make_server(Database(a.db), a.port)
    print(f"http://127.0.0.1:{srv.server_address[1]}/web/index.html")
    srv.serve_forever()


if __name__ == "__main__":
    main()
