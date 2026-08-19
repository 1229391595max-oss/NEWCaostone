from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import stat

import pytest

import scripts.run_ai_enablement as run_ai_enablement
from scripts.ai_enablement_contract import STATE_ORDER
from scripts.azure_ai_enablement_actions import AzureAIEnablementActionInvalid
from scripts.create_ai_enablement_package import (
    ARTIFACTS,
    AZURE_TARGET,
    build_ai_enablement_package,
    write_ai_enablement_package,
)
from scripts.run_ai_enablement import (
    AIEnablementRunInvalid,
    d3_state_from_paths,
    execute_ai_enablement,
    main,
)


NOW = datetime(2026, 8, 17, 12, 30, 0, tzinfo=UTC)
HEAD = "1" * 40
TREE = "2" * 40
DIGEST = "sha256:" + ("a" * 64)
SENTINEL = "sentinel-provider-value-never-serialize"
SUBSCRIPTION = "fc89e7d3-5428-425e-863f-415859810c2c"
TENANT = "13d04c38-d91c-4f9f-8b65-6af2b515dd63"
CLIENT_ID = "33333333-3333-4333-8333-333333333333"


def _reconciliation(role: str, index: int) -> dict[str, object]:
    return {
        "role": role,
        "acknowledgement": "accepted",
        "predecessor_revision": f"newcaostone-demo-app--step-{index}-old",
        "target_revision": f"newcaostone-demo-app--step-{index}-new",
        "target_image_digest": DIGEST,
        "final_state": "healthy_target",
        "application_read_count": 2,
        "revision_read_count": 2,
        "elapsed_milliseconds": 5000,
    }


RECONCILIATIONS = [
    _reconciliation(role, index)
    for index, role in enumerate(
        (
            "ai_disabled_candidate",
            "budget_enabled",
            "budget_recovery",
            "provider_enabled",
            "provider_recovery",
            "ai_enabled",
        ),
        start=1,
    )
]
EMERGENCY_RECOVERY = {
    "ai_disabled_confirmed": True,
    "placeholder_overwrite_succeeded": True,
    "reconciliation": _reconciliation("emergency_disabled", 7),
}


def _package(
    *, role_assignment_state: str = "legacy_only"
) -> dict[str, object]:
    return build_ai_enablement_package(
        generated_at=NOW - timedelta(minutes=30),
        role_assignment_state=role_assignment_state,
        repository={
            "branch": "codex/newcaostone-authoritative-v1",
            "head_sha": HEAD,
            "tree_sha": TREE,
            "clean": True,
        },
        azure_target=deepcopy(AZURE_TARGET),
        candidate={
            "image_repository": "bizpulse",
            "source_tree_sha": TREE,
            "dockerfile_sha256": "3" * 64,
            "runtime_lock_sha256": "4" * 64,
            "image_input_sha256": "5" * 64,
            "candidate_image_digest": None,
        },
        control_sha256={
            "infra/ai_enablement.bicep": "6" * 64,
            "infra/ai_secret_write.bicep": "a" * 64,
            "scripts/ai_enablement_contract.py": "7" * 64,
            "scripts/azure_ai_enablement_actions.py": "b" * 64,
            "scripts/azure_ai_reconciliation.py": "c" * 64,
            "scripts/azure_ai_revision.py": "8" * 64,
            "scripts/run_ai_enablement.py": "9" * 64,
        },
        d3={
            "branch": "codex/deployed-diagnostic-d3",
            "selected_base_sha": "afd3a2f0a9311aafaca35ad4a412c911aadf1e32",
            "package_sha256": (
                "2ca7c7aa0d133b94607569af437dcf0f6a2b7aa44afc475c332dfe16e0ac8687"
            ),
            "package_mode": "0600",
            "receipt_present": False,
            "observation_present": False,
        },
    )


