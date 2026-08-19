from __future__ import annotations

import subprocess

import pytest

from scripts.run_azure_readback import (
    AzureReadbackInvalid,
    _HttpViewer,
    run_azure_readback,
)
from scripts.run_hosted_check import HostedCheckInvalid

SUBSCRIPTION = "11111111-1111-4111-8111-111111111111"
AUTHORIZATION = "22222222-2222-4222-8222-222222222222"
CURRENT = "bpapprovedregistry.azurecr.io/bizpulse@sha256:" + "b" * 64
ROLLBACK = "bpapprovedregistry.azurecr.io/bizpulse@sha256:" + "d" * 64


class Viewer:
    instances = []

    def __init__(self, _url: str, _ai_enabled: bool):
        self.closed = False
        self.reconnects = 0
        self.instances.append(self)

    def snapshot(self):
        return {
            "dataset_version_id": "33333333-3333-4333-8333-333333333333",
            "release_hash": "release",
            "analysis_hash": "analysis",
            "action_hash": "actions",
            "chat_hash": "chat",
            "session_id": "44444444-4444-4444-8444-444444444444",
            "status": "active",
        }

    def reconnect(self):
        self.reconnects += 1

    def close(self):
        self.closed = True


def test_restart_and_rollback_keep_same_pinned_viewer_authority() -> None:
    Viewer.instances.clear()
    commands: list[tuple[str, ...]] = []
    images: list[str] = []

    def resolver(**kwargs):
        images.append(kwargs["image"])
        return "https://bp-approved-app.synthetic.azurecontainerapps.io"

    def mutate(command, **_kwargs):
        commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    common = {
        "subscription_id": SUBSCRIPTION,
        "resource_group": "rg-approved",
        "app_name": "bp-approved-app",
        "current_image": CURRENT,
        "authorization_id": AUTHORIZATION,
        "resolver": resolver,
        "health_verifier": lambda _url: None,
        "viewer_factory": Viewer,
        "mutation_runner": mutate,
    }
    run_azure_readback(
        **common,
        operation="restart",
        revision="bp-approved-app--bbbbbbbbbbbb",
    )
    run_azure_readback(
        **common,
        operation="rollback",
        rollback_image=ROLLBACK,
    )

    assert [command[2:4] for command in commands] == [
        ("revision", "restart"),
        ("update", "--name"),
        ("update", "--name"),
    ]
    assert images == [CURRENT, CURRENT, CURRENT, ROLLBACK, CURRENT]
    assert [viewer.reconnects for viewer in Viewer.instances] == [1, 2]


def test_rollback_waits_for_exact_latest_ready_revision_before_snapshot() -> None:
    Viewer.instances.clear()
    attempts = {"rollback": 0}
    sleeps: list[float] = []
    now = {"value": 0.0}
    commands: list[tuple[str, ...]] = []

    def resolver(**kwargs):
        if kwargs["image"] == ROLLBACK:
            attempts["rollback"] += 1
            if attempts["rollback"] < 3:
                raise HostedCheckInvalid("hosted_check_resource_invalid")
        return "https://bp-approved-app.synthetic.azurecontainerapps.io"

    def mutate(command, **_kwargs):
        commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    def sleeper(seconds: float) -> None:
        sleeps.append(seconds)
        now["value"] += seconds

    run_azure_readback(
        subscription_id=SUBSCRIPTION,
        resource_group="rg-approved",
        app_name="bp-approved-app",
        current_image=CURRENT,
        authorization_id=AUTHORIZATION,
        operation="rollback",
        rollback_image=ROLLBACK,
        resolver=resolver,
        health_verifier=lambda _url: None,
        viewer_factory=Viewer,
        mutation_runner=mutate,
        sleeper=sleeper,
        monotonic=lambda: now["value"],
    )

    assert attempts["rollback"] == 3
    assert sleeps == [5, 5]
    assert [command[2:4] for command in commands] == [
        ("update", "--name"),
        ("update", "--name"),
    ]


