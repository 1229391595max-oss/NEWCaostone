from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Callable

import pytest

from scripts.azure_ai_reconciliation import (
    AzureAIReconciliationInvalid,
    PendingAITransition,
    reconcile_ai_transition,
)


PREDECESSOR = "newcaostone-demo-app--ai-off-old"
TARGET = "newcaostone-demo-app--ai-off-target"
THIRD = "newcaostone-demo-app--unexpected-third"
PREDECESSOR_IMAGE = "sellernorthbpacr.azurecr.io/bizpulse@sha256:" + ("b" * 64)
TARGET_IMAGE = "sellernorthbpacr.azurecr.io/bizpulse@sha256:" + ("c" * 64)
REGISTRY_IDENTITY = (
    "/subscriptions/11111111-1111-4111-8111-111111111111/"
    "resourceGroups/rg-bizpulse-centralus/providers/Microsoft.ManagedIdentity/"
    "userAssignedIdentities/newcaostone-demo-registry"
)
AI_IDENTITY = (
    "/subscriptions/11111111-1111-4111-8111-111111111111/"
    "resourceGroups/rg-bizpulse-centralus/providers/Microsoft.ManagedIdentity/"
    "userAssignedIdentities/newcaostone-ai-identity"
)
IMMUTABLE_CONFIGURATION = {
    "activeRevisionsMode": "Single",
    "ingress": {
        "external": True,
        "fqdn": "newcaostone-demo-app.example.azurecontainerapps.io",
        "traffic": [{"latestRevision": True, "weight": 100}],
    },
    "registries": [
        {
            "server": "sellernorthbpacr.azurecr.io",
            "identity": REGISTRY_IDENTITY,
        }
    ],
}


class FakeClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


class SequenceReader:
    def __init__(self, values: list[object]) -> None:
        self.values = values
        self.calls = 0

    def __call__(self):
        index = min(self.calls, len(self.values) - 1)
        self.calls += 1
        value = self.values[index]
        if isinstance(value, BaseException):
            raise value
        return deepcopy(value)


def _projection(*, revision: str, image: str, enabled: bool) -> dict[str, object]:
    identities = {REGISTRY_IDENTITY: {}}
    environment = [
        {"name": "BIZPULSE_AI_CHAT_ENABLED", "value": str(enabled).lower()},
        {"name": "BIZPULSE_RUNTIME_ENVIRONMENT", "value": "cloud"},
    ]
    if enabled:
        identities[AI_IDENTITY] = {}
        environment.extend(
            [
                {
                    "name": "BIZPULSE_OPENAI_KEY_VAULT_URL",
                    "value": "https://newcaostone-ai-kv.vault.azure.net",
                },
                {
                    "name": "BIZPULSE_OPENAI_KEY_VAULT_SECRET_NAME",
                    "value": "openai-api-key",
                },
            ]
        )
    return {
        "location": "Central US",
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": identities,
        },
        "properties": {
            "template": {
                "revisionSuffix": revision.rsplit("--", 1)[1],
                "containers": [
                    {
                        "name": "bizpulse",
                        "image": image,
                        "env": environment,
                        "probes": [{"type": "Readiness"}],
                        "resources": {"cpu": 0.5, "memory": "1Gi"},
                    }
                ],
                "scale": {"minReplicas": 1, "maxReplicas": 1},
            }
        },
    }


def _application(
    projection: dict[str, object],
    *,
    latest: str,
    ready: str,
    provisioning: str = "Succeeded",
) -> dict[str, object]:
    result = deepcopy(projection)
    result["properties"] = {
        "latestRevisionName": latest,
        "latestReadyRevisionName": ready,
        "provisioningState": provisioning,
        "configuration": deepcopy(IMMUTABLE_CONFIGURATION),
        "template": deepcopy(projection["properties"]["template"]),
    }
    return result


def _revision(
    name: str,
    *,
    active: bool = True,
    health: str | None = "Healthy",
    provisioning: str = "Provisioned",
) -> dict[str, object]:
    return {
        "name": name,
        "properties": {
            "active": active,
            "healthState": health,
            "provisioningState": provisioning,
        },
    }


def _pending(
    *,
    started_at: float = 0.0,
    role: str = "ai_disabled_candidate",
) -> PendingAITransition:
    return PendingAITransition(
        role=role,
        acknowledgement="accepted",
        started_at=started_at,
        predecessor_revision=PREDECESSOR,
        target_revision=TARGET,
        predecessor_projection=_projection(
            revision=PREDECESSOR,
            image=PREDECESSOR_IMAGE,
            enabled=False,
        ),
        target_projection=_projection(
            revision=TARGET,
            image=TARGET_IMAGE,
            enabled=False,
        ),
        target_image=TARGET_IMAGE,
        immutable_configuration=IMMUTABLE_CONFIGURATION,
    )


