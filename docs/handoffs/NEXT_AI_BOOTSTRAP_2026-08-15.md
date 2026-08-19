# NEWCaostone Next-AI Bootstrap

<!-- authority:current:start -->
Current deployed and development facts are generated from `bizpulse/release/current_authority.json`.

- Deployed candidate: `537effe3036f77f83225beef12589bd447205a8b`
- Deployed attestation: `168349f0d6242405f37fa9a44dbad17f03063d96`
- Deployed image: `sha256:2a95c20046cde04a383a280b350a450c15cc7c46df92e1e8eaf5014eeb5c8512`
- Deployed revision: `newcaostone-demo-app--recover-78eaaf31-2a95c20`
- Hosted migration: `0008_ai_budget_ledger`
- Hosted AI: `disabled`
- Attested rollback candidate: `537effe3036f77f83225beef12589bd447205a8b`
- Attested rollback image: `sha256:2a95c20046cde04a383a280b350a450c15cc7c46df92e1e8eaf5014eeb5c8512`
- Repository migration: `0017_ai_turn_credential_binding`
- Repository AI capability: `implemented`
- Observation: `2026-08-16T01:26:00Z`
- Observation expires: `2026-08-16T20:25:35Z`
- This block grants no Azure, registry, secret, paid-AI, push, PR, CI, or deployment authority.
<!-- authority:current:end -->

## Supersession notice

This historical bootstrap is not a continuation authority. The generated
snapshot above expired when the 2026-08-16 partial release attempt began. Read
`CURRENT_STATUS.md`, `docs/handoffs/CURRENT_HANDOFF.md`, and
`bizpulse/docs/operations/2026-08-16-two-stage-release-partial-failure.md`
instead. Do not replay any command in this file.

## Local implementation takeover

Use
`/Users/maxli/Desktop/NEWCaostone/.worktrees/integrated-viewer-ai-anti-drift`
on `codex/integrated-viewer-ai-anti-drift`. The immutable batch base is
`d1f1d8e69bac3bb9c94532daa56fb3016d852442`; never substitute the deployed
anchor when running changed-path verification.

Tasks 1–13 of the integrated Viewer / AI / Anti-Drift plan are implemented.
The concentrated local acceptance command passed 16 tests in 71.37 seconds
with local PostgreSQL, Azurite, Chrome, local assets and fake AI. Exact details
are in `docs/reviews/2026-08-15-integrated-viewer-ai-local-acceptance.md`.

The immediate sequence is:

1. commit only the Task 13 implementation, tests, policy and evidence docs;
2. run `verify_changed.py` against the approved development baseline with
   `--no-reuse`;
3. inspect the ignored sanitized observation file required by Task 14;
4. if it is missing, stale or unbound, stop fail-closed without creating a
   release claim;
5. otherwise perform only Task 14's local authority refresh, candidate
   verification and local attestation protocol.

No Azure, registry, Keychain, secret, paid AI, push, PR, CI or deployment
mutation is authorized. The hosted runtime remains the generated authority
shown above, with hosted AI disabled. Local acceptance must not be relabeled as
Hosted verified, Azure accepted or Production ready.

<!-- authority:history:start -->

Last updated: 2026-08-15 (America/Chicago)

> **Current Azure authority correction:** Before relying on any later
> historical prose in this file, use the 2026-08-15 read-only snapshot: current
> candidate `3e933d083b3ab4dba36d8053f56ecf2d68d31f1e`, attestation child
> `cda718a0869bc8bb815ebe632e728c266f588d39`, image
> `sha256:95088291d0d9402d3b580b3fde5afce816bcc5281d1281be088cb1cbe713e1c7`,
> image-input `69e53aecd6659df38db57c8090f8adf1363263c9d356b47c8a857f199a93f885`,
> and ready revision `newcaostone-demo-app--95088291d0d9`. It is external,
> Single, 100% latest, one ready replica, and AI-disabled. Lower
> `2173222`/`78e9e62`/`cb77be5` statements are historical only.

This file is a copy-ready takeover prompt plus a compact truth model. It has no
password, hash value, token, connection string, storage key, session pepper, or
API key value.

## Copy this to the next AI

