# BizPulse Integrated Viewer, AI, and Anti-Drift Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不削弱 NEWCaostone 现有 Operator、Viewer、确定性分析、Action 与安全边界的前提下，完成 CAPTSONE 视觉语言迁移、三个月共享示例数据、Viewer 轻量动作模拟、Ask BizPulse 提示词与月报，并先建立可机器检查的“当前发布权威”，避免旧 SHA、镜像、迁移版本、AI 状态和测试结论再次进入活跃说明或发布命令。

**Architecture:** 先以 `release/current_authority.json`、不可变候选 attestation、文档漂移检查器和 changed-path 验证策略构成 anti-drift 控制面；产品面继续使用 FastAPI 模块化单体、PostgreSQL 权威状态、Azure Blob 版本化对象和原生 HTML/CSS/ES modules。所有 Viewer 共用一个已经预计算并发布的三个月版本；每个 Viewer 只保存有界 Chat 和 Action overlay。AI 只对服务器选出的有界确定性事实做解释，浏览器不接触 Key，也不能触发导入、全量重算或外部执行。

**Tech Stack:** Python 3.12; FastAPI 0.138.2; SQLAlchemy Core 2.0.51; Alembic 1.18.5; PostgreSQL 17; pandas 3.0.3; openpyxl 3.1.5; XlsxWriter 3.2.9; OpenAI Python SDK 2.52.0 Responses API; native browser ES modules; Node 24 built-in test runner; pytest 9.1.1; Ruff 0.15.20; existing Azure read-only/release tooling.

## Global Constraints

- 执行代码改动时使用从 `/Users/maxli/Desktop/NEWCaostone/.worktrees/implementation` 派生的新分支或工作树；开始前先运行 `git status --short`，若出现非本计划改动，保留并绕开，不覆盖。
- `DEPLOYED_RELEASE_SHA=537effe3036f77f83225beef12589bd447205a8b` 仅表示当前 Azure 镜像的已部署源代码，用于明确的发布兼容性或部署比较；禁止把它当作新功能起点、`git reset`/`checkout` 目标或 changed-path 默认基线。
- `DEVELOPMENT_START_SHA=3e4cc229245cf32a13623da23eaa9685e176a82b` 是本计划的本地开发起点。先从该提交派生工作，再精确引入 `handoff/integrated-viewer-ai-anti-drift-v1` 所绑定的设计/计划范围。计划中的 `verify_changed.py --base` 固定使用这个开发锚点；每批开始另行记录实际 `BATCH_BASE_SHA` 供冲突和审计使用。
- 产品权威设计是 `docs/superpowers/specs/2026-08-15-bizpulse-integrated-viewer-ai-experience-design.md`；发布身份拆分基础是 `bizpulse/docs/superpowers/specs/2026-08-15-observed-current-release-authority-design.md`。本计划获批前不执行 Task 1 功能改动。
- `/Users/maxli/Desktop/CAPTSONE` 及用户提供的七个表格只允许读取。最终应用和测试不得依赖 Desktop 绝对路径；可发布输入必须来自本仓库的确定性 generator、manifest 和 fixtures。
- 根工作区的 brainstorm 端口/token、编辑器 history、pip cache、测试 cache 与已消费上线包都不是源代码或计划输入；只可在确认无活跃进程、无唯一证据后精确清理。`NEXT_AI_HANDOFF.md` 是本轮纳入版本控制的当前入口。
- 已完成的 `observed_current_image_digest` 与 `rollback_image_digest` 分离是本计划的基础，不重新实现、不合并两个字段。前者是更新前的只读 Azure 观察；后者来自候选 attestation，保持不可变。
- `release/current_authority.json` 是“当前/下一步”说明的唯一机器权威；历史 attestation 继续不可变。历史值只能进入显式历史区，不得进入当前结论、下一步命令或可执行代码块。
- 每个实现任务遵循 RED → 最小实现 → GREEN → 一次本地提交。任务内只跑聚焦测试和 `verify_changed.py` 选出的检查；完整 PostgreSQL、全部前端、浏览器、exact-15、restart、rollback 与 release gate 只在 Task 14 的集中发布阶段执行。该阶段由现有两提交 attestation 协议要求的 detached-candidate 复验不属于可缓存的开发复用。
- changed-path 证据只可用于开发阶段复用，并绑定完整代码域 fingerprint；候选发布、attestation、部署或启动验收不得复用该证据，必须绑定完整候选 Git SHA 并重新运行完整 gate。
- Viewer 不出现上传、导入、映射、标准化、commit、重算、publish、正式 export 或 outcome 控件；也不显示“点击后才告知无权”的死按钮。Operator 保留这些现有能力和后端授权。
- Viewer 只读共享预计算版本；15 个并发 Viewer 不复制源文件、标准化数据或分析结果。Viewer Action 只做三个白名单 O(1) 估算，不能调用 AI、分析 worker 或数据库全量计算。
- BRL UI 固定两位小数；普通小数、比率、天数和评分最多两位；整数数量不显示小数。数据库、API、`Decimal`、导入、证据与 export 精度不改变。
- 英文和中文是两个完整 catalog；禁止永久拼接成 `English / 中文` 的正常 UI 文案。hash、版本 ID、错误 code、证据 alias 和 source value 不翻译。
- 用户可见界面移除 `Operator sign in`、`Course Demo`、`Synthetic Demo Data / 纯合成演示`、截图中的常驻 `v2`、`Period unavailable` 和孤立 `BRL` 胶囊。必要的数据边界仅低频显示 `Sample data / 示例数据`。
- OpenAI Key 只能由服务器 secret 注入。本计划不授权读取、创建、显示或轮换 Key，不授权真实 provider/付费调用、GitHub push、Azure/registry/DNS/secret 修改或部署。
- 当前 hosted AI 仍是 `disabled`；本地实现、fake-provider 测试、可达 URL、部署、Hosted verified、Azure Demo accepted 和 Production ready 必须分开记录，不得互相替代。
- AI Key/bootstrap 的相邻任务是独立依赖。开始 Task 9 前先核对 implementation 分支的 Git HEAD、迁移 head、AI 配置测试和相邻任务提交；若其结果已提交，就消费其服务器端 secret/availability 接口而不重复实现；若只有未提交重叠改动，就保留并暂停重叠文件。没有该结果时继续用现有 disabled seam 与 fake provider 完成本地实现，不读取或伪造 Key。
- Operator 用户名/密码、多账户、注册和密码轮换均不在本计划范围内。

---

## Authority and dependency map

```text
read-only Azure observation ──> release/current_authority.json <── candidate attestation
                                      │
                                      ├──> active status/handoff generated blocks
                                      ├──> authority_doc_drift / freshness checks
                                      └──> changed-path verification selection

fixed-seed generator ──> one canonical three-month release ──> shared Viewer reads
                                                        ├──> deterministic dashboards
                                                        ├──> Action simulation inputs
                                                        └──> bounded Ask BizPulse tools

server prompt catalog ──> editable browser draft ──> explicit Send
                                  │                    ├── exact template: fixed plan
                                  │                    └── edited text: whitelist planner
                                  └── no request, attempt, or token on preset click
```

Implementation order is intentional:

1. Tasks 1–3 stop current-fact drift and make verification scope deterministic.
2. Tasks 4–7 establish shared UI contracts, Product Theater, canonical data and Viewer/Operator capability separation.
3. Tasks 8–11 add Action Sandbox and Ask BizPulse behavior without adding heavy Viewer computation.
4. Task 12 completes the visual/copy migration across all feature pages.
5. Task 13 performs concentrated browser, capacity, restart and rollback acceptance.
6. Task 14 refreshes current authority, runs the one full release gate and creates the immutable local attestation.

## Target file map

```text
bizpulse/
  release/
    current_authority.json
    authority-document-policy.json
    verification-policy.json
    attestations/*.json
  scripts/
    release_authority.py
    refresh_current_authority.py
    check_authority_contract.py
    select_required_checks.py
    verify_changed.py
    verify_release.py
    create_release_manifest.py
  src/
    synthetic/{contracts.py,generator.py,release_profile.py,seed.py}
    actions/simulation.py
    ai/{contracts.py,prompt_catalog.py,query_catalog.py,query_executor.py}
    services/{public_release_service.py,profit_bridge_service.py,action_service.py,ai_chat_service.py}
    repositories/ai_chat.py
    db/schema.py
  api/
    routers/public_release.py
    v1/schemas/{actions.py,ai_chat.py}
    v1/routers/{actions.py,ai_chat.py}
  frontend/
    {welcome.html,login.html,index.html}
    assets/core/{formatters.mjs,product-theater.mjs}
    assets/product-theater/{overview.svg,profit-bridge.svg,inventory-forecast.svg,ask-bizpulse.svg}
    assets/features/workspace/public-view.mjs
    assets/features/action-inbox/simulation.mjs
    assets/features/ask-bizpulse/{state.mjs,effects.mjs,view-model.mjs,view.mjs}
    assets/i18n/catalog.mjs
  alembic/versions/0009_prompt_preset_audit.py
  tests/
    release/{test_authority_contract.py,test_select_required_checks.py,test_release_scripts.py}
    unit/ai/{test_prompt_catalog.py,test_query_catalog.py,test_query_executor.py}
    unit/test_synthetic_generator.py
    unit/actions/test_simulation.py
    frontend/{formatters.test.mjs,product-theater.test.mjs,copy-contract.test.mjs}
    acceptance/{test_browser_smoke.py,test_exact_15_sessions.py,test_restart_readback.py,test_rollback_compatibility.py}
```

## Task 1: Establish one current-release authority and fail-fast document drift checks

**Files:**

- Create: `bizpulse/release/current_authority.json`
- Create: `bizpulse/release/authority-document-policy.json`
- Create: `bizpulse/scripts/release_authority.py`
- Create: `bizpulse/scripts/refresh_current_authority.py`
- Create: `bizpulse/scripts/check_authority_contract.py`
- Create: `bizpulse/tests/release/test_authority_contract.py`
- Modify: `CURRENT_STATUS.md`
- Modify: `AUTHORIZATION_LEDGER.md`
- Modify: `docs/handoffs/CURRENT_HANDOFF.md`
- Modify: `docs/handoffs/NEXT_AI_BOOTSTRAP_2026-08-15.md`
- Modify: `docs/handoffs/AZURE_LAUNCH_HANDOFF_2026-08-15.md`

**Interfaces:**

- `load_current_authority(path: Path, *, now: datetime | None = None, require_fresh_observation: bool = False) -> CurrentAuthority`
- `refresh_current_authority(observation: Mapping[str, object], attestations: Path, *, observed_at: datetime, expires_at: datetime) -> dict[str, object]`
- `check_authority_documents(authority: CurrentAuthority, policy: Mapping[str, object], repository_root: Path) -> tuple[AuthorityViolation, ...]`
- `render_authority_blocks(authority: CurrentAuthority, policy: Mapping[str, object], repository_root: Path) -> tuple[Path, ...]` rewrites only marked current blocks and never touches history text.
- CLI failure example: `authority_doc_drift:CURRENT_STATUS.md:12:observed_deployment.candidate_git_sha:expected=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:actual=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb`.
- Freshness failure format: `authority_observation_stale:<observed_at>:<expires_at>`.
- `--mode docs` validates schema and document consistency without requiring a still-live cloud observation; `--mode release` additionally requires `now < expires_at`.

- [ ] **Step 1: Write the failing authority tests**

```python
def test_observed_image_and_attested_rollback_are_independent(tmp_path):
    payload = authority_payload(
        observed_image="sha256:" + "a" * 64,
        rollback_image="sha256:" + "b" * 64,
    )
    authority = load_current_authority(write_json(tmp_path, payload))
    assert authority.observed_deployment.image_digest.endswith("a" * 64)
    assert authority.attested_rollback.image_digest.endswith("b" * 64)


def test_active_old_sha_reports_exact_file_and_line(tmp_path):
    authority = load_current_authority(write_json(tmp_path, authority_payload()))
    status = tmp_path / "CURRENT_STATUS.md"
    status.write_text("## Current\nDeploy `" + "c" * 40 + "` next.\n")
    violations = check_authority_documents(
        authority,
        one_file_policy("CURRENT_STATUS.md"),
        tmp_path,
    )
    assert violations[0].render().startswith(
        "authority_doc_drift:CURRENT_STATUS.md:2:observed_deployment.candidate_git_sha:"
    )


def test_history_value_is_allowed_but_not_in_a_command_block(tmp_path):
    document = """<!-- authority:history:start -->
Historical candidate `cccccccccccccccccccccccccccccccccccccccc`.
<!-- authority:history:end -->
```sh
deploy cccccccccccccccccccccccccccccccccccccccc
```
"""
    assert check_text(document)[0].line == 5


def test_release_mode_rejects_an_expired_observation(tmp_path):
    path = write_json(tmp_path, authority_payload(expires_at="2026-08-15T17:00:00Z"))
    with pytest.raises(AuthorityInvalid, match="authority_observation_stale"):
        load_current_authority(
            path,
            now=datetime(2026, 8, 15, 17, 0, 1, tzinfo=UTC),
            require_fresh_observation=True,
        )
```

