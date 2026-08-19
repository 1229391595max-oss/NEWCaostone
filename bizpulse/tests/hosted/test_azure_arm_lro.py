from __future__ import annotations

import pytest

from scripts.azure_arm_lro import ARMOperationInvalid, ARMResponse, wait_for_arm_patch


SUBSCRIPTION = "11111111-1111-4111-8111-111111111111"
APP_RESOURCE_ID = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-bizpulse-centralus/"
    "providers/Microsoft.App/containerApps/newcaostone-demo-app"
)
APP_URL = f"https://management.azure.com{APP_RESOURCE_ID}?api-version=2025-01-01"
OPERATION_URL = (
    f"https://management.azure.com/subscriptions/{SUBSCRIPTION}/providers/"
    "Microsoft.App/locations/centralus/operations/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    "?api-version=2025-01-01"
)
OPERATION_STATUS_URL = (
    f"https://management.azure.com/subscriptions/{SUBSCRIPTION}/providers/"
    "Microsoft.App/locations/centralus/operationStatuses/"
    "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb?api-version=2025-01-01"
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


def test_wait_for_arm_patch_polls_exact_resource_provisioning_state() -> None:
    calls: list[tuple[str, str]] = []
    service_location = (
        f"https://management.azure.com/subscriptions/{SUBSCRIPTION}/providers/"
        "Microsoft.App/locations/centralus/containerAppsOperationStatuses/"
        "cccccccc-cccc-4ccc-8ccc-cccccccccccc?api-version=2025-01-01"
    )
    responses = iter(
        (
            ARMResponse(
                status_code=202,
                headers={"Location": service_location},
                payload={},
            ),
            ARMResponse(
                status_code=200,
                headers={},
                payload={
                    "id": APP_RESOURCE_ID,
                    "provisioningState": "Updating",
                },
            ),
            ARMResponse(
                status_code=200,
                headers={},
                payload={
                    "id": APP_RESOURCE_ID,
                    "provisioningState": "Succeeded",
                },
            ),
        )
    )
    clock = FakeClock()

    wait_for_arm_patch(
        app_resource_id=APP_RESOURCE_ID,
        patch_body={"location": "Central US"},
        request=lambda method, url, _body: calls.append((method, url))
        or next(responses),
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
    )

    assert calls == [
        ("PATCH", APP_URL),
        ("GET", APP_URL),
        ("GET", APP_URL),
    ]
    assert clock.sleeps == [5.0, 5.0]


def test_wait_for_arm_patch_ignores_async_url_and_polls_exact_resource() -> None:
    calls: list[tuple[str, str]] = []
    responses = iter(
        (
            ARMResponse(
                status_code=202,
                headers={"Azure-AsyncOperation": OPERATION_URL},
                payload={},
            ),
            ARMResponse(
                status_code=200,
                headers={},
                payload={
                    "id": APP_RESOURCE_ID,
                    "provisioningState": "Succeeded",
                },
            ),
        )
    )
    clock = FakeClock()

    wait_for_arm_patch(
        app_resource_id=APP_RESOURCE_ID,
        patch_body={"location": "Central US"},
        request=lambda method, url, body: calls.append((method, url))
        or next(responses),
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
    )

    assert calls == [
        ("PATCH", APP_URL),
        ("GET", APP_URL),
    ]
    assert clock.sleeps == [5.0]


def test_wait_for_arm_patch_ignores_container_apps_operation_status_url() -> None:
    calls: list[tuple[str, str]] = []
    responses = iter(
        (
            ARMResponse(
                status_code=202,
                headers={"Azure-AsyncOperation": OPERATION_STATUS_URL},
                payload={},
            ),
            ARMResponse(
                status_code=200,
                headers={},
                payload={
                    "id": APP_RESOURCE_ID,
                    "provisioningState": "Succeeded",
                },
            ),
        )
    )
    clock = FakeClock()

    wait_for_arm_patch(
        app_resource_id=APP_RESOURCE_ID,
        patch_body={"location": "Central US"},
        request=lambda method, url, _body: calls.append((method, url))
        or next(responses),
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
    )

    assert calls == [("PATCH", APP_URL), ("GET", APP_URL)]


def test_wait_for_arm_patch_honors_initial_retry_after_before_polling() -> None:
    responses = iter(
        (
            ARMResponse(
                status_code=202,
                headers={
                    "Azure-AsyncOperation": OPERATION_URL,
                    "Retry-After": "7",
                },
                payload={},
            ),
            ARMResponse(
                status_code=200,
                headers={},
                payload={
                    "id": APP_RESOURCE_ID,
                    "provisioningState": "Succeeded",
                },
            ),
        )
    )
    clock = FakeClock()

    wait_for_arm_patch(
        app_resource_id=APP_RESOURCE_ID,
        patch_body={"location": "Central US"},
        request=lambda _method, _url, _body: next(responses),
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
    )

    assert clock.sleeps == [7.0]


def test_wait_for_arm_patch_requires_resource_identity_and_terminal_state() -> None:
    responses = iter(
        (
            ARMResponse(status_code=202, headers={"Location": OPERATION_URL}, payload={}),
            ARMResponse(
                status_code=200,
                headers={},
                payload={
                    "id": APP_RESOURCE_ID,
                    "provisioningState": "Succeeded",
                },
            ),
        )
    )
    clock = FakeClock()

    wait_for_arm_patch(
        app_resource_id=APP_RESOURCE_ID,
        patch_body={"location": "Central US"},
        request=lambda _method, _url, _body: next(responses),
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
    )

    assert clock.sleeps == [5.0]


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (
            ARMResponse(
                status_code=202,
                headers={"Azure-AsyncOperation": OPERATION_URL, "Retry-After": "0"},
                payload={},
            ),
            "ai_enablement_patch_unconfirmed",
        ),
        (
            ARMResponse(status_code=500, headers={}, payload={}),
            "ai_enablement_patch_unconfirmed",
        ),
        (
            ARMResponse(
                status_code=202,
                headers={"Azure-AsyncOperation": OPERATION_URL},
                payload=[],  # type: ignore[arg-type]
            ),
            "ai_enablement_patch_unconfirmed",
        ),
    ],
)
def test_wait_for_arm_patch_rejects_malformed_initial_response(
    response: ARMResponse, expected_code: str
) -> None:
    calls: list[str] = []

    with pytest.raises(ARMOperationInvalid, match=expected_code):
        wait_for_arm_patch(
            app_resource_id=APP_RESOURCE_ID,
            patch_body={"location": "Central US"},
            request=lambda method, _url, _body: calls.append(method) or response,
            monotonic=FakeClock().monotonic,
            sleeper=FakeClock().sleep,
        )

    assert calls == ["PATCH"]


