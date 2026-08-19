# BizPulse AI Enablement and Prompt Preset Restoration Design

**Date:** 2026-08-17
**Status:** local implementation complete; final verification and exact package pending
**Batch base:** `afd3a2f0a9311aafaca35ad4a412c911aadf1e32`
**Branch:** `codex/ai-enable-preset-buttons`
**Worktree:** `/Users/maxli/Desktop/NEWCaostone/.worktrees/ai-enable-preset-buttons`

## 1. Decision and non-authority boundary

This batch restores the six server-owned Ask BizPulse prompt preset buttons,
closes their audit-integrity gap, and prepares a separately hash-approved AI
enablement release. It may implement, test, build and inspect local artifacts.
It grants no authority to read a real OpenAI key, use Keychain, publish an
image, mutate Azure, call a real provider, spend provider budget, access the
public Demo URL, push, open a PR, or run CI.

The user selected D3 HEAD `afd3a2f` as the new base. The existing D3 branch,
package, receipt path and observation path are immutable and out of scope. No
D1, D2, D3, V4, V5, V6 or older two-stage package may be replayed or adapted.

## 2. Read-only preflight result

| Area | State | Evidence and consequence |
| --- | --- | --- |
| Git base | confirmed | New clean branch/worktree starts exactly at `afd3a2f`; base tree is `679e8f26f1b537be2573981951eabc722bdb4a27`. |
| Authority documents | conflict resolved | The implementation-worktree documents are stale. Root/D2/D3 records plus the user's explicit base choice control this batch. `check_authority_contract.py --mode docs` passes, but `release/current_authority.json` is expired and must not be presented as current Azure proof. |
| D3 | preserved | D3 package exists mode `0600`, SHA-256 `2ca7c7aa0d133b94607569af437dcf0f6a2b7aa44afc475c332dfe16e0ac8687`; its receipt and observation are absent. This batch never invokes or changes it. |
| Azure app | read-only observed | `newcaostone-demo-app` is provisioned in Central US, Single revision mode, with `newcaostone-demo-app--713a6984d4a0` latest/ready and 100% latest traffic. Control-plane health is not Hosted acceptance. |
| Azure image | read-only observed | Active image is `sellernorthbpacr.azurecr.io/bizpulse@sha256:713a6984d4a034a0be73b46c10a897aeb236c201325ff8a88ba524fc6c10295c`; min/max replicas are `1/1`. |
| Azure AI state | read-only observed | `BIZPULSE_AI_CHAT_ENABLED=false`; no `OPENAI_API_KEY` env reference, no `OPENAI_BASE_URL`, and no `openai-api-key` secret name. Existing non-AI secret names remain unchanged. |
| Azure identity | read-only observed | The app uses the existing user-assigned `newcaostone-demo-registry` identity. No Key Vault data-plane authority is established for this app. |
| Prompt Catalog | confirmed | The exact six bilingual/versioned server templates already exist in `src/ai/prompt_catalog.py`; schema, service and frontend carry most audit and interaction fields. |
| Button regression | diagnosed | Disabled `GET /api/v1/ai-chat/turns` returns `recommended_questions=()`, so the frontend has nothing to render. The old no-AI design explicitly hid questions; 5A now supersedes that behavior. |
| Preset forgery gap | diagnosed | The server checks id/locale/version/SHA but currently accepts changed arbitrary text with those fields. The frontend also keeps preset metadata after editing. Both layers must fail closed. |
| Existing Bicep secret path | rejected for this batch | Both current `openaiApiKey` declarations use `@secure()`, but the full application deployment also requires PostgreSQL, Operator and session credentials. Reusing those credentials violates the user's boundary. The AI key moves to a separate task-owned Key Vault deployment with no non-AI credential inputs. |
| Provider endpoint | conflict | Bicep currently accepts and injects arbitrary `openAiBaseUrl`. That violates the approved official-provider-only boundary. |
| Operator/account task | unknown but non-blocking locally | No verified password-change artifact exists in this selected branch. This batch does not inspect, reset, reuse or modify Operator, Keychain, PostgreSQL or session credentials. |
| Hosted acceptance | pending | No public URL request was made. Existing health/browser/capacity/expiry/restart/rollback acceptance remains distinct from this local batch. |

## 3. Fixed provider and budget contract

The server, Bicep, tests and future package must agree on exactly:

```text
provider = OpenAI Platform Responses API
model = gpt-5.4-nano-2026-03-17
reasoning_effort = low
daily_provider_attempts = 120
monthly_total_tokens = 150000
session_attempts_per_minute = 3
global_attempts_per_minute = 20
max_concurrent_turns = 15
max_output_tokens = 2800
provider_timeout_seconds = 30
provider_retries = 0
tools = []
```