- [ ] **Step 2: Run RED**

Run:

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
.venv/bin/pytest tests/release/test_authority_contract.py -q
```

Expected: collection fails because `scripts.release_authority` and the authority files do not exist.

- [ ] **Step 3: Implement the exact authority schema and local refresh seam**

`current_authority.json` uses this shape; refresh code validates every digest/SHA and writes keys in sorted order:

```json
{
  "attested_rollback": {
    "candidate_attestation_path": "release/attestations/7f548862b67761ea28776e4a2d749b03beb8b1d1.json",
    "git_sha": "3e933d083b3ab4dba36d8053f56ecf2d68d31f1e",
    "image_digest": "sha256:95088291d0d9402d3b580b3fde5afce816bcc5281d1281be088cb1cbe713e1c7"
  },
  "development": {
    "ai_capability_state": "implemented",
    "repository_migration_head": "0008_ai_budget_ledger"
  },
  "freshness": {
    "evidence_kind": "sanitized_azure_readback",
    "evidence_sha256": "69e53aecd6659df38db57c8090f8adf1363263c9d356b47c8a857f199a93f885",
    "expires_at": "2026-08-16T00:00:00Z",
    "observed_at": "2026-08-15T00:00:00Z"
  },
  "observed_deployment": {
    "ai_runtime_state": "disabled",
    "attestation_git_sha": "cda718a0869bc8bb815ebe632e728c266f588d39",
    "candidate_git_sha": "3e933d083b3ab4dba36d8053f56ecf2d68d31f1e",
    "database_migration_head": "0008_ai_budget_ledger",
    "image_digest": "sha256:95088291d0d9402d3b580b3fde5afce816bcc5281d1281be088cb1cbe713e1c7",
    "revision": "newcaostone-demo-app--95088291d0d9"
  },
  "prepared_candidate": null,
  "schema_version": "bizpulse.current-authority.v1"
}
```

The checked-in initial values must be produced from the latest already-sanitized readback and matching attestation, not copied from a lower prose section. `refresh_current_authority.py` accepts local JSON input and never invokes Azure, prints secrets, or changes external state. A future read-only Azure observation is first saved as a sanitized projection, then passed to the same command. `--repository-only` is a separate local mode that updates the Alembic head and implemented AI capability without changing observed deployment, rollback or freshness fields.

- [ ] **Step 4: Implement generated active blocks and explicit history fences**

Every configured current document receives exactly one generated block:

```markdown
<!-- authority:current:start -->
Current deployed candidate, image, migration and AI state are generated from
`bizpulse/release/current_authority.json`.
<!-- authority:current:end -->
```

Old evidence stays recoverable only inside:

```markdown
<!-- authority:history:start -->
Historical observations and consumed packages are retained here for audit.
<!-- authority:history:end -->
```

The checker scans current/active/next/deployment/rollback headings and all command fences. An old value inside a history fence is allowed only as prose; any command containing it still fails. Normalize the currently contradictory lower `2173222`/`cb77be5`/`sha256:78e9e62cbc5182f7d049475df977aa641296361a1d953fb1a9a63e970a91a878` sections so they cannot be interpreted as current instructions.

- [ ] **Step 5: Run GREEN and the real document check**

Run:

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
.venv/bin/pytest tests/release/test_authority_contract.py -q
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation
bizpulse/.venv/bin/python bizpulse/scripts/check_authority_contract.py --mode docs
```

Expected: tests pass and CLI prints `authority_contract=ok`.

- [ ] **Step 6: Commit Task 1**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation
git add CURRENT_STATUS.md AUTHORIZATION_LEDGER.md docs/handoffs/CURRENT_HANDOFF.md docs/handoffs/NEXT_AI_BOOTSTRAP_2026-08-15.md docs/handoffs/AZURE_LAUNCH_HANDOFF_2026-08-15.md bizpulse/release/current_authority.json bizpulse/release/authority-document-policy.json bizpulse/scripts/release_authority.py bizpulse/scripts/refresh_current_authority.py bizpulse/scripts/check_authority_contract.py bizpulse/tests/release/test_authority_contract.py
git commit -m 'feat: establish current release authority contract'
```

## Task 2: Select tests from changed paths and bind reusable development evidence to domain fingerprints

**Files:**

- Create: `bizpulse/release/verification-policy.json`
- Create: `bizpulse/scripts/select_required_checks.py`
- Create: `bizpulse/scripts/verify_changed.py`
- Create: `bizpulse/tests/release/test_select_required_checks.py`
- Modify: `bizpulse/.gitignore`

**Interfaces:**

- `select_required_checks(paths: Iterable[str], policy: VerificationPolicy) -> tuple[Check, ...]`
- `domain_fingerprint(repository_root: Path, domain: DomainPolicy) -> str`
- `verify_changed.py --base 3e4cc229245cf32a13623da23eaa9685e176a82b [--no-reuse]` executes argv arrays without `shell=True` and writes ignored development evidence under `.artifacts/verification/`.
- A fingerprint is SHA-256 over every current file in the selected domain as sorted `relative_path + NUL + file_sha256`; it is not merely the changed-file list or whole repository Git SHA.

- [ ] **Step 1: Write the failing selector/fingerprint tests**

```python
@pytest.mark.parametrize(
    ("paths", "names"),
    [
        (("CURRENT_STATUS.md",), ("authority_contract",)),
        (("bizpulse/frontend/assets/views.mjs",), ("frontend", "browser_local")),
        (("bizpulse/src/ai/prompt_catalog.py",), ("ai_focused", "frontend", "browser_local")),
        (("bizpulse/infra/main.bicep",), ("ai_infra_boundary", "release_static")),
        (("bizpulse/src/synthetic/generator.py",), ("synthetic", "postgres_seed", "browser_local")),
        (("bizpulse/alembic/versions/0009_prompt_preset_audit.py",), ("migration", "restart", "rollback")),
        (("bizpulse/release/attestations/" + "a" * 40 + ".json",), ("full_release_gate",)),
    ],
)
def test_policy_selects_required_checks(paths, names):
    assert tuple(item.name for item in select_required_checks(paths, POLICY)) == names


def test_domain_fingerprint_changes_for_an_unchanged_path_in_same_domain(tmp_path):
    write_domain(tmp_path, {"a.py": "one", "b.py": "two"})
    first = domain_fingerprint(tmp_path, python_domain())
    (tmp_path / "b.py").write_text("changed")
    assert domain_fingerprint(tmp_path, python_domain()) != first


def test_release_evidence_never_reuses_a_domain_cache():
    assert POLICY.check("full_release_gate").reuse == "never"
```

- [ ] **Step 2: Run RED**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
.venv/bin/pytest tests/release/test_select_required_checks.py -q
```

Expected: import failure because the selector and policy do not exist.

- [ ] **Step 3: Implement the declarative path policy**

Use exact argv arrays in `verification-policy.json`; no command string is passed through a shell:

```json
{
  "schema_version": "bizpulse.verification-policy.v1",
  "checks": {
    "authority_contract": [".venv/bin/python", "scripts/check_authority_contract.py", "--mode", "docs"],
    "frontend": ["npm", "test"],
    "ai_focused": [".venv/bin/pytest", "tests/unit/ai", "tests/services/test_ai_chat_service.py", "tests/security/test_ai_chat_boundary.py", "-q"],
    "ai_infra_boundary": [".venv/bin/pytest", "tests/infra/test_bicep_contract.py", "tests/services/test_ai_chat_container.py", "tests/security/test_ai_chat_boundary.py", "-q"],
    "release_static": [".venv/bin/pytest", "tests/release/test_container_contract.py", "tests/release/test_release_scripts.py", "-q"],
    "synthetic": [".venv/bin/pytest", "tests/unit/test_synthetic_generator.py", "-q"],
    "postgres_seed": [".venv/bin/python", "scripts/test_postgres.py", "tests/integration/test_synthetic_seed.py", "-q"],
    "migration": [".venv/bin/python", "scripts/test_postgres.py", "tests/postgres/test_migration_chain.py", "tests/postgres/test_0009_prompt_preset_audit.py", "-q"],
    "browser_local": [".venv/bin/python", "scripts/test_postgres.py", "tests/acceptance/test_browser_smoke.py", "-q"],
    "restart": [".venv/bin/python", "scripts/test_postgres.py", "tests/acceptance/test_restart_readback.py", "-q"],
    "rollback": [".venv/bin/python", "scripts/test_postgres.py", "tests/acceptance/test_rollback_compatibility.py", "-q"]
  }
}
```

The policy also maps domains to globs and ordered check names. Documentation-only edits run only the authority contract. Candidate/attestation/launch-package paths select `full_release_gate`, which `verify_changed.py` refuses to cache and delegates to the final release procedure.

- [ ] **Step 4: Implement cache safety and failure behavior**

```python
def can_reuse(evidence: Mapping[str, object], *, check: Check, fingerprint: str) -> bool:
    return (
        check.reuse == "development_only"
        and evidence.get("schema_version") == "bizpulse.development-evidence.v1"
        and evidence.get("check") == check.name
        and evidence.get("domain_fingerprint") == fingerprint
        and evidence.get("passed") is True
    )
```

Every evidence file records check name, argv, domain fingerprint, start/end time and exit code. Never store environment values, output containing secrets, cookies or credentials. A missing policy match fails closed, for example `verification_policy_unmapped_path:bizpulse/src/new_module.py`.

- [ ] **Step 5: Run GREEN and select checks for the current task**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
.venv/bin/pytest tests/release/test_select_required_checks.py -q
.venv/bin/python scripts/verify_changed.py --base 3e4cc229245cf32a13623da23eaa9685e176a82b --no-reuse
```

Expected: tests pass; selected checks complete green; output lists each check as `run`, never as release evidence.

- [ ] **Step 6: Commit Task 2**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation
git add bizpulse/.gitignore bizpulse/release/verification-policy.json bizpulse/scripts/select_required_checks.py bizpulse/scripts/verify_changed.py bizpulse/tests/release/test_select_required_checks.py
git commit -m 'feat: select verification by code domain'
```

## Task 3: Remove mutable release literals and bind final gates to immutable attestations

**Files:**

- Modify: `bizpulse/scripts/verify_release.py`
- Modify: `bizpulse/scripts/create_release_manifest.py`
- Modify: `bizpulse/tests/release/test_release_scripts.py`
- Modify: `bizpulse/tests/release/test_release_manifest.py`
- Modify: `bizpulse/tests/hosted/test_verify_azure_demo.py`
- Modify: `bizpulse/tests/acceptance/test_rollback_compatibility.py`

**Interfaces:**

- Development/static checks derive repository migration head from Alembic and observed runtime facts from `current_authority.json`.
- Creating a candidate requires a fresh current observation and copies the exact rollback identity into the new immutable candidate attestation.
- `--verify-attestation` replays the values committed in that attestation; later changes to `current_authority.json` cannot rewrite or invalidate historical proof.
- Remove module constants `EXPECTED_MIGRATION_HEAD` and `VERIFIED_ROLLBACK_SHA` and all tests importing them.

- [ ] **Step 1: Write failing release-authority tests**

```python
def test_candidate_manifest_captures_fresh_current_as_immutable_rollback(tmp_path):
    authority = authority_file(tmp_path, observed_sha="a" * 40, fresh=True)
    manifest = create_manifest_for_test(current_authority_path=authority)
    assert manifest["rollback_compatible_prior_sha"] == "a" * 40
    assert manifest["migration_head"] == migration_head()


def test_attestation_verification_uses_committed_rollback_after_current_changes(tmp_path):
    manifest = attestation_payload(rollback_sha="a" * 40)
    authority_file(tmp_path, observed_sha="b" * 40, fresh=True)
    assert attested_rollback_sha(manifest) == "a" * 40


def test_release_modules_have_no_mutable_identity_constants():
    source = (PROJECT_ROOT / "scripts/verify_release.py").read_text()
    assert "EXPECTED_MIGRATION_HEAD" not in source
    assert "VERIFIED_ROLLBACK_SHA" not in source
```

