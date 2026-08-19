"""Disposable Uvicorn application used only by restart acceptance."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from azure.core.credentials import AzureNamedKeyCredential
from azure.storage.blob import ContainerClient
from azure.storage.blob._shared.parser import (
    DEVSTORE_ACCOUNT_KEY,
    DEVSTORE_ACCOUNT_NAME,
)
from sqlalchemy import create_engine

from tests.acceptance.support import azure_storage, build_acceptance_app
from tests.auth_support import MutableClock
from tests.services.test_ai_chat_service import ProviderUnavailableGateway
from src.services.ai_chat_service import AIBudgetLimits

engine = create_engine(os.environ["BIZPULSE_TEST_DATABASE_URL"])
container = ContainerClient(
    account_url=os.environ["BIZPULSE_TEST_BLOB_ACCOUNT_URL"],
    container_name=os.environ["BIZPULSE_TEST_BLOB_CONTAINER"],
    credential=AzureNamedKeyCredential(
        DEVSTORE_ACCOUNT_NAME,
        DEVSTORE_ACCOUNT_KEY,
    ),
)
gateway_mode = os.getenv("BIZPULSE_TEST_GATEWAY_MODE", "normal")
gateway = ProviderUnavailableGateway() if gateway_mode == "unavailable" else None
budget_limits = (
    AIBudgetLimits(500, 1, 15, 5, 100)
    if gateway_mode == "budget"
    else None
)
app = build_acceptance_app(
    engine,
    azure_storage(engine, container),
    allowed_origin=os.getenv("BIZPULSE_TEST_ALLOWED_ORIGIN"),
    clock=MutableClock(datetime.now(UTC)),
    gateway=gateway,
    budget_limits=budget_limits,
    ai_enabled=gateway_mode != "disabled",
)
