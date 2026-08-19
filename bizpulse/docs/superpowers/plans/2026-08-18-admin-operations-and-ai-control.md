# Admin Operations and AI Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a protected `/admin` operations cockpit that reuses the Operator data workflow and safely manages one shared OpenAI API key with independent Operator and Demo AI switches.

**Architecture:** PostgreSQL owns the two runtime channel flags and the exact active Key Vault secret version. Operator and Demo turns continue through one `AIChatService`, but each turn checks its actor-specific flag and passes the shared exact credential version into a version-keyed provider. The admin browser uses same-origin Operator APIs only; candidate credentials are validated and rotated through a compensating server-side saga and are never returned or persisted outside Key Vault.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, SQLAlchemy Core, Alembic, PostgreSQL, Azure Key Vault SDK, Azure Managed Identity, OpenAI Python SDK Responses API, browser-native ES modules, Node test runner, pytest, Ruff, Azure Container Apps/Bicep.

## Global Constraints

- Preserve the existing single-Operator account and opaque `bp_operator_session`; do not introduce a second admin credential system.
- `/demo` sessions may never load an admin document or call an admin API.
- Both AI channels always use one exact Key Vault secret version; per-channel keys are forbidden.
- `operator_enabled` and `demo_enabled` default to `false` and remain independently controllable.
- The approved provider settings remain `https://api.openai.com/v1`, `gpt-5.4-nano-2026-03-17`, and reasoning effort `low`.
- Preserve the current AI limits: 120 daily attempts, 150,000 monthly tokens, 3 attempts per session per minute, 20 global attempts per minute, 15 concurrent turns, and 2,800 output tokens.
- Never persist or emit an OpenAI API key or Operator password in PostgreSQL, Blob, HTML, JavaScript storage, cookies, logs, traces, receipts, errors, or delivery documents.
- Every admin mutation requires same-origin validation, Operator CSRF, current Operator password, optimistic revision where applicable, and an idempotency key.
- Provider qualification uses no SDK retry. A timeout is an unknown outcome and must not activate a candidate.
- Do not replay R19 or any stopped/failed release package. Hosted work requires a fresh exact-hash package and a newly observed Azure baseline.
- Keep `/Users/maxli/Desktop/CAPTSONE` read-only. All implementation lives in `/Users/maxli/Desktop/NEWCaostone`.

---

## File Structure

### Database and domain

- Create `alembic/versions/0015_admin_ai_control.py`: create the control and audit tables.
- Modify `src/db/schema.py`: SQLAlchemy Core definitions matching migration 0015.
- Create `src/repositories/admin_ai.py`: typed control-state and audit persistence.
- Create `src/services/admin_summary_service.py`: safe operations-cockpit projection.
- Create `src/services/ai_control_service.py`: channel mutations and credential activation authority.
- Create `src/services/openai_key_rotation_service.py`: bounded validation/write/readback/compensation saga.

### Authentication, provider, and runtime

- Modify `src/services/operator_auth_service.py`: password-only reauthentication without issuing a session.
- Modify `src/secrets/azure_openai.py`: exact-version reads, version-keyed cache, and secret-manager operations.
- Create `src/ai/credential_validation.py`: minimal fixed-model candidate validation.
- Modify `src/ai/openai_gateway.py`: accept the exact credential version for every provider call.
- Modify `src/services/ai_chat_service.py`: enforce the actor-specific channel before budget/provider use.
- Modify `src/config.py` and `api/container.py`: construct admin AI capability while database flags remain fail-closed.

### HTTP API and shell

- Create `api/dependencies/admin.py`: Operator-only admin and mutation guards.
- Create `api/v1/schemas/admin.py`: secret-safe request and response schemas.
- Create `api/v1/routers/admin.py`: summary, status, channel, and rotation endpoints.
- Modify `api/v1/router.py` and `api/main.py`: register admin APIs and protected shell routes.
- Modify `frontend/assets/login.mjs` and `frontend/index.html`: safe return path and admin entry.

### Frontend admin features

- Create `frontend/admin.html` and `frontend/assets/admin.mjs`: admin shell and navigation.
- Create `frontend/assets/data-sources/admin.mjs`: same-origin admin API adapter.
- Create `frontend/assets/features/admin-overview/{state,effects,view}.mjs`.
- Create `frontend/assets/features/admin-status/{state,effects,view}.mjs`.
- Create `frontend/assets/features/admin-ai/{state,effects,view}.mjs`.
- Modify `frontend/assets/i18n/catalog.mjs` and `frontend/assets/styles.css`: bilingual copy and selected cockpit layout.

### Infrastructure and acceptance

- Modify `infra/ai_enablement.bicep`, `infra/modules/app.bicep`, `infra/main.bicep`, and the active environment parameters: attach the task-owned AI identity and exact-secret data-plane role required for read/write rotation.
- Create `tests/hosted/verify_admin_ai_control.py`: hosted Operator/Demo shared-version acceptance.
- Create `scripts/create_admin_ai_release_package.py` and `scripts/run_admin_ai_release.py`: fresh-package, one-shot release controller with terminal receipt.

---

### Task 1: PostgreSQL AI Control and Audit Authority

**Files:**
- Create: `alembic/versions/0015_admin_ai_control.py`
- Modify: `src/db/schema.py`
- Create: `src/repositories/admin_ai.py`
- Create: `tests/repositories/test_admin_ai_repository.py`

**Interfaces:**
- Consumes: `PostgresUnitOfWork`, workspace ID, Operator UUID, UTC timestamps.
- Produces: `AIControlProjection`, `AdminAuditProjection`, and `AIControlRepository` methods `get_or_create()`, `lock()`, `activate_key()`, `set_channels()`, and `append_audit()`.

- [ ] **Step 1: Write failing migration and repository tests**

```python
def test_control_defaults_fail_closed_and_audit_is_secret_free(migrated_engine):
    seed_operator(migrated_engine, fast_password_hasher())
    now = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    with PostgresUnitOfWork(migrated_engine) as uow:
        repository = AIControlRepository(uow.connection)
        state = repository.get_or_create(WORKSPACE_ID, now=now)
        event = repository.append_audit(
            workspace_id=WORKSPACE_ID,
            operator_id=OperatorRepository(uow.connection).get_active(WORKSPACE_ID).id,
            action="channels.update",
            result="succeeded",
            safe_error_code=None,
            prior_revision=state.revision,
            resulting_revision=state.revision,
            request_id="request-1",
            now=now,
        )
    assert state.operator_enabled is False
    assert state.demo_enabled is False
    assert state.key_version is None
    assert event.action == "channels.update"
    assert "key" not in repr(event).lower()
```

- [ ] **Step 2: Run the focused test and verify the missing schema fails**

Run: `python -m pytest tests/repositories/test_admin_ai_repository.py -q`

Expected: FAIL because `src.repositories.admin_ai` and migration `0015_admin_ai_control` do not exist.

- [ ] **Step 3: Add migration and matching SQLAlchemy tables**