def test_admin_ai_compatible_candidate_is_an_allowed_reconciliation_role() -> None:
    pending = _pending(role="admin_ai_compatible_candidate")
    application = _application(
        pending.target_projection,
        latest=TARGET,
        ready=TARGET,
    )

    evidence = reconcile_ai_transition(
        pending,
        application_reader=SequenceReader([application]),
        revisions_reader=SequenceReader([[_revision(TARGET)]]),
        monotonic=lambda: 0.0,
        sleeper=lambda _seconds: None,
    )

    assert evidence["role"] == "admin_ai_compatible_candidate"
    assert evidence["final_state"] == "healthy_target"


def test_reconciliation_waits_for_announced_ready_and_healthy_target() -> None:
    pending = _pending()
    predecessor = pending.predecessor_projection
    target = pending.target_projection
    applications = SequenceReader(
        [
            _application(
                predecessor,
                latest=PREDECESSOR,
                ready=PREDECESSOR,
            ),
            _application(target, latest=TARGET, ready=PREDECESSOR),
            _application(target, latest=TARGET, ready=PREDECESSOR),
            _application(target, latest=TARGET, ready=TARGET),
        ]
    )
    revisions = SequenceReader(
        [
            [
                _revision(PREDECESSOR),
                _revision(TARGET, health=None, provisioning="Provisioning"),
            ],
            [
                _revision(PREDECESSOR),
                _revision(TARGET),
            ],
            [
                _revision(PREDECESSOR, active=False),
                _revision(TARGET),
            ],
        ]
    )
    clock = FakeClock()

    evidence = reconcile_ai_transition(
        pending,
        application_reader=applications,
        revisions_reader=revisions,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
    )

    assert evidence == {
        "role": "ai_disabled_candidate",
        "acknowledgement": "accepted",
        "predecessor_revision": PREDECESSOR,
        "target_revision": TARGET,
        "target_image_digest": "sha256:" + ("c" * 64),
        "final_state": "healthy_target",
        "application_read_count": 4,
        "revision_read_count": 3,
        "elapsed_milliseconds": 15000,
    }
    assert applications.calls == 4
    assert revisions.calls == 3
    assert clock.sleeps == [5.0, 5.0, 5.0]


def test_reconciliation_uses_exact_application_template_with_narrow_revision_state() -> None:
    pending = _pending()
    target = pending.target_projection
    applications = SequenceReader(
        [_application(target, latest=TARGET, ready=TARGET)]
    )
    revisions = SequenceReader(
        [
            [
                {
                    "name": TARGET,
                    "properties": {
                        "active": True,
                        "healthState": "Healthy",
                        "provisioningState": "Provisioned",
                    },
                }
            ]
        ]
    )
    clock = FakeClock()

    evidence = reconcile_ai_transition(
        pending,
        application_reader=applications,
        revisions_reader=revisions,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
    )

    assert evidence["final_state"] == "healthy_target"
    assert evidence["application_read_count"] == 1
    assert evidence["revision_read_count"] == 1


def _terminal_case(
    mutation: str,
) -> tuple[dict[str, object], list[dict[str, object]], str, int]:
    pending = _pending()
    target = deepcopy(pending.target_projection)
    latest = TARGET
    ready = TARGET
    provisioning = "Succeeded"
    revisions = [_revision(TARGET)]
    code = "ai_reconciliation_drift"
    revision_reads = 0
    if mutation == "third_latest":
        latest = THIRD
    elif mutation == "third_active":
        ready = PREDECESSOR
        revisions.append(_revision(THIRD))
        revision_reads = 1
    elif mutation == "wrong_image":
        target["properties"]["template"]["containers"][0]["image"] = (
            PREDECESSOR_IMAGE
        )
    elif mutation == "partial_identity":
        target["identity"]["userAssignedIdentities"][AI_IDENTITY] = {}
    elif mutation == "failed":
        provisioning = "Failed"
        code = "ai_reconciliation_failed"
    elif mutation == "unhealthy":
        revisions = [_revision(TARGET, health="Unhealthy")]
        code = "ai_reconciliation_failed"
        revision_reads = 1
    else:  # pragma: no cover - guarded by parametrization
        raise AssertionError(mutation)
    return (
        _application(
            target,
            latest=latest,
            ready=ready,
            provisioning=provisioning,
        ),
        revisions,
        code,
        revision_reads,
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "third_latest",
        "third_active",
        "wrong_image",
        "partial_identity",
        "failed",
        "unhealthy",
    ],
)
def test_terminal_profiles_stop_without_retry(mutation: str) -> None:
    application, revision_rows, code, revision_reads = _terminal_case(mutation)
    applications = SequenceReader([application])
    revisions = SequenceReader([revision_rows])
    clock = FakeClock()

    with pytest.raises(AzureAIReconciliationInvalid, match=code) as raised:
        reconcile_ai_transition(
            _pending(),
            application_reader=applications,
            revisions_reader=revisions,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )

    assert raised.value.evidence["application_read_count"] == 1
    assert raised.value.evidence["revision_read_count"] == revision_reads
    assert raised.value.evidence["elapsed_milliseconds"] == 0
    assert applications.calls == 1
    assert revisions.calls == revision_reads
    assert clock.sleeps == []