def test_unready_rollback_stops_before_forward_update() -> None:
    Viewer.instances.clear()
    now = {"value": 0.0}
    commands: list[tuple[str, ...]] = []

    def resolver(**kwargs):
        if kwargs["image"] == ROLLBACK:
            raise HostedCheckInvalid("hosted_check_resource_invalid")
        return "https://bp-approved-app.synthetic.azurecontainerapps.io"

    def mutate(command, **_kwargs):
        commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    with pytest.raises(AzureReadbackInvalid, match="azure_readback_revision_not_ready"):
        run_azure_readback(
            subscription_id=SUBSCRIPTION,
            resource_group="rg-approved",
            app_name="bp-approved-app",
            current_image=CURRENT,
            authorization_id=AUTHORIZATION,
            operation="rollback",
            rollback_image=ROLLBACK,
            resolver=resolver,
            health_verifier=lambda _url: None,
            viewer_factory=Viewer,
            mutation_runner=mutate,
            sleeper=lambda seconds: now.__setitem__("value", now["value"] + seconds),
            monotonic=lambda: now["value"],
        )

    assert [command[2:4] for command in commands] == [("update", "--name")]


def test_recover_forwards_healthy_rollback_without_second_rollback_update() -> None:
    Viewer.instances.clear()
    state = {
        "image": ROLLBACK,
        "revision": "rollback-22222222-ddddddd",
    }
    commands: list[tuple[str, ...]] = []

    def resolver(**kwargs):
        if kwargs["image"] != state["image"]:
            raise HostedCheckInvalid("hosted_check_resource_invalid")
        if kwargs.get("recovery_role") == "rollback":
            if state["revision"].startswith("rollback-"):
                return "https://bp-approved-app.synthetic.azurecontainerapps.io"
            raise HostedCheckInvalid("hosted_check_resource_invalid")
        if kwargs.get("expected_revision_suffix") == state["revision"]:
            return "https://bp-approved-app.synthetic.azurecontainerapps.io"
        raise HostedCheckInvalid("hosted_check_resource_invalid")

    def mutate(command, **_kwargs):
        tokens = tuple(command)
        commands.append(tokens)
        state.update(
            image=tokens[tokens.index("--image") + 1],
            revision=tokens[tokens.index("--revision-suffix") + 1],
        )
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    run_azure_readback(
        subscription_id=SUBSCRIPTION,
        resource_group="rg-approved",
        app_name="bp-approved-app",
        current_image=CURRENT,
        authorization_id=AUTHORIZATION,
        operation="recover",
        rollback_image=ROLLBACK,
        resolver=resolver,
        health_verifier=lambda _url: None,
        viewer_factory=Viewer,
        mutation_runner=mutate,
    )

    assert len(commands) == 1
    assert commands[0][commands[0].index("--image") + 1] == CURRENT
    assert commands[0][commands[0].index("--revision-suffix") + 1].startswith(
        "recover-22222222-bbbbbbb"
    )


def test_recover_rejects_when_current_state_is_not_exact_rollback() -> None:
    clock = iter((0.0, 0.0, 301.0))
    with pytest.raises(AzureReadbackInvalid, match="azure_readback_revision_not_ready"):
        run_azure_readback(
            subscription_id=SUBSCRIPTION,
            resource_group="rg-approved",
            app_name="bp-approved-app",
            current_image=CURRENT,
            authorization_id=AUTHORIZATION,
            operation="recover",
            rollback_image=ROLLBACK,
            resolver=lambda **_kwargs: (_ for _ in ()).throw(
                HostedCheckInvalid("hosted_check_resource_invalid")
            ),
            health_verifier=lambda _url: None,
            viewer_factory=Viewer,
            mutation_runner=lambda command, **_kwargs: subprocess.CompletedProcess(
                command, 0, stdout="{}", stderr=""
            ),
            sleeper=lambda _seconds: None,
            monotonic=lambda: next(clock),
        )