@pytest.mark.parametrize("status", ["Failed", "Canceled"])
def test_wait_for_arm_patch_rejects_terminal_failure(status: str) -> None:
    responses = iter(
        (
            ARMResponse(
                status_code=202,
                headers={"Azure-AsyncOperation": OPERATION_URL},
                payload={},
            ),
            ARMResponse(
                status_code=200,
                headers={},
                payload={
                    "id": APP_RESOURCE_ID,
                    "provisioningState": status,
                },
            ),
        )
    )
    clock = FakeClock()

    with pytest.raises(ARMOperationInvalid, match="ai_enablement_arm_operation_failed"):
        wait_for_arm_patch(
            app_resource_id=APP_RESOURCE_ID,
            patch_body={"location": "Central US"},
            request=lambda _method, _url, _body: next(responses),
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )


def test_wait_for_arm_patch_rejects_direct_success_without_the_expected_app_id() -> None:
    with pytest.raises(ARMOperationInvalid, match="ai_enablement_patch_unconfirmed"):
        wait_for_arm_patch(
            app_resource_id=APP_RESOURCE_ID,
            patch_body={"location": "Central US"},
            request=lambda _method, _url, _body: ARMResponse(
                status_code=200,
                headers={},
                payload={},
            ),
        )


def test_wait_for_arm_patch_rejects_polled_resource_identity_drift() -> None:
    responses = iter(
        (
            ARMResponse(status_code=202, headers={}, payload={}),
            ARMResponse(
                status_code=200,
                headers={},
                payload={
                    "id": f"{APP_RESOURCE_ID}-other",
                    "provisioningState": "Succeeded",
                },
            ),
        )
    )
    clock = FakeClock()

    with pytest.raises(ARMOperationInvalid, match="ai_enablement_patch_unconfirmed"):
        wait_for_arm_patch(
            app_resource_id=APP_RESOURCE_ID,
            patch_body={"location": "Central US"},
            request=lambda _method, _url, _body: next(responses),
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )


def test_wait_for_arm_patch_never_requests_a_service_supplied_location() -> None:
    calls: list[tuple[str, str]] = []
    clock = FakeClock()
    non_operation_url = (
        f"https://management.azure.com/subscriptions/{SUBSCRIPTION}/resourceGroups/"
        "rg-bizpulse-centralus?api-version=2025-01-01"
    )

    responses = iter(
        (
            ARMResponse(
                status_code=202,
                headers={"Azure-AsyncOperation": non_operation_url},
                payload={},
            ),
            ARMResponse(
                status_code=200,
                headers={},
                payload={
                    "id": APP_RESOURCE_ID,
                    "provisioningState": "Succeeded",
                },
            ),
        )
    )

    wait_for_arm_patch(
        app_resource_id=APP_RESOURCE_ID,
        patch_body={"location": "Central US"},
        request=lambda method, url, _body: calls.append((method, url))
        or next(responses),
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
    )

    assert calls == [("PATCH", APP_URL), ("GET", APP_URL)]


def test_wait_for_arm_patch_rejects_success_reported_after_deadline() -> None:
    clock = FakeClock()

    def request(method, _url, _body):
        if method == "PATCH":
            return ARMResponse(
                status_code=202,
                headers={
                    "Azure-AsyncOperation": OPERATION_URL,
                    "Retry-After": "1",
                },
                payload={},
            )
        clock.value = 301.0
        return ARMResponse(
            status_code=200,
            headers={},
            payload={
                "id": APP_RESOURCE_ID,
                "provisioningState": "Succeeded",
            },
        )

    with pytest.raises(ARMOperationInvalid, match="ai_enablement_patch_unconfirmed"):
        wait_for_arm_patch(
            app_resource_id=APP_RESOURCE_ID,
            patch_body={"location": "Central US"},
            request=request,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )


def test_wait_for_arm_patch_rejects_a_nonfinite_clock_before_the_patch() -> None:
    calls: list[str] = []

    with pytest.raises(ARMOperationInvalid, match="ai_enablement_patch_unconfirmed"):
        wait_for_arm_patch(
            app_resource_id=APP_RESOURCE_ID,
            patch_body={"location": "Central US"},
            request=lambda method, _url, _body: calls.append(method)
            or ARMResponse(
                status_code=200,
                headers={},
                payload={"id": APP_RESOURCE_ID},
            ),
            monotonic=lambda: float("nan"),
        )

    assert calls == []