```python
ai_control_state = sa.Table(
    "ai_control_state",
    metadata,
    sa.Column("workspace_id", sa.Text(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("operator_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("demo_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("key_version", sa.Text(), nullable=True),
    sa.Column("key_fingerprint", sa.Text(), nullable=True),
    sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("updated_by_operator_id", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("revision >= 0", name="ck_ai_control_state_revision"),
    sa.CheckConstraint(
        "(key_version IS NULL AND key_fingerprint IS NULL AND verified_at IS NULL) OR "
        "(key_version IS NOT NULL AND key_fingerprint ~ '^[0-9a-f]{64}$' AND verified_at IS NOT NULL)",
        name="ck_ai_control_state_key_binding",
    ),
)

admin_audit_events = sa.Table(
    "admin_audit_events",
    metadata,
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column("workspace_id", sa.Text(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
    sa.Column("operator_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("operator_accounts.id", ondelete="RESTRICT"), nullable=False),
    sa.Column("action", sa.Text(), nullable=False),
    sa.Column("result", sa.Text(), nullable=False),
    sa.Column("safe_error_code", sa.Text(), nullable=True),
    sa.Column("prior_revision", sa.Integer(), nullable=False),
    sa.Column("resulting_revision", sa.Integer(), nullable=False),
    sa.Column("request_id", sa.Text(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)
```

Migration 0015 must create the same columns, checks, foreign keys, and indexes; its downgrade drops audit before control state.

- [ ] **Step 4: Implement typed projections and repository mutations**

```python
@dataclass(frozen=True, slots=True)
class AIControlProjection:
    workspace_id: str
    operator_enabled: bool
    demo_enabled: bool
    key_version: str | None
    key_fingerprint: str | None
    verified_at: datetime | None
    revision: int
    updated_by_operator_id: UUID | None
    updated_at: datetime

class AIControlRepository:
    def lock(self, workspace_id: str) -> AIControlProjection:
        row = self._connection.execute(
            select(*ai_control_state.c)
            .where(ai_control_state.c.workspace_id == workspace_id)
            .with_for_update(of=ai_control_state)
        ).mappings().one()
        return AIControlProjection(**row)
```

`activate_key()` must update only when `revision == expected_revision`; `set_channels()` must increment revision once and reject a lost update by returning `None`.

- [ ] **Step 5: Run migration/repository tests and schema parity checks**

Run: `python -m pytest tests/repositories/test_admin_ai_repository.py tests/db -q`

Expected: PASS, including upgrade/downgrade and schema metadata parity.

- [ ] **Step 6: Commit Task 1**

```bash
git add alembic/versions/0015_admin_ai_control.py src/db/schema.py src/repositories/admin_ai.py tests/repositories/test_admin_ai_repository.py
git commit -m "feat: add admin AI control authority"
```

---

### Task 2: Operator Reauthentication and Admin Guards

**Files:**
- Modify: `src/services/operator_auth_service.py`
- Create: `api/dependencies/admin.py`
- Create: `tests/services/test_operator_reauthentication.py`
- Create: `tests/security/test_admin_boundary.py`

**Interfaces:**
- Consumes: `OperatorPrincipal`, `SecretStr`, `RequestMeta`, existing Operator cookie and CSRF authority.
- Produces: `OperatorAuthService.reauthenticate(principal, password, request_meta) -> bool`, `require_admin_operator(request)`, and `require_admin_mutation(request)`.

- [ ] **Step 1: Write failing reauthentication and Demo-denial tests**

```python
def test_reauthenticate_checks_current_operator_without_issuing_session(service, principal):
    before = count_operator_sessions(service.engine)
    assert service.reauthenticate(principal, SecretStr(PASSWORD), request_meta()) is True
    assert service.reauthenticate(principal, SecretStr("wrong"), request_meta()) is False
    assert count_operator_sessions(service.engine) == before

def test_demo_cookie_cannot_call_admin_summary(client, demo_cookie):
    client.cookies.set("bp_demo_session", demo_cookie)
    response = client.get("/api/v1/admin/summary")
    assert response.status_code == 401
    assert response.json() == {"code": "AUTHENTICATION_REQUIRED"}
```

- [ ] **Step 2: Run the focused tests and verify missing interfaces fail**

Run: `python -m pytest tests/services/test_operator_reauthentication.py tests/security/test_admin_boundary.py -q`

Expected: FAIL because reauthentication and admin dependencies are not implemented.

- [ ] **Step 3: Implement password-only reauthentication with existing rate limits**

```python
def reauthenticate(
    self,
    principal: OperatorPrincipal,
    password: SecretStr,
    request_meta: RequestMeta,
) -> bool:
    self._ensure_attempt_allowed(request_meta.source_address_hash, request_meta.now)
    candidate = password.get_secret_value()
    with PostgresUnitOfWork(self._engine) as uow:
        operator = OperatorRepository(uow.connection).authenticate(
            workspace_id=principal.workspace_id,
            login_name=principal.login_name,
            verifier=lambda stored: self._verify(stored, candidate),
            fallback_hash=self._fallback_hash,
        )
    candidate = ""
    if operator is None or operator.id != principal.operator_id:
        self._record_failed_attempt(request_meta.source_address_hash, request_meta.now)
        return False
    self._clear_failed_attempts(request_meta.source_address_hash)
    return True
```

Extract `_verify(stored_hash, candidate)` so login and reauthentication use identical Argon2 handling.

- [ ] **Step 4: Implement admin dependencies by composing existing Operator and CSRF guards**

```python
def require_admin_operator(request: Request) -> OperatorPrincipal:
    return resolve_operator(request)

def require_admin_mutation(request: Request) -> OperatorPrincipal:
    principal = resolve_operator(request)
    require_allowed_origin(request)
    token = request.headers.get("X-CSRF-Token")
    service = request.app.state.container.operator_auth_service
    if token is None or service is None or not service.csrf_matches(principal.session_id, token):
        raise CsrfValidationError
    return principal
```

- [ ] **Step 5: Run service and security tests**

Run: `python -m pytest tests/services/test_operator_reauthentication.py tests/security/test_admin_boundary.py tests/security/test_auth_csrf_cookies.py -q`

Expected: PASS with no new session row and no Demo access.

- [ ] **Step 6: Commit Task 2**

```bash
git add src/services/operator_auth_service.py api/dependencies/admin.py tests/services/test_operator_reauthentication.py tests/security/test_admin_boundary.py
git commit -m "feat: require operator reauthentication for admin mutations"
```

---

### Task 3: Exact-Version Key Vault Provider and Candidate Validation

**Files:**
- Modify: `src/secrets/azure_openai.py`
- Create: `src/ai/credential_validation.py`
- Modify: `tests/unit/secrets/test_azure_openai.py`
- Create: `tests/unit/ai/test_credential_validation.py`

**Interfaces:**
- Consumes: Azure `SecretClient`, managed-identity credential, approved OpenAI model/base URL/effort.
- Produces: `SecretVersion(value: str, version: str)`, `OpenAISecretManager.read(version)`, `write(value)`, `AzureOpenAIClientProvider.acquire(version)`, and `OpenAICredentialValidator.validate(value) -> CredentialValidationResult`.

- [ ] **Step 1: Write failing exact-version cache and no-retry validator tests**