def test_readback_reconnects_before_comparing_mutated_revision() -> None:
    class StaleConnectionViewer(Viewer):
        def __init__(self, url: str, ai_enabled: bool):
            super().__init__(url, ai_enabled)
            self.fresh_transport = False

        def reconnect(self):
            super().reconnect()
            self.fresh_transport = True

        def snapshot(self):
            authority = super().snapshot()
            if self.fresh_transport:
                authority["release_hash"] = "incompatible-new-revision"
            return authority

    with pytest.raises(
        AzureReadbackInvalid,
        match="azure_readback_authority_changed",
    ):
        run_azure_readback(
            subscription_id=SUBSCRIPTION,
            resource_group="rg-approved",
            app_name="bp-approved-app",
            current_image=CURRENT,
            authorization_id=AUTHORIZATION,
            operation="restart",
            revision="bp-approved-app--bbbbbbbbbbbb",
            resolver=lambda **_kwargs: (
                "https://bp-approved-app.synthetic.azurecontainerapps.io"
            ),
            health_verifier=lambda _url: None,
            viewer_factory=StaleConnectionViewer,
            mutation_runner=lambda command, **_kwargs: subprocess.CompletedProcess(
                command, 0, stdout="{}", stderr=""
            ),
        )


def test_rollback_recovers_an_already_active_prior_rehearsal() -> None:
    state = {"image": ROLLBACK, "revision": "old-rollback"}
    commands: list[tuple[str, ...]] = []

    def resolver(**kwargs):
        expected_image = kwargs["image"]
        role = kwargs.get("recovery_role")
        suffix = kwargs.get("expected_revision_suffix")
        if expected_image != state["image"]:
            raise HostedCheckInvalid("hosted_check_resource_invalid")
        if role == "rollback" and state["revision"] == "old-rollback":
            return "https://bp-approved-app.synthetic.azurecontainerapps.io"
        if suffix == state["revision"]:
            return "https://bp-approved-app.synthetic.azurecontainerapps.io"
        raise HostedCheckInvalid("hosted_check_resource_invalid")

    def mutate(command, **_kwargs):
        tokens = tuple(command)
        commands.append(tokens)
        suffix = tokens[tokens.index("--revision-suffix") + 1]
        image = tokens[tokens.index("--image") + 1]
        state.update(image=image, revision=suffix)
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    run_azure_readback(
        subscription_id=SUBSCRIPTION,
        resource_group="rg-approved",
        app_name="bp-approved-app",
        current_image=CURRENT,
        authorization_id=AUTHORIZATION,
        operation="rollback",
        rollback_image=ROLLBACK,
        resolver=resolver,
        health_verifier=lambda _url: None,
        viewer_factory=Viewer,
        mutation_runner=mutate,
    )

    assert [command[2:4] for command in commands] == [
        ("update", "--name"),
        ("update", "--name"),
        ("update", "--name"),
    ]


def test_disabled_ai_readback_requires_explicit_safe_unavailable_projection(
    monkeypatch,
) -> None:
    class Response:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class Client:
        def post(self, url, **_kwargs):
            if url.endswith("/api/demo/sessions"):
                return Response(
                    201,
                    {
                        "csrf_token": "csrf",
                        "session": {"session_id": "session"},
                    },
                )
            return Response(200, {"overlay_revision": 1})

        def get(self, url):
            if url.endswith("/api/demo/sessions/current"):
                return Response(
                    200,
                    {
                        "session": {
                            "dataset_version_id": "version",
                            "session_id": "session",
                            "status": "active",
                        }
                    },
                )
            if url.endswith("/api/v1/ai-chat/turns"):
                return Response(
                    200,
                    {
                        "items": [],
                        "saved_items": [],
                        "recommended_questions": [],
                        "availability": "unavailable",
                        "unavailable_code": "AI_CHAT_UNAVAILABLE",
                    },
                )
            if url.endswith("/api/demo/release/actions"):
                return Response(
                    200,
                    {"items": [{"id": "action", "current_revision": 1}]},
                )
            if url.endswith("/overlays"):
                return Response(200, {"items": [{"overlay_revision": 1}]})
            return Response(200, {"authority": url.rsplit("/", 1)[-1]})

        def delete(self, _url, **_kwargs):
            return Response(204)

        def close(self):
            return None

    monkeypatch.setattr("scripts.run_azure_readback.httpx.Client", lambda **_kwargs: Client())
    viewer = _HttpViewer(
        "https://bp-approved-app.synthetic.azurecontainerapps.io",
        False,
    )
    try:
        assert viewer.snapshot()["status"] == "active"
    finally:
        viewer.close()


