"""Fail-closed Azure ARM long-running-operation handling for one PATCH."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
import math
import re
import time


ARM_HOST = "management.azure.com"
ARM_API_VERSION = "2025-01-01"
MAX_ARM_OPERATION_SECONDS = 300.0
DEFAULT_POLL_SECONDS = 5.0
MAX_RETRY_AFTER_SECONDS = 15

_APP_RESOURCE_ID = re.compile(
    r"/subscriptions/"
    r"(?P<subscription>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})/"
    r"resourceGroups/[A-Za-z0-9._()-]+/"
    r"providers/Microsoft\.App/containerApps/[a-z0-9-]+",
    re.IGNORECASE,
)
@dataclass(frozen=True)
class ARMResponse:
    """Small non-persistent projection of an ARM HTTP response."""

    status_code: int
    headers: Mapping[str, str]
    payload: Mapping[str, object]


class ARMOperationInvalid(RuntimeError):
    """Raised with a closed code; remote response data is never retained."""


ARMRequester = Callable[[str, str, Mapping[str, object] | None], ARMResponse]


def _invalid(code: str) -> ARMOperationInvalid:
    return ARMOperationInvalid(code)


def _application_url(app_resource_id: str) -> str:
    if _APP_RESOURCE_ID.fullmatch(app_resource_id) is None:
        raise _invalid("ai_enablement_patch_unconfirmed")
    return f"https://{ARM_HOST}{app_resource_id}?api-version={ARM_API_VERSION}"


def _response(value: object) -> ARMResponse:
    if not isinstance(value, ARMResponse):
        raise _invalid("ai_enablement_patch_unconfirmed")
    if (
        not isinstance(value.status_code, int)
        or isinstance(value.status_code, bool)
        or not isinstance(value.headers, Mapping)
        or not isinstance(value.payload, Mapping)
        or not all(
            isinstance(key, str) and isinstance(item, str)
            for key, item in value.headers.items()
        )
    ):
        raise _invalid("ai_enablement_patch_unconfirmed")
    return ARMResponse(
        status_code=value.status_code,
        headers=deepcopy(dict(value.headers)),
        payload=deepcopy(dict(value.payload)),
    )


def _header(response: ARMResponse, name: str) -> str | None:
    values = {
        key.casefold(): value for key, value in response.headers.items()
    }
    return values.get(name.casefold())


def _wait_seconds(response: ARMResponse) -> float:
    retry_after = _header(response, "Retry-After")
    if retry_after is None:
        return DEFAULT_POLL_SECONDS
    if not retry_after.isdecimal():
        raise _invalid("ai_enablement_patch_unconfirmed")
    delay = int(retry_after)
    if not 1 <= delay <= MAX_RETRY_AFTER_SECONDS:
        raise _invalid("ai_enablement_patch_unconfirmed")
    return float(delay)


def _elapsed_seconds(monotonic: Callable[[], float], started_at: float) -> float:
    try:
        elapsed = monotonic() - started_at
    except Exception as error:
        raise _invalid("ai_enablement_patch_unconfirmed") from error
    if (
        not isinstance(elapsed, (int, float))
        or isinstance(elapsed, bool)
        or not math.isfinite(float(elapsed))
        or elapsed < 0
    ):
        raise _invalid("ai_enablement_patch_unconfirmed")
    return float(elapsed)


def _resource_state(response: ARMResponse, *, app_resource_id: str) -> str:
    if response.status_code == 202:
        return "waiting"
    if response.status_code != 200:
        raise _invalid("ai_enablement_patch_unconfirmed")
    resource_id = response.payload.get("id")
    status = response.payload.get("provisioningState")
    if (
        not isinstance(resource_id, str)
        or resource_id.casefold() != app_resource_id.casefold()
        or not isinstance(status, str)
    ):
        raise _invalid("ai_enablement_patch_unconfirmed")
    normalized = status.casefold()
    if normalized == "succeeded":
        return "succeeded"
    if normalized in {"accepted", "creating", "inprogress", "running", "updating"}:
        return "waiting"
    if normalized in {"failed", "canceled", "cancelled"}:
        raise _invalid("ai_enablement_arm_operation_failed")
    raise _invalid("ai_enablement_patch_unconfirmed")


def wait_for_arm_patch(
    *,
    app_resource_id: str,
    patch_body: Mapping[str, object],
    request: ARMRequester,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    """Issue one ARM PATCH and wait for its allowed long-running operation."""

    application_url = _application_url(app_resource_id)
    if not isinstance(patch_body, Mapping):
        raise _invalid("ai_enablement_patch_unconfirmed")
    try:
        started_at = monotonic()
    except Exception as error:
        raise _invalid("ai_enablement_patch_unconfirmed") from error
    if (
        not isinstance(started_at, (int, float))
        or isinstance(started_at, bool)
        or not math.isfinite(float(started_at))
    ):
        raise _invalid("ai_enablement_patch_unconfirmed")
    try:
        initial = _response(
            request("PATCH", application_url, deepcopy(dict(patch_body)))
        )
    except ARMOperationInvalid:
        raise
    except Exception as error:
        raise _invalid("ai_enablement_patch_unconfirmed") from error
    if _elapsed_seconds(monotonic, float(started_at)) > MAX_ARM_OPERATION_SECONDS:
        raise _invalid("ai_enablement_patch_unconfirmed")
    response_id = initial.payload.get("id")
    if initial.status_code in {200, 201}:
        if (
            not isinstance(response_id, str)
            or response_id.casefold() != app_resource_id.casefold()
        ):
            raise _invalid("ai_enablement_patch_unconfirmed")
        return
    if initial.status_code != 202:
        raise _invalid("ai_enablement_patch_unconfirmed")
    if response_id is not None and (
        not isinstance(response_id, str)
        or response_id.casefold() != app_resource_id.casefold()
    ):
        raise _invalid("ai_enablement_patch_unconfirmed")
    initial_delay = _wait_seconds(initial)
    if (
        _elapsed_seconds(monotonic, float(started_at)) + initial_delay
        > MAX_ARM_OPERATION_SECONDS
    ):
        raise _invalid("ai_enablement_patch_unconfirmed")
    try:
        sleeper(initial_delay)
    except Exception as error:
        raise _invalid("ai_enablement_patch_unconfirmed") from error
    while True:
        if _elapsed_seconds(monotonic, float(started_at)) >= MAX_ARM_OPERATION_SECONDS:
            raise _invalid("ai_enablement_patch_unconfirmed")
        try:
            resource = _response(request("GET", application_url, None))
        except ARMOperationInvalid:
            raise
        except Exception as error:
            raise _invalid("ai_enablement_patch_unconfirmed") from error
        if _elapsed_seconds(monotonic, float(started_at)) > MAX_ARM_OPERATION_SECONDS:
            raise _invalid("ai_enablement_patch_unconfirmed")
        state = _resource_state(resource, app_resource_id=app_resource_id)
        if state == "succeeded":
            return
        delay = _wait_seconds(resource)
        if _elapsed_seconds(monotonic, float(started_at)) + delay > MAX_ARM_OPERATION_SECONDS:
            raise _invalid("ai_enablement_patch_unconfirmed")
        try:
            sleeper(delay)
        except Exception as error:
            raise _invalid("ai_enablement_patch_unconfirmed") from error