```python
def test_provider_caches_by_exact_secret_version(secret_client):
    provider = AzureOpenAIClientProvider(
        vault_url=VAULT_URL,
        secret_name=SECRET_NAME,
        managed_identity_client_id=CLIENT_ID,
        secret_client=secret_client,
    )
    with provider.acquire("version-a"):
        pass
    with provider.acquire("version-b"):
        pass
    assert secret_client.requested_versions == ["version-a", "version-b"]

def test_validator_uses_fixed_model_store_false_and_zero_retries(fake_openai_factory):
    result = OpenAICredentialValidator(client_factory=fake_openai_factory).validate("candidate")
    assert result.status == "verified"
    assert fake_openai_factory.options["max_retries"] == 0
    assert fake_openai_factory.request["model"] == APPROVED_OPENAI_MODEL
    assert fake_openai_factory.request["store"] is False
```

- [ ] **Step 2: Run tests and verify versioned interfaces are absent**

Run: `python -m pytest tests/unit/secrets/test_azure_openai.py tests/unit/ai/test_credential_validation.py -q`

Expected: FAIL on missing `acquire(version)`, secret-manager, and validator APIs.

- [ ] **Step 3: Implement exact-version secret management and version-keyed caching**

```python
@dataclass(frozen=True, slots=True, repr=False)
class SecretVersion:
    value: str
    version: str

def read(self, version: str) -> SecretVersion:
    secret = self._secret_client.get_secret(self._secret_name, version=version)
    if not secret.value or not secret.properties.version:
        raise OpenAISecretUnavailable("openai_secret_unavailable")
    return SecretVersion(secret.value, secret.properties.version)

@contextmanager
def acquire(self, version: str) -> Iterator[OpenAIClientProtocol]:
    api_key = self._secret_value(version)
    client = OpenAI(
        api_key=api_key,
        base_url=APPROVED_OPENAI_BASE_URL,
        max_retries=0,
        timeout=OPENAI_PROVIDER_TIMEOUT_SECONDS,
    )
    try:
        yield client
    finally:
        client.close()
        api_key = ""
```

The cache must be `dict[str, tuple[str, float]]`, bounded to the active and immediately prior versions, and fully cleared on `close()`.

- [ ] **Step 4: Implement the fixed-model credential validator**

```python
class OpenAICredentialValidator:
    def validate(self, candidate: str) -> CredentialValidationResult:
        client = self._client_factory(
            api_key=candidate,
            base_url=APPROVED_OPENAI_BASE_URL,
            max_retries=0,
            timeout=30.0,
        )
        try:
            response = client.responses.create(
                model=APPROVED_OPENAI_MODEL,
                reasoning={"effort": APPROVED_REASONING_EFFORT},
                input="Return exactly: ready",
                max_output_tokens=32,
                store=False,
            )
        except AuthenticationError:
            return CredentialValidationResult("rejected", None)
        except (APIConnectionError, APITimeoutError):
            return CredentialValidationResult("unknown", None)
        finally:
            client.close()
            candidate = ""
        if response.status != "completed":
            return CredentialValidationResult("rejected", None)
        return CredentialValidationResult("verified", getattr(response, "_request_id", None))
```

The result representation contains status and request ID only; it must never retain the candidate or output text.

- [ ] **Step 5: Run provider, validator, and secret-representation tests**

Run: `python -m pytest tests/unit/secrets/test_azure_openai.py tests/unit/ai/test_credential_validation.py tests/security/test_auth_csrf_cookies.py -q`

Expected: PASS; candidate text is absent from all representations.

- [ ] **Step 6: Commit Task 3**

```bash
git add src/secrets/azure_openai.py src/ai/credential_validation.py tests/unit/secrets/test_azure_openai.py tests/unit/ai/test_credential_validation.py
git commit -m "feat: bind OpenAI clients to exact secret versions"
```

---

### Task 4: AI Channel and Key-Rotation Services

**Files:**
- Create: `src/services/ai_control_service.py`
- Create: `src/services/openai_key_rotation_service.py`
- Create: `tests/services/test_ai_control_service.py`
- Create: `tests/services/test_openai_key_rotation_service.py`

**Interfaces:**
- Consumes: `AIControlRepository`, `OperatorAuthService`, `OpenAISecretManager`, `OpenAICredentialValidator`, session-pepper bytes, and clock.
- Produces: `AIControlService.get()`, `require_enabled(actor_kind) -> str`, `set_channels(...) -> AIControlProjection`, and `OpenAIKeyRotationService.rotate(...) -> AIControlProjection`.

- [ ] **Step 1: Write failing channel and compensation tests**

```python
def test_operator_and_demo_flags_are_independent(control_service_with_verified_key):
    changed = control_service_with_verified_key.set_channels(
        principal=operator_principal(),
        expected_revision=0,
        operator_enabled=True,
        demo_enabled=False,
        request_id="request-1",
    )
    assert control_service_with_verified_key.require_enabled("operator") == changed.key_version
    with pytest.raises(AIChannelDisabled):
        control_service_with_verified_key.require_enabled("demo")

def test_post_write_validation_failure_restores_old_secret(rotation_service, control_service, secret_manager):
    with pytest.raises(AIKeyRotationFailed, match="ADMIN_AI_KEY_REJECTED"):
        rotation_service.rotate(candidate=SecretStr("new-key"), **rotation_arguments())
    assert secret_manager.latest_value == "old-key"
    assert control_service.get().key_version == "old-version"
```

- [ ] **Step 2: Run focused tests and verify services are absent**

Run: `python -m pytest tests/services/test_ai_control_service.py tests/services/test_openai_key_rotation_service.py -q`

Expected: FAIL because both service modules are missing.

- [ ] **Step 3: Implement fail-closed channel checks and optimistic mutation**

```python
def require_enabled(self, actor_kind: Literal["operator", "demo"]) -> str:
    state = self.get()
    enabled = state.operator_enabled if actor_kind == "operator" else state.demo_enabled
    if not enabled:
        raise AIChannelDisabled("AI_CHAT_CHANNEL_DISABLED")
    if state.key_version is None or state.verified_at is None:
        raise AIControlUnavailable("AI_CHAT_UNAVAILABLE")
    return state.key_version
```

`set_channels()` must reject enabling when no verified key exists, lock the row, compare `expected_revision`, update both booleans once, and append one audit event in the same transaction.

- [ ] **Step 4: Implement the non-retried rotation saga with compensation**