def test_timeout_uses_exact_read_and_time_ceilings() -> None:
    pending = _pending()
    target = pending.target_projection
    applications = SequenceReader(
        [_application(target, latest=TARGET, ready=PREDECESSOR)]
    )
    revisions = SequenceReader(
        [[_revision(TARGET, health=None, provisioning="Provisioning")]]
    )
    clock = FakeClock()

    with pytest.raises(
        AzureAIReconciliationInvalid,
        match="ai_reconciliation_timeout",
    ) as raised:
        reconcile_ai_transition(
            pending,
            application_reader=applications,
            revisions_reader=revisions,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )

    assert raised.value.evidence == {
        "role": "ai_disabled_candidate",
        "acknowledgement": "accepted",
        "predecessor_revision": PREDECESSOR,
        "target_revision": TARGET,
        "target_image_digest": "sha256:" + ("c" * 64),
        "final_state": "timeout",
        "application_read_count": 25,
        "revision_read_count": 25,
        "elapsed_milliseconds": 120000,
    }
    assert applications.calls == 25
    assert revisions.calls == 25
    assert clock.sleeps == [5.0] * 24


@pytest.mark.parametrize("reader_name", ["application", "revisions"])
def test_reader_failures_emit_only_closed_safe_evidence(reader_name: str) -> None:
    pending = _pending()
    target = pending.target_projection
    safe_app = _application(target, latest=TARGET, ready=PREDECESSOR)
    sentinel = "sentinel-raw-azure-response-must-not-serialize"
    application_reader: Callable[[], object]
    revisions_reader: Callable[[], object]
    if reader_name == "application":
        application_reader = SequenceReader([RuntimeError(sentinel)])
        revisions_reader = SequenceReader([[]])
    else:
        application_reader = SequenceReader([safe_app])
        revisions_reader = SequenceReader([RuntimeError(sentinel)])
    clock = FakeClock()

    with pytest.raises(
        AzureAIReconciliationInvalid,
        match="ai_reconciliation_read_failed",
    ) as raised:
        reconcile_ai_transition(
            pending,
            application_reader=application_reader,
            revisions_reader=revisions_reader,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )

    assert raised.value.evidence["final_state"] == "read_failed"
    assert sentinel not in str(raised.value)
    assert sentinel not in repr(raised.value.evidence)


def test_invalid_pending_transition_fails_before_any_read() -> None:
    applications = SequenceReader(
        [
            _application(
                _pending().predecessor_projection,
                latest=PREDECESSOR,
                ready=PREDECESSOR,
            )
        ]
    )
    revisions = SequenceReader([[]])

    with pytest.raises(
        AzureAIReconciliationInvalid,
        match="ai_reconciliation_contract_invalid",
    ):
        reconcile_ai_transition(
            replace(_pending(), acknowledgement="unknown"),
            application_reader=applications,
            revisions_reader=revisions,
            monotonic=FakeClock().monotonic,
            sleeper=FakeClock().sleep,
        )

    assert applications.calls == 0
    assert revisions.calls == 0


def test_configuration_drift_is_terminal_before_revision_read() -> None:
    pending = _pending()
    application = _application(
        pending.target_projection,
        latest=TARGET,
        ready=PREDECESSOR,
    )
    application["properties"]["configuration"]["ingress"]["traffic"] = [
        {"latestRevision": True, "weight": 50}
    ]
    applications = SequenceReader([application])
    revisions = SequenceReader([[]])

    with pytest.raises(
        AzureAIReconciliationInvalid,
        match="ai_reconciliation_drift",
    ):
        reconcile_ai_transition(
            pending,
            application_reader=applications,
            revisions_reader=revisions,
            monotonic=FakeClock().monotonic,
            sleeper=FakeClock().sleep,
        )

    assert applications.calls == 1
    assert revisions.calls == 0
