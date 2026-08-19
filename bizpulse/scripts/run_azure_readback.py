"""Restart or rollback one exact app while preserving a pinned viewer authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

import httpx

_SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_SCRIPT_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_PROJECT_ROOT))

from scripts.run_hosted_check import (  # noqa: E402
    HostedCheckInvalid,
    resolve_hosted_url,
)
from scripts.verify_hosted_health import (  # noqa: E402
    HostedHealthInvalid,
    verify_hosted_health,
)

UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)
NAME_PATTERN = re.compile(r"[a-z][a-z0-9-]{1,62}[a-z0-9]")
IMAGE_PATTERN = re.compile(
    r"[a-z0-9]{5,50}\.azurecr\.io/[a-z0-9][a-z0-9._/-]{1,127}@sha256:[0-9a-f]{64}"
)
READINESS_TIMEOUT_SECONDS = 300.0
READINESS_POLL_SECONDS = 5.0
NO_AI_CHAT_AUTHORITY = {
    "availability": "unavailable",
    "unavailable_code": "AI_CHAT_UNAVAILABLE",
}


class AzureReadbackInvalid(RuntimeError):
    """Restart/rollback did not preserve the pinned public authority."""


class ViewerAuthority(Protocol):
    def snapshot(self) -> dict[str, str]: ...

    def reconnect(self) -> None: ...

    def close(self) -> None: ...


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


class _HttpViewer:
    def __init__(self, url: str, ai_enabled: bool):
        self.url = url.rstrip("/")
        self.ai_enabled = ai_enabled
        self.client = httpx.Client(timeout=30, follow_redirects=False, trust_env=False)
        admitted = self.client.post(
            f"{self.url}/api/demo/sessions",
            headers={"Origin": self.url},
        )
        if admitted.status_code != 201:
            self.client.close()
            raise AzureReadbackInvalid("azure_readback_session_failed")
        payload = admitted.json()
        self.csrf = str(payload["csrf_token"])
        self.session_id = str(payload["session"]["session_id"])
        self.action_id: str | None = None
        self.chat_turn_id: str | None = None
        try:
            self._prepare_session_state()
        except Exception:
            self.close()
            raise

    def _prepare_session_state(self) -> None:
        actions = self._get("/api/demo/release/actions")
        if not isinstance(actions, dict) or not isinstance(actions.get("items"), list):
            raise AzureReadbackInvalid("azure_readback_action_authority_failed")
        items = actions["items"]
        if not items or not isinstance(items[0], dict):
            raise AzureReadbackInvalid("azure_readback_action_authority_failed")
        action = items[0]
        self.action_id = str(action["id"])
        simulated = self.client.post(
            f"{self.url}/api/demo/actions/{self.action_id}/commands",
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": f"azure-readback-action-{self.session_id}",
                "Origin": self.url,
                "X-CSRF-Token": self.csrf,
            },
            json={
                "adjustment": {},
                "base_revision": int(action["current_revision"]),
                "command": "review",
                "reason": "Synthetic Azure recovery readback",
            },
        )
        if simulated.status_code != 200:
            raise AzureReadbackInvalid("azure_readback_action_simulation_failed")
        if self.ai_enabled:
            chat = self.client.post(
                f"{self.url}/api/v1/ai-chat/turns",
                headers={
                    "Content-Type": "application/json",
                    "Idempotency-Key": f"azure-readback-chat-{self.session_id}",
                    "Origin": self.url,
                    "X-CSRF-Token": self.csrf,
                },
                # A short ambiguous question creates a durable deterministic
                # clarification turn before any provider attempt.
                json={"question": "why"},
            )
            if chat.status_code != 201:
                raise AzureReadbackInvalid("azure_readback_chat_prepare_failed")
            chat_payload = chat.json()
            if chat_payload.get("status") != "clarification_required":
                raise AzureReadbackInvalid("azure_readback_chat_prepare_failed")
            self.chat_turn_id = str(chat_payload["id"])

    def reconnect(self) -> None:
        """Preserve the viewer cookie jar while forcing a new network transport."""

        cookies = httpx.Cookies(self.client.cookies)
        self.client.close()
        self.client = httpx.Client(
            timeout=30,
            follow_redirects=False,
            trust_env=False,
            cookies=cookies,
        )

    def _get(self, path: str) -> object:
        response = self.client.get(f"{self.url}{path}")
        if response.status_code != 200:
            raise AzureReadbackInvalid("azure_readback_read_failed")
        return response.json()

    def snapshot(self) -> dict[str, str]:
        session = self._get("/api/demo/sessions/current")
        session_data = session["session"]
        if str(session_data["session_id"]) != self.session_id:
            raise AzureReadbackInvalid("azure_readback_session_changed")
        chat = self.client.get(f"{self.url}/api/v1/ai-chat/turns")
        if self.ai_enabled:
            if chat.status_code != 200:
                raise AzureReadbackInvalid("azure_readback_chat_failed")
            chat_authority: object = chat.json()
            if not isinstance(chat_authority, dict) or self.chat_turn_id not in {
                str(item.get("id"))
                for item in chat_authority.get("items", [])
                if isinstance(item, dict)
            }:
                raise AzureReadbackInvalid("azure_readback_chat_state_missing")
        else:
            payload = chat.json()
            if (
                chat.status_code == 200
                and payload
                == {
                    "items": [],
                    "saved_items": [],
                    "recommended_questions": [],
                    **NO_AI_CHAT_AUTHORITY,
                }
            ) or (
                chat.status_code == 503
                and payload == {"code": "AI_CHAT_UNAVAILABLE"}
            ):
                chat_authority = NO_AI_CHAT_AUTHORITY
            else:
                raise AzureReadbackInvalid("azure_readback_chat_boundary_failed")
        action_authority = self._get("/api/demo/release/actions")
        overlays = self._get(f"/api/demo/actions/{self.action_id}/overlays")
        if not isinstance(overlays, dict) or not overlays.get("items"):
            raise AzureReadbackInvalid("azure_readback_action_state_missing")
        return {
            "action_hash": _canonical_hash(
                {"actions": action_authority, "overlays": overlays}
            ),
            "analysis_hash": _canonical_hash(
                self._get("/api/demo/release/analyses/sales_ads")
            ),
            "chat_hash": _canonical_hash(chat_authority),
            "dataset_version_id": str(session_data["dataset_version_id"]),
            "release_hash": _canonical_hash(
                self._get("/api/demo/release/current")
            ),
            "session_id": self.session_id,
            "status": str(session_data["status"]),
        }

    def close(self) -> None:
        try:
            self.client.delete(
                f"{self.url}/api/demo/sessions",
                headers={"Origin": self.url, "X-CSRF-Token": self.csrf},
            )
        finally:
            self.client.close()


def _run_mutation(
    command: Sequence[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    try:
        completed = runner(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise AzureReadbackInvalid("azure_readback_mutation_failed") from error
    if completed.returncode != 0 or len(completed.stdout) > 1_000_000:
        raise AzureReadbackInvalid("azure_readback_mutation_failed")


def _wait_for_hosted_authority(
    resolve: Callable[..., str],
    image: str,
    *,
    suffix: str | None = None,
    recovery_role: str | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> str:
    """Wait only for the exact revision authority after one Azure mutation."""

    deadline = monotonic() + READINESS_TIMEOUT_SECONDS
    while True:
        try:
            return resolve(image, suffix=suffix, recovery_role=recovery_role)
        except HostedCheckInvalid:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise AzureReadbackInvalid("azure_readback_revision_not_ready")
            sleeper(min(READINESS_POLL_SECONDS, remaining))


def run_azure_readback(
    *,
    subscription_id: str,
    resource_group: str,
    app_name: str,
    current_image: str,
    authorization_id: str,
    operation: str,
    revision: str | None = None,
    rollback_image: str | None = None,
    ai_enabled: bool = False,
    resolver: Callable[..., str] = resolve_hosted_url,
    health_verifier: Callable[[str], None] = verify_hosted_health,
    viewer_factory: Callable[[str, bool], ViewerAuthority] = _HttpViewer,
    mutation_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    sleeper: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    if (
        UUID_PATTERN.fullmatch(subscription_id) is None
        or UUID_PATTERN.fullmatch(authorization_id) is None
        or NAME_PATTERN.fullmatch(resource_group) is None
        or NAME_PATTERN.fullmatch(app_name) is None
        or IMAGE_PATTERN.fullmatch(current_image) is None
        or operation not in {"restart", "rollback", "recover"}
        or (
            operation == "restart"
            and (
                revision
                != f"{app_name}--{current_image.rsplit('@sha256:', 1)[1][:12]}"
                or rollback_image is not None
            )
        )
        or (
            operation in {"rollback", "recover"}
            and (
                revision is not None
                or rollback_image is None
                or IMAGE_PATTERN.fullmatch(rollback_image) is None
            )
        )
    ):
        raise AzureReadbackInvalid("azure_readback_authority_invalid")
    common = (
        "--resource-group",
        resource_group,
        "--subscription",
        subscription_id,
        "--output",
        "json",
    )
    current_suffix = current_image.rsplit("@sha256:", 1)[1][:12]
    authorization_prefix = authorization_id.replace("-", "")[:8]
    rollback_digest = (
        str(rollback_image).rsplit("@sha256:", 1)[1]
        if rollback_image is not None
        else ""
    )
    rollback_suffix = f"rollback-{authorization_prefix}-{rollback_digest[:7]}"
    forward_suffix = f"forward-{authorization_prefix}-{current_suffix[:7]}"
    recover_suffix = f"recover-{authorization_prefix}-{current_suffix[:7]}"

    def resolve(
        image: str,
        *,
        suffix: str | None = None,
        recovery_role: str | None = None,
    ) -> str:
        return resolver(
            subscription_id=subscription_id,
            resource_group=resource_group,
            app_name=app_name,
            image=image,
            expected_revision_suffix=suffix,
            recovery_role=recovery_role,
        )

    def wait_for_authority(
        image: str,
        *,
        suffix: str | None = None,
        recovery_role: str | None = None,
    ) -> str:
        return _wait_for_hosted_authority(
            resolve,
            image,
            suffix=suffix,
            recovery_role=recovery_role,
            sleeper=sleeper,
            monotonic=monotonic,
        )

    def compare_after_change(
        viewer: ViewerAuthority,
        url: str,
        before: dict[str, str],
    ) -> None:
        health_verifier(url)
        viewer.reconnect()
        if viewer.snapshot() != before:
            raise AzureReadbackInvalid("azure_readback_authority_changed")

    try:
        recovered_rollback = False
        if operation == "recover":
            url = wait_for_authority(
                str(rollback_image), recovery_role="rollback"
            )
        else:
            try:
                url = resolve(current_image, suffix=current_suffix)
            except HostedCheckInvalid:
                try:
                    url = resolve(current_image, recovery_role="current")
                except HostedCheckInvalid:
                    if operation != "rollback" or rollback_image is None:
                        raise
                    url = wait_for_authority(
                        str(rollback_image), recovery_role="rollback"
                    )
                    recovered_rollback = True
        viewer = viewer_factory(url, ai_enabled)
        before = viewer.snapshot()
        if recovered_rollback:
            recovery_forward = (
                "az",
                "containerapp",
                "update",
                "--name",
                app_name,
                "--image",
                current_image,
                "--revision-suffix",
                recover_suffix,
                *common,
            )
            try:
                _run_mutation(recovery_forward, runner=mutation_runner)
            except AzureReadbackInvalid as mutation_error:
                try:
                    url = wait_for_authority(current_image, suffix=recover_suffix)
                except AzureReadbackInvalid:
                    raise mutation_error
            else:
                url = wait_for_authority(current_image, suffix=recover_suffix)
            compare_after_change(viewer, url, before)
            before = viewer.snapshot()
        if operation == "restart":
            _run_mutation(
                (
                    "az",
                    "containerapp",
                    "revision",
                    "restart",
                    "--name",
                    app_name,
                    "--revision",
                    str(revision),
                    *common,
                ),
                runner=mutation_runner,
            )
            url = wait_for_authority(current_image, suffix=current_suffix)
            compare_after_change(viewer, url, before)
            return
        if operation == "recover":
            forward_command = (
                "az",
                "containerapp",
                "update",
                "--name",
                app_name,
                "--image",
                current_image,
                "--revision-suffix",
                recover_suffix,
                *common,
            )
            try:
                _run_mutation(forward_command, runner=mutation_runner)
            except AzureReadbackInvalid as mutation_error:
                try:
                    url = wait_for_authority(current_image, suffix=recover_suffix)
                except AzureReadbackInvalid:
                    raise mutation_error
            else:
                url = wait_for_authority(current_image, suffix=recover_suffix)
            compare_after_change(viewer, url, before)
            return
        rollback_command = (
            "az",
            "containerapp",
            "update",
            "--name",
            app_name,
            "--image",
            str(rollback_image),
            "--revision-suffix",
            rollback_suffix,
            *common,
        )
        try:
            _run_mutation(rollback_command, runner=mutation_runner)
        except AzureReadbackInvalid as mutation_error:
            try:
                url = wait_for_authority(
                    str(rollback_image), suffix=rollback_suffix
                )
            except AzureReadbackInvalid:
                raise mutation_error
        else:
            url = wait_for_authority(str(rollback_image), suffix=rollback_suffix)
        compare_after_change(viewer, url, before)
        forward_command = (
            "az",
            "containerapp",
            "update",
            "--name",
            app_name,
            "--image",
            current_image,
            "--revision-suffix",
            forward_suffix,
            *common,
        )
        try:
            _run_mutation(forward_command, runner=mutation_runner)
        except AzureReadbackInvalid as mutation_error:
            try:
                url = wait_for_authority(current_image, suffix=forward_suffix)
            except AzureReadbackInvalid:
                raise mutation_error
        else:
            url = wait_for_authority(current_image, suffix=forward_suffix)
        compare_after_change(viewer, url, before)
    except (HostedCheckInvalid, HostedHealthInvalid, httpx.HTTPError, KeyError, TypeError, ValueError) as error:
        raise AzureReadbackInvalid("azure_readback_failed") from error
    finally:
        if "viewer" in locals():
            viewer.close()


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--app", required=True)
    parser.add_argument("--current-image", required=True)
    parser.add_argument("--authorization-id", required=True)
    parser.add_argument(
        "--operation", choices=("restart", "rollback", "recover"), required=True
    )
    parser.add_argument("--revision")
    parser.add_argument("--rollback-image")
    parser.add_argument("--ai-enabled", choices=("true", "false"), required=True)
    options = parser.parse_args(arguments)
    try:
        run_azure_readback(
            subscription_id=options.subscription,
            resource_group=options.resource_group,
            app_name=options.app,
            current_image=options.current_image,
            authorization_id=options.authorization_id,
            operation=options.operation,
            revision=options.revision,
            rollback_image=options.rollback_image,
            ai_enabled=options.ai_enabled == "true",
        )
    except AzureReadbackInvalid:
        print("azure_readback=failed")
        return 1
    print("azure_readback=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