```python
def rotate(self, *, principal, candidate: SecretStr, expected_revision: int, request_id: str):
    candidate_value = candidate.get_secret_value()
    first = self._validator.validate(candidate_value)
    if first.status != "verified":
        candidate_value = ""
        raise self._validation_error(first.status)
    with PostgresUnitOfWork(self._engine) as uow:
        repository = AIControlRepository(uow.connection)
        prior = repository.lock(self._workspace_id)
        if prior.revision != expected_revision:
            raise AIStateConflict
        previous = self._secrets.read(prior.key_version) if prior.key_version else None
        written = self._secrets.write(candidate_value)
        readback = self._secrets.read(written.version)
        second = self._validator.validate(readback.value)
        if second.status != "verified":
            if previous is not None:
                self._secrets.write(previous.value)
            raise self._validation_error(second.status)
        activated = repository.activate_key(
            workspace_id=self._workspace_id,
            expected_revision=prior.revision,
            key_version=written.version,
            key_fingerprint=self._fingerprint(candidate_value),
            verified_at=self._clock(),
            operator_id=principal.operator_id,
        )
        repository.append_audit(
            workspace_id=self._workspace_id,
            operator_id=principal.operator_id,
            action="key.rotate",
            result="succeeded",
            safe_error_code=None,
            prior_revision=prior.revision,
            resulting_revision=activated.revision,
            request_id=request_id,
            now=self._clock(),
        )
    candidate_value = ""
    return activated
```

Wrap the method in `try/finally` so candidate, readback, and previous value references are cleared. Map first/second `unknown` to `ADMIN_AI_VALIDATION_OUTCOME_UNKNOWN` and do not retry.

- [ ] **Step 5: Run service tests including concurrent and no-prior-key cases**

Run: `python -m pytest tests/services/test_ai_control_service.py tests/services/test_openai_key_rotation_service.py -q`

Expected: PASS for independent flags, stale revision, row locking, initial configuration, compensation, and unknown outcomes.

- [ ] **Step 6: Commit Task 4**

```bash
git add src/services/ai_control_service.py src/services/openai_key_rotation_service.py tests/services/test_ai_control_service.py tests/services/test_openai_key_rotation_service.py
git commit -m "feat: add verified admin AI control services"
```

---

### Task 5: Shared Runtime Enforcement for Operator and Demo

**Files:**
- Modify: `src/ai/openai_gateway.py`
- Modify: `src/services/ai_chat_service.py`
- Modify: `api/container.py`
- Modify: `src/config.py`
- Modify: `tests/services/test_ai_chat_service.py`
- Modify: `tests/services/test_ai_chat_container.py`
- Modify: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: `AIControlService.require_enabled(actor_kind) -> key_version` and `AzureOpenAIClientProvider.acquire(key_version)`.
- Produces: `OpenAIGateway.plan(..., credential_version: str)` and `explain(..., credential_version: str)`; every AI turn binds one version before provider use.

- [ ] **Step 1: Write failing shared-version and pre-budget gate tests**

```python
def test_operator_and_demo_turns_use_same_control_version(ai_service, gateway, control):
    control.operator_enabled = True
    control.demo_enabled = True
    control.key_version = "shared-version"
    ai_service.submit(operator_principal(), **turn_arguments("operator-turn"))
    ai_service.submit(demo_principal(), **turn_arguments("demo-turn"))
    assert gateway.credential_versions == ["shared-version", "shared-version"]

def test_disabled_demo_is_rejected_before_budget_reservation(ai_service, budget_repository):
    with pytest.raises(AIChatUnavailable, match="AI_CHAT_CHANNEL_DISABLED"):
        ai_service.submit(demo_principal(), **turn_arguments("demo-turn"))
    assert budget_repository.attempt_count() == 0
```

- [ ] **Step 2: Run focused runtime tests and verify signatures fail**

Run: `python -m pytest tests/services/test_ai_chat_service.py tests/services/test_ai_chat_container.py tests/unit/test_config.py -q`

Expected: FAIL because the gateway and service do not accept a credential version.

- [ ] **Step 3: Bind the exact version at turn start and pass it through both gateway phases**

```python
credential_version = self._ai_control.require_enabled(principal.actor_kind)
planning = self._gateway.plan(
    question,
    capability_catalog,
    history,
    credential_version=credential_version,
)
answer = self._gateway.explain(
    question,
    tool_result,
    history,
    credential_version=credential_version,
)
```

Both calls for one turn must use the same local `credential_version`, even if an administrator rotates the key between planning and explanation.

- [ ] **Step 4: Update gateway acquisition and container construction**

```python
def _parse(self, *, stage, prompt, payload, schema, credential_version: str):
    with self._client_provider.acquire(credential_version) as acquired_client:
        client = acquired_client.with_options(max_retries=0, timeout=PROVIDER_TIMEOUT_SECONDS)
        response = client.responses.parse(
            model=self.model,
            reasoning={"effort": self.reasoning_effort},
            max_output_tokens=MAX_OUTPUT_TOKENS,
            tools=[],
            input=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": str(payload)},
            ],
            text_format=schema,
        )
    if getattr(response, "status", None) != "completed":
        raise ProviderUnavailable(f"provider_{stage}_incomplete")
    parsed = getattr(response, "output_parsed", None)
    usage = getattr(response, "usage", None)
    if not isinstance(parsed, schema) or usage is None:
        raise ProviderUnavailable(f"provider_{stage}_invalid_output")
    return ProviderResult(parsed, usage.input_tokens, usage.output_tokens)
```

When `BIZPULSE_AI_CHAT_ENABLED=true`, `ApiContainer.build()` must construct the versioned provider, `AIControlService`, rotation service, and `AIChatService`. Database channel defaults remain false, so capability construction alone cannot send a provider request.

- [ ] **Step 5: Run chat, configuration, budget, and provider tests**

Run: `python -m pytest tests/services/test_ai_chat_service.py tests/services/test_ai_chat_container.py tests/unit/test_config.py tests/unit/ai tests/unit/secrets -q`

Expected: PASS; disabled turns create zero provider attempts and zero budget reservations.

- [ ] **Step 6: Commit Task 5**

```bash
git add src/ai/openai_gateway.py src/services/ai_chat_service.py api/container.py src/config.py tests/services/test_ai_chat_service.py tests/services/test_ai_chat_container.py tests/unit/test_config.py
git commit -m "feat: enforce runtime AI channels by actor"
```

---

### Task 6: Administrator Summary and AI APIs

**Files:**
- Create: `src/services/admin_summary_service.py`
- Create: `api/v1/schemas/admin.py`
- Create: `api/v1/routers/admin.py`
- Modify: `api/v1/router.py`
- Modify: `api/container.py`
- Create: `tests/api/test_admin_api.py`
- Create: `tests/services/test_admin_summary_service.py`
- Modify: `tests/security/test_headers.py`

**Interfaces:**
- Consumes: admin dependencies, public release service, import/dataset repositories, readiness dependencies, control and rotation services.
- Produces: `GET /api/v1/admin/summary`, `GET /api/v1/admin/ai`, `PATCH /api/v1/admin/ai/channels`, and `POST /api/v1/admin/ai/key-rotations`.

- [ ] **Step 1: Write failing safe-projection and mutation-contract tests**

```python
def test_admin_ai_projection_never_returns_version_or_secret(operator_client):
    response = operator_client.get("/api/v1/admin/ai")
    assert response.status_code == 200
    serialized = response.text.lower()
    assert "key_version" not in serialized
    assert "openai-api-key" not in serialized
    assert response.json()["credential"]["fingerprint"] == "7fa2c91e"

def test_rotation_requires_csrf_password_and_idempotency(operator_client):
    response = operator_client.post(
        "/api/v1/admin/ai/key-rotations",
        json={"candidate_key": "sentinel", "current_password": PASSWORD, "expected_revision": 0},
    )
    assert response.status_code == 403
    assert "sentinel" not in response.text
```

