from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
from pathlib import Path

import httpx
from sqlalchemy import Engine, func, select

from src.ai.query_catalog import QueryCatalog
from src.db.schema import (
    action_cards,
    ai_chat_turns,
    analysis_runs,
    dataset_artifacts,
    dataset_series,
    dataset_versions,
    demo_sessions,
    new_product_forecasts,
    profit_bridges,
    public_releases,
)
from src.repositories.datasets import DatasetRepository
from tests.auth_support import PASSWORD
from tests.acceptance.support import (
    acceptance_server,
    azure_storage,
    azurite_container,
    seed_fixed_release,
)
from tests.import_support import WORKSPACE_ID

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GATE = PROJECT_ROOT / "scripts" / "browser_release_gate.mjs"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def _canonical_row_counts(engine: Engine) -> dict[str, int]:
    tables = {
        "dataset_series": dataset_series,
        "dataset_versions": dataset_versions,
        "dataset_artifacts": dataset_artifacts,
        "analysis_runs": analysis_runs,
        "new_product_forecasts": new_product_forecasts,
        "profit_bridges": profit_bridges,
        "public_releases": public_releases,
    }
    with engine.connect() as connection:
        return {
            name: int(connection.scalar(select(func.count()).select_from(table)) or 0)
            for name, table in tables.items()
        }


def test_browser_gate_allows_bounded_slow_chrome_startup() -> None:
    source = GATE.read_text()
    assert "const CHROME_START_TIMEOUT_MS = 30_000;" in source
    assert "const CDP_CONNECT_TIMEOUT_MS = 30_000;" in source
    assert "const CDP_COMMAND_TIMEOUT_MS = 30_000;" in source
    assert "while (Date.now() < deadline)" in source
    assert "child.exitCode !== null || child.signalCode !== null" in source


def test_browser_reload_accepts_only_the_navigation_acknowledgement_race() -> None:
    source = GATE.read_text()
    assert "cdp_command_failed:${authority.method}:${message.error.message}" in source
    assert 'error.message !== "cdp_command_failed:Page.reload:Inspected target navigated or closed"' in source
    assert 'await this.waitFor("document.readyState === \'complete\'", "page-reload")' in source


def test_navigation_click_accepts_only_the_expected_runtime_acknowledgement() -> None:
    source = GATE.read_text()
    assert "async clickSelectorForNavigation(selector)" in source
    assert "async clickTextForNavigation(text)" in source
    assert (
        'error.message !== "cdp_command_failed:Runtime.evaluate:Inspected target navigated or closed"'
        in source
    )
    assert 'await page.clickSelectorForNavigation("[data-demo-start]");' in source
    assert "await page.clickTextForNavigation(ui.importDemoData);" in source
    assert source.count(
        'await operator.clickSelectorForNavigation("[data-login-form] button[type=\'submit\']");'
    ) == 2


def test_browser_gate_reports_bounded_preparation_response_on_failure() -> None:
    source = GATE.read_text()
    assert "this.preparationResponses = [];" in source
    assert 'pathname.endsWith("/prepare")' in source
    assert '"operator-calculation-resolution"' in source
    assert "if (!publishReady)" in source
    assert "operator-calculations-retry-ready" in source
    assert "preparation_responses:${JSON.stringify(page.preparationResponses)}" in source


def test_scope_gate_checks_console_errors_after_session_shutdown() -> None:
    source = GATE.read_text()
    scope_gate = source[
        source.index("async function scopeReadonlyGate()") : source.index(
            "async function paidAiGate()"
        )
    ]

    network_idle = scope_gate.index("await page.waitForNetworkIdle();")
    session_end = scope_gate.index("await endDemoSession(page);")
    assert network_idle < session_end
    assert session_end < scope_gate.index(
        "assert(page.consoleErrors.length === 0"
    )
    assert "await sleep(100); // Drain ordered CDP diagnostics." in scope_gate
    assert "async waitForNetworkIdle(" in source
    assert 'this.inFlightRequests.set(message.params.requestId' in source
    assert 'this.inFlightRequests.delete(message.params.requestId)' in source


def test_scope_gate_waits_for_action_overlays_before_leaving_actions() -> None:
    source = GATE.read_text()
    scope_gate = source[
        source.index("async function scopeReadonlyGate()") : source.index(
            "async function paidAiGate()"
        )
    ]

    action_loaded = scope_gate.index('"scope-action-loaded"')
    workspace_route = scope_gate.index('await route(page, "workspace"')
    assert action_loaded < workspace_route
    assert "document.querySelector('.action-card')" in scope_gate
    assert "ui.actionsEmpty" in scope_gate