- [ ] **Step 2: Run RED**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
.venv/bin/pytest tests/release/test_release_scripts.py tests/release/test_release_manifest.py -q
```

Expected: new assertions fail because the two release identity constants are still hardcoded and imported.

- [ ] **Step 3: Refactor release creation and verification**

`create_release_manifest.py` loads a fresh authority only while creating a new candidate:

```python
authority = load_current_authority(
    PROJECT_ROOT / "release/current_authority.json",
    require_fresh_observation=True,
)
rollback_sha = authority.observed_deployment.candidate_git_sha
rollback_digest = authority.observed_deployment.image_digest
candidate_migration_head = migration_head()
if candidate_migration_head != authority.development.repository_migration_head:
    raise ReleaseVerificationError("repository_migration_authority_drift")
```

It writes `rollback_sha`, `rollback_digest`, `candidate_migration_head`, current-authority evidence hash and generation time into the candidate attestation. The verifier reads those committed fields, checks rollback ancestry and additive migration compatibility, and never substitutes current prose or a newer authority file. The acceptance rollback test receives its SHA/digest from the attestation fixture through pytest parameters, not a source literal.

- [ ] **Step 4: Put authority lint at the front of every release gate**

The first static release check is:

```python
_run_gate(
    "authority_contract",
    [sys.executable, "scripts/check_authority_contract.py", "--mode", "release"],
)
```

If the observation is stale or docs drift, stop before PostgreSQL, Node, browser, image, registry or Azure work. The final candidate path still runs the full gate even when all development-domain fingerprints are unchanged.

- [ ] **Step 5: Run GREEN**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
.venv/bin/pytest tests/release/test_release_scripts.py tests/release/test_release_manifest.py tests/hosted/test_verify_azure_demo.py tests/acceptance/test_rollback_compatibility.py -q
.venv/bin/python scripts/check_authority_contract.py --mode docs
```

Expected: all focused tests pass and no release identity is imported from a mutable module constant.

- [ ] **Step 6: Commit Task 3**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation
git add bizpulse/scripts/verify_release.py bizpulse/scripts/create_release_manifest.py bizpulse/tests/release/test_release_scripts.py bizpulse/tests/release/test_release_manifest.py bizpulse/tests/hosted/test_verify_azure_demo.py bizpulse/tests/acceptance/test_rollback_compatibility.py
git commit -m 'refactor: bind release gates to authority records'
```

## Task 4: Create shared localization and number-display contracts

**Files:**

- Create: `bizpulse/frontend/assets/core/formatters.mjs`
- Create: `bizpulse/tests/frontend/formatters.test.mjs`
- Create: `bizpulse/tests/frontend/i18n.test.mjs`
- Modify: `bizpulse/frontend/assets/i18n/catalog.mjs`
- Modify: `bizpulse/frontend/assets/app.mjs`
- Modify: `bizpulse/frontend/assets/welcome.mjs`
- Modify: `bizpulse/frontend/assets/login.mjs`

**Interfaces:**

- `t(language: "en" | "zh", key: string, parameters?: object) -> string`; missing locale/key throws `I18N_KEY_MISSING` in tests and returns a safe localized fallback only at the render boundary.
- `formatBrl(value, language) -> string` always displays exactly two decimals.
- `formatDecimal(value, language)`, `formatDays(value, language)` and `formatScore(value, language)` display at most two decimals.
- `formatInteger(value, language)` displays no decimal places.
- `formatPercentRatio(value, language)` accepts a ratio such as `0.12345` and displays `12.35%`.
- All formatters return `—` for `null`, `undefined`, non-finite input or a value that cannot be parsed; they never mutate raw API objects.

- [ ] **Step 1: Write failing formatter and catalog-completeness tests**

```javascript
test("display formatters round only at the UI boundary", () => {
  assert.equal(formatBrl("1234.567", "en"), "R$1,234.57");
  assert.equal(formatDecimal("8.500", "en"), "8.5");
  assert.equal(formatDays("12.345", "en"), "12.35 days");
  assert.equal(formatInteger("42.9", "en"), "43");
  assert.equal(formatPercentRatio("0.12345", "en"), "12.35%");
  assert.equal(formatBrl(null, "en"), "—");
});

test("English and Chinese catalogs have identical complete key sets", () => {
  assert.deepEqual(
    Object.keys(catalog.en).sort(),
    Object.keys(catalog.zh).sort(),
  );
  for (const locale of ["en", "zh"]) {
    for (const value of Object.values(catalog[locale])) {
      assert.ok(value.trim().length > 0);
    }
  }
});
```

- [ ] **Step 2: Run RED**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
node --test tests/frontend/formatters.test.mjs tests/frontend/i18n.test.mjs
```

Expected: import failure because the shared formatter and complete catalog APIs do not exist.

- [ ] **Step 3: Implement pure display formatters**

```javascript
const localeByLanguage = Object.freeze({ en: "en-US", zh: "zh-CN" });

export function formatBrl(value, language) {
  const number = finiteNumber(value);
  if (number === null) return "—";
  const parts = new Intl.NumberFormat(localeByLanguage[language], {
    style: "currency",
    currency: "BRL",
    currencyDisplay: "narrowSymbol",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).formatToParts(number);
  return parts.map(({ value: part }) => part).join("").replaceAll("\u00a0", "");
}
```

Keep parsing and formatting inside this module. Do not change API `Decimal` serialization, calculation modules, evidence values or XLSX exports.

- [ ] **Step 4: Implement full catalog access and persist only the language choice**

The catalog contains separate complete strings for public, login, shell, every feature, errors, chart summaries, presets and accessibility labels. `localStorage` may store only `bp_language`; it must not store session, Chat, action, credential, release or business data.

- [ ] **Step 5: Run GREEN and changed-path verification**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
node --test tests/frontend/formatters.test.mjs tests/frontend/i18n.test.mjs tests/frontend/shell.test.mjs tests/frontend/login.test.mjs
.venv/bin/python scripts/verify_changed.py --base 3e4cc229245cf32a13623da23eaa9685e176a82b
```

Expected: all selected tests pass; output formatting is display-only and catalog keys are symmetrical.

- [ ] **Step 6: Commit Task 4**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation
git add bizpulse/frontend/assets/core/formatters.mjs bizpulse/frontend/assets/i18n/catalog.mjs bizpulse/frontend/assets/app.mjs bizpulse/frontend/assets/welcome.mjs bizpulse/frontend/assets/login.mjs bizpulse/tests/frontend/formatters.test.mjs bizpulse/tests/frontend/i18n.test.mjs
git commit -m 'feat: centralize UI locale and number contracts'
```

## Task 5: Build the shared four-slide Product Theater for welcome and sign-in

**Files:**

- Create: `bizpulse/frontend/assets/core/product-theater.mjs`
- Create: `bizpulse/frontend/assets/product-theater/overview.svg`
- Create: `bizpulse/frontend/assets/product-theater/profit-bridge.svg`
- Create: `bizpulse/frontend/assets/product-theater/inventory-forecast.svg`
- Create: `bizpulse/frontend/assets/product-theater/ask-bizpulse.svg`
- Create: `bizpulse/tests/frontend/product-theater.test.mjs`
- Modify: `bizpulse/frontend/welcome.html`
- Modify: `bizpulse/frontend/login.html`
- Modify: `bizpulse/frontend/assets/welcome.mjs`
- Modify: `bizpulse/frontend/assets/login.mjs`
- Modify: `bizpulse/frontend/assets/welcome.css`
- Modify: `bizpulse/frontend/assets/styles.css`
- Modify: `bizpulse/tests/frontend/login.test.mjs`
- Modify: `bizpulse/tests/frontend/shell.test.mjs`

**Interfaces:**

- `createProductTheater(root, { intervalMs = 6000, documentRef, windowRef, scheduler }) -> ProductTheaterController`.
- Controller methods: `goTo(index)`, `next()`, `previous()`, `pause(reason)`, `resume(reason)`, `destroy()`, `currentIndex()`.
- Shared slide IDs: `overview`, `profit_bridge`, `inventory_forecast`, `ask_bizpulse`.
- Autoplay pauses for hover, focus-within, manual interaction and hidden document; manual navigation restarts the six-second window.
- `prefers-reduced-motion: reduce` disables autoplay and perspective movement.

- [ ] **Step 1: Write failing controller and shell tests**

```javascript
test("theater advances every six seconds and manual navigation resets time", () => {
  const scheduler = fakeScheduler();
  const controller = createProductTheater(fakeRoot(), {
    intervalMs: 6000,
    documentRef: visibleDocument(),
    windowRef: motionAllowedWindow(),
    scheduler,
  });
  scheduler.advance(5999);
  assert.equal(controller.currentIndex(), 0);
  scheduler.advance(1);
  assert.equal(controller.currentIndex(), 1);
  controller.goTo(3);
  scheduler.advance(5999);
  assert.equal(controller.currentIndex(), 3);
});

test("reduced motion keeps the first useful static slide", () => {
  const controller = createProductTheater(fakeRoot(), {
    documentRef: visibleDocument(),
    windowRef: reducedMotionWindow(),
    scheduler: fakeScheduler(),
  });
  assert.equal(controller.currentIndex(), 0);
  assert.equal(controller.autoplayEnabled(), false);
});
```

Also assert both HTML shells import the same controller, have four local slide assets, contain no remote URL, and preserve `autocomplete="username"`, `autocomplete="current-password"`, `/api/operator/login`, same-origin credentials, CSRF storage and password clearing.

- [ ] **Step 2: Run RED**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
node --test tests/frontend/product-theater.test.mjs tests/frontend/login.test.mjs tests/frontend/shell.test.mjs
```

Expected: failure because the shared controller, four assets and new page structure do not exist.

- [ ] **Step 3: Implement the controller and code-native assets**

```javascript
export const PRODUCT_SLIDES = Object.freeze([
  "overview",
  "profit_bridge",
  "inventory_forecast",
  "ask_bizpulse",
]);

export function createProductTheater(root, options = {}) {
  const intervalMs = options.intervalMs ?? 6000;
  if (intervalMs !== 6000) throw new Error("PRODUCT_THEATER_INTERVAL_INVALID");
  return createController(root, { ...options, intervalMs, slideIds: PRODUCT_SLIDES });
}
```

SVGs are local, abstract product diagrams built from the new palette; they contain no real screenshot, person, product photo, customer data, remote font, external image reference or script. Total uncompressed size of the four files stays at or below 500 KiB.

- [ ] **Step 4: Rebuild welcome and login layout without moving the form**

- Welcome: value proposition and `Explore BizPulse`/`Sign in` actions on the left, Product Theater on the right.
- Login: fixed form column with `Account`, `Password`, `Sign in`; compact Product Theater in the other column.
- Mobile: fixed-height theater precedes the form; slide changes cannot alter form coordinates or page height.
- No-JS/asset failure: slide 1 and both entry links remain visible and usable.
- Keep the login endpoint, error mapping, security cookies, redirect and credential behavior byte-for-byte unless a test requires an accessibility wrapper.

- [ ] **Step 5: Run GREEN, size and local-asset checks**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
node --test tests/frontend/product-theater.test.mjs tests/frontend/login.test.mjs tests/frontend/shell.test.mjs
test "$(find frontend/assets/product-theater -type f -name '*.svg' -exec wc -c {} + | awk 'END {print $1}')" -le 512000
.venv/bin/python scripts/verify_changed.py --base 3e4cc229245cf32a13623da23eaa9685e176a82b
```

Expected: all tests pass, aggregate SVG size is at most 512000 bytes and no public page requests an external asset.