- [ ] **Step 2: Run API tests and verify routes are missing**

Run: `python -m pytest tests/api/test_admin_api.py tests/services/test_admin_summary_service.py -q`

Expected: FAIL with 404 or missing admin schemas/services.

- [ ] **Step 3: Implement secret-safe schemas and safe exception mapping**

```python
class AIChannelsUpdateRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    operator_enabled: bool
    demo_enabled: bool
    current_password: SecretStr

class AIKeyRotationRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    candidate_key: SecretStr
    current_password: SecretStr

class AICredentialProjection(BaseModel):
    configured: bool
    fingerprint: str | None
    verified_at: datetime | None
```

Add explicit handlers for `ADMIN_AI_STATE_CONFLICT`, `ADMIN_AI_OPERATION_BUSY`, `ADMIN_AI_KEY_REJECTED`, `ADMIN_AI_VALIDATION_OUTCOME_UNKNOWN`, and `ADMIN_AI_SECRET_UNAVAILABLE`. Never serialize exception strings from Azure or OpenAI.

- [ ] **Step 4: Implement summary and mutation routes**

```python
@router.patch("/ai/channels", response_model=AIControlResponse)
def update_channels(payload: AIChannelsUpdateRequest, request: Request, principal=Depends(require_admin_mutation)):
    _reauthenticate(request, principal, payload.current_password)
    result = request.app.state.container.ai_control_service.set_channels(
        principal=principal,
        expected_revision=payload.expected_revision,
        operator_enabled=payload.operator_enabled,
        demo_enabled=payload.demo_enabled,
        request_id=request_id(request.scope),
    )
    return project_ai_control(result)
```

Rotation uses the same guard plus `Idempotency-Key`. Apply `PRIVATE_NO_STORE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}` to every response.

- [ ] **Step 5: Run API, headers, secret-leak, and rate-limit tests**

Run: `python -m pytest tests/api/test_admin_api.py tests/services/test_admin_summary_service.py tests/security/test_admin_boundary.py tests/security/test_headers.py -q`

Expected: PASS; the submitted sentinel key and password are absent from response text, logs captured by `caplog`, and database projections.

- [ ] **Step 6: Commit Task 6**

```bash
git add src/services/admin_summary_service.py api/v1/schemas/admin.py api/v1/routers/admin.py api/v1/router.py api/container.py tests/api/test_admin_api.py tests/services/test_admin_summary_service.py tests/security/test_headers.py
git commit -m "feat: expose protected admin operations APIs"
```

---

### Task 7: Protected Admin Shell and Safe Login Return

**Files:**
- Modify: `api/main.py`
- Modify: `frontend/index.html`
- Modify: `frontend/assets/login.mjs`
- Create: `frontend/admin.html`
- Create: `tests/api/test_admin_shell.py`
- Modify: `tests/frontend/login.test.mjs`
- Modify: `tests/frontend/shell.test.mjs`

**Interfaces:**
- Consumes: existing `resolve_operator()` and `/api/operator/login`.
- Produces: protected `/admin`, `/admin/data`, `/admin/status`, `/admin/ai`; allowlisted login `next`; `/app` sidebar admin entry.

- [ ] **Step 1: Write failing route and open-redirect tests**

```python
@pytest.mark.parametrize("path", ["/admin", "/admin/data", "/admin/status", "/admin/ai"])
def test_admin_document_requires_operator_and_returns_shell(authenticated_client, path):
    assert authenticated_client.get(path).status_code == 200
    assert "BP Admin" in authenticated_client.get(path).text

def test_unauthenticated_admin_navigation_redirects_to_allowlisted_login(client):
    response = client.get("/admin/ai", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/admin/ai"
```

- [ ] **Step 2: Run shell tests and verify routes/files are absent**

Run: `python -m pytest tests/api/test_admin_shell.py -q && node --test tests/frontend/login.test.mjs tests/frontend/shell.test.mjs`

Expected: FAIL on missing admin shell and safe return handling.

- [ ] **Step 3: Add protected shell routes and Operator-only entry**

```python
def _admin_shell(request: Request) -> Response:
    try:
        resolve_operator(request)
    except AuthenticationRequiredError:
        target = quote(request.url.path, safe="/")
        return RedirectResponse(url=f"/login?next={target}", status_code=303)
    return _shell(FRONTEND_ROOT / "admin.html")

for path in ("/admin", "/admin/data", "/admin/status", "/admin/ai"):
    application.add_api_route(path, _admin_shell, methods=["GET"], include_in_schema=False)
```

Add an `/app` sidebar-footer link with `href="/admin"`; do not add it to public or Demo navigation.

- [ ] **Step 4: Implement allowlisted post-login navigation**

```javascript
function safeNext(search) {
  const value = new URLSearchParams(search).get("next");
  return value === "/app" || /^\/admin(?:\/(?:data|status|ai))?$/.test(value ?? "")
    ? value
    : "/app";
}

window.location.assign(safeNext(window.location.search));
```

Export `safeNext` and add a Node test proving `https://attacker.test`, `//attacker.test`, encoded external URLs, and unknown local paths all resolve to `/app`.

- [ ] **Step 5: Run route, redirect, shell, and browser security tests**

Run: `python -m pytest tests/api/test_admin_shell.py tests/security/test_admin_boundary.py -q && node --test tests/frontend/login.test.mjs tests/frontend/shell.test.mjs`

Expected: PASS; an external, protocol-relative, encoded, or unknown `next` target resolves to `/app`.

- [ ] **Step 6: Commit Task 7**

```bash
git add api/main.py frontend/index.html frontend/assets/login.mjs frontend/admin.html tests/api/test_admin_shell.py tests/frontend/login.test.mjs tests/frontend/shell.test.mjs
git commit -m "feat: add protected administrator shell"
```

---

### Task 8: Operations Cockpit, Data Management, and System Status UI

**Files:**
- Create: `frontend/assets/admin.mjs`
- Create: `frontend/assets/data-sources/admin.mjs`
- Create: `frontend/assets/features/admin-overview/state.mjs`
- Create: `frontend/assets/features/admin-overview/effects.mjs`
- Create: `frontend/assets/features/admin-overview/view.mjs`
- Create: `frontend/assets/features/admin-status/state.mjs`
- Create: `frontend/assets/features/admin-status/effects.mjs`
- Create: `frontend/assets/features/admin-status/view.mjs`
- Modify: `frontend/assets/i18n/catalog.mjs`
- Modify: `frontend/assets/styles.css`
- Create: `tests/frontend/admin-shell.test.mjs`
- Create: `tests/frontend/admin-overview.test.mjs`

**Interfaces:**
- Consumes: `AdminDataSource.loadSummary()`, existing `OperatorDataSource`, and exported `renderWorkspace()`.
- Produces: four-route admin navigation, 30-second safe summary refresh, cockpit cards, recent activity, reused data workflow, and safe status panels.

- [ ] **Step 1: Write failing frontend contracts**

