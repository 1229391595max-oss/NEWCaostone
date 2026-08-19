from __future__ import annotations

import ast
import http.client
import importlib.util
import threading
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVER_PATH = PROJECT_ROOT / "scripts/phase1_fence_server.py"
FENCED_BODY = b'{"status":"phase1-fenced"}\n'
NOT_FOUND_BODY = b'{"error":"not_found"}\n'
METHOD_NOT_ALLOWED_BODY = b'{"error":"method_not_allowed"}\n'


def _load_server_module() -> ModuleType:
    assert SERVER_PATH.is_file(), "phase1_fence_server_missing"
    spec = importlib.util.spec_from_file_location("phase1_fence_server", SERVER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def _running_server() -> Iterator[tuple[str, int]]:
    module = _load_server_module()
    server = module.build_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield str(host), int(port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _request(
    host: str,
    port: int,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection(host, port, timeout=2)
    try:
        connection.request(method, path, body=body)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def test_phase1_fence_serves_only_bounded_health_responses() -> None:
    with _running_server() as (host, port):
        for path in ("/health/live", "/health/ready"):
            status, headers, body = _request(host, port, "GET", path)

            assert status == 200
            assert headers["Content-Type"] == "application/json"
            assert headers["Cache-Control"] == "no-store"
            assert headers["Content-Length"] == str(len(FENCED_BODY))
            assert body == FENCED_BODY

        for path in ("/", "/metrics", "/health/live?secret-sentinel"):
            status, headers, body = _request(host, port, "GET", path)

            assert status == 404
            assert headers["Content-Length"] == str(len(NOT_FOUND_BODY))
            assert body == NOT_FOUND_BODY
            assert b"secret-sentinel" not in body


def test_phase1_fence_rejects_mutating_methods_without_reflection() -> None:
    with _running_server() as (host, port):
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            status, headers, body = _request(
                host,
                port,
                method,
                "/health/ready?secret-sentinel",
                body=b"secret-body-sentinel",
            )

            assert status == 405
            assert headers["Content-Length"] == str(len(METHOD_NOT_ALLOWED_BODY))
            assert body == METHOD_NOT_ALLOWED_BODY
            assert b"secret" not in body


def test_phase1_fence_has_no_application_or_external_dependency_imports() -> None:
    assert SERVER_PATH.is_file(), "phase1_fence_server_missing"
    source = SERVER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_modules.update(
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )

    assert imported_modules <= {"__future__", "http", "typing"}
    lowered = source.lower()
    for forbidden in (
        "os.environ",
        "getenv",
        "sqlalchemy",
        "azure",
        "from api",
        "import api",
        "from src",
        "import src",
    ):
        assert forbidden not in lowered
