"""Stand-in for llama.cpp's llama-server in tests: same command line, /health, and the mock AI on /v1."""
import argparse
from http.server import ThreadingHTTPServer

import mock_llm

ap = argparse.ArgumentParser()
ap.add_argument("-m")
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--port", type=int)
ap.add_argument("-c")
ap.add_argument("-t")
ap.add_argument("--jinja", action="store_true")
a, _ = ap.parse_known_args()


class H(mock_llm.Handler):
    def do_GET(self):
        if self.path == "/health":
            return self._json({"status": "ok"})
        return super().do_GET()


print("llama server listening", flush=True)
srv = ThreadingHTTPServer((a.host, a.port), H)
srv.requests = []
srv.serve_forever()