The official OpenAI model page was checked on 2026-08-17 and still lists the
fixed snapshot with Responses and low reasoning support. This is an OpenAI
Platform configuration. An Azure OpenAI key, endpoint or deployment name is a
different product contract and is rejected rather than translated.

`OPENAI_BASE_URL` is permitted only when it is absent or exactly the official
`https://api.openai.com/v1` URL. Deployment does not inject the variable at
all. Unknown, proxy, loopback and alternate endpoints fail before SDK client
construction.

## 4. Prompt preset architecture

### 4.1 One server-owned catalog in both AI modes

`ApiContainer` owns one `QueryCatalog` even when `ai_chat_service` is absent.
The disabled authenticated list route projects recommended questions from that
catalog while retaining `availability=unavailable`. Write endpoints still
return `503 AI_CHAT_UNAVAILABLE`, construct no SDK client and make no provider
request.

The six IDs and localized labels remain:

1. `monthly_sales_report` — Generate this month's sales report / 生成本月销售报告
2. `profit_changes` — Explain profit changes / 分析利润变化原因
3. `inventory_risks` — Find inventory risks / 查找库存风险
4. `advertising_performance` — Summarize advertising performance / 总结广告表现
5. `forecast_30_days` — Summarize the 30-day forecast / 总结未来 30 天预测
6. `next_actions` — Prioritize next actions / 给出下一步行动建议

No Product Opportunity, web search, upload, import, calculation trigger,
database write or simulated external action is added.

### 4.2 Applicability and isolation

The route first authenticates and resolves the exact workspace, dataset,
store tuple, period and currency. Catalog projection is then filtered against
the principal's available pinned forecast/profit authorities. The frontend
applies the current pinned-context filter. Store and period are never accepted
from a preset template; a submit carries only selected store IDs and the server
re-resolves them against the dataset catalog. All six remain applicable in the
normal complete synthetic release, satisfying the bilingual six-button gate.

### 4.3 Fill, focus and replacement

A preset click only dispatches a local state transition. It fills the current
locale's server-projected template, selects its audit metadata, focuses the
textarea and places the caret at the end. It never calls `effects.submit`.

If a non-empty draft exists, the draft is preserved and an accessible modal
alert dialog offers Replace or Keep editing. Focus starts on Replace, Tab/Shift
Tab remain within the two actions, Escape is equivalent to Keep editing, and
the textarea regains focus after either decision.

Native buttons and textarea expose their disabled state. The unavailable notice
uses a polite status region. The existing `820px` breakpoint keeps presets in a
single column on mobile.

### 4.4 Audit integrity

The official-preset invariant is:

```text
question == catalog.templates[locale]
AND preset id, locale, version and SHA-256 all match the same catalog record
```

If the user changes even one character after filling a preset, the frontend
clears selected preset metadata and submits ordinary free text. Independently,
the backend rejects any request that supplies preset metadata with non-exact
template text. This prevents a modified client from disguising arbitrary text
as an official preset.

## 5. Secret architecture decision

### 5.1 Option comparison

| Dimension | A. Container Apps Secret | B. Task-owned Key Vault runtime read |
| --- | --- | --- |
| Git/package/browser | No value is stored when the deploy process uses a secure Bicep parameter and secretRef only. | Also no value is stored if implemented correctly. |
| argv/process list | Value stays out of argv when read by the local protected process and passed through environment-backed secure parameters. | Bootstrap still needs a protected write into Key Vault; identity/resource IDs appear but the value must remain off argv. |
| Runtime exposure | App receives `OPENAI_API_KEY=secretRef:openai-api-key`; frontend never receives it. | App receives only a vault URL, secret name and UAMI client ID, then resolves the value in process only when a provider stage begins. |
| Rotation/revocation | New secret value plus new revision, traffic verification, then old revision deactivation/removal. Provider revocation remains separate. | Better centralized version/audit model, but needs vault permissions and reference/version lifecycle. |
| Least privilege | The current full deployment must reuse unrelated PostgreSQL, Operator and session credentials. | A dedicated UAMI receives `Key Vault Secrets User` on a dedicated one-secret vault. Existing identities and credentials are untouched. |
| Recovery/tool support | Azure CLI `containerapp secret set` first reads existing secret values and performs a full update, violating the no-touch boundary. | A separate Bicep deployment creates the vault/UAMI/role/secret without any existing application secret values. The application revision update carries only non-secret configuration. |
| Demo fit | Fewer resources, but incompatible with the explicit non-reuse requirement. | Slightly more code and Azure objects, but isolates the AI credential and avoids all existing credentials. |