def test_paid_ai_gate_is_one_manual_monthly_send_without_action_write() -> None:
    source = GATE.read_text()
    paid_gate = source[
        source.index("async function paidAiGate()") : source.index("let result;")
    ]

    assert "await askMonthlyReportAfterExplicitSend(page, 1);" in paid_gate
    assert "askAdvertisingPerformance" not in paid_gate
    assert "Prepare one synthetic stockout action" not in paid_gate
    assert "Create Action draft" not in paid_gate
    assert "providerTurns: audit.attempt_count" in paid_gate
    assert "audit.attempt_count === 1" in paid_gate
    assert "audit.ledger_attempt_count === 1" in paid_gate
    assert "await startDemo(page);" in paid_gate
    assert "response.csrfHeaderPresent" in paid_gate
    assert "response.presetAuditComplete" in paid_gate
    assert "response.storeScopeCount >= 1" in paid_gate
    assert "location.pathname === '/demo'" in paid_gate


def test_hosted_ai_disabled_gate_checks_visible_disabled_presets_without_send() -> None:
    source = GATE.read_text()

    assert 'scenario === "ai-disabled"' in source
    assert "async function aiDisabledGate()" in source
    disabled_gate = source.split("async function aiDisabledGate()", 1)[1].split(
        "async function", 1
    )[0]
    assert "six-prompt-presets" in disabled_gate
    assert "ui.aiDisabled" in disabled_gate
    assert "button:disabled" in disabled_gate
    assert "chatRequestsBefore" in disabled_gate
    assert "chatRequestsAfter" in disabled_gate
    assert "clickText(ui.monthlySales)" not in disabled_gate
    assert "clickSelector(\".chat-form button[type='submit']\")" not in disabled_gate


def _run_gate(base_url: str, scenario: str) -> dict[str, object]:
    node = shutil.which("node")
    assert node is not None, "local_release_node_missing"
    assert CHROME.is_file(), "local_release_browser_missing"
    process = subprocess.Popen(
        [node, str(GATE), base_url, scenario],
        cwd=PROJECT_ROOT,
        env={**os.environ, "BIZPULSE_BROWSER_OPERATOR_PASSWORD": PASSWORD},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=180)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=5)
        raise AssertionError(stderr or stdout or "browser_release_gate_timeout")
    assert process.returncode == 0, stderr or stdout
    return json.loads(stdout.strip().splitlines()[-1])