```javascript
test("admin shell exposes selected cockpit navigation", async () => {
  const html = await read("admin.html");
  assert.deepEqual(
    [...html.matchAll(/data-admin-route="([^"]+)"/g)].map((match) => match[1]),
    ["overview", "data", "status", "ai"],
  );
  assert.match(html, /href="\/app"[^>]*>Return to workspace/);
});

test("summary refresh is bounded to thirty seconds", () => {
  const effects = createAdminOverviewEffects({ dataSource, dispatch, setInterval: fakeInterval });
  effects.start();
  assert.equal(fakeInterval.delay, 30_000);
});
```

- [ ] **Step 2: Run frontend tests and verify modules are missing**

Run: `node --test tests/frontend/admin-shell.test.mjs tests/frontend/admin-overview.test.mjs`

Expected: FAIL on missing admin modules.

- [ ] **Step 3: Implement the admin data source and overview state/effects**

```javascript
export class AdminDataSource {
  constructor(apiClient) { this.api = apiClient; }
  loadSummary() {
    return this.api.request("/api/v1/admin/summary", { cache: "no-store" });
  }
  loadAI() {
    return this.api.request("/api/v1/admin/ai", { cache: "no-store" });
  }
}

export function reduceAdminOverview(state, action) {
  if (action.type === "load/succeeded") return { status: "ready", payload: action.payload, error: null };
  if (action.type === "load/failed") return { ...state, status: "failed", error: action.code };
  return state;
}
```

- [ ] **Step 4: Render the selected cockpit and reuse the existing data workflow**

```javascript
if (route === "data") {
  renderWorkspace(root, operatorDataSource, release, () => currentRoute === "data", getScope);
  return;
}
if (route === "overview") {
  renderAdminOverview(root, overviewState, { language });
  return;
}
renderAdminStatus(root, statusState, { language });
```

Do not copy import-state or upload code into admin modules. The cockpit renders only the safe summary fields defined by the API schema.

- [ ] **Step 5: Add bilingual strings, cockpit styles, and accessibility assertions**

Add exact English/Chinese catalog keys for overview, data management, system status, AI management, credential state, ordinary login, public Demo, validation, rollback, and safe errors. Status changes use `role="status"`; failures use `role="alert"`; route buttons maintain `aria-current="page"`.

```javascript
const adminCatalog = {
  en: {
    "admin.nav.overview": "Overview",
    "admin.nav.data": "Data Management",
    "admin.nav.status": "System Status",
    "admin.nav.ai": "AI Management",
    "admin.ai.operator": "Ordinary Login AI",
    "admin.ai.demo": "Public Demo AI",
    "admin.ai.rotate": "Validate and safely replace",
  },
  zh: {
    "admin.nav.overview": "总览",
    "admin.nav.data": "数据管理",
    "admin.nav.status": "系统状态",
    "admin.nav.ai": "AI 管理",
    "admin.ai.operator": "普通登录 AI",
    "admin.ai.demo": "公开 Demo AI",
    "admin.ai.rotate": "验证并安全替换",
  },
};
```

Run: `node --test tests/frontend/admin-shell.test.mjs tests/frontend/admin-overview.test.mjs tests/frontend/i18n.test.mjs tests/frontend/workspace.test.mjs`

Expected: PASS with no external assets and no model selector.

- [ ] **Step 6: Commit Task 8**

```bash
git add frontend/assets/admin.mjs frontend/assets/data-sources/admin.mjs frontend/assets/features/admin-overview frontend/assets/features/admin-status frontend/assets/i18n/catalog.mjs frontend/assets/styles.css tests/frontend/admin-shell.test.mjs tests/frontend/admin-overview.test.mjs
git commit -m "feat: build admin operations cockpit"
```

---

### Task 9: Shared-Key AI Management UI

**Files:**
- Create: `frontend/assets/features/admin-ai/state.mjs`
- Create: `frontend/assets/features/admin-ai/effects.mjs`
- Create: `frontend/assets/features/admin-ai/view.mjs`
- Modify: `frontend/assets/data-sources/admin.mjs`
- Modify: `frontend/assets/admin.mjs`
- Create: `tests/frontend/admin-ai-state.test.mjs`
- Create: `tests/frontend/admin-ai-effects.test.mjs`
- Create: `tests/frontend/admin-ai-view.test.mjs`
- Modify: `tests/frontend/browser-process-env.test.mjs`

**Interfaces:**
- Consumes: admin AI GET/PATCH/POST APIs and CSRF helpers.
- Produces: independent channel controls, shared credential projection, password-confirmed key rotation, deterministic loading/conflict/rollback states, and immediate post-mutation refresh.

- [ ] **Step 1: Write failing state and secret-clearing tests**

```javascript
test("operator and demo toggles remain independent", () => {
  const state = reduceAdminAI(initialAdminAIState(), {
    type: "load/succeeded",
    payload: { revision: 4, operator_enabled: true, demo_enabled: false, credential: { configured: true } },
  });
  assert.equal(state.payload.operator_enabled, true);
  assert.equal(state.payload.demo_enabled, false);
});

test("rotation clears both secret inputs after failure", async () => {
  await effects.rotate({ candidateKey: "sentinel-key", currentPassword: "sentinel-password" });
  assert.deepEqual(clearedFields, ["candidateKey", "currentPassword"]);
  assert.doesNotMatch(JSON.stringify(actions), /sentinel-key|sentinel-password/);
});
```

- [ ] **Step 2: Run focused frontend tests and verify modules are absent**

Run: `node --test tests/frontend/admin-ai-state.test.mjs tests/frontend/admin-ai-effects.test.mjs tests/frontend/admin-ai-view.test.mjs`

Expected: FAIL on missing admin AI modules.

- [ ] **Step 3: Implement state and API effects without retaining credentials**

```javascript
async function rotate({ candidateKey, currentPassword, expectedRevision }) {
  dispatch({ type: "rotation/started" });
  try {
    const result = await dataSource.rotateKey({ candidateKey, currentPassword, expectedRevision });
    dispatch({ type: "rotation/succeeded", payload: result });
  } catch (error) {
    dispatch({ type: "rotation/failed", code: error.code ?? "ADMIN_AI_SECRET_UNAVAILABLE" });
  } finally {
    clearSecrets();
    await load();
  }
}
```

The reducer stores only revision, booleans, configured flag, fingerprint prefix, timestamps, loading state, and safe error codes.

- [ ] **Step 4: Render shared credential and two password-confirmed controls**

The view must create password inputs with `autocomplete="current-password"`, a candidate input with `autocomplete="off"`, independent ordinary-login and public-Demo buttons, and a single **Validate and safely replace** action. `input.value = ""` executes after every submit outcome and when leaving the route.

```javascript
const candidate = element("input", "admin-secret-input");
candidate.type = "password";
candidate.autocomplete = "off";
const currentPassword = element("input", "admin-secret-input");
currentPassword.type = "password";
currentPassword.autocomplete = "current-password";
const clearSecrets = () => {
  candidate.value = "";
  currentPassword.value = "";
};
rotateButton.addEventListener("click", async () => {
  try {
    await effects.rotate({
      candidateKey: candidate.value,
      currentPassword: currentPassword.value,
      expectedRevision: state.payload.revision,
    });
  } finally {
    clearSecrets();
  }
});
```

