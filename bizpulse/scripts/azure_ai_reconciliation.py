"""Bounded, fail-closed reconciliation for one Container Apps AI revision."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import math
import re
import time


MAX_RECONCILIATION_SECONDS = 120.0
POLL_INTERVAL_SECONDS = 5.0
MAX_APPLICATION_READS = 25
MAX_REVISION_READS = 25
ALLOWED_ROLES = frozenset(
    {
        "ai_disabled_candidate",
        "admin_ai_compatible_candidate",
        "budget_enabled",
        "budget_recovery",
        "provider_enabled",
        "provider_recovery",
        "ai_enabled",
        "emergency_disabled",
    }
)
FINAL_STATES = frozenset(
    {"healthy_target", "drift", "failed", "read_failed", "timeout"}
)

_REVISION_PATTERN = re.compile(r"[a-z][a-z0-9-]{2,126}")
_IMAGE_PATTERN = re.compile(
    r"[a-z0-9][a-z0-9-]{2,49}\.azurecr\.io/"
    r"[a-z0-9][a-z0-9._/-]{1,127}@sha256:[0-9a-f]{64}"
)
_WAITING_PROVISIONING_STATES = frozenset(
    {"InProgress", "Provisioning", "Updating"}
)


@dataclass(frozen=True)
class PendingAITransition:
    """Exact predecessor and target authority for one acknowledged PATCH."""

    role: str
    acknowledgement: str
    started_at: float
    predecessor_revision: str
    target_revision: str
    predecessor_projection: Mapping[str, object]
    target_projection: Mapping[str, object]
    target_image: str
    immutable_configuration: Mapping[str, object]


@dataclass(frozen=True)
class ReconciliationEvidence:
    """Closed, non-secret evidence safe for an execution receipt."""

    role: str
    acknowledgement: str
    predecessor_revision: str
    target_revision: str
    target_image_digest: str
    final_state: str
    application_read_count: int
    revision_read_count: int
    elapsed_milliseconds: int

    def as_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "acknowledgement": self.acknowledgement,
            "predecessor_revision": self.predecessor_revision,
            "target_revision": self.target_revision,
            "target_image_digest": self.target_image_digest,
            "final_state": self.final_state,
            "application_read_count": self.application_read_count,
            "revision_read_count": self.revision_read_count,
            "elapsed_milliseconds": self.elapsed_milliseconds,
        }


class AzureAIReconciliationInvalid(RuntimeError):
    """One transition failed with only a stable code and sanitized evidence."""

    def __init__(
        self,
        code: str,
        evidence: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(code)
        self.evidence = deepcopy(dict(evidence or {}))


def _contract_invalid() -> AzureAIReconciliationInvalid:
    return AzureAIReconciliationInvalid("ai_reconciliation_contract_invalid")


def _projection(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != {
        "location",
        "identity",
        "properties",
    }:
        raise _contract_invalid()
    location = value.get("location")
    identity = value.get("identity")
    properties = value.get("properties")
    if (
        not isinstance(location, str)
        or not location
        or not isinstance(identity, Mapping)
        or not isinstance(properties, Mapping)
        or set(properties) != {"template"}
        or not isinstance(properties.get("template"), Mapping)
    ):
        raise _contract_invalid()
    return deepcopy(dict(value))


def _validate_pending(pending: object) -> PendingAITransition:
    if (
        not isinstance(pending, PendingAITransition)
        or pending.role not in ALLOWED_ROLES
        or pending.acknowledgement != "accepted"
        or not isinstance(pending.started_at, (int, float))
        or isinstance(pending.started_at, bool)
        or not math.isfinite(float(pending.started_at))
        or float(pending.started_at) < 0
        or not isinstance(pending.predecessor_revision, str)
        or _REVISION_PATTERN.fullmatch(pending.predecessor_revision) is None
        or not isinstance(pending.target_revision, str)
        or _REVISION_PATTERN.fullmatch(pending.target_revision) is None
        or pending.target_revision == pending.predecessor_revision
        or not isinstance(pending.target_image, str)
        or _IMAGE_PATTERN.fullmatch(pending.target_image) is None
    ):
        raise _contract_invalid()
    predecessor = _projection(pending.predecessor_projection)
    target = _projection(pending.target_projection)
    configuration = pending.immutable_configuration
    if (
        not isinstance(configuration, Mapping)
        or set(configuration) != {"activeRevisionsMode", "ingress", "registries"}
        or configuration.get("activeRevisionsMode") != "Single"
        or not isinstance(configuration.get("ingress"), Mapping)
        or not isinstance(configuration.get("registries"), list)
    ):
        raise _contract_invalid()
    try:
        target_containers = target["properties"]["template"]["containers"]
    except (KeyError, TypeError) as error:
        raise _contract_invalid() from error
    if (
        not isinstance(target_containers, list)
        or len(target_containers) != 1
        or not isinstance(target_containers[0], Mapping)
        or target_containers[0].get("image") != pending.target_image
    ):
        raise _contract_invalid()
    return PendingAITransition(
        role=pending.role,
        acknowledgement=pending.acknowledgement,
        started_at=float(pending.started_at),
        predecessor_revision=pending.predecessor_revision,
        target_revision=pending.target_revision,
        predecessor_projection=predecessor,
        target_projection=target,
        target_image=pending.target_image,
        immutable_configuration=deepcopy(dict(configuration)),
    )


def _elapsed_milliseconds(
    pending: PendingAITransition,
    monotonic: Callable[[], float],
) -> int:
    try:
        observed = monotonic()
    except Exception as error:
        raise _contract_invalid() from error
    if (
        not isinstance(observed, (int, float))
        or isinstance(observed, bool)
        or not math.isfinite(float(observed))
        or float(observed) < pending.started_at
    ):
        raise _contract_invalid()
    return int((float(observed) - pending.started_at) * 1000)


def _evidence(
    pending: PendingAITransition,
    *,
    final_state: str,
    application_reads: int,
    revision_reads: int,
    monotonic: Callable[[], float],
) -> dict[str, object]:
    if final_state not in FINAL_STATES:
        raise _contract_invalid()
    return ReconciliationEvidence(
        role=pending.role,
        acknowledgement=pending.acknowledgement,
        predecessor_revision=pending.predecessor_revision,
        target_revision=pending.target_revision,
        target_image_digest=pending.target_image.rsplit("@", 1)[1],
        final_state=final_state,
        application_read_count=application_reads,
        revision_read_count=revision_reads,
        elapsed_milliseconds=min(
            _elapsed_milliseconds(pending, monotonic),
            int(MAX_RECONCILIATION_SECONDS * 1000),
        ),
    ).as_dict()


def _raise_terminal(
    code: str,
    pending: PendingAITransition,
    *,
    final_state: str,
    application_reads: int,
    revision_reads: int,
    monotonic: Callable[[], float],
) -> None:
    raise AzureAIReconciliationInvalid(
        code,
        _evidence(
            pending,
            final_state=final_state,
            application_reads=application_reads,
            revision_reads=revision_reads,
            monotonic=monotonic,
        ),
    )


def _application_state(
    value: object,
    pending: PendingAITransition,
) -> tuple[str, str, str, str]:
    if not isinstance(value, Mapping) or set(value) != {
        "location",
        "identity",
        "properties",
    }:
        raise ValueError("application_shape")
    properties = value.get("properties")
    if not isinstance(properties, Mapping) or set(properties) != {
        "configuration",
        "latestRevisionName",
        "latestReadyRevisionName",
        "provisioningState",
        "template",
    }:
        raise ValueError("application_shape")
    projection = {
        "location": value.get("location"),
        "identity": deepcopy(value.get("identity")),
        "properties": {"template": deepcopy(properties.get("template"))},
    }
    configuration = properties.get("configuration")
    predecessor = dict(pending.predecessor_projection)
    target = dict(pending.target_projection)
    if configuration != pending.immutable_configuration:
        profile = "drift"
    elif projection == predecessor:
        profile = "predecessor"
    elif projection == target:
        profile = "target"
    else:
        profile = "drift"
    latest = properties.get("latestRevisionName")
    ready = properties.get("latestReadyRevisionName")
    provisioning = properties.get("provisioningState")
    if not all(isinstance(item, str) for item in (latest, ready, provisioning)):
        raise ValueError("application_shape")
    return profile, str(latest), str(ready), str(provisioning)


def _revision_state(value: object) -> tuple[str, bool, str | None, str | None]:
    if not isinstance(value, Mapping) or set(value) != {"name", "properties"}:
        raise ValueError("revision_shape")
    name = value.get("name")
    properties = value.get("properties")
    if (
        not isinstance(name, str)
        or _REVISION_PATTERN.fullmatch(name) is None
        or not isinstance(properties, Mapping)
        or set(properties) != {"active", "healthState", "provisioningState"}
        or not isinstance(properties.get("active"), bool)
        or properties.get("healthState") is not None
        and not isinstance(properties.get("healthState"), str)
        or properties.get("provisioningState") is not None
        and not isinstance(properties.get("provisioningState"), str)
    ):
        raise ValueError("revision_shape")
    return (
        name,
        bool(properties["active"]),
        properties.get("healthState"),
        properties.get("provisioningState"),
    )


def reconcile_ai_transition(
    pending: PendingAITransition,
    *,
    application_reader: Callable[[], Mapping[str, object]],
    revisions_reader: Callable[[], Sequence[Mapping[str, object]]],
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    """Poll one acknowledged transition without retrying its PATCH."""

    validated = _validate_pending(pending)
    application_reads = 0
    revision_reads = 0
    allowed_revisions = {
        validated.predecessor_revision,
        validated.target_revision,
    }

    for cycle in range(MAX_APPLICATION_READS):
        if _elapsed_milliseconds(validated, monotonic) > int(
            MAX_RECONCILIATION_SECONDS * 1000
        ):
            _raise_terminal(
                "ai_reconciliation_timeout",
                validated,
                final_state="timeout",
                application_reads=application_reads,
                revision_reads=revision_reads,
                monotonic=monotonic,
            )
        application_reads += 1
        try:
            raw_application = application_reader()
            profile, latest, ready, app_provisioning = _application_state(
                raw_application,
                validated,
            )
        except AzureAIReconciliationInvalid:
            raise
        except Exception:
            _raise_terminal(
                "ai_reconciliation_read_failed",
                validated,
                final_state="read_failed",
                application_reads=application_reads,
                revision_reads=revision_reads,
                monotonic=monotonic,
            )

        if app_provisioning in {"Failed", "Unhealthy"}:
            _raise_terminal(
                "ai_reconciliation_failed",
                validated,
                final_state="failed",
                application_reads=application_reads,
                revision_reads=revision_reads,
                monotonic=monotonic,
            )
        if (
            profile == "drift"
            or latest not in allowed_revisions
            or ready not in allowed_revisions
            or app_provisioning
            not in {"Succeeded", *_WAITING_PROVISIONING_STATES}
            or profile == "predecessor"
            and validated.target_revision in {latest, ready}
        ):
            _raise_terminal(
                "ai_reconciliation_drift",
                validated,
                final_state="drift",
                application_reads=application_reads,
                revision_reads=revision_reads,
                monotonic=monotonic,
            )

        target_announced = validated.target_revision in {latest, ready}
        target_row: tuple[str, bool, str | None, str | None] | None = None
        if target_announced:
            revision_reads += 1
            try:
                raw_revisions = revisions_reader()
                if (
                    not isinstance(raw_revisions, Sequence)
                    or isinstance(raw_revisions, (str, bytes, bytearray))
                ):
                    raise ValueError("revision_list_shape")
                revisions = [_revision_state(item) for item in raw_revisions]
            except Exception:
                _raise_terminal(
                    "ai_reconciliation_read_failed",
                    validated,
                    final_state="read_failed",
                    application_reads=application_reads,
                    revision_reads=revision_reads,
                    monotonic=monotonic,
                )
            if any(name not in allowed_revisions and active for name, active, *_ in revisions):
                _raise_terminal(
                    "ai_reconciliation_drift",
                    validated,
                    final_state="drift",
                    application_reads=application_reads,
                    revision_reads=revision_reads,
                    monotonic=monotonic,
                )
            target_row = next(
                (item for item in revisions if item[0] == validated.target_revision),
                None,
            )
            if target_row is not None:
                _, target_active, target_health, target_provisioning = target_row
                if target_health == "Unhealthy" or target_provisioning == "Failed":
                    _raise_terminal(
                        "ai_reconciliation_failed",
                        validated,
                        final_state="failed",
                        application_reads=application_reads,
                        revision_reads=revision_reads,
                        monotonic=monotonic,
                    )
                if (
                    profile == "target"
                    and latest == validated.target_revision
                    and ready == validated.target_revision
                    and app_provisioning == "Succeeded"
                    and target_active
                    and target_health == "Healthy"
                    and target_provisioning == "Provisioned"
                ):
                    return _evidence(
                        validated,
                        final_state="healthy_target",
                        application_reads=application_reads,
                        revision_reads=revision_reads,
                        monotonic=monotonic,
                    )

        elapsed = _elapsed_milliseconds(validated, monotonic)
        if (
            cycle == MAX_APPLICATION_READS - 1
            or elapsed >= int(MAX_RECONCILIATION_SECONDS * 1000)
            or revision_reads >= MAX_REVISION_READS
        ):
            _raise_terminal(
                "ai_reconciliation_timeout",
                validated,
                final_state="timeout",
                application_reads=application_reads,
                revision_reads=revision_reads,
                monotonic=monotonic,
            )
        try:
            sleeper(POLL_INTERVAL_SECONDS)
        except Exception:
            _raise_terminal(
                "ai_reconciliation_read_failed",
                validated,
                final_state="read_failed",
                application_reads=application_reads,
                revision_reads=revision_reads,
                monotonic=monotonic,
            )

    raise AssertionError("unreachable")