def _write_package(
    tmp_path: Path,
    *,
    package: dict[str, object] | None = None,
) -> tuple[Path, str]:
    path, _receipt, _observation = _artifact_paths(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_ai_enablement_package(path, package or _package())
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_paths(root: Path) -> tuple[Path, Path, Path]:
    return (
        root / ARTIFACTS["package_path"],
        root / ARTIFACTS["receipt_path"],
        root / ARTIFACTS["observation_path"],
    )


def _readonly_result(package: dict[str, object]) -> dict[str, object]:
    specification = package["execution_contract"]["states"][
        "readonly_revalidation"
    ]
    return {
        "operations": deepcopy(specification["operations"]),
        "evidence": deepcopy(specification["expected_evidence"]),
        "outputs": {
            "rollback_revision": package["azure_target"]["rollback_revision"],
            "ai_enabled": False,
            "vault_state": "existing_exact",
            "identity_state": "existing_exact",
            "role_assignment_state": package["prepackage_gate"][
                "role_assignment_state"
            ],
            "diagnostic_setting_state": "existing_exact",
            "secret_values_read": 0,
        },
    }


def _safe_result(
    package: dict[str, object],
    state: str,
) -> dict[str, object]:
    specification = package["execution_contract"]["states"][state]
    outputs: dict[str, object] = {}
    if state == "publish_candidate_image":
        outputs = {"candidate_image_digest": DIGEST}
    elif state == "activate_ai_disabled_candidate":
        outputs = {
            "candidate_image_digest": DIGEST,
            "revision": "newcaostone-demo-app--ai-disabled-aaaaaaa",
        }
    elif state == "verify_ai_disabled_candidate":
        outputs = {
            "candidate_image_digest": DIGEST,
            "ai_enabled": False,
            "reconciliation": deepcopy(RECONCILIATIONS[0]),
        }
    elif state == "reconcile_ai_vault_identity_role_diagnostics":
        outputs = {
            "vault_url": "https://newcaostone-ai-kv.vault.azure.net",
            "identity_resource_id": (
                f"/subscriptions/{SUBSCRIPTION}/resourceGroups/"
                "rg-bizpulse-centralus/providers/Microsoft.ManagedIdentity/"
                "userAssignedIdentities/newcaostone-ai-identity"
            ),
            "managed_identity_client_id": CLIENT_ID,
        }
    elif state == "paid_model_qualification":
        outputs = {"paid_call_count": 12}
    elif state == "budget_failure_rehearsal":
        outputs = {"reconciliations": deepcopy(RECONCILIATIONS[1:3])}
    elif state == "provider_failure_rehearsal":
        outputs = {"reconciliations": deepcopy(RECONCILIATIONS[3:5])}
    elif state == "activate_ai_enabled_revision":
        outputs = {
            "candidate_image_digest": DIGEST,
            "final_revision": "newcaostone-demo-app--ai-enabled-aaaaaaa",
        }
    elif state == "verify_ai_enabled_revision":
        outputs = {
            "candidate_image_digest": DIGEST,
            "ai_enabled": True,
            "reconciliation": deepcopy(RECONCILIATIONS[5]),
        }
    elif state == "paid_hosted_manual_send_smoke":
        outputs = {"paid_call_count": 1}
    return {
        "operations": deepcopy(specification["operations"]),
        "evidence": deepcopy(specification["expected_evidence"]),
        "outputs": outputs,
    }


def _dependencies(
    package: dict[str, object],
    *,
    calls: list[dict[str, object]],
    key_provider=lambda: SENTINEL,
):
    def operation_executor(
        state: str,
        *,
        environment: dict[str, str],
        secret_value: str | None,
        context: dict[str, object],
    ) -> dict[str, object]:
        calls.append(
            {
                "state": state,
                "environment": dict(environment),
                "secret_value": secret_value,
                "context": deepcopy(context),
            }
        )
        return _safe_result(package, state)

    return {
        "repository_reader": lambda: deepcopy(package["repository"]),
        "control_reader": lambda: deepcopy(package["control_sha256"]),
        "prior_attempts_reader": lambda: deepcopy(package["prior_attempts"]),
        "d3_reader": lambda: deepcopy(package["d3"]),
        "azure_revalidator": lambda _package: _readonly_result(package),
        "paid_preflight": lambda _package: {
            "price_evidence_present": True,
            "maximum_estimated_cost": "0.19",
        },
        "operation_executor": operation_executor,
        "emergency_recovery": lambda **_kwargs: deepcopy(EMERGENCY_RECOVERY),
        "key_provider": key_provider,
        "stdin_is_tty": lambda: True,
    }


def _execute(
    *,
    package_path: Path,
    approved_sha256: str,
    receipt_path: Path,
    dependencies: dict[str, object],
    now: datetime = NOW,
    observation_path: Path | None = None,
) -> dict[str, object]:
    return execute_ai_enablement(
        package_path=package_path,
        approved_sha256=approved_sha256,
        receipt_path=receipt_path,
        observation_path=(
            observation_path
            if observation_path is not None
            else _artifact_paths(package_path.parent.parent)[2]
        ),
        now=now,
        **dependencies,
    )


@pytest.mark.parametrize("failure", ["hash", "mode", "expired"])
def test_package_gate_stops_before_azure_key_or_receipt(
    tmp_path: Path,
    failure: str,
) -> None:
    path, digest = _write_package(tmp_path)
    receipt_path = _artifact_paths(tmp_path)[1]
    package = _package()
    calls: list[dict[str, object]] = []
    key_calls = 0

    def key_provider() -> str:
        nonlocal key_calls
        key_calls += 1
        return SENTINEL

    if failure == "hash":
        digest = "f" * 64
    elif failure == "mode":
        path.chmod(0o644)
    else:
        now = NOW + timedelta(days=2)
    if failure != "expired":
        now = NOW

    with pytest.raises(AIEnablementRunInvalid):
        _execute(
            package_path=path,
            approved_sha256=digest,
            receipt_path=receipt_path,
            dependencies=_dependencies(
                package,
                calls=calls,
                key_provider=key_provider,
            ),
            now=now,
        )
    assert calls == []
    assert key_calls == 0
    assert not receipt_path.exists()


@pytest.mark.parametrize(
    "drift",
    ["repository", "control", "prior", "d3", "azure", "price"],
)
def test_authority_drift_stops_before_key_and_next_state(
    tmp_path: Path,
    drift: str,
) -> None:
    path, digest = _write_package(tmp_path)
    receipt_path = _artifact_paths(tmp_path)[1]
    package = _package()
    calls: list[dict[str, object]] = []
    key_calls = 0

    def key_provider() -> str:
        nonlocal key_calls
        key_calls += 1
        return SENTINEL

    dependencies = _dependencies(package, calls=calls, key_provider=key_provider)
    if drift == "repository":
        dependencies["repository_reader"] = lambda: {
            **package["repository"],
            "head_sha": "f" * 40,
        }
    elif drift == "control":
        dependencies["control_reader"] = lambda: {
            **package["control_sha256"],
            "scripts/run_ai_enablement.py": "f" * 64,
        }
    elif drift == "prior":
        dependencies["prior_attempts_reader"] = lambda: {
            **package["prior_attempts"],
            "r3": {
                **package["prior_attempts"]["r3"],
                "receipt_sha256": "f" * 64,
            },
        }
    elif drift == "d3":
        dependencies["d3_reader"] = lambda: {
            **package["d3"],
            "receipt_present": True,
        }
    elif drift == "azure":
        dependencies["azure_revalidator"] = lambda _package: {
            **_readonly_result(package),
            "outputs": {
                **_readonly_result(package)["outputs"],
                "ai_enabled": True,
            },
        }
    else:
        dependencies["paid_preflight"] = lambda _package: {
            "price_evidence_present": False,
            "maximum_estimated_cost": None,
        }

    with pytest.raises(AIEnablementRunInvalid):
        _execute(
            package_path=path,
            approved_sha256=digest,
            receipt_path=receipt_path,
            dependencies=dependencies,
        )
    assert calls == []
    assert key_calls == 0


def test_closed_azure_preflight_failure_code_is_preserved_before_receipt(
    tmp_path: Path,
) -> None:
    path, digest = _write_package(tmp_path)
    package = _package()
    calls: list[dict[str, object]] = []
    receipt_path = _artifact_paths(tmp_path)[1]
    dependencies = _dependencies(package, calls=calls)

    def fail_azure_preflight(_package: object) -> object:
        raise AzureAIEnablementActionInvalid("ai_enablement_azure_read_failed")

    dependencies["azure_revalidator"] = fail_azure_preflight

    with pytest.raises(
        AIEnablementRunInvalid,
        match="ai_enablement_azure_read_failed",
    ):
        _execute(
            package_path=path,
            approved_sha256=digest,
            receipt_path=receipt_path,
            dependencies=dependencies,
        )

    assert calls == []
    assert not receipt_path.exists()


def test_runner_rejects_non_package_bound_artifact_paths_before_azure_or_key(
    tmp_path: Path,
) -> None:
    path, digest = _write_package(tmp_path)
    package = _package()
    calls: list[dict[str, object]] = []
    dependencies = _dependencies(package, calls=calls)

    with pytest.raises(
        AIEnablementRunInvalid,
        match="ai_enablement_artifact_path_drift",
    ):
        _execute(
            package_path=path,
            approved_sha256=digest,
            receipt_path=tmp_path / "wrong-receipt.json",
            dependencies=dependencies,
        )

    assert calls == []


def test_success_scopes_sentinel_to_qualification_and_one_secret_write(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path, digest = _write_package(tmp_path)
    package = _package()
    calls: list[dict[str, object]] = []
    _package_path, receipt_path, observation_path = _artifact_paths(tmp_path)
    parent_before = dict(os.environ)

    result = _execute(
        package_path=path,
        approved_sha256=digest,
        receipt_path=receipt_path,
        observation_path=observation_path,
        dependencies=_dependencies(package, calls=calls),
    )

    assert result == {
        "state": "completed",
        "candidate_image_digest": DIGEST,
        "final_revision": "newcaostone-demo-app--ai-enabled-aaaaaaa",
        "paid_call_count": 13,
    }
    assert [item["state"] for item in calls] == list(STATE_ORDER[1:])
    verify_enabled_call = next(
        item for item in calls if item["state"] == "verify_ai_enabled_revision"
    )
    assert verify_enabled_call["context"]["final_revision"] == (
        "newcaostone-demo-app--ai-enabled-aaaaaaa"
    )
    for call in calls:
        if call["state"] == "paid_model_qualification":
            assert call["environment"] == {
                "BIZPULSE_DEPLOY_OPENAI_API_KEY": SENTINEL
            }
            assert call["secret_value"] is None
        elif call["state"] == "real_secret_write":
            assert call["environment"] == {}
            assert call["secret_value"] == SENTINEL
        else:
            assert call["environment"] == {}
            assert call["secret_value"] is None
    assert os.environ == parent_before
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    receipt = json.loads(receipt_path.read_text())
    observation = json.loads(observation_path.read_text())
    assert stat.S_IMODE(observation_path.stat().st_mode) == 0o600
    assert observation["schema_version"] == (
        "newcaostone.ai-enablement-observation.v1"
    )
    assert [item["role"] for item in observation["reconciliations"]] == [
        item["role"] for item in RECONCILIATIONS
    ]
    assert receipt["schema_version"] == "newcaostone.ai-enablement-receipt.v2"
    assert receipt["observation_sha256"] == hashlib.sha256(
        observation_path.read_bytes()
    ).hexdigest()
    assert receipt["paid_call_count"] == 13
    assert receipt["completed_states"] == list(STATE_ORDER)
    assert SENTINEL not in path.read_text()
    assert SENTINEL not in receipt_path.read_text()
    assert SENTINEL not in observation_path.read_text()
    assert SENTINEL not in repr(result)
    captured = capsys.readouterr()
    assert SENTINEL not in captured.out
    assert SENTINEL not in captured.err


def test_fresh_officer_only_successor_package_executes_after_migration(
    tmp_path: Path,
) -> None:
    package = _package(role_assignment_state="officer_only")
    path, digest = _write_package(tmp_path, package=package)
    calls: list[dict[str, object]] = []
    _package_path, receipt_path, observation_path = _artifact_paths(tmp_path)

    result = _execute(
        package_path=path,
        approved_sha256=digest,
        receipt_path=receipt_path,
        observation_path=observation_path,
        dependencies=_dependencies(package, calls=calls),
    )

    assert result["state"] == "completed"
    assert calls[0]["context"]["completed_states"] == [
        "readonly_revalidation"
    ]


@pytest.mark.parametrize(
    ("package_phase", "observed_phase"),
    [
        ("legacy_only", "officer_only"),
        ("officer_only", "legacy_only"),
    ],
)
def test_stale_package_cannot_cross_role_assignment_phase(
    tmp_path: Path,
    package_phase: str,
    observed_phase: str,
) -> None:
    package = _package(role_assignment_state=package_phase)
    path, digest = _write_package(tmp_path, package=package)
    calls: list[dict[str, object]] = []
    dependencies = _dependencies(package, calls=calls)
    observed = _readonly_result(package)
    observed["outputs"]["role_assignment_state"] = observed_phase
    dependencies["azure_revalidator"] = lambda _package: observed

    with pytest.raises(
        AIEnablementRunInvalid,
        match="ai_enablement_azure_authority_drift",
    ):
        _execute(
            package_path=path,
            approved_sha256=digest,
            receipt_path=_artifact_paths(tmp_path)[1],
            dependencies=dependencies,
        )

    assert calls == []


def test_missing_key_stops_after_paid_preflight_without_paid_or_secret_action(
    tmp_path: Path,
) -> None:
    path, digest = _write_package(tmp_path)
    receipt = _artifact_paths(tmp_path)[1]
    package = _package()
    calls: list[dict[str, object]] = []

    with pytest.raises(
        AIEnablementRunInvalid,
        match="ai_enablement_key_input_missing",
    ):
        _execute(
            package_path=path,
            approved_sha256=digest,
            receipt_path=receipt,
            dependencies=_dependencies(
                package,
                calls=calls,
                key_provider=lambda: "",
            ),
        )
    qualification_index = STATE_ORDER.index("paid_model_qualification")
    assert [item["state"] for item in calls] == list(
        STATE_ORDER[1:qualification_index]
    )
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
    failed = json.loads(receipt.read_text())
    assert failed["schema_version"] == "newcaostone.ai-enablement-attempt.v2"
    assert failed["state"] == "failed"
    assert failed["failure_code"] == "ai_enablement_key_input_missing"
    assert failed["recovery"] is None
    assert [item["role"] for item in failed["reconciliations"]] == [
        "ai_disabled_candidate",
        "budget_enabled",
        "budget_recovery",
        "provider_enabled",
        "provider_recovery",
    ]


def test_closed_action_failure_code_is_preserved_in_the_failed_receipt(
    tmp_path: Path,
) -> None:
    path, digest = _write_package(tmp_path)
    receipt = _artifact_paths(tmp_path)[1]
    package = _package()
    calls: list[dict[str, object]] = []
    dependencies = _dependencies(package, calls=calls)
    original = dependencies["operation_executor"]

    def executor(state: str, **kwargs):
        if state == "verify_ai_disabled_candidate":
            raise AzureAIEnablementActionInvalid(
                "ai_enablement_revision_unverified"
            )
        return original(state, **kwargs)

    dependencies["operation_executor"] = executor

    with pytest.raises(
        AIEnablementRunInvalid,
        match="ai_enablement_revision_unverified",
    ):
        _execute(
            package_path=path,
            approved_sha256=digest,
            receipt_path=receipt,
            dependencies=dependencies,
        )

    failed = json.loads(receipt.read_text())
    assert failed["failure_code"] == "ai_enablement_revision_unverified"
    assert failed["recovery"] is None


def test_non_tty_stops_before_azure_or_key(tmp_path: Path) -> None:
    path, digest = _write_package(tmp_path)
    receipt_path = _artifact_paths(tmp_path)[1]
    package = _package()
    calls: list[dict[str, object]] = []
    dependencies = _dependencies(package, calls=calls)
    dependencies["stdin_is_tty"] = lambda: False

    with pytest.raises(
        AIEnablementRunInvalid,
        match="ai_enablement_tty_required",
    ):
        _execute(
            package_path=path,
            approved_sha256=digest,
            receipt_path=receipt_path,
            dependencies=dependencies,
        )
    assert calls == []


def test_d3_reader_verifies_exact_owner_only_package_and_absent_outputs(
    tmp_path: Path,
) -> None:
    d3_package = tmp_path / "d3.json"
    d3_package.write_bytes(b"exact-d3-package")
    d3_package.chmod(0o600)
    expected = _package()["d3"]
    expected["package_sha256"] = hashlib.sha256(
        d3_package.read_bytes()
    ).hexdigest()

    assert d3_state_from_paths(
        expected=expected,
        package_path=d3_package,
        receipt_path=tmp_path / "receipt.json",
        observation_path=tmp_path / "observation.json",
    ) == expected

    (tmp_path / "receipt.json").write_text("{}")
    with pytest.raises(AIEnablementRunInvalid, match="ai_enablement_d3_drift"):
        d3_state_from_paths(
            expected=expected,
            package_path=d3_package,
            receipt_path=tmp_path / "receipt.json",
            observation_path=tmp_path / "observation.json",
        )


def test_cli_wires_real_default_executor_instead_of_inert_placeholder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def fake_execute(**kwargs):
        captured.update(kwargs)
        return {
            "state": "completed",
            "candidate_image_digest": DIGEST,
            "final_revision": "newcaostone-demo-app--ai-enabled-aaaaaaa",
            "paid_call_count": 13,
        }

    monkeypatch.setattr("scripts.run_ai_enablement.execute_ai_enablement", fake_execute)
    package_path = tmp_path / "package.json"
    receipt_path = tmp_path / "receipt.json"
    observation_path = tmp_path / "observation.json"
    d3_path = tmp_path / "d3.json"

    assert main(
        [
            "--package",
            str(package_path),
            "--approved-sha256",
            "a" * 64,
            "--receipt",
            str(receipt_path),
            "--observation",
            str(observation_path),
            "--d3-package",
            str(d3_path),
            "--d3-receipt",
            str(tmp_path / "d3-receipt.json"),
            "--d3-observation",
            str(tmp_path / "d3-observation.json"),
        ]
    ) == 0

    assert captured["package_path"] == package_path
    assert captured["receipt_path"] == receipt_path
    assert captured["observation_path"] == observation_path
    assert callable(captured["repository_reader"])
    assert callable(captured["control_reader"])
    assert callable(captured["d3_reader"])
    assert callable(captured["azure_revalidator"])
    assert callable(captured["paid_preflight"])
    assert callable(captured["operation_executor"])
    assert callable(captured["key_provider"])
    assert captured["key_provider"] is run_ai_enablement.read_openai_api_key
    assert callable(captured["stdin_is_tty"])
    output = capsys.readouterr()
    assert output.out == "ai_enablement=completed\n"
    assert "executor_not_configured" not in output.out


def test_cli_reports_only_closed_failure_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_execute(**_kwargs):
        raise AIEnablementRunInvalid("ai_enablement_azure_read_failed")

    monkeypatch.setattr("scripts.run_ai_enablement.execute_ai_enablement", fake_execute)

    assert main(
        [
            "--package",
            str(tmp_path / "package.json"),
            "--approved-sha256",
            "a" * 64,
            "--receipt",
            str(tmp_path / "receipt.json"),
            "--observation",
            str(tmp_path / "observation.json"),
            "--d3-package",
            str(tmp_path / "d3.json"),
            "--d3-receipt",
            str(tmp_path / "d3-receipt.json"),
            "--d3-observation",
            str(tmp_path / "d3-observation.json"),
        ]
    ) == 1

    output = capsys.readouterr()
    assert output.out == (
        "ai_enablement=failed\n"
        "reason=ai_enablement_azure_read_failed\n"
    )
    assert output.err == ""


def test_browser_operator_keychain_reader_uses_native_current_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class Pair:
        password = "operator-secret"

    class Controller:
        def current_pair(self):
            calls.append("current_pair")
            return Pair()

    monkeypatch.setattr(
        run_ai_enablement,
        "_operator_keychain_controller",
        lambda: Controller(),
    )
    monkeypatch.setenv("BIZPULSE_BROWSER_OPERATOR_PASSWORD", "ambient-must-not-read")

    assert run_ai_enablement.read_browser_operator_password() == "operator-secret"
    assert calls == ["current_pair"]


def test_openai_key_reader_uses_local_hidden_dialog_and_not_ambient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []

    class Root:
        def withdraw(self) -> None:
            events.append("withdraw")

        def attributes(self, name: str, value: bool) -> None:
            events.append((name, value))

        def destroy(self) -> None:
            events.append("destroy")

    root = Root()

    def dialog_reader(title: str, prompt: str, **kwargs: object) -> str:
        events.append((title, prompt, kwargs))
        return SENTINEL

    monkeypatch.setenv("BIZPULSE_DEPLOY_OPENAI_API_KEY", "ambient-must-not-read")

    assert run_ai_enablement.read_openai_api_key(
        root_factory=lambda: root,
        dialog_reader=dialog_reader,
    ) == SENTINEL
    assert events[0:2] == ["withdraw", ("-topmost", True)]
    title, prompt, kwargs = events[2]
    assert title == "BizPulse AI Enablement"
    assert "Azure Key Vault" in prompt
    assert kwargs == {"show": "*", "parent": root}
    assert events[3] == "destroy"


@pytest.mark.parametrize("bad_digest", ["sha256:short", "sha256:" + ("f" * 64)])
def test_image_digest_invalid_or_readback_drift_stops_immediately(
    tmp_path: Path,
    bad_digest: str,
) -> None:
    path, digest = _write_package(tmp_path)
    receipt_path = _artifact_paths(tmp_path)[1]
    package = _package()
    calls: list[dict[str, object]] = []
    dependencies = _dependencies(package, calls=calls)
    original = dependencies["operation_executor"]

    def executor(state: str, **kwargs):
        result = original(state, **kwargs)
        if state == "publish_candidate_image" and bad_digest == "sha256:short":
            result["outputs"]["candidate_image_digest"] = bad_digest
        if state == "activate_ai_disabled_candidate" and bad_digest != "sha256:short":
            result["outputs"]["candidate_image_digest"] = bad_digest
        return result

    dependencies["operation_executor"] = executor
    with pytest.raises(AIEnablementRunInvalid):
        _execute(
            package_path=path,
            approved_sha256=digest,
            receipt_path=receipt_path,
            dependencies=dependencies,
        )
    expected_calls = 1 if bad_digest == "sha256:short" else 2
    assert len(calls) == expected_calls


def test_first_operation_mismatch_or_interrupt_has_no_retry_or_next_state(
    tmp_path: Path,
) -> None:
    for failure in ("mismatch", "interrupt"):
        root = tmp_path / failure
        path, digest = _write_package(root)
        receipt = _artifact_paths(root)[1]
        package = _package()
        calls: list[dict[str, object]] = []
        dependencies = _dependencies(package, calls=calls)
        original = dependencies["operation_executor"]

        def executor(state: str, **kwargs):
            result = original(state, **kwargs)
            if failure == "interrupt":
                raise KeyboardInterrupt
            result["operations"] = {"acr.publish.immutable": 2}
            return result

        dependencies["operation_executor"] = executor
        with pytest.raises(AIEnablementRunInvalid):
            _execute(
                package_path=path,
                approved_sha256=digest,
                receipt_path=receipt,
                dependencies=dependencies,
            )
        assert len(calls) == 1
        assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
        failed = json.loads(receipt.read_text())
        assert failed["state"] == "failed"
        assert failed["schema_version"] == (
            "newcaostone.ai-enablement-attempt.v2"
        )


@pytest.mark.parametrize(
    "failure_state",
    [
        "real_secret_write",
        "activate_ai_enabled_revision",
        "verify_ai_enabled_revision",
        "paid_hosted_manual_send_smoke",
        "sanitize_receipt",
    ],
)
def test_every_failure_from_real_write_attempt_triggers_one_emergency_recovery(
    tmp_path: Path,
    failure_state: str,
) -> None:
    path, digest = _write_package(tmp_path)
    receipt = _artifact_paths(tmp_path)[1]
    package = _package()
    calls: list[dict[str, object]] = []
    recoveries: list[dict[str, object]] = []
    dependencies = _dependencies(package, calls=calls)
    original = dependencies["operation_executor"]

    def executor(state: str, **kwargs):
        if state == failure_state:
            raise RuntimeError("synthetic-ambiguous-failure")
        return original(state, **kwargs)

    dependencies["operation_executor"] = executor
    def emergency_recovery(**kwargs):
        recoveries.append(deepcopy(kwargs))
        return deepcopy(EMERGENCY_RECOVERY)

    dependencies["emergency_recovery"] = emergency_recovery

    with pytest.raises(AIEnablementRunInvalid):
        _execute(
            package_path=path,
            approved_sha256=digest,
            receipt_path=receipt,
            dependencies=dependencies,
        )

    assert len(recoveries) == 1
    assert recoveries[0]["real_secret_write_attempted"] is True
    assert recoveries[0]["context"]["candidate_image_digest"] == DIGEST
    failed = json.loads(receipt.read_text())
    assert failed["state"] == "failed"
    assert failed["failure_code"] == "ai_enablement_operation_failed"
    assert failed["recovery"] == EMERGENCY_RECOVERY
    assert SENTINEL not in json.dumps(failed)


def test_observation_write_failure_recovers_once_and_finalizes_failed_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, digest = _write_package(tmp_path)
    _package_path, receipt, observation = _artifact_paths(tmp_path)
    package = _package()
    calls: list[dict[str, object]] = []
    recoveries: list[dict[str, object]] = []
    dependencies = _dependencies(package, calls=calls)

    def emergency_recovery(**kwargs):
        recoveries.append(deepcopy(kwargs))
        return deepcopy(EMERGENCY_RECOVERY)

    dependencies["emergency_recovery"] = emergency_recovery
    monkeypatch.setattr(
        "scripts.run_ai_enablement._write_owner_only_observation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AIEnablementRunInvalid("ai_enablement_observation_write_failed")
        ),
    )
    with pytest.raises(
        AIEnablementRunInvalid,
        match="ai_enablement_observation_write_failed",
    ):
        _execute(
            package_path=path,
            approved_sha256=digest,
            receipt_path=receipt,
            dependencies=dependencies,
        )

    assert len(recoveries) == 1
    failed = json.loads(receipt.read_text())
    assert failed["state"] == "failed"
    assert failed["failure_code"] == "ai_enablement_observation_write_failed"
    assert failed["recovery"] == EMERGENCY_RECOVERY
    assert not observation.exists()


def test_emergency_recovery_failure_is_closed_and_never_serializes_exception(
    tmp_path: Path,
) -> None:
    path, digest = _write_package(tmp_path)
    receipt = _artifact_paths(tmp_path)[1]
    package = _package()
    calls: list[dict[str, object]] = []
    dependencies = _dependencies(package, calls=calls)
    original = dependencies["operation_executor"]

    def executor(state: str, **kwargs):
        if state == "verify_ai_enabled_revision":
            raise RuntimeError("provider exploded with private data")
        return original(state, **kwargs)

    def emergency_recovery(**_kwargs):
        raise RuntimeError("recovery raw stdout private data")

    dependencies["operation_executor"] = executor
    dependencies["emergency_recovery"] = emergency_recovery
    with pytest.raises(
        AIEnablementRunInvalid,
        match="ai_enablement_emergency_disable_failed",
    ) as raised:
        _execute(
            package_path=path,
            approved_sha256=digest,
            receipt_path=receipt,
            dependencies=dependencies,
        )

    failed_text = receipt.read_text()
    failed = json.loads(failed_text)
    assert failed["failure_code"] == "ai_enablement_emergency_disable_failed"
    assert failed["recovery"] is None
    assert "provider exploded" not in failed_text
    assert "raw stdout" not in failed_text
    assert SENTINEL not in failed_text
    assert SENTINEL not in repr(raised.value)


def test_reserved_receipt_finalize_failure_emergency_disables_and_fences_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, digest = _write_package(tmp_path)
    receipt = _artifact_paths(tmp_path)[1]
    package = _package()
    calls: list[dict[str, object]] = []
    recoveries: list[dict[str, object]] = []
    dependencies = _dependencies(package, calls=calls)
    def emergency_recovery(**kwargs):
        recoveries.append(deepcopy(kwargs))
        return deepcopy(EMERGENCY_RECOVERY)

    dependencies["emergency_recovery"] = emergency_recovery
    monkeypatch.setattr(
        "scripts.run_ai_enablement._finalize_reserved_receipt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk-full")),
    )
    with pytest.raises(
        AIEnablementRunInvalid,
        match="ai_enablement_receipt_write_failed",
    ):
        _execute(
            package_path=path,
            approved_sha256=digest,
            receipt_path=receipt,
            dependencies=dependencies,
        )

    assert len(recoveries) == 1
    assert json.loads(receipt.read_text())["state"] == "started"
    with pytest.raises(AIEnablementRunInvalid, match="ai_enablement_receipt_exists"):
        _execute(
            package_path=path,
            approved_sha256=digest,
            receipt_path=receipt,
            dependencies=dependencies,
        )