- [ ] **Step 5: Run all admin frontend and secret-source scans**

Run: `node --test tests/frontend/admin-*.test.mjs tests/frontend/browser-process-env.test.mjs tests/frontend/i18n.test.mjs`

Expected: PASS; checked-in browser sources contain no real key, environment read, Key Vault identifier, Azure resource ID, or persisted password path.

- [ ] **Step 6: Commit Task 9**

```bash
git add frontend/assets/features/admin-ai frontend/assets/data-sources/admin.mjs frontend/assets/admin.mjs tests/frontend/admin-ai-state.test.mjs tests/frontend/admin-ai-effects.test.mjs tests/frontend/admin-ai-view.test.mjs tests/frontend/browser-process-env.test.mjs
git commit -m "feat: add shared-key AI administration UI"
```

---

### Task 10: Hosted Identity, Key Vault Role, and App Configuration

**Files:**
- Modify: `infra/ai_enablement.bicep`
- Modify: `infra/modules/app.bicep`
- Modify: `infra/main.bicep`
- Modify: `infra/environments/demo.bicepparam`
- Modify: `tests/infra/test_ai_enablement_bicep.py`
- Modify: `tests/infra/test_bicep_contract.py`
- Modify: `tests/infra/test_deployed_release_bicep_projection.py`

**Interfaces:**
- Consumes: task-owned OpenAI managed identity and canonical `openai-api-key` secret.
- Produces: application identity attachment, fixed Key Vault bindings, approved budgets, and secret-scoped read/write data-plane permission without Azure control-plane mutation permission.

- [ ] **Step 1: Write failing least-privilege infrastructure tests**

```python
def test_admin_ai_identity_is_scoped_to_canonical_secret() -> None:
    compiled = compile_bicep(PROJECT_ROOT / "infra/ai_enablement.bicep")
    assignment = role_assignment_for(compiled, "openai-api-key")
    assert assignment["scope"].endswith("/secrets/openai-api-key")
    assert assignment["properties"]["principalId"] == "[reference(resourceId('Microsoft.ManagedIdentity/userAssignedIdentities', parameters('openaiIdentityName')), '2023-01-31').principalId]"

def test_capability_does_not_enable_either_database_channel() -> None:
    source = (PROJECT_ROOT / "infra/modules/app.bicep").read_text()
    assert "BIZPULSE_OPERATOR_AI_ENABLED" not in source
    assert "BIZPULSE_DEMO_AI_ENABLED" not in source
```

- [ ] **Step 2: Run infra tests and verify the write role/configuration contract fails**

Run: `python -m pytest tests/infra/test_ai_enablement_bicep.py tests/infra/test_bicep_contract.py tests/infra/test_deployed_release_bicep_projection.py -q`

Expected: FAIL because the current identity is read-only/conditionally absent and current projections are release-time gated.

- [ ] **Step 3: Update Bicep to attach capability while database flags remain false**

The app template must supply the approved model, effort, five budgets, Key Vault URL, canonical secret name, and managed-identity client ID when admin AI capability is enabled. It must not inject `OPENAI_API_KEY`, a Key Vault secret reference, or either channel flag.

Use the existing task-owned identity. Assign its data-plane role at the exact secret scope only. Do not grant `Owner`, `Contributor`, `Key Vault Administrator`, role-assignment write, or vault permission-management actions.

```bicep
resource vault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: openaiKeyVaultName
}

resource canonicalSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' existing = {
  parent: vault
  name: 'openai-api-key'
}

resource adminAiSecretOfficer 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(canonicalSecret.id, openaiIdentity.id, 'admin-ai-secret-officer')
  scope: canonicalSecret
  properties: {
    principalId: openaiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
    )
  }
}
```

- [ ] **Step 4: Compile Bicep and run contract projections**

Run: `az bicep build --file infra/main.bicep --stdout >/dev/null && python -m pytest tests/infra/test_ai_enablement_bicep.py tests/infra/test_bicep_contract.py tests/infra/test_deployed_release_bicep_projection.py -q`

Expected: Bicep compilation succeeds and all focused infrastructure tests pass.

- [ ] **Step 5: Run configuration and secret-leak scans**

Run: `python -m pytest tests/unit/test_config.py tests/security tests/infra -q && rg -n 'OPENAI_API_KEY|sk-[A-Za-z0-9]' frontend api src infra/environments`

Expected: tests PASS; `rg` reports only explicit forbidden-name assertions or configuration guards, never a credential value or browser injection.

- [ ] **Step 6: Commit Task 10**

```bash
git add infra/ai_enablement.bicep infra/modules/app.bicep infra/main.bicep infra/environments/demo.bicepparam tests/infra/test_ai_enablement_bicep.py tests/infra/test_bicep_contract.py tests/infra/test_deployed_release_bicep_projection.py
git commit -m "feat: provision least-privilege admin AI capability"
```

---

### Task 11: Full Local Verification and Fresh Hosted Release Controller

**Files:**
- Create: `tests/hosted/test_admin_ai_release_contract.py`
- Create: `tests/hosted/verify_admin_ai_control.py`
- Create: `scripts/create_admin_ai_release_package.py`
- Create: `scripts/run_admin_ai_release.py`
- Modify: `docs/operations/AZURE_LAUNCH_RUNBOOK.md`

**Interfaces:**
- Consumes: exact Git commit/tree, exact linux/amd64 image digest, fresh Azure read-only observation, protected admin APIs, and a one-time user-entered OpenAI key.
- Produces: a fresh single-use authorization package, terminal attempt receipt, and sanitized hosted acceptance evidence for both actor kinds.

- [ ] **Step 1: Write failing package and verifier contract tests**

```python
def test_package_binds_exact_source_image_baseline_and_no_secret(package):
    assert package["repository"]["source_sha"] == SOURCE_SHA
    assert package["candidate"]["image_digest"].startswith("sha256:")
    assert package["azure_baseline"]["observed_at"] is not None
    assert package["execution_contract"]["attempts"] == 1
    assert "api_key" not in json.dumps(package).lower()

def test_hosted_verifier_requires_shared_fingerprint_for_both_actor_kinds(result):
    assert result["operator_turn"]["status"] == "completed"
    assert result["demo_turn"]["status"] == "completed"
    assert result["operator_turn"]["credential_fingerprint"] == result["demo_turn"]["credential_fingerprint"]
```

- [ ] **Step 2: Run contract tests and verify scripts are missing**

Run: `python -m pytest tests/hosted/test_admin_ai_release_contract.py -q`

Expected: FAIL because the fresh-package generator and controller do not exist.

- [ ] **Step 3: Implement a fresh-package generator with current-baseline binding**

The generator must refuse a dirty tracked tree, non-linux/amd64 image, missing exact digest, stale authority file, expired package, absent healthy current revision, or any prior package hash. It writes mode `0600`, contains no command that reads an ambient `OPENAI_API_KEY`, and names a new terminal receipt path.