def test_real_browser_runs_full_same_origin_release_gate(
    migrated_engine: Engine,
) -> None:
    with azurite_container() as container:
        storage = azure_storage(migrated_engine, container)
        seed_fixed_release(migrated_engine, storage)
        scope_counts_before = _canonical_row_counts(migrated_engine)

        with acceptance_server(migrated_engine, container) as base_url:
            scope_readonly = _run_gate(base_url, "scope-readonly")
            assert _canonical_row_counts(migrated_engine) == scope_counts_before
            try:
                full = _run_gate(base_url, "full")
            except AssertionError as error:
                with migrated_engine.connect() as connection:
                    session_rows = connection.execute(
                        select(
                            demo_sessions.c.id,
                            demo_sessions.c.dataset_version_id,
                            demo_sessions.c.chat_epoch,
                            demo_sessions.c.status,
                            demo_sessions.c.demo_data_imported_at,
                            demo_sessions.c.created_at,
                            demo_sessions.c.last_seen_at,
                            demo_sessions.c.idle_expires_at,
                            demo_sessions.c.absolute_expires_at,
                        ).order_by(demo_sessions.c.created_at)
                    ).mappings().all()
                    turn_rows = connection.execute(
                        select(
                            ai_chat_turns.c.demo_session_id,
                            ai_chat_turns.c.status,
                            ai_chat_turns.c.turn_sequence,
                        )
                        .where(ai_chat_turns.c.actor_kind == "demo")
                        .order_by(
                            ai_chat_turns.c.demo_session_id,
                            ai_chat_turns.c.turn_sequence,
                        )
                    ).mappings().all()
                diagnostics = {
                    "sessions": [
                        {key: str(value) for key, value in row.items()}
                        for row in session_rows
                    ],
                    "turns": [
                        {key: str(value) for key, value in row.items()}
                        for row in turn_rows
                    ],
                }
                raise AssertionError(
                    f"{error};session_diagnostics={json.dumps(diagnostics, sort_keys=True)}"
                ) from error
            with migrated_engine.connect() as connection:
                current = DatasetRepository(connection).current_release(
                    WORKSPACE_ID
                )
                assert current is not None
                current_actions = int(
                    connection.scalar(
                        select(func.count())
                        .select_from(action_cards)
                        .where(
                            action_cards.c.dataset_version_id
                            == current.dataset_version_id,
                            action_cards.c.status == "approved",
                        )
                    )
                    or 0
                )
            assert current_actions >= 1
            recovered = _run_gate(base_url, "core")
        with acceptance_server(
            migrated_engine,
            container,
            gateway_mode="unavailable",
        ) as base_url:
            unavailable = _run_gate(base_url, "provider-unavailable")
        with acceptance_server(
            migrated_engine,
            container,
            gateway_mode="budget",
        ) as base_url:
            budget = _run_gate(base_url, "budget")
        with acceptance_server(
            migrated_engine,
            container,
            gateway_mode="disabled",
        ) as base_url:
            with httpx.Client(base_url=base_url, timeout=10) as viewer:
                    session = viewer.post(
                        "/api/demo/sessions",
                        headers={"Origin": base_url},
                    )
                    viewer.post(
                        "/api/demo/sessions/current/import-demo-data",
                        headers={
                            "Origin": base_url,
                            "X-CSRF-Token": session.json()["csrf_token"],
                        },
                    )
                    no_ai_list = viewer.get("/api/v1/ai-chat/turns")
            no_ai_core = _run_gate(base_url, "core")

    assert full == {
        "consoleErrors": 0,
        "editedPrompt": True,
        "externalRequests": 0,
        "languages": ["en", "zh"],
        "loginSignIn": True,
        "monthlyPreset": True,
        "operator": True,
        "operatorExport": True,
        "operatorImport": True,
        "operatorOutcome": True,
        "operatorPublish": True,
        "pinnedRefresh": True,
        "productTheater": {
            "autoplay": True,
            "manual": True,
            "reducedMotion": True,
            "slides": 4,
        },
        "scenario": "full",
        "sessionsEnded": 2,
        "sixPresets": True,
        "viewerAreas": 6,
        "viewerEstimates": 3,
        "viewers": 2,
        "viewports": [390, 820, 1280],
    }
    assert scope_readonly == {
        "bilingual": True,
        "consoleErrors": 0,
        "externalRequests": 0,
        "keyboard": True,
        "narrow": True,
        "options": 3,
        "scenario": "scope-readonly",
        "switches": 3,
    }
    assert unavailable == {
        "consoleErrors": 0,
        "externalRequests": 0,
        "ledgerAttemptCount": 1,
        "ledgerReservedTokens": 80000,
        "providerAttemptCount": 1,
        "providerErrorCode": "provider_auth_rejected",
        "providerReservedTokens": 80000,
        "providerStatus": "failed",
        "scenario": "provider-unavailable",
        "state": "AI_CHAT_UNAVAILABLE",
    }
    assert recovered == {
        "consoleErrors": 0,
        "externalRequests": 0,
        "operator": True,
        "operatorExport": True,
        "operatorImport": True,
        "operatorOutcome": True,
        "operatorPublish": True,
        "pinnedRefresh": True,
        "scenario": "core",
        "sessionsEnded": 2,
        "viewers": 2,
        "viewports": [390, 820, 1280],
    }
    assert budget == {
        "consoleErrors": 0,
        "externalRequests": 0,
        "ledgerAttemptCount": 0,
        "ledgerReservedTokens": 0,
        "providerAttemptCount": 0,
        "providerReservedTokens": 0,
        "scenario": "budget",
        "state": "AI_CHAT_BUDGET_EXHAUSTED",
    }
    assert session.status_code == 201
    disabled_payload = no_ai_list.json()
    assert disabled_payload["items"] == []
    assert disabled_payload["saved_items"] == []
    assert disabled_payload["availability"] == "unavailable"
    assert disabled_payload["unavailable_code"] == "AI_CHAT_UNAVAILABLE"
    assert [
        item["id"] for item in disabled_payload["recommended_questions"]
    ] == list(QueryCatalog().recommended_ids())
    assert no_ai_core == {
        "consoleErrors": 0,
        "externalRequests": 0,
        "operator": True,
        "operatorExport": True,
        "operatorImport": True,
        "operatorOutcome": True,
        "operatorPublish": True,
        "pinnedRefresh": True,
        "scenario": "core",
        "sessionsEnded": 2,
        "viewers": 2,
        "viewports": [390, 820, 1280],
    }