- [ ] **Step 6: Commit Task 5**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation
git add bizpulse/frontend/welcome.html bizpulse/frontend/login.html bizpulse/frontend/assets/core/product-theater.mjs bizpulse/frontend/assets/product-theater bizpulse/frontend/assets/welcome.mjs bizpulse/frontend/assets/login.mjs bizpulse/frontend/assets/welcome.css bizpulse/frontend/assets/styles.css bizpulse/tests/frontend/product-theater.test.mjs bizpulse/tests/frontend/login.test.mjs bizpulse/tests/frontend/shell.test.mjs
git commit -m 'feat: add shared product theater entry pages'
```

## Task 6: Generate one deterministic three-month release and one reusable cost workbook

**Files:**

- Create: `bizpulse/src/synthetic/release_profile.py`
- Create: `bizpulse/src/synthetic/reference_contract.py`
- Modify: `bizpulse/src/synthetic/contracts.py`
- Modify: `bizpulse/src/synthetic/generator.py`
- Modify: `bizpulse/src/synthetic/manifest.py`
- Modify: `bizpulse/src/synthetic/seed.py`
- Modify: `bizpulse/src/services/public_release_service.py`
- Modify: `bizpulse/src/services/profit_bridge_service.py`
- Modify: `bizpulse/tests/unit/test_synthetic_generator.py`
- Modify: `bizpulse/tests/integration/test_synthetic_seed.py`
- Modify: `bizpulse/tests/services/test_public_release_service.py`
- Modify: `bizpulse/tests/services/test_profit_bridge_service.py`
- Modify: `bizpulse/tests/api/test_public_release.py`
- Regenerate: `bizpulse/tests/fixtures/synthetic/v1/manifest.json`
- Regenerate: `bizpulse/tests/fixtures/synthetic/v1/*.{csv,json,xlsx}`
- Create generated fixture: `bizpulse/tests/fixtures/synthetic/v1/bizpulse_demo_costs.xlsx`

**Interfaces:**

- `PUBLIC_RELEASE_PROFILE` owns reporting period `2026-05-01` through `2026-07-31`, current period `2026-07-01` through `2026-07-31`, comparison period `2026-06-01` through `2026-06-30`, store `SYNTH-STORE-01` and currency `BRL`.
- Manifest separates `reporting_period` from older FIFO support history, so earlier receipt dates do not falsely lengthen the displayed sales period.
- Generator version becomes `1.4.0`; seed remains `20260813`.
- `bizpulse_demo_costs.xlsx` has exactly `sku_costs`, `inventory_receipts`, `platform_fees` sheets and reuses canonical rows already used by FIFO/profit, rather than creating a second cost authority.
- The user-provided `/Users/maxli/Desktop/CAPTSONE/bizpulse/data/demo/bizpulse_demo_sales.csv` is recorded as excluded reference material because it uses USD and the incompatible `BP-*` SKU namespace. It cannot be counted with the BRL canonical `SYNTH-SKU-*` sales authority.

Read-only reference decisions are fixed as follows:

| User-provided file | Reference use | Canonical runtime role |
|---|---|---|
| `bizpulse_demo_daily_sales_performance_20260701-20260731.xlsx` | Validate July daily totals/columns | None; derived summary cannot become a second sales source |
| `bizpulse_demo_sales_by_variant_20260701-20260731.xlsx` | Validate BRL SKU-level coverage | None; generator `sales.csv` remains the one sales authority |
| `bizpulse_demo_overall_advertising_20260701-20260731.csv` | Validate advertising fields and BRL units | Generator advertising rows |
| `bizpulse_demo_inventory_snapshot_20260731.xlsx` | Validate inventory snapshot fields | Generator inventory snapshots |
| `bizpulse_demo_inventory_reported_velocity_20260702-20260731.xlsx` | Validate velocity/cover inputs | Precomputed replenishment inputs |
| `bizpulse_demo_operations.xlsx` | Reuse the cost/expense, receipt-batch and inventory concepts | Canonical costs, receipts, expenses and fees generated once |
| `bizpulse_demo_sales.csv` | Compatibility inspection only | Excluded: USD plus `BP-*` namespace mismatch |

The reference contract stores filename, expected columns, currency/SKU decision and inclusion reason only. It does not copy Desktop bytes into runtime and does not expose internal safety banners in the UI.

- [ ] **Step 1: Write failing three-month, workbook and duplicate-authority tests**

```python
def test_release_has_three_complete_months_and_one_currency() -> None:
    bundle = generate_demo(seed=20260813)
    tables = analysis_tables(bundle)
    assert {row["date"][:7] for row in tables["daily_sales"]} == {
        "2026-05", "2026-06", "2026-07"
    }
    assert bundle.manifest.reporting_period == ("2026-05-01", "2026-07-31")
    assert {row["currency"] for row in tables["daily_sales"]} == {"BRL"}


def test_cost_workbook_reuses_canonical_cost_rows() -> None:
    bundle = generate_demo(seed=20260813)
    workbook = workbook_file(bundle, "bizpulse_demo_costs.xlsx")
    book = load_workbook(BytesIO(workbook.content), read_only=True, data_only=True)
    try:
        assert book.sheetnames == ["sku_costs", "inventory_receipts", "platform_fees"]
        assert sheet_records(book["sku_costs"]) == canonical_sku_cost_rows(bundle)
    finally:
        book.close()


def test_incompatible_legacy_sales_file_cannot_become_sales_authority() -> None:
    decision = classify_reference("bizpulse_demo_sales.csv")
    assert decision.included is False
    assert decision.reason == "currency_and_sku_namespace_mismatch"
    assert canonical_role_count(generate_demo(), "sales_authority") == 1
```

- [ ] **Step 2: Run RED**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
.venv/bin/pytest tests/unit/test_synthetic_generator.py tests/services/test_public_release_service.py tests/services/test_profit_bridge_service.py -q
```

Expected: assertions fail because the current generator covers only June/July through July 30, has no release profile and no dedicated cost workbook.

- [ ] **Step 3: Centralize the period profile and extend deterministic generation**

```python
PUBLIC_RELEASE_PROFILE = PublicReleaseProfile(
    store_id="SYNTH-STORE-01",
    currency="BRL",
    reporting_period=(date(2026, 5, 1), date(2026, 7, 31)),
    comparison_period=(date(2026, 6, 1), date(2026, 6, 30)),
    current_period=(date(2026, 7, 1), date(2026, 7, 31)),
    supporting_history_start=date(2026, 3, 15),
)
```

Replace `PUBLIC_ANALYSIS_SCOPE`, `PUBLIC_BASELINE_PERIOD` and `PUBLIC_CURRENT_PERIOD` literals with projections from this object. Generate May, June and July using the same fixed seed and scenario rules; preserve deterministic ordering and stable hashes.

- [ ] **Step 4: Generate the one cost workbook from existing canonical tables**

```python
cost_workbook_tables = {
    "sku_costs": _sku_cost_rows(tables["products"], valid_from=START_DATE),
    "inventory_receipts": tables["receipt_lots"],
    "platform_fees": tables["platform_fees"],
}
files.append(_xlsx_file("bizpulse_demo_costs.xlsx", cost_workbook_tables))
```

Do not add another sales workbook. `operator_import.xlsx` remains the reusable Operator import workbook; the new cost workbook fills only cost/FIFO/fee coverage. Regenerate fixtures only with `scripts/generate_synthetic_demo.py`, then verify the directory byte-for-byte against the generator.

- [ ] **Step 5: Precompute and seed one shared release**

Seed monthly sales/profit snapshots for May, June and July, current July inventory/FIFO/replenishment, June→July Profit Bridge, forecast and Action authority once. `seed_demo` remains idempotent by manifest hash; a second seed adds no dataset, release, Blob or analysis copy. Public release response includes `reporting_period`, `current_period`, `comparison_period`, `currency`, `source_roles` and `content_sha256`.

- [ ] **Step 6: Run GREEN with fixture regeneration and PostgreSQL seed tests**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
.venv/bin/python scripts/generate_synthetic_demo.py --seed 20260813 --output tests/fixtures/synthetic/v1
.venv/bin/pytest tests/unit/test_synthetic_generator.py tests/services/test_public_release_service.py tests/services/test_profit_bridge_service.py tests/api/test_public_release.py -q
.venv/bin/python scripts/test_postgres.py tests/integration/test_synthetic_seed.py -q
.venv/bin/python scripts/verify_changed.py --base 3e4cc229245cf32a13623da23eaa9685e176a82b
```

Expected: tests pass; repeated generation is byte-identical; second seed creates no additional shared data objects.

- [ ] **Step 7: Commit Task 6**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation
git add bizpulse/src/synthetic/release_profile.py bizpulse/src/synthetic/reference_contract.py bizpulse/src/synthetic/contracts.py bizpulse/src/synthetic/generator.py bizpulse/src/synthetic/manifest.py bizpulse/src/synthetic/seed.py bizpulse/src/services/public_release_service.py bizpulse/src/services/profit_bridge_service.py bizpulse/tests/unit/test_synthetic_generator.py bizpulse/tests/integration/test_synthetic_seed.py bizpulse/tests/services/test_public_release_service.py bizpulse/tests/services/test_profit_bridge_service.py bizpulse/tests/api/test_public_release.py bizpulse/tests/fixtures/synthetic/v1
git commit -m 'feat: seed one shared three-month release'
```

## Task 7: Preserve Operator workflow and replace the Viewer import explanation with useful Data & Evidence

**Files:**

- Create: `bizpulse/frontend/assets/features/workspace/public-view.mjs`
- Modify: `bizpulse/frontend/assets/views.mjs`
- Modify: `bizpulse/frontend/assets/data-sources/public.mjs`
- Modify: `bizpulse/frontend/assets/data-sources/operator.mjs`
- Modify: `bizpulse/frontend/assets/features/workspace/view.mjs`
- Modify: `bizpulse/frontend/index.html`
- Modify: `bizpulse/api/routers/public_release.py`
- Modify: `bizpulse/tests/frontend/workspace.test.mjs`
- Modify: `bizpulse/tests/frontend/shell.test.mjs`
- Modify: `bizpulse/tests/frontend/api-client.test.mjs`
- Modify: `bizpulse/tests/api/test_public_release.py`
- Modify: `bizpulse/tests/security/test_upload_boundary.py`

**Interfaces:**

- `renderPublicDataEvidence(root, release, { language, onOpenEvidence })` renders period, currency, version, content hash, canonical source roles, precomputed analyses and evidence state.
- `PublicDataSource` exposes only release/analysis/forecast/profit/action-overlay/Chat methods. It has no upload, import, mapping, commit, run-analysis, publish, export or outcome method.
- `OperatorDataSource` retains its existing upload/import/version/publish/forecast/profit/action/export/outcome/Chat methods and same CSRF/auth rules.
- Viewer controls are absent in DOM and source capability map, not disabled after click.

- [ ] **Step 1: Write failing capability and Viewer projection tests**

```javascript
test("viewer data source has no operator data mutation capability", () => {
  const viewer = new PublicDataSource(fakeApi(), "version-1");
  for (const name of [
    "upload", "import", "commit", "publish", "runProfitBridge",
    "createForecast", "exportAction", "recordActionOutcome",
  ]) {
    assert.equal(typeof viewer[name], "undefined");
  }
});

test("operator data source keeps the complete workflow", () => {
  const operator = new OperatorDataSource(fakeApi(), "version-1");
  for (const name of [
    "publish", "runProfitBridge", "createForecast", "exportAction",
    "recordActionOutcome",
  ]) {
    assert.equal(typeof operator[name], "function");
  }
});

test("viewer workspace renders evidence rather than upload-denial copy", async () => {
  const text = renderViewerWorkspace(releaseFixture()).textContent;
  assert.match(text, /2026-05-01/);
  assert.match(text, /2026-07-31/);
  assert.doesNotMatch(text, /upload|import demo data/i);
});
```

- [ ] **Step 2: Run RED**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
node --test tests/frontend/workspace.test.mjs tests/frontend/shell.test.mjs tests/frontend/api-client.test.mjs
.venv/bin/pytest tests/api/test_public_release.py tests/security/test_upload_boundary.py -q
```

Expected: Viewer workspace still renders the read-only upload denial and release metadata lacks the three-month projection.

- [ ] **Step 3: Implement the public projection and capability split**

```javascript
export function renderPublicDataEvidence(root, release, options) {
  const model = toPublicDataEvidenceModel(release, options.language);
  root.replaceChildren(
    releaseSummary(model),
    sourceCoverage(model),
    precomputedAnalysisCoverage(model),
    evidenceAccess(model, options.onOpenEvidence),
  );
}
```

The page explains what is loaded and which analyses are ready. It does not mention unavailable upload/import controls. Missing period/currency/version returns a structured `PUBLIC_RELEASE_METADATA_INCOMPLETE` state instead of `Period unavailable`.

- [ ] **Step 4: Preserve and regression-test Operator import**

Keep the current Operator stages `source → recognition → mapping → quality → preview → commit`, release CAS publish, file boundary, CSRF, import retry and route-completion fence. Do not rename backend endpoints or change authorization while moving markup/classes.

- [ ] **Step 5: Run GREEN and selected verification**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
node --test tests/frontend/workspace.test.mjs tests/frontend/shell.test.mjs tests/frontend/api-client.test.mjs
.venv/bin/pytest tests/api/test_public_release.py tests/security/test_upload_boundary.py -q
.venv/bin/python scripts/verify_changed.py --base 3e4cc229245cf32a13623da23eaa9685e176a82b
```

Expected: Viewer has a useful Data & Evidence page and no Operator mutation method; Operator workflow tests remain green.

- [ ] **Step 6: Commit Task 7**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation
git add bizpulse/frontend/assets/features/workspace/public-view.mjs bizpulse/frontend/assets/features/workspace/view.mjs bizpulse/frontend/assets/views.mjs bizpulse/frontend/assets/data-sources/public.mjs bizpulse/frontend/assets/data-sources/operator.mjs bizpulse/frontend/index.html bizpulse/api/routers/public_release.py bizpulse/tests/frontend/workspace.test.mjs bizpulse/tests/frontend/shell.test.mjs bizpulse/tests/frontend/api-client.test.mjs bizpulse/tests/api/test_public_release.py bizpulse/tests/security/test_upload_boundary.py
git commit -m 'feat: separate viewer evidence from operator import'
```

## Task 8: Add a session-only Action Sandbox with three bounded estimates

**Files:**

- Create: `bizpulse/src/actions/simulation.py`
- Create: `bizpulse/frontend/assets/features/action-inbox/simulation.mjs`
- Create: `bizpulse/tests/unit/actions/test_simulation.py`
- Modify: `bizpulse/src/actions/contracts.py`
- Modify: `bizpulse/src/services/action_service.py`
- Modify: `bizpulse/src/repositories/actions.py`
- Modify: `bizpulse/api/v1/schemas/actions.py`
- Modify: `bizpulse/api/v1/routers/actions.py`
- Modify: `bizpulse/frontend/assets/features/action-inbox/view-model.mjs`
- Modify: `bizpulse/frontend/assets/features/action-inbox/view.mjs`
- Modify: `bizpulse/frontend/assets/features/action-inbox/effects.mjs`
- Modify: `bizpulse/frontend/assets/data-sources/public.mjs`
- Modify: `bizpulse/tests/services/test_action_service.py`
- Modify: `bizpulse/tests/api/v1/test_actions.py`
- Modify: `bizpulse/tests/frontend/action-inbox.test.mjs`
- Modify: `bizpulse/tests/security/test_cross_session_isolation.py`

**Interfaces:**

- `ActionSimulationInputs(unit_cost_brl: Decimal | None, precomputed_daily_velocity: Decimal | None, baseline_budget_brl: Decimal | None, currency: Literal["BRL"])`.
- `project_simulation_inputs(action, completed_replenishment_snapshot) -> ActionSimulationInputs` accepts only typed precomputed fields; it never parses human labels or calls an analysis runner.
- Browser `estimateSimulation(input) -> { purchaseCashBrl, budgetDeltaBrl, additionalCoverDays }`; money math uses integer cents and quantity, while cover days is formatted to at most two decimals.
- `DELETE /api/demo/action-sandbox` deletes only the current Demo session's overlays and returns `{ "deleted_overlays": int }`.
- Every estimate is labeled `Simulation estimate`; missing cost, budget or non-positive velocity yields `unavailable`, never zero invented as fact.

- [ ] **Step 1: Write failing backend and frontend formula/boundary tests**

```python
def test_projection_uses_only_precomputed_structured_inputs() -> None:
    inputs = project_simulation_inputs(
        action_revision(quantity=Decimal("40"), budget_brl=Decimal("500.00")),
        replenishment_item(
            unit_cost_brl=Decimal("12.50"),
            daily_velocity=Decimal("5"),
        ),
    )
    assert inputs == ActionSimulationInputs(
        unit_cost_brl=Decimal("12.50"),
        precomputed_daily_velocity=Decimal("5"),
        baseline_budget_brl=Decimal("500.00"),
        currency="BRL",
    )


def test_missing_velocity_is_unavailable_not_zero() -> None:
    inputs = project_simulation_inputs(action_revision(), replenishment_item(daily_velocity=None))
    assert inputs.precomputed_daily_velocity is None
```

```javascript
test("sandbox calculates only the three allowlisted estimates", () => {
  assert.deepEqual(estimateSimulation({
    quantity: "40",
    unitCostBrl: "12.50",
    simulatedBudgetBrl: "650.00",
    baselineBudgetBrl: "500.00",
    precomputedDailyVelocity: "5",
  }), {
    purchaseCashBrl: "500.00",
    budgetDeltaBrl: "150.00",
    additionalCoverDays: "8",
  });
});

test("changing sandbox inputs makes no analysis or AI request", async () => {
  const calls = trackedDataSource();
  renderAndEditSimulation(calls);
  assert.equal(calls.loadAnalysis.length, 0);
  assert.equal(calls.submitChatTurn.length, 0);
});
```

- [ ] **Step 2: Run RED**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
.venv/bin/pytest tests/unit/actions/test_simulation.py tests/services/test_action_service.py tests/security/test_cross_session_isolation.py -q
node --test tests/frontend/action-inbox.test.mjs
```

Expected: imports or assertions fail because structured inputs, pure estimates and reset endpoint do not exist.

- [ ] **Step 3: Implement the structured server projection**

```python
@dataclass(frozen=True, slots=True)
class ActionSimulationInputs:
    unit_cost_brl: Decimal | None
    precomputed_daily_velocity: Decimal | None
    baseline_budget_brl: Decimal | None
    currency: Literal["BRL"] = "BRL"
```

Read cost and velocity only from the completed, session-pinned replenishment authority already associated with the action revision. The API serializes decimals as strings. Do not persist calculated purchase cash, budget delta or cover days as authoritative Action facts.

Tighten the Viewer request schema to allow only `quantity` and `budget_brl` in `adjustment`; reject client-supplied `expected_impact`, `limitations`, cost, velocity or calculated estimate fields as `demo_action_adjustment_invalid`. Operator Action revision input retains its existing separately authorized schema.

- [ ] **Step 4: Implement exact browser calculations and session reset**

Parse BRL strings to cents with a strict two-decimal parser and use `BigInt` for money multiplication/subtraction. Keep quantity integer and reject negative/out-of-bound values before command submission. `Review`, `Adjust`, `Approve`, `Dismiss` still create only session overlays. `Reset my simulation` calls the new session-scoped delete endpoint; it does not clear the shared action or another session.

- [ ] **Step 5: Run GREEN and isolation checks**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
.venv/bin/pytest tests/unit/actions/test_simulation.py tests/services/test_action_service.py tests/api/v1/test_actions.py tests/security/test_cross_session_isolation.py -q
node --test tests/frontend/action-inbox.test.mjs
.venv/bin/python scripts/verify_changed.py --base 3e4cc229245cf32a13623da23eaa9685e176a82b
```

Expected: formulas, unavailable states, session A/B isolation and reset semantics pass; no test observes an analysis or AI call from input editing.

- [ ] **Step 6: Commit Task 8**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation
git add bizpulse/src/actions/simulation.py bizpulse/src/actions/contracts.py bizpulse/src/services/action_service.py bizpulse/src/repositories/actions.py bizpulse/api/v1/schemas/actions.py bizpulse/api/v1/routers/actions.py bizpulse/frontend/assets/features/action-inbox/simulation.mjs bizpulse/frontend/assets/features/action-inbox/view-model.mjs bizpulse/frontend/assets/features/action-inbox/view.mjs bizpulse/frontend/assets/features/action-inbox/effects.mjs bizpulse/frontend/assets/data-sources/public.mjs bizpulse/tests/unit/actions/test_simulation.py bizpulse/tests/services/test_action_service.py bizpulse/tests/api/v1/test_actions.py bizpulse/tests/frontend/action-inbox.test.mjs bizpulse/tests/security/test_cross_session_isolation.py
git commit -m 'feat: add bounded viewer action sandbox'
```

## Task 9: Add a server-versioned prompt catalog and auditable actual prompt text

**Files:**

- Create: `bizpulse/src/ai/prompt_catalog.py`
- Create: `bizpulse/alembic/versions/0009_prompt_preset_audit.py`
- Create: `bizpulse/tests/unit/ai/test_prompt_catalog.py`
- Create: `bizpulse/tests/postgres/test_0009_prompt_preset_audit.py`
- Modify: `bizpulse/src/ai/contracts.py`
- Modify: `bizpulse/src/ai/query_catalog.py`
- Modify: `bizpulse/src/services/ai_chat_service.py`
- Modify: `bizpulse/src/repositories/ai_chat.py`
- Modify: `bizpulse/src/db/schema.py`
- Modify: `bizpulse/api/v1/schemas/ai_chat.py`
- Modify: `bizpulse/api/v1/routers/ai_chat.py`
- Modify: `bizpulse/tests/services/test_ai_chat_service.py`
- Modify: `bizpulse/tests/api/v1/test_ai_chat.py`
- Modify: `bizpulse/tests/repositories/test_foundation_repositories.py`
- Modify: `bizpulse/tests/postgres/test_migration_chain.py`
- Modify: `bizpulse/tests/security/test_ai_chat_boundary.py`
- Modify: `bizpulse/frontend/assets/features/ask-bizpulse/view.mjs`
- Modify: `bizpulse/tests/frontend/ask-bizpulse-view.test.mjs`
- Modify generated authority: `bizpulse/release/current_authority.json`
- Modify generated current blocks: `CURRENT_STATUS.md`
- Modify generated current blocks: `docs/handoffs/CURRENT_HANDOFF.md`
- Modify generated current blocks: `docs/handoffs/NEXT_AI_BOOTSTRAP_2026-08-15.md`

**Interfaces:**

- Six preset IDs: `monthly_sales_report`, `profit_changes`, `inventory_risks`, `advertising_performance`, `forecast_30_days`, `next_actions`.
- `PromptPreset` contains localized label/template, `template_version`, allowed `context_kind`, deterministic `intent`, `max_chars`, availability and per-locale SHA-256.
- New API requests always carry the actual visible `question`. Preset use additionally carries all of `recommended_question_id`, `prompt_locale`, `prompt_template_version`, `prompt_template_sha256`; partial metadata fails closed.
- Exact unedited template plus valid metadata selects a fixed server plan. Edited text with valid catalog metadata is treated as free text and goes through the existing whitelist planner. Unknown ID, wrong version/digest, illegal context or inconsistent locale fails `prompt_preset_contract_invalid`.
- New turns store actual text and preset audit metadata. Legacy rows remain readable with explicit `legacy_unrecorded`; migration must not invent historical prompt text.

- [ ] **Step 1: Write failing catalog, request and migration tests**

```python
def test_catalog_has_six_localized_versioned_presets() -> None:
    catalog = PromptCatalog.default()
    assert catalog.ids() == (
        "monthly_sales_report",
        "profit_changes",
        "inventory_risks",
        "advertising_performance",
        "forecast_30_days",
        "next_actions",
    )
    for preset in catalog.items():
        assert set(preset.labels) == {"en", "zh"}
        assert set(preset.templates) == {"en", "zh"}
        assert preset.template_version == "2026-08-15.v1"


def test_exact_template_uses_fixed_plan_but_edited_text_uses_planner(ai_service):
    preset = PromptCatalog.default().get("inventory_risks")
    exact = ai_service.resolve_prompt(prompt_request(preset, preset.templates["en"]))
    edited = ai_service.resolve_prompt(prompt_request(preset, preset.templates["en"] + " Focus on SKU 001."))
    assert exact.fixed_plan.tool == "inventory_risk_lookup"
    assert edited.fixed_plan is None


def test_legacy_turn_is_marked_unrecorded_without_fake_question(migrated_connection):
    row = migrated_connection.execute(select_legacy_turn()).mappings().one()
    assert row["question"] is None
    assert row["prompt_audit_state"] == "legacy_unrecorded"
```

- [ ] **Step 2: Run RED**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
.venv/bin/pytest tests/unit/ai/test_prompt_catalog.py tests/services/test_ai_chat_service.py tests/api/v1/test_ai_chat.py -q
.venv/bin/python scripts/test_postgres.py tests/postgres/test_0009_prompt_preset_audit.py tests/postgres/test_migration_chain.py -q
```

Expected: new catalog/migration imports fail and current API still accepts a preset ID without the actual prompt text.

- [ ] **Step 3: Implement catalog and request validation**

```python
@dataclass(frozen=True, slots=True)
class PromptPreset:
    id: str
    labels: Mapping[Literal["en", "zh"], str]
    templates: Mapping[Literal["en", "zh"], str]
    template_version: str
    context_kind: str | None
    intent: str
    max_chars: int
    available: bool

    def template_sha256(self, locale: Literal["en", "zh"]) -> str:
        return sha256(self.templates[locale].encode("utf-8")).hexdigest()
```

The monthly report preset starts unavailable until Task 10 registers its tool; the other five map to existing fixed plans. For one transitional commit, the UI sends the catalog template and complete metadata when a preset is clicked so all API tests remain green; Task 11 changes the click behavior from send to draft-fill.

- [ ] **Step 4: Add append-only migration `0009_prompt_preset_audit`**

Add `prompt_template_version`, `prompt_template_sha256`, `prompt_locale`, and `prompt_audit_state`. Replace the old exactly-one question constraint with a rollback-compatible constraint: `recorded` rows require actual non-null `question` and either all preset metadata or none; `legacy_unrecorded` rows retain the prior exactly-one `question`/`recommended_question_id` shape with all new metadata null. Give old-application inserts the `legacy_unrecorded` default, while the new repository always writes `recorded`. This lets the attested rollback app continue to insert/read after the additive migration without inventing text for older preset-only rows. Preserve existing turns, attempts, tool runs, evidence, idempotency and saved-audit relationships. Release rollback never runs an Alembic downgrade.

Update only the development portion of current authority and its generated document blocks:

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
.venv/bin/python scripts/refresh_current_authority.py --repository-only --output release/current_authority.json --document-policy release/authority-document-policy.json --write-documents
.venv/bin/python scripts/check_authority_contract.py --mode docs
```

Expected: `development.repository_migration_head` becomes `0009_prompt_preset_audit`; observed hosted database head and AI runtime state remain unchanged.

- [ ] **Step 5: Persist actual sent text and include it in history**

`question_digest` is computed from the actual question. Idempotency request hash includes actual text and all preset metadata. History returns actual question for new turns and an explicit localized “prompt text unavailable for legacy record” projection for legacy rows. Never replace the displayed question with only the preset ID.

- [ ] **Step 6: Run GREEN, security and migration checks**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
.venv/bin/pytest tests/unit/ai/test_prompt_catalog.py tests/unit/ai/test_query_catalog.py tests/services/test_ai_chat_service.py tests/api/v1/test_ai_chat.py tests/security/test_ai_chat_boundary.py -q
.venv/bin/python scripts/test_postgres.py tests/postgres/test_0009_prompt_preset_audit.py tests/postgres/test_migration_chain.py -q
node --test tests/frontend/ask-bizpulse-view.test.mjs
.venv/bin/python scripts/verify_changed.py --base 3e4cc229245cf32a13623da23eaa9685e176a82b
```

Expected: catalog validation, actual-text audit, legacy projection, migration and AI secret boundaries all pass with fake providers only.

- [ ] **Step 7: Commit Task 9**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation
git add bizpulse/src/ai/prompt_catalog.py bizpulse/src/ai/contracts.py bizpulse/src/ai/query_catalog.py bizpulse/src/services/ai_chat_service.py bizpulse/src/repositories/ai_chat.py bizpulse/src/db/schema.py bizpulse/api/v1/schemas/ai_chat.py bizpulse/api/v1/routers/ai_chat.py bizpulse/alembic/versions/0009_prompt_preset_audit.py bizpulse/frontend/assets/features/ask-bizpulse/view.mjs bizpulse/tests/unit/ai/test_prompt_catalog.py bizpulse/tests/unit/ai/test_query_catalog.py bizpulse/tests/services/test_ai_chat_service.py bizpulse/tests/api/v1/test_ai_chat.py bizpulse/tests/repositories/test_foundation_repositories.py bizpulse/tests/postgres/test_0009_prompt_preset_audit.py bizpulse/tests/postgres/test_migration_chain.py bizpulse/tests/security/test_ai_chat_boundary.py bizpulse/tests/frontend/ask-bizpulse-view.test.mjs bizpulse/release/current_authority.json CURRENT_STATUS.md docs/handoffs/CURRENT_HANDOFF.md docs/handoffs/NEXT_AI_BOOTSTRAP_2026-08-15.md
git commit -m 'feat: version and audit prompt presets'
```

## Task 10: Add one bounded precomputed monthly sales report tool

**Files:**

- Create: `bizpulse/src/ai/monthly_sales_report.py`
- Create: `bizpulse/tests/unit/ai/test_monthly_sales_report.py`
- Modify: `bizpulse/src/ai/contracts.py`
- Modify: `bizpulse/src/ai/prompt_catalog.py`
- Modify: `bizpulse/src/ai/query_catalog.py`
- Modify: `bizpulse/src/ai/query_executor.py`
- Modify: `bizpulse/src/services/ai_chat_service.py`
- Modify: `bizpulse/tests/unit/ai/test_query_catalog.py`
- Modify: `bizpulse/tests/unit/ai/test_query_executor.py`
- Modify: `bizpulse/tests/integration/test_ai_chat_tools.py`
- Modify: `bizpulse/tests/services/test_ai_chat_service.py`

**Interfaces:**

- Add `monthly_sales_report_lookup` to `ToolName`, `ARGUMENT_MODELS`, `QUERY_TOOL_NAMES` and backend handler registry.
- `MonthlySalesReportArguments(report: Literal["latest_completed"] = "latest_completed")` has no model-controlled dates, table, store, currency, limit or SQL field.
- `read_monthly_sales_report(connection, scope, readers) -> MonthlySalesReport` reads only exact completed snapshots pinned to the session release and returns at most 25 facts, 10 evidence aliases, 50 limitations and 64 KiB.
- Period title comes from the release scope (`2026-07-01`–`2026-07-31`), never from `date.today()` or browser time.
- The tool covers current net sales/orders/units/AOV, ad spend and efficiency, prior-period changes, bounded top/bottom SKU, material inventory/profit limitations and directly relevant Action baseline.

- [ ] **Step 1: Write failing tool and no-recalculation tests**

```python
def test_monthly_report_is_one_registered_bounded_tool() -> None:
    plan = QueryPlan(
        tool="monthly_sales_report_lookup",
        arguments={"report": "latest_completed"},
    )
    result = executor_with_precomputed_snapshots().execute(plan, JULY_SCOPE)
    assert result.tool == "monthly_sales_report_lookup"
    assert len(result.facts) <= 25
    assert len({ref for fact in result.facts for ref in fact.evidence_refs}) <= 10
    assert fact(result, "report_period").value == "2026-07-01..2026-07-31"


def test_monthly_report_never_invokes_analysis_run_or_raw_scan() -> None:
    readers = tracked_snapshot_readers()
    read_monthly_sales_report(read_only_connection(), JULY_SCOPE, readers)
    assert readers.run_calls == []
    assert readers.raw_table_calls == []
    assert set(readers.completed_snapshot_kinds) <= {
        "sales_ads", "operating_profit", "inventory_risk", "replenishment"
    }
```

- [ ] **Step 2: Run RED**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
.venv/bin/pytest tests/unit/ai/test_monthly_sales_report.py tests/unit/ai/test_query_catalog.py tests/unit/ai/test_query_executor.py -q
```

Expected: `monthly_sales_report_lookup` is rejected as an unknown tool.

- [ ] **Step 3: Implement the precomputed read model inside the existing read-only transaction**

```python
MONTHLY_REPORT_FACT_LIMIT = 25

def read_monthly_sales_report(connection, scope, readers):
    current = readers.completed_analysis(connection, "sales_ads", scope, previous=False)
    previous = readers.completed_analysis(connection, "sales_ads", scope, previous=True)
    profit = readers.completed_analysis(connection, "operating_profit", scope, previous=False)
    inventory = readers.completed_analysis(connection, "inventory_risk", scope, previous=False)
    actions = readers.pinned_actions(connection, scope)
    return build_monthly_report(scope, current, previous, profit, inventory, actions)
```

The `PostgresQueryBackend` already sets `SET TRANSACTION READ ONLY` and a five-second statement timeout. Keep all reads in that one transaction. Missing optional snapshots add stable limitation codes; they do not trigger a job, import, recomputation or raw-data fallback.

- [ ] **Step 4: Enable the monthly preset and preserve one bounded AI explanation**

Exact unchanged monthly template maps directly to this one tool and skips the planning provider call. The existing answer step may make one bounded provider call after server facts are available. Edited text returns to the whitelist planner and still selects at most one registered tool. AI unavailable returns `AI_CHAT_UNAVAILABLE`; it must not substitute a prerecorded answer.

- [ ] **Step 5: Run GREEN and PostgreSQL integration checks**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
.venv/bin/pytest tests/unit/ai/test_monthly_sales_report.py tests/unit/ai/test_query_catalog.py tests/unit/ai/test_query_executor.py tests/services/test_ai_chat_service.py -q
.venv/bin/python scripts/test_postgres.py tests/integration/test_ai_chat_tools.py -q
.venv/bin/python scripts/verify_changed.py --base 3e4cc229245cf32a13623da23eaa9685e176a82b
```

Expected: monthly report is available, bounded to actual July release scope, and no analysis runner/raw scan is called.

- [ ] **Step 6: Commit Task 10**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation
git add bizpulse/src/ai/monthly_sales_report.py bizpulse/src/ai/contracts.py bizpulse/src/ai/prompt_catalog.py bizpulse/src/ai/query_catalog.py bizpulse/src/ai/query_executor.py bizpulse/src/services/ai_chat_service.py bizpulse/tests/unit/ai/test_monthly_sales_report.py bizpulse/tests/unit/ai/test_query_catalog.py bizpulse/tests/unit/ai/test_query_executor.py bizpulse/tests/integration/test_ai_chat_tools.py bizpulse/tests/services/test_ai_chat_service.py
git commit -m 'feat: add bounded monthly sales report tool'
```

## Task 11: Make prompt buttons fill an editable draft and require explicit Send

**Files:**

- Modify: `bizpulse/frontend/assets/features/ask-bizpulse/state.mjs`
- Modify: `bizpulse/frontend/assets/features/ask-bizpulse/effects.mjs`
- Modify: `bizpulse/frontend/assets/features/ask-bizpulse/view-model.mjs`
- Modify: `bizpulse/frontend/assets/features/ask-bizpulse/view.mjs`
- Modify: `bizpulse/frontend/assets/data-sources/public.mjs`
- Modify: `bizpulse/frontend/assets/data-sources/operator.mjs`
- Modify: `bizpulse/tests/frontend/ask-bizpulse-state.test.mjs`
- Modify: `bizpulse/tests/frontend/ask-bizpulse-effects.test.mjs`
- Modify: `bizpulse/tests/frontend/ask-bizpulse-view-model.test.mjs`
- Modify: `bizpulse/tests/frontend/ask-bizpulse-view.test.mjs`
- Modify: `bizpulse/tests/integration/test_chat_session_recovery.py`

**Interfaces:**

- State fields: `draftText`, `selectedPreset`, `pendingReplacement`, `composerFocused`, plus existing submit/history state.
- Preset click dispatches `chat/preset-fill-requested`; it never invokes `submitChatTurn`, consumes an attempt or creates an idempotency key.
- Empty draft fills immediately and moves focus to the textarea end. Non-empty draft opens a keyboard-accessible confirmation with `Replace` and `Keep editing`; no silent overwrite.
- Send submits trimmed visible text plus the selected preset metadata. Editing retains preset metadata so the server can choose fixed-plan versus whitelist-planner behavior.
- Successful history renders the exact sent `question`; clearing/ending the session resets draft and pending replacement for that session only.

- [ ] **Step 1: Write failing interaction tests**

```javascript
test("preset click fills the draft without sending", async () => {
  const api = fakeChatApi();
  const view = renderComposer({ api, presets: [monthlyPreset()] });
  view.clickPreset("monthly_sales_report");
  assert.equal(view.textarea.value, monthlyPreset().template);
  assert.equal(api.submitChatTurn.calls.length, 0);
  assert.equal(view.textarea.selectionStart, view.textarea.value.length);
});

test("a nonempty draft requires explicit replacement", () => {
  let state = { ...initialAskBizPulseState(RELEASE, "viewer"), draftText: "My question" };
  state = reduceAskBizPulse(state, {
    type: "chat/preset-fill-requested",
    preset: monthlyPreset(),
  });
  assert.equal(state.draftText, "My question");
  assert.equal(state.pendingReplacement.id, "monthly_sales_report");
});

test("Send carries visible text and complete preset audit", async () => {
  const api = fakeChatApi();
  const view = renderComposer({ api, presets: [monthlyPreset()] });
  view.clickPreset("monthly_sales_report");
  view.textarea.value += " Focus on the top three SKUs.";
  await view.clickSend();
  assert.deepEqual(api.submitChatTurn.calls[0].payload, {
    question: view.textarea.value,
    recommended_question_id: "monthly_sales_report",
    prompt_locale: "en",
    prompt_template_version: "2026-08-15.v1",
    prompt_template_sha256: monthlyPreset().templateSha256,
  });
});

test.each([
  "AI_CHAT_UNAVAILABLE",
  "AI_BUDGET_EXHAUSTED",
  "AI_RATE_LIMITED",
  "AI_PROVIDER_TIMEOUT",
  "chat_evidence_insufficient",
  "provider_outcome_unknown",
])("composer keeps a distinct localized failure state for %s", (code) => {
  assert.equal(toAskBizPulseViewModel(failedState(code)).messageCode, code);
});
```

- [ ] **Step 2: Run RED**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
node --test tests/frontend/ask-bizpulse-state.test.mjs tests/frontend/ask-bizpulse-effects.test.mjs tests/frontend/ask-bizpulse-view-model.test.mjs tests/frontend/ask-bizpulse-view.test.mjs
```

Expected: current preset click immediately calls `effects.submit` and state has no draft replacement flow.

- [ ] **Step 3: Implement reducer-first draft behavior**

```javascript
case "chat/preset-fill-requested":
  if (state.draftText.trim()) {
    return { ...state, pendingReplacement: action.preset };
  }
  return {
    ...state,
    draftText: action.preset.template,
    selectedPreset: action.preset,
    pendingReplacement: null,
    composerFocused: true,
  };
```

All state changes remain deterministic and testable without DOM. The view owns focus movement; the effect layer owns only API calls and idempotency after explicit submit.

- [ ] **Step 4: Implement accessible replacement and Send flow**

Render six preset buttons, textarea, remaining-length state, Send button and a small confirmation panel with `role="alertdialog"`. `Escape`/`Keep editing` restores focus without changing text; `Replace` writes the template and focuses the caret at the end. When AI is unavailable, presets, textarea and Send remain visible but disabled with one localized reason. Keep unavailable, budget, rate-limit, timeout, insufficient-evidence and provider-outcome-unknown codes distinct in state and localized UI. Clicking disabled controls never records an attempt.

- [ ] **Step 5: Run GREEN and recovery checks**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
node --test tests/frontend/ask-bizpulse-state.test.mjs tests/frontend/ask-bizpulse-effects.test.mjs tests/frontend/ask-bizpulse-view-model.test.mjs tests/frontend/ask-bizpulse-view.test.mjs
.venv/bin/python scripts/test_postgres.py tests/integration/test_chat_session_recovery.py -q
.venv/bin/python scripts/verify_changed.py --base 3e4cc229245cf32a13623da23eaa9685e176a82b
```

Expected: fill/replace/edit/manual-send/history/recovery pass and preset click alone produces zero network calls.

- [ ] **Step 6: Commit Task 11**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation
git add bizpulse/frontend/assets/features/ask-bizpulse/state.mjs bizpulse/frontend/assets/features/ask-bizpulse/effects.mjs bizpulse/frontend/assets/features/ask-bizpulse/view-model.mjs bizpulse/frontend/assets/features/ask-bizpulse/view.mjs bizpulse/frontend/assets/data-sources/public.mjs bizpulse/frontend/assets/data-sources/operator.mjs bizpulse/tests/frontend/ask-bizpulse-state.test.mjs bizpulse/tests/frontend/ask-bizpulse-effects.test.mjs bizpulse/tests/frontend/ask-bizpulse-view-model.test.mjs bizpulse/tests/frontend/ask-bizpulse-view.test.mjs bizpulse/tests/integration/test_chat_session_recovery.py
git commit -m 'feat: make prompt presets editable before send'
```

## Task 12: Complete the CAPTSONE-derived visual migration across every functional page

**Files:**

- Create: `bizpulse/tests/frontend/copy-contract.test.mjs`
- Modify: `bizpulse/frontend/index.html`
- Modify: `bizpulse/frontend/assets/styles.css`
- Modify: `bizpulse/frontend/assets/views.mjs`
- Modify: `bizpulse/frontend/assets/core/charts.mjs`
- Modify: `bizpulse/frontend/assets/core/evidence-drawer.mjs`
- Modify: `bizpulse/frontend/assets/features/overview/view.mjs`
- Modify: `bizpulse/frontend/assets/features/analysis/view.mjs`
- Modify: `bizpulse/frontend/assets/features/analysis/view-model.mjs`
- Modify: `bizpulse/frontend/assets/features/inventory/view.mjs`
- Modify: `bizpulse/frontend/assets/features/inventory/view-model.mjs`
- Modify: `bizpulse/frontend/assets/features/profit/view.mjs`
- Modify: `bizpulse/frontend/assets/features/profit/view-model.mjs`
- Modify: `bizpulse/frontend/assets/features/forecast/view.mjs`
- Modify: `bizpulse/frontend/assets/features/forecast/view-model.mjs`
- Modify: `bizpulse/frontend/assets/features/action-inbox/view.mjs`
- Modify: `bizpulse/frontend/assets/features/action-inbox/view-model.mjs`
- Modify: `bizpulse/frontend/assets/features/ask-bizpulse/view.mjs`
- Modify: `bizpulse/frontend/assets/features/ask-bizpulse/view-model.mjs`
- Modify: `bizpulse/frontend/assets/i18n/catalog.mjs`
- Modify: `bizpulse/src/ai/query_executor.py`
- Modify: `bizpulse/tests/unit/ai/test_query_executor.py`
- Modify: `bizpulse/tests/frontend/*.test.mjs`

**Interfaces:**

- Visual tokens: page `#f6f5f1`, secondary surface `#efeee8`, cards `#ffffff`, primary/focus `#534ab7`, selected tint `#eeedfe`; green/amber/red remain semantic status colors.
- Desktop uses a 56px navigation rail, compact analytical cards and 8–10px application radii; public Product Theater may use 16–20px radii.
- All feature views receive current language and call `t()`/shared formatters. Visible labels are never bilingual string concatenations.
- Evidence drawer keeps focus trap, Escape close and trigger focus restoration.
- Chart components expose a localized text summary using the same display formatter.
- 820px and below: KPI grids become two columns. 560px and below: one column. At 390px, no blocking page-level horizontal overflow; wide tables use a labeled scroll region.

- [ ] **Step 1: Write failing copy, navigation, formatting and token tests**

```javascript
test("visible frontend sources contain no retired demo copy", async () => {
  const visible = await readVisibleFrontendSources();
  for (const retired of [
    /Operator sign in/i,
    /Course Demo/i,
    /Synthetic Demo Data/i,
    /纯合成演示/,
    /Period unavailable/i,
  ]) {
    assert.doesNotMatch(visible, retired);
  }
});

test("there are no nonfunctional decision-center entries", async () => {
  const source = await read("assets/features/ask-bizpulse/view.mjs");
  assert.doesNotMatch(source, /Product Opportunities|Favorites|Operating Advice/);
  assert.doesNotMatch(source, /handler \? "button" : "span"/);
});

test("feature views use the central formatter", async () => {
  const sources = await readFeatureViews();
  assert.doesNotMatch(sources, /\.toFixed\(/);
  assert.doesNotMatch(sources, /new Intl\.NumberFormat/);
  assert.match(sources, /formatBrl|formatDecimal|formatInteger|formatPercentRatio/);
});

test("application tokens match the selected warm Product Theater language", async () => {
  const css = await read("assets/styles.css");
  for (const token of ["#f6f5f1", "#efeee8", "#534ab7", "#eeedfe", "56px"]) {
    assert.match(css, new RegExp(token.replace("#", "\\#"), "i"));
  }
});
```

- [ ] **Step 2: Run RED**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
node --test tests/frontend/copy-contract.test.mjs tests/frontend/shell.test.mjs tests/frontend/charts.test.mjs tests/frontend/analytics.test.mjs tests/frontend/action-inbox.test.mjs tests/frontend/ask-bizpulse-view.test.mjs
```

Expected: current feature source still contains retired copy, bilingual literals, local number formatting and nonfunctional decision-center labels.

- [ ] **Step 3: Apply the shell and component visual adapter**

Use CSS custom properties once and map existing semantic classes onto them:

```css
:root {
  --bp-page: #f6f5f1;
  --bp-surface-muted: #efeee8;
  --bp-card: #ffffff;
  --bp-primary: #534ab7;
  --bp-primary-soft: #eeedfe;
  --bp-border: #d9d8d2;
  --bp-nav-rail: 56px;
  --bp-radius-card: 9px;
  --bp-radius-theater: 18px;
}
```

Preserve the six primary routes `workspace`, `overview`, `sales`, `inventory`, `profit`, `briefing`. Within the decision center, render only Ask BizPulse, Forecast and Action Inbox because all three have working navigation and content.

- [ ] **Step 4: Migrate all visible copy and numeric rendering**

- Remove the screenshot-style chip row; period appears in page/report title, BRL appears beside money/table axes, and version/hash appears in Data & Evidence or the evidence drawer.
- Replace every visible bilingual literal with catalog keys and one selected language.
- Replace scattered `toFixed`, ad-hoc BRL and count formatters in views/view-models/charts with Task 4 functions.
- Replace the AI executor's user-facing `Synthetic Demo data only` literal with stable code `sample_data_only`; keep all limitation/error codes stable in API state and localize only at render time. Source workbooks and Operator exports may retain internal safety banners, but the ordinary frontend must not surface them as page chrome.
- Use `Sample data`/`示例数据` at most once per shell when a boundary reminder is necessary; do not repeat it on every card.
- Preserve every working control, spinner, empty/error state, evidence alias, action command, forecast input and Operator import button.

- [ ] **Step 5: Add accessibility and responsive behavior**

Every interactive target is at least 42px, focus rings use `--bp-primary`, icons have accessible names/tooltips and status is not color-only. Add chart text summaries. Verify keyboard navigation for primary routes, Product Theater, Evidence drawer, preset buttons, replacement confirmation and Action commands.

- [ ] **Step 6: Run complete frontend GREEN and static copy scan**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
npm test
.venv/bin/pytest tests/unit/ai/test_query_executor.py -q
if rg -n -i 'Operator sign in|Course Demo|Synthetic Demo Data|纯合成演示|Period unavailable' frontend; then exit 1; fi
.venv/bin/python scripts/verify_changed.py --base 3e4cc229245cf32a13623da23eaa9685e176a82b
```

Expected: all frontend tests pass and `rg` prints no retired user-visible copy. Internal stable codes such as `pure_synthetic` remain allowed because they are not display strings.

- [ ] **Step 7: Commit Task 12**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation
git add bizpulse/frontend bizpulse/src/ai/query_executor.py bizpulse/tests/unit/ai/test_query_executor.py bizpulse/tests/frontend
git commit -m 'feat: migrate full product UI to warm theater style'
```

## Task 13: Close browser, capacity, restart, rollback and evidence gates without deployment overclaim

**Files:**

- Modify: `bizpulse/tests/acceptance/test_browser_smoke.py`
- Modify: `bizpulse/tests/acceptance/test_exact_15_sessions.py`
- Modify: `bizpulse/tests/acceptance/test_restart_readback.py`
- Modify: `bizpulse/tests/acceptance/test_rollback_compatibility.py`
- Modify: `bizpulse/tests/security/test_cross_session_isolation.py`
- Modify: `bizpulse/tests/security/test_ai_chat_boundary.py`
- Modify: `bizpulse/release/verification-policy.json`
- Modify: `CURRENT_STATUS.md`
- Modify: `docs/handoffs/CURRENT_HANDOFF.md`
- Modify: `docs/handoffs/NEXT_AI_BOOTSTRAP_2026-08-15.md`
- Create: `docs/reviews/2026-08-15-integrated-viewer-ai-local-acceptance.md`

**Interfaces:**

- Browser matrix: 1280×900, 820×900 and 390×844; English and Chinese; reduced motion on/off where relevant.
- Capacity contract: exactly 15 simultaneous Viewer sessions pin the same `release_id` and `dataset_version_id`; dataset/version/artifact/analysis/Blob counts are unchanged by admission and Action edits.
- Restart contract: public release remains authoritative; unexpired sessions follow the existing recovery contract; expired session Chat/overlays cannot return.
- Rollback contract: additive `0009` migration remains readable by the attested rollback application; no Alembic downgrade occurs.
- AI acceptance uses fake providers and injected test secrets only. No real Key or paid request.

- [ ] **Step 1: Expand acceptance tests and verify RED against missing behavior**

```python
def test_exact_15_viewers_share_one_release_without_data_or_analysis_copies(app, engine):
    before = durable_release_counts(engine)
    before_blobs = blob_object_count()
    sessions = admit_viewers(app, count=15)
    assert {session.release_id for session in sessions} == {sessions[0].release_id}
    simulate_one_action_per_session(app, sessions)
    after = durable_release_counts(engine)
    assert after.datasets == before.datasets
    assert after.dataset_versions == before.dataset_versions
    assert after.dataset_artifacts == before.dataset_artifacts
    assert after.analysis_runs == before.analysis_runs
    assert after.public_releases == before.public_releases
    assert blob_object_count() == before_blobs


def test_browser_monthly_preset_waits_for_send_and_uses_release_period(page):
    page.get_by_role("button", name="Generate this month's sales report").click()
    expect(page.locator("textarea")).to_have_value(re.compile("latest completed month"))
    assert provider_attempt_count() == 0
    page.get_by_role("button", name="Send").click()
    expect(page.get_by_text(re.compile("2026-07-01.*2026-07-31")).first).to_be_visible()
```

Browser assertions also cover four-slide autoplay/manual/reduced-motion behavior, stable login form, `Sign in`, six Viewer areas, evidence, three Action estimates, session reset, six presets, draft replacement, edited prompt, AI unavailable, Operator import/publish/export/outcome presence, no Viewer mutation controls, no remote images, no console errors and no blocking overflow. Acceptance also proves one-in-flight AI enforcement, global budget enforcement, zero new analysis rows from Action edits, and cleanup of only the expired session's Chat/overlays.

- [ ] **Step 2: Run focused RED**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
.venv/bin/python scripts/test_postgres.py tests/acceptance/test_exact_15_sessions.py tests/acceptance/test_browser_smoke.py -q
```

Expected: at least the newly added full Product Theater/draft/report/capacity assertions fail until acceptance helpers and any remaining wiring are completed.

- [ ] **Step 3: Implement only acceptance-discovered wiring fixes**

Fix the smallest product seam that caused each failure. Do not weaken assertions, add waits that hide races, insert prerecorded AI answers or relax Viewer/Operator boundaries. Use fake provider responses bound to returned server facts. Keep exact-15 as a bounded demonstration-capacity claim, not a Production load claim.

- [ ] **Step 4: Run focused GREEN for acceptance and security**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
.venv/bin/python scripts/test_postgres.py tests/acceptance/test_exact_15_sessions.py tests/acceptance/test_restart_readback.py tests/acceptance/test_rollback_compatibility.py tests/acceptance/test_browser_smoke.py tests/security/test_cross_session_isolation.py tests/security/test_ai_chat_boundary.py -q
```

Expected: all focused acceptance/security tests pass with local PostgreSQL, local assets and fake providers.

- [ ] **Step 5: Update evidence documents through the authority contract**

The review records:

- Implemented and locally verified behaviors, exact commands and counts.
- Demo-limited facts: pure sample data, exact-15 scope, no real-market proof, no external action execution.
- Current hosted observation remains whatever `current_authority.json` says; local work does not change deployed/Hosted verified/Azure accepted states.
- AI capability can be implemented locally while hosted runtime remains `disabled`.
- OpenAI Key creation/injection, paid call and Azure deployment remain separately unauthorized.

Regenerate current blocks from the authority file, place old narrative under history fences and run:

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation
bizpulse/.venv/bin/python bizpulse/scripts/check_authority_contract.py --mode docs
```

Expected: `authority_contract=ok`.

- [ ] **Step 6: Commit the final implementation candidate**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation
git add bizpulse/tests/acceptance bizpulse/tests/security/test_cross_session_isolation.py bizpulse/tests/security/test_ai_chat_boundary.py bizpulse/release/verification-policy.json CURRENT_STATUS.md docs/handoffs/CURRENT_HANDOFF.md docs/handoffs/NEXT_AI_BOOTSTRAP_2026-08-15.md docs/reviews/2026-08-15-integrated-viewer-ai-local-acceptance.md
git commit -m 'test: close integrated viewer and AI acceptance'
git status --short
```

Expected: clean implementation worktree. If unrelated user files appear, do not stage them.

- [ ] **Step 7: Run the changed-path selector without claiming release evidence**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
.venv/bin/python scripts/verify_changed.py --base 3e4cc229245cf32a13623da23eaa9685e176a82b --no-reuse
```

Expected: selected development checks pass. If policy classifies the accumulated candidate as requiring the full gate, the script prints `full_release_gate_required` and exits without trying to reuse development evidence; Task 14 owns that gate.

## Task 14: Refresh current authority and create the exact local release attestation

**Files:**

- Modify generated authority: `bizpulse/release/current_authority.json`
- Modify generated blocks: `CURRENT_STATUS.md`
- Modify generated blocks: `AUTHORIZATION_LEDGER.md`
- Modify generated blocks: `docs/handoffs/CURRENT_HANDOFF.md`
- Modify generated blocks: `docs/handoffs/NEXT_AI_BOOTSTRAP_2026-08-15.md`
- Modify generated blocks: `docs/handoffs/AZURE_LAUNCH_HANDOFF_2026-08-15.md`
- Create generated attestation under: `bizpulse/release/attestations/` using the exact candidate Git SHA as the filename

**Interfaces:**

- Input is one fresh, sanitized, read-only deployment observation under ignored `.artifacts/authority/current-observation.json` plus matching checked-in attestations.
- Authority refresh rewrites only `authority:current` blocks. It cannot edit history blocks or accept manual SHA/digest overrides.
- The final product candidate is the clean commit that contains the refreshed authority and generated current blocks.
- The attestation is a required manifest-only direct child of that exact candidate and is verified from a detached candidate worktree.

- [ ] **Step 1: Require fresh read-only evidence and run the authority GREEN check before constructing a candidate**

No Azure mutation is permitted. If the sanitized observation file is absent, expired, inconsistent with a checked-in attestation or names an unknown image, stop with `authority_observation_stale` or `authority_observation_unbound`. Local Task 13 evidence remains valid only as local product evidence; do not create a release claim.

With a valid local projection, run:

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
.venv/bin/python scripts/refresh_current_authority.py --observation-json .artifacts/authority/current-observation.json --attestation-dir release/attestations --output release/current_authority.json --document-policy release/authority-document-policy.json --write-documents
.venv/bin/python scripts/check_authority_contract.py --mode release
```

Expected: refresh prints `current_authority=updated`; check prints `authority_contract=ok`. The command performs local file writes only and never calls Azure.

- [ ] **Step 2: Review the exact authority diff and commit the candidate**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation
git diff --check
git diff -- bizpulse/release/current_authority.json CURRENT_STATUS.md AUTHORIZATION_LEDGER.md docs/handoffs/CURRENT_HANDOFF.md docs/handoffs/NEXT_AI_BOOTSTRAP_2026-08-15.md docs/handoffs/AZURE_LAUNCH_HANDOFF_2026-08-15.md
git add bizpulse/release/current_authority.json CURRENT_STATUS.md AUTHORIZATION_LEDGER.md docs/handoffs/CURRENT_HANDOFF.md docs/handoffs/NEXT_AI_BOOTSTRAP_2026-08-15.md docs/handoffs/AZURE_LAUNCH_HANDOFF_2026-08-15.md
git commit -m 'chore: refresh authority for integrated viewer AI candidate'
git status --short
```

Expected: only generated current facts changed and the implementation worktree is clean.

- [ ] **Step 3: Run the concentrated full gate through the existing candidate builder**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
.venv/bin/python scripts/create_release_manifest.py --candidate-sha HEAD
```

Expected: the builder first validates fresh authority and then runs the complete PostgreSQL suite, complete frontend suite, exact-15/restart/rollback, Ruff, compile, diff and browser gates against the exact clean candidate in the release protocol. It prints `release_manifest=ok` and creates only that candidate's attestation JSON. A failure is not partial success: diagnose the exact failing node, commit a correction, refresh authority if expired, discard the old evidence and repeat this step for the new SHA.

- [ ] **Step 4: Commit only the manifest child and reverify the detached candidate**

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation
candidate_sha="$(git rev-parse HEAD)"
git add "bizpulse/release/attestations/${candidate_sha}.json"
git diff --cached --name-only
git commit -m 'chore: attest integrated viewer AI candidate'
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse
.venv/bin/python scripts/create_release_manifest.py --verify-attestation
```

Expected: the staged-path check lists exactly one candidate-named JSON file; final command prints `release_attestation=ok` and exact candidate/attestation SHAs. This protocol intentionally adds one manifest-only proof commit after the Task 14 candidate commit.

- [ ] **Step 5: Stop at local attestation**

Do not build or publish a registry image, inject an OpenAI Key, modify Azure, deploy, run hosted capacity, restart or rollback. Those actions require a new value-complete package and explicit authorization. Report local token/test counts and evidence state without upgrading CI, deployed, Hosted verified, Azure Demo accepted or Production-ready status.

## Plan Self-Review

- **Spec coverage:** Tasks 4–7 cover the approved full-surface visual migration, four-slide public/login experience, separate language catalogs, display precision, one shared three-month release, one cost workbook and Viewer/Operator split. Task 8 covers only the three approved Action estimates and session lifecycle. Tasks 9–11 cover six presets, editable draft, explicit Send, auditable text, fixed-versus-edited planning and the one-tool monthly report. Tasks 12–13 cover complete page migration, accessibility, capacity and evidence-separated acceptance; Task 14 performs only current-authority refresh and local release proof.
- **Anti-drift coverage:** Task 1 creates a single current authority, history fences, exact file/line errors and freshness; Task 2 maps paths to checks and fingerprints full code domains; Task 3 removes mutable SHA/migration literals from release code while preserving immutable attestation replay.
- **Placeholder scan:** No implementation step depends on an unspecified function, future endpoint, unknown schema field or copied current-release literal. Runtime-dependent SHA/digest/time values must enter through a validated observation or attestation; absence is a named fail-closed state.
- **Type consistency:** Money remains Python `Decimal`/API decimal string and UI cents; quantities are integers; ratios/days are display-only numbers; preset ID/version/digest/locale are all-or-none; legacy prompt text is explicitly nullable and marked `legacy_unrecorded`; observed and rollback image digests are distinct typed fields.
- **Test consistency:** Every implementation task contains a focused RED command, a bounded implementation target, a GREEN command and one code commit. Task 14 is a release-proof workflow and deliberately produces the exact candidate plus one required manifest-only child. Development evidence may be reused only by code-domain fingerprint; final evidence is always rerun against the exact clean candidate SHA.
- **Evidence consistency:** The plan can establish Implemented and Locally verified states only. It does not turn local tests, fake AI, a reachable old URL, an attestation or documentation into CI, deployed, Hosted verified, Azure Demo accepted or Production-ready proof.
- **Security and authority consistency:** Viewer cannot upload or invoke Operator routes; AI cannot see raw uploads, credentials, schema discovery or arbitrary SQL; the browser cannot see the Key; no action estimate mutates deterministic KPI/forecast/profit/action authority; no external write is included in the implementation tasks.