```python
def build_package(*, source_sha, source_tree, image_digest, baseline, expires_at, receipt_path):
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise PackageInvalid("source_sha_invalid")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest):
        raise PackageInvalid("image_digest_invalid")
    if baseline["health_state"] != "Healthy" or baseline["ready"] is not True:
        raise PackageInvalid("azure_baseline_not_healthy")
    package = {
        "schema_version": "newcaostone.admin-ai-release.v1",
        "repository": {"source_sha": source_sha, "source_tree": source_tree},
        "candidate": {"image_digest": image_digest, "platform": "linux/amd64"},
        "azure_baseline": baseline,
        "execution_contract": {"attempts": 1, "receipt_path": receipt_path},
        "expires_at": expires_at,
    }
    assert "OPENAI_API_KEY" not in json.dumps(package)
    return package
```

- [ ] **Step 4: Implement the one-shot controller and sanitized verifier**

The controller sequence is fixed:

1. repeat read-only preflight and stop on drift;
2. publish the exact candidate image;
3. deploy database migration and app capability with both DB channels false;
4. verify `/health/ready`, `/admin`, and safe summary;
5. prompt locally once for the candidate key without echo;
6. submit it only to the protected admin rotation endpoint;
7. enable ordinary-login AI and run one hosted turn;
8. enable Demo AI and run one hosted turn;
9. prove the same safe fingerprint appears in both audit projections;
10. independently disable and re-enable both channels;
11. submit a known-invalid non-secret sentinel and prove the prior fingerprint/state remains authoritative;
12. write exactly one terminal receipt and never retry automatically.

The receipt contains hashes, safe states, request IDs, revision names, and fingerprint prefixes only.

```python
STATES = (
    "readonly_revalidation",
    "publish_candidate_image",
    "deploy_admin_ai_capability",
    "verify_ai_disabled_candidate",
    "rotate_key_through_admin",
    "verify_operator_ai",
    "verify_demo_ai",
    "verify_independent_channel_switches",
    "verify_invalid_candidate_rollback",
)

def run_once(package, operations):
    receipt = AttemptReceipt(package_sha256=sha256_json(package))
    try:
        for state in STATES:
            operations.run(state)
            receipt.complete(state)
    except Exception as error:
        receipt.fail(safe_code(error))
    finally:
        receipt.write_once(package["execution_contract"]["receipt_path"], mode=0o600)
    return receipt
```

- [ ] **Step 5: Run the complete local release gate**

Run: `python -m pytest -q`

Expected: all Python tests PASS.

Run: `npm test`

Expected: all frontend tests PASS.

Run: `python -m ruff check api src scripts tests alembic`

Expected: no Ruff violations.

Run: `git diff --check`

Expected: no whitespace errors.

- [ ] **Step 6: Commit Task 11**

```bash
git add tests/hosted/test_admin_ai_release_contract.py tests/hosted/verify_admin_ai_control.py scripts/create_admin_ai_release_package.py scripts/run_admin_ai_release.py docs/operations/AZURE_LAUNCH_RUNBOOK.md
git commit -m "feat: add one-shot admin AI hosted acceptance"
```

---

### Task 12: Review, Exact-Hash Build, Hosted Acceptance, and Evidence Closeout

**Files:**
- Create at execution time: `.tmp/LAUNCH_AUTHORIZATION_ADMIN_AI_<fresh-id>.json`
- Create at execution time: `.tmp/ADMIN_AI_RELEASE_RECEIPT_<fresh-id>.json`
- Create after success: `deliverables/closeout/admin-ai-hosted-acceptance.json`
- Modify after success: `release/current_authority.json`
- Modify after success: `../CURRENT_STATUS.md`
- Modify after success: `../CURRENT_HANDOFF.md`
- Modify after success: `../NEXT_AI_HANDOFF.md`
- Modify after success: `../docs/handoffs/AZURE_LAUNCH_HANDOFF_2026-08-15.md`

**Interfaces:**
- Consumes: reviewed Task 1–11 commits and the fresh release controller.
- Produces: hosted evidence or one terminal failure receipt; never a replayable partial package.

- [ ] **Step 1: Invoke the required completion-review skill and resolve findings**

Use `superpowers:requesting-code-review`. Address every confirmed correctness, security, and spec-coverage issue with a new failing test before changing implementation.

- [ ] **Step 2: Re-run the complete local release gate on the reviewed HEAD**

Run: `python -m pytest -q && npm test && python -m ruff check api src scripts tests alembic && git diff --check`

Expected: every command exits 0 on the same clean tracked tree.

- [ ] **Step 3: Build and inspect the exact linux/amd64 candidate image**

Run: `docker buildx build --platform linux/amd64 --load -t newcaostone-admin-ai:$(git rev-parse --short=12 HEAD) .`

Expected: build succeeds.

Run: `docker image inspect newcaostone-admin-ai:$(git rev-parse --short=12 HEAD) --format '{{.Os}}/{{.Architecture}} user={{.Config.User}} id={{.Id}}'`

Expected: `linux/amd64`, non-root user `bizpulse`, and a concrete image ID.

- [ ] **Step 4: Generate one fresh authority package after a read-only Azure observation**

Run the package generator documented by Task 11 with the exact reviewed HEAD, exact image digest, new observation timestamp, and a new output/receipt path. Confirm mode `0600` and record its SHA-256. Do not select any R19 or earlier package.

- [ ] **Step 5: Execute the package exactly once and complete hosted acceptance**

Run the controller once. Enter the OpenAI Platform key only into the controller-triggered secure local prompt. Do not place it in shell history, environment variables, files, chat, or receipts.

Expected success evidence:

- live revision is Healthy and `/health/ready` is ready;
- `/admin` is Operator protected and Demo denied;
- key rotation returns a safe fingerprint only;
- `/app` and `/demo` each complete a real AI turn using the same fingerprint;
- the two channel switches operate independently;
- invalid replacement leaves the prior fingerprint and flags unchanged;
- no secret appears in logs, responses, audit rows, or deliverables.

On any first failure, stop and preserve the terminal receipt. Do not regenerate or replay within the same attempt.

- [ ] **Step 6: Save sanitized evidence and update authority documents**

Write `deliverables/closeout/admin-ai-hosted-acceptance.json` with exact commit, image digest, revision, safe fingerprint prefix, control revision, Operator/Demo results, timestamps, and receipt hash. Update `release/current_authority.json`, `../CURRENT_STATUS.md`, `../CURRENT_HANDOFF.md`, `../NEXT_AI_HANDOFF.md`, and `../docs/handoffs/AZURE_LAUNCH_HANDOFF_2026-08-15.md` so local implementation, deployment, hosted verification, and Production status remain separate claims.

- [ ] **Step 7: Commit evidence only after successful hosted verification**

```bash
git add deliverables/closeout/admin-ai-hosted-acceptance.json release/current_authority.json ../CURRENT_STATUS.md ../CURRENT_HANDOFF.md ../NEXT_AI_HANDOFF.md ../docs/handoffs/AZURE_LAUNCH_HANDOFF_2026-08-15.md
git commit -m "docs: record hosted admin AI acceptance"
```

If hosted verification failed, do not create a success deliverable or success commit; retain only the owner-only terminal receipt outside tracked evidence.
