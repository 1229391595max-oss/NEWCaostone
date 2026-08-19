"""Serve fixed health responses while the cloud schema is not yet prepared."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Final


HOST: Final = "0.0.0.0"
PORT: Final = 8000
FENCED_BODY: Final = b'{"status":"phase1-fenced"}\n'
NOT_FOUND_BODY: Final = b'{"error":"not_found"}\n'
METHOD_NOT_ALLOWED_BODY: Final = b'{"error":"method_not_allowed"}\n'
HEALTH_PATHS: Final = frozenset({"/health/live", "/health/ready"})


class Phase1FenceHandler(BaseHTTPRequestHandler):
    """Return only bounded, value-free responses and emit no request logs."""

    def _write(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        body = FENCED_BODY if self.path in HEALTH_PATHS else NOT_FOUND_BODY
        self._write(200 if self.path in HEALTH_PATHS else 404, body)

    def _method_not_allowed(self) -> None:
        self._write(405, METHOD_NOT_ALLOWED_BODY)

    do_POST = _method_not_allowed
    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed
    do_OPTIONS = _method_not_allowed

    def log_message(self, _format: str, *args: object) -> None:
        del _format, args


def build_server(host: str = HOST, port: int = PORT) -> ThreadingHTTPServer:
    """Build the bounded server; tests may pass port zero for isolation."""

    return ThreadingHTTPServer((host, port), Phase1FenceHandler)


def main() -> int:
    """Serve until the Container App revision is stopped."""

    with build_server() as server:
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