```text
接管 /Users/maxli/Desktop/NEWCaostone 项目，但先不要执行代码、测试、Git、Docker、
registry 或 Azure 写入。用户在 2026-08-15 明确暂停工作以完成交接；只有当用户在
新任务中再次明确说“继续”或“接管并继续”后才恢复。

必须依次完整读取：
1. /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/docs/handoffs/NEXT_AI_BOOTSTRAP_2026-08-15.md
2. /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/docs/handoffs/AZURE_LAUNCH_HANDOFF_2026-08-15.md
3. /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/docs/handoffs/CURRENT_HANDOFF.md
4. /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/CURRENT_STATUS.md
5. /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/AUTHORIZATION_LEDGER.md
6. 上述文件指向的批准设计和当前 remediation plan。

然后只读核对 git status/diff/HEAD，不要仅凭聊天摘要猜测授权、完成或测试状态。
当前分支 codex/newcaostone-implementation-v3；先用 Git 读取实际 HEAD 与 worktree 状态，
不要把这份 handoff 的历史暂停点当作候选 SHA。当前 Azure 健康运行的是候选 2173222 /
attestation cb77be5 / digest sha256:78e9e62...；它不是尚未 attested 的 successor。

当前修复目标：关闭 production hosted seed 不为当前公开版本创建 Action 的 vertical gap。
实现已加入 DemoActionAuthority、PublicReleaseService eligibility、真实 container wiring、
production-path browser fixture，以及 seed replay 对 seeded version + current public version 的
Action backfill。replenishment 完整时使用 exact replenishment Action；sales-only/current v2
则使用 exact Profit Bridge evidence-review Action，不把 missing 变成 zero。

同版本 Action 去重测试已通过；不放宽的 browser gate 已由用户从原生 macOS Terminal
运行，并以 PostgreSQL 包装器得到 `2 passed in 23.26s`。Codex 终端沙箱仍无法启动
Chromium（已安装 Chrome 152 在 macOS 应用注册层 SIGABRT，官方 Chrome for Testing
headless shell 也被 MachPortRendezvous 拒绝），但这是该沙箱的宿主边界，不是当前
BizPulse 页面失败。不要重装、修复或修改用户的 Chrome。后续 release verifier 若需要
浏览器，必须从原生终端或 CI 浏览器宿主运行同一不放宽的 gate。

之后按 handoff 的 verification -> independent review -> candidate commit -> exact linux/amd64 image
-> manifest-only child -> detached attestation -> new mode-0600 restricted no-AI update package 顺序执行。
所有旧 cleanup/launch/update package 都已 consumed，绝不重跑。当前不需要 cleanup，必须保留健康
PostgreSQL/Blob/runtime。未来外部写入只有在生成新 value-complete package 并得到用户对其完整
SHA-256 的明确批准后才允许；旧批准、笼统“授权”、设计批准或可访问 URL 都不能替代新 SHA 批准。

不启用或读取 OpenAI Key，不做付费 AI。任何密码/Hash/Key/token/connection string 不得打印、
写文件、写聊天或放 argv。凭据只按 Azure handoff 中的 Keychain service/account 名在内存加载。
macOS security 弹窗不能仅凭截图判断所需密码；先核对触发进程和精确 Keychain 项，或取消，
绝不把任何 Demo/Azure/数据库/API 秘密粘贴进去。

每个状态必须分开陈述：implemented、tested、committed、attested、image built、registry published、
deployed、hosted accepted、Production-ready。当前是 dirty local implementation + focused green +
native-Terminal browser gate green；Azure 旧版本健康但 hosted acceptance 未完成，Production-ready=false。
```

## One-paragraph status for a human

NEWCaostone 的无 AI 合成 Azure Demo 当前在线且健康，运行固定旧候选
`2173222`、镜像 digest `sha256:78e9e62...`，PostgreSQL/Blob/migration
`0008` 正常；但 V3 hosted browser 在 Action Card 处停止，因此容量、自然到期、
restart 和 rollback 验收未完成。工作树里已有未提交 successor：它把 production
seed、当前公开版本和 Action eligibility 接通，并用真实 Chrome 证明 sales-only v2
可获得 exact Profit Bridge evidence-review Action。当前 Docker PostgreSQL 聚焦集已通过，
且原生终端的精确浏览器 gate 已通过；历史完整 Python 套件的唯一失败仅是 Codex
终端 Chromium 启动边界。更大的 release verifier、独立复审、commit、镜像、attestation 和新
SHA-bound update package 仍未完成。所有旧包已消耗，当前无需
清理，不能直接重试 Azure。

## Credential handoff rule

No successor needs a plaintext secret from chat. The exact Keychain service and
account names, Azure secret names, identities, and safe child-environment names
are documented in `AZURE_LAUNCH_HANDOFF_2026-08-15.md`. If a value is absent
from Keychain or does not verify against its paired authority, stop and ask the
user to recreate/approve it; never reconstruct or rotate a credential silently.

## Do not infer these false statements

- “The URL works, therefore hosted acceptance is complete.” False.
- “The browser test passed locally, therefore Azure v2 is repaired.” False; the
  updated image and idempotent seed replay have not been deployed.
- “The local diff exists, therefore it is committed or attested.” False.
- “A prior approval can be reused for the next image.” False.
- “The user authorized AI later, therefore an OpenAI Key may be read now.”
  False; that is a separate future task.
- “An old Azure resource looks related, therefore it may be deleted.” False;
  exact value-complete cleanup authority is required.

## Handoff acceptance checklist

A successor has correctly taken over only after it can state, without reading a
secret value:

- the worktree, branch, HEAD, and dirty paths;
- the exact deployed candidate/attestation/digest and AI-disabled state;
- why hosted V3 stopped and which gates never ran;
- why current v2 needs seed replay backfill;
- which focused tests passed and which complete release/attestation gates remain;
- why every old package is consumed;
- the next external approval boundary and exact stop conditions.

<!-- authority:history:end -->