def test_disabled_ai_readback_accepts_legacy_safe_unavailable_error(
    monkeypatch,
) -> None:
    class Response:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class Client:
        def post(self, url, **_kwargs):
            if url.endswith("/api/demo/sessions"):
                return Response(
                    201,
                    {
                        "csrf_token": "csrf",
                        "session": {"session_id": "session"},
                    },
                )
            return Response(200, {"overlay_revision": 1})

        def get(self, url):
            if url.endswith("/api/demo/sessions/current"):
                return Response(
                    200,
                    {
                        "session": {
                            "dataset_version_id": "version",
                            "session_id": "session",
                            "status": "active",
                        }
                    },
                )
            if url.endswith("/api/v1/ai-chat/turns"):
                return Response(503, {"code": "AI_CHAT_UNAVAILABLE"})
            if url.endswith("/api/demo/release/actions"):
                return Response(
                    200,
                    {"items": [{"id": "action", "current_revision": 1}]},
                )
            if url.endswith("/overlays"):
                return Response(200, {"items": [{"overlay_revision": 1}]})
            return Response(200, {"authority": url.rsplit("/", 1)[-1]})

        def delete(self, _url, **_kwargs):
            return Response(204)

        def close(self):
            return None

    monkeypatch.setattr("scripts.run_azure_readback.httpx.Client", lambda **_kwargs: Client())
    viewer = _HttpViewer(
        "https://bp-approved-app.synthetic.azurecontainerapps.io",
        False,
    )
    try:
        assert viewer.snapshot()["chat_hash"]
    finally:
        viewer.close()


def test_enabled_ai_readback_creates_deterministic_no_provider_turn(
    monkeypatch,
) -> None:
    questions: list[object] = []

    class Response:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class Client:
        def post(self, url, **kwargs):
            if url.endswith("/api/demo/sessions"):
                return Response(
                    201,
                    {
                        "csrf_token": "csrf",
                        "session": {"session_id": "session"},
                    },
                )
            if url.endswith("/api/v1/ai-chat/turns"):
                questions.append(kwargs["json"])
                return Response(
                    201,
                    {"id": "turn-1", "status": "clarification_required"},
                )
            return Response(200, {"overlay_revision": 1})

        def get(self, url):
            if url.endswith("/api/demo/sessions/current"):
                return Response(
                    200,
                    {
                        "session": {
                            "dataset_version_id": "version",
                            "session_id": "session",
                            "status": "active",
                        }
                    },
                )
            if url.endswith("/api/v1/ai-chat/turns"):
                return Response(200, {"items": [{"id": "turn-1"}]})
            if url.endswith("/api/demo/release/actions"):
                return Response(
                    200,
                    {"items": [{"id": "action", "current_revision": 1}]},
                )
            if url.endswith("/overlays"):
                return Response(200, {"items": [{"overlay_revision": 1}]})
            return Response(200, {"authority": url.rsplit("/", 1)[-1]})

        def delete(self, _url, **_kwargs):
            return Response(204)

        def close(self):
            return None

    monkeypatch.setattr("scripts.run_azure_readback.httpx.Client", lambda **_kwargs: Client())
    viewer = _HttpViewer(
        "https://bp-approved-app.synthetic.azurecontainerapps.io",
        True,
    )
    try:
        assert viewer.snapshot()["chat_hash"]
        assert questions == [{"question": "why"}]
    finally:
        viewer.close()
