from __future__ import annotations

from threading import Lock

from scripts.verify_hosted_capacity import verify_hosted_capacity


def test_capacity_keeps_all_fifteen_sessions_active_through_reads(monkeypatch) -> None:
    authority = {"active": 0, "peak": 0, "serial": 0}
    lock = Lock()

    class Response:
        def __init__(self, status_code: int, payload: object | None = None):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class Client:
        def __init__(self, **_kwargs):
            self.session_id = ""

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, _url, **_kwargs):
            with lock:
                authority["serial"] += 1
                authority["active"] += 1
                authority["peak"] = max(authority["peak"], authority["active"])
                self.session_id = f"session-{authority['serial']}"
            return Response(
                201,
                {
                    "csrf_token": f"csrf-{self.session_id}",
                    "session": {"session_id": self.session_id},
                },
            )

        def get(self, url):
            with lock:
                assert authority["active"] == 15
            if url.endswith("/current"):
                return Response(200, {"dataset_version_id": "version-1"})
            return Response(200, {"analysis": "verified"})

        def delete(self, _url, **_kwargs):
            with lock:
                authority["active"] -= 1
            return Response(204)

        def close(self):
            return None

    monkeypatch.setattr("scripts.verify_hosted_capacity.httpx.Client", Client)

    verify_hosted_capacity(
        "https://bp-approved-app.synthetic.azurecontainerapps.io"
    )

    assert authority == {"active": 0, "peak": 15, "serial": 15}