**Decision:** use Option B with an Azure Key Vault public endpoint and Azure
RBAC. The user selected this lower-cost, faster variant and accepted its wider
network exposure. The vault still requires TLS and Entra authentication for
every data-plane request. Private endpoint, firewall allowlisting and Demo
passcode admission are explicitly deferred; none is silently implied.

The task creates a new Standard-tier vault whose exact globally unique name is
bound into the final package. It has Azure RBAC enabled, soft delete and purge
protection enabled, `publicNetworkAccess=Enabled`, and contains only the exact
`openai-api-key` secret. It is not the visible existing `sellernorthbp-kv` and
does not read, modify, attach or inherit from any existing vault.

A new package-bound UAMI is attached alongside, never instead of, the existing
registry identity. It receives only `Key Vault Secrets User` on this dedicated
one-secret vault. The vault emits audit diagnostics to the existing declared
Log Analytics workspace without logging secret values. No browser, frontend
bundle, API response or Container Apps configuration contains the key.

### 5.2 Protected local input and split deployment

The assistant never receives the key. After exact package approval, a
user-operated local launcher uses hidden input. The runner never logs, hashes,
validates or echoes it. The fixed paid-qualification child alone receives
`BIZPULSE_DEPLOY_OPENAI_API_KEY`. The separate one-secret Bicep deployment
receives an ARM parameter document through child stdin; its `openAiApiKey`
parameter is decorated `@secure()` and therefore is not stored in deployment
history or command output. The value never appears in argv or a parameter file.
Each child scope is cleared immediately after exit, and the parent drops its
in-memory reference after the last authorized write.

The base AI Bicep entry point accepts no secret at all and creates only the new
vault, UAMI, vault-scoped read role and diagnostics. The secret-write entry
point references only that vault and contains exactly one
`Microsoft.KeyVault/vaults/secrets` resource. Neither accepts a PostgreSQL
password, Operator hash, session pepper, Blob credential or existing Container
Apps secret. ARM does not return the Key Vault secret value. The package and
receipt record only resource IDs and boolean presence/readiness projections.

### 5.3 Runtime provider

Cloud AI requires exactly three non-secret settings: the task-owned HTTPS vault
origin, the exact secret name `openai-api-key`, and the dedicated UAMI client
ID. Unknown vault hosts, paths, query strings, secret names or malformed client
IDs fail closed. Local tests continue to inject a fake OpenAI client and never
construct Azure credentials.

`ManagedIdentityCredential(client_id=...)` and `SecretClient` are constructed
without fetching the secret. The first real provider stage performs a bounded
Key Vault read with a 5-second connection/read timeout, SDK retries disabled,
logging disabled and a 60-second in-process cache. Expired cache entries are
cleared before refresh. A refresh failure has no stale-secret fallback and is
translated to the existing safe AI-unavailable response with no Key Vault or
SDK diagnostics. The credential, client and cached value are cleared/closed on
application shutdown.

Budget reservation remains before the provider stage, so a Key Vault failure
is conservatively recorded as a failed AI attempt and may consume the existing
reserved-token allowance. It makes zero OpenAI requests and cannot increase
paid spend; the conservative charge prevents repeated outage probing from
bypassing the approved daily/monthly safety boundary.

## 6. Revision, traffic and rollback design

The code/UI/Bicep fixes require a new immutable linux/amd64 image. Local image
identity, source HEAD/tree and image-input hash are proved before packaging.
Registry publication remains an external action inside the later exact package.

Execution order after separate approval is fixed:

1. Verify package hash/mode/expiry, clean committed HEAD/tree, target and local
   image labels, fixed price/cap evidence and receipt absence before credentials
   or external commands. Reserve a durable owner-only `started` receipt before
   the first mutation; its presence permanently fences replay.
2. Re-read the exact app/revision/traffic/image/AI-disabled projection, existing
   identity set and exact ACR authority. Confirm the package-bound vault/UAMI
   names are absent and the existing vault remains out of scope. Any drift
   stops with zero mutation.
3. Publish and verify only the package-bound immutable image.
4. Deploy the new image as an AI-disabled revision with no OpenAI secret or
   reference; route 100% only after strict health and non-AI browser gates pass.
   This exact revision becomes the rollback revision.
5. Create only the package-bound vault, UAMI, vault-scope read role, diagnostics
   and non-secret runtime bindings. Rehearse budget exhaustion without reading
   a Key Vault secret or making a provider request, then restore and verify the
   exact AI-disabled revision and remove the AI identity binding. Record zero
   provider attempts, zero synchronized ledger rows and a fresh ready-revision
   readback.
6. Store a generated invalid placeholder as `openai-api-key`, attach the
   dedicated UAMI, and rehearse provider authentication failure only against
   the official OpenAI endpoint. Then, in the same atomic rehearsal state,
   restore the exact AI-disabled revision and remove the UAMI binding. The
   placeholder remains inert because soft-delete plus purge protection would
   prevent immediate same-name recreation. The safe provider attempt must show
   one synchronized reservation and `provider_auth_rejected`; a Key Vault lookup
   failure is a different safe code and fails the rehearsal. Retry count is zero.
7. Run the fixed 12-case paid model qualification only after all prior evidence
   pass and the package's paid cap remains available.
8. Overwrite the placeholder with a new real secret version, attach the
   dedicated UAMI, set only the three non-secret Key Vault bindings, enable AI
   and create a distinct revision. Container Apps has no OpenAI secret or
   `OPENAI_API_KEY` environment variable. Do not assume a vault update restarts
   code or clears its short cache.
9. Verify the new revision before sending traffic, then route 100% and run one
   monthly-report hosted smoke with manual Send semantics through the public
   Azure Demo Viewer path, not the Operator or localhost path. Observe the Demo
   session/CSRF boundary, preset audit quartet, store/workspace scope and ledger.
10. Finalize the reserved receipt and destroy the runner's in-memory key
    reference.

No canary split is used because the app is in Single revision mode and the Demo
has one replica. The AI-enabled revision is accepted only after the AI-disabled
candidate has passed. Provider and budget rehearsals always restore an
AI-disabled revision before propagating a failed assertion. A final enabled
revision verification or paid-smoke failure permits one additional emergency
AI-disable patch, removing the UAMI and all three runtime bindings. The dedicated
vault, UAMI, role and secret versions remain for audit/recovery; deleting the
protected secret would block same-name reuse. If a real value was written,
recovery overwrites the current version with a fresh invalid placeholder, and
suspected exposure additionally requires provider-side revocation.

## 7. Budget and stop conditions

The package uses a 24-hour expiry, deploy/provider retry limit zero and one
read-only retry only where the existing contract explicitly permits it. It
binds a maximum of 12 paid qualification calls plus one hosted paid smoke. The
cost caps are explicit decimal values in the package; the runner stops before
the first paid call if usage/cap evidence is missing or ambiguous.

Automatic stop conditions include target, tenant, subscription, resource,
identity, source SHA/tree, image, migration, traffic, AI flag, vault/UAMI/role,
secret name, model, endpoint, budget, receipt, expiry, account/scope, or rollback drift;
unknown provider outcome; any console/security leak; and any missing rollback
readiness evidence.

## 8. Evidence contract

Receipts contain only package/commit/tree/image/revision identifiers, boolean
secret-presence/ref projections, safe stage codes, call counts, token counts,
cost totals/caps and hashes of fixed case IDs/evidence structures. They never
contain a key, Authorization header, prompt/template text, user text, raw model
response, database credential, session value, customer data, stdout or stderr.

Evidence states remain separate:

- Local implemented
- Local verified
- Azure read-only observed
- Azure mutation accepted
- Hosted verified
- Paid AI qualified
- Production ready

The first three do not imply any later state. This remains a bounded synthetic
Demo and is not Production ready.

## 9. Local acceptance

TDD tests cover exact six-button EN/ZH projection, disabled visibility and zero
submit/provider calls, fill/focus/no-auto-send, replacement dialog behavior,
manual submit audit quartet, edit-to-free-text downgrade, backend tamper
rejection, server scope isolation, failure rendering, endpoint/config drift,
secure Bicep parameters, vault/UAMI/runtime-binding lifecycle and
package/runner sanitization. Tests also prove no existing credential or existing
Key Vault is accepted as an AI deployment input.

The final local browser acceptance uses a fake provider and no key. Screenshots
prove: six buttons are visible, click fills/focuses the textarea, and no turn is
created until Send is clicked. Local acceptance is followed by authority,
changed-path no-reuse, Bicep compilation/static, full release and secret scans.

The later hosted acceptance is intentionally stronger: it must prove the
public Azure `/demo` Viewer can perform the same explicit manual-send flow with
the real provider while all existing session, CSRF, workspace/store/dataset and
budget limits remain active. An Operator-only hosted result does not pass.

## 10. Explicitly deferred Demo passcode

A shared Demo admission passcode can later reduce casual viewer access and AI
abuse, but it does not secure the Key Vault public endpoint. Key Vault remains
protected by Entra authentication, the dedicated UAMI and least-privilege RBAC.
The passcode would be a separate server-verified admission control in front of
`POST /api/demo/sessions`, layered with the existing source/session/global and
AI budget limits. It is not part of this batch, no passcode is collected, and
the current Try Demo behavior is unchanged.
