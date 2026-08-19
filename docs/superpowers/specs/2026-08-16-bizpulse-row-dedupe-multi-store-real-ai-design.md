# BizPulse 行级去重、多店铺范围与真实 AI 设计

状态：已获用户批准，待实施计划与实施

日期：2026-08-16（America/Chicago）

文档版本：1.0

目标仓库：`/Users/maxli/Desktop/NEWCaostone`

实施顺序：行级自动去重 → 多店铺选择与范围 → Azure Demo 真实 AI

## 1. 目的

在不削弱现有 Operator、Viewer、确定性计算、不可变数据版本和权限边界的前提下：

1. 为 BP 资料库增加按业务键工作的行级自动去重；
2. 为 Operator 和 Viewer 增加贯穿全部产品面的店铺范围；
3. 为 Demo 增加一家低流量、刚起步的第二店；
4. 最后以服务器端 Secret、固定模型和硬预算在 Azure Demo 开启真实 AI。

本设计采用“数据集范围方案”：不移植 CAPTSONE 旧版完整的店铺身份、共享库存池、
跨店分摊和 Portfolio 系统，而是在 NEWCaostone 当前数据版本、确定性分析和 Chat
架构上增量实现。

## 2. 已确认决定

- 两家店共享一份商品目录；第二家店只上架三个已有 SKU。
- 完全相同的业务行自动去重；同业务键但业务值冲突时停止导入，不覆盖、不求和。
- 销售行不能只按 `store_id + order_id` 去重；当前规范键为
  `store_id + order_id + sku_id`，因此同一订单中的不同 SKU 均保留。
- 顶部提供 `All stores / 全部店铺`、主店和新店三个范围。
- Overview、Inventory、Profit、Forecast、Action、BP Library 和 Ask BizPulse
  必须使用同一全局店铺范围。
- 第二家店从 2026-07-08 开始营业，流量约为主店的 10%–20%。
- 真实 AI 同时服务 Viewer 和 Operator，但只读取服务器选出的有界确定性事实。
- Azure Demo AI 模型固定为 `gpt-5.4-nano-2026-03-17`，reasoning effort 为 `low`。
- AI 硬限制固定为：

| 限制 | 批准值 |
|---|---:|
| 每日 provider attempts | 120 |
| 每月总 tokens | 150,000 |
| 单会话每分钟 attempts | 3 |
| 全局每分钟 attempts | 20 |
| 最大并发 Chat turns | 15 |
| 单次最大输出 tokens | 2,800 |

## 3. 当前起点与复用边界

NEWCaostone 当前已经具备：

- 工作流级重复文件 SHA 拒绝；
- 相同规范化数据源和相同数据集内容的重复拒绝；
- 多个标准表中的 `store_id` 字段；
- 单店分析过滤和 AI `store_ids` 合同的部分基础；
- BP Library 工作簿、分页和行详情；
- 服务器端 OpenAI gateway、AI budget ledger、不可用/限流/预算/超时状态；
- Azure Container Apps `openai-api-key` secretRef 接线；
- AI 默认关闭和固定模型/effort 的 fail-closed 配置。

当前缺口是：现有重复检查针对文件、数据源或完整数据集，不会删除单个文件或重叠
月份中的重复业务行；公共发布、示例生成器、页面范围和 AI principal 仍固定为第一店。

CAPTSONE 只作为只读设计参考。不得 checkout、复制其迁移历史或直接移植重量级
multi-store program。所有实现发生在 NEWCaostone 隔离工作树。

## 4. 总体数据流

```text
当前不可变数据版本 + 本次全部规范化上传
  → 按角色完成字段和值标准化
  → 建立数据集店铺目录
  → 按表级业务键比较行
  → 完全相同：确定性保留一行并记录去重
  → 同键不同值：生成冲突报告并阻止提交
  → 无冲突：生成新的不可变数据版本
  → 预计算 All stores、主店、新店三个分析范围
  → 发布 Viewer 共享版本
  → AI 只读取所选范围的预计算事实
```

旧版本永不被原地修改。任何一次成功导入都生成一个新的精确版本；失败导入不改变
当前版本、当前发布或现有分析权威。

## 5. 行级自动去重

### 5.1 去重位置

行级去重发生在 adapter 已完成规范字段映射、日期/整数/金额标准化之后，在持久化
新数据版本之前。这样 `5`、`5.0` 和 `5.00` 不会因为显示格式不同而被当作三条记录。

比较集合包括：

- 当前数据版本内已经存在的规范化行；
- 本次工作流的所有文件、sheet 和角色；
- 同一文件内重复出现的行。

去重不比较上传临时 ID、对象路径、文件 SHA 或解析时间等摄取元数据。来源文件、
sheet 和源行号作为 provenance 保留，用于质量报告和冲突定位，但不进入业务值相等
判断。

### 5.2 业务键

| 标准表角色 | 业务键 |
|---|---|
| `daily_sales` | `store_id + order_id + sku_id` |
| `shopee_advertising` | `store_id + date + sku_id` |
| `product_inventory_sales` | `store_id + date + sku_id` |
| `inventory_movement` | `store_id + movement_id` |
| `inventory_receipt_lot` | `store_id + lot_id` |
| `outbound_event` | `store_id + outbound_id` |
| `refund` | `store_id + refund_id` |
| `settlement` | `store_id + fee_id` 或 `store_id + settlement_id` |
| `fulfillment_cost` | `store_id + fulfillment_id` |
| `operating_expense` | 有店铺时 `store_id + expense_id`；共享费用为 `expense_id` |
| `fx_effect` | `store_id + fx_effect_id` |
| `other_variable_cost` | `store_id + cost_id` |
| `product_catalog` | `sku_id` |
| `replenishment_policy` | `store_id + sku_id` |
| `fx_assumption` | `currency + period_start + period_end` |
| `new_product_benchmark` | `forecast_id` |
| `new_product_backtest_window` | `window_id` |

角色缺少构成业务键的必要字段时，不能退化为整行 hash 后继续提交；应返回明确的
`business_key_incomplete` 质量错误。

### 5.3 决策规则

对同一业务键：

- 所有规范化业务值相同：视为完全重复，保留一行；
- 任一业务值不同：视为冲突，整次提交停止；
- 不因“后上传”“文件名更大”“日期更新”自动选择胜者；
- 不对数量、金额、点击、订单或库存求和；
- 不用 AI 判断哪行正确。

保留优先级固定为：当前资料库已有行优先于本次上传；本次上传之间按上传创建时间、
文件名、sheet 顺序和源行号建立稳定顺序。优先级只决定完全相同行的 provenance，
不能解决冲突。

### 5.4 多店铺缺失店铺字段

店铺相关表缺少 `store_id` 时：

- 单店文件可在上传预览中由 Operator 一次指定所属店铺；
- 多店文件必须自身包含可映射的店铺字段；
- 含多个店铺的数据版本不得自动把缺失值归到默认店；
- 商品目录、汇率、新品基准等明确共享角色不要求 `store_id`；
- 经营费用允许显式标为共享，不能用空值暗中平均分摊。

### 5.5 质量报告与界面

上传预览按总计和每张表显示：

- `Rows read / 读取行数`；
- `Rows retained / 保留行数`；
- `Duplicates removed / 已删除重复行`；
- `Conflicts / 冲突行`。

完全重复不要求额外确认。存在冲突时，页面按“表格 → 业务键 → 冲突字段 → 来源”
展示前 50 条，并提供完整冲突 CSV。每条来源包含文件名、sheet、源行号以及“当前
资料库”或“本次上传”标记。冲突页面不得显示 Blob 路径、对象 digest 或内部凭证。

## 6. 数据集店铺目录与全局范围

### 6.1 数据集店铺目录

每个不可变数据版本包含一份有界店铺目录，至少包括：

- stable `store_id`；
- 本地化安全显示名；
- `currency`；
- 营业开始日期（可空）；
- 当前数据版本中是否有数据；
- 生命周期标签：`established` 或 `new`。

目录优先读取显式 store catalog；没有显示名的真实上传退化为安全的 `store_id`。
不得从任意自由文本相似度自动合并两个店铺 ID。本轮不实现旧 CAPTSONE 的长期别名
映射和 owner-scoped store identity 系统。

### 6.2 统一范围合同

前后端使用同一个版本绑定的店铺范围：

- `all` 在服务器解析为该版本店铺目录中的全部有效 `store_id`；
- 单店解析为只含一个 `store_id` 的有序集合；
- 客户端不能提交目录以外的店铺；
- Dataset、period、currency 和 store scope 一起进入分析、Action 和 AI 权威。

Viewer 只能选择共享发布版本内的店铺；Operator 只能选择其当前精确数据版本内的
店铺。切换范围不改变数据版本。

### 6.3 全局选择器

应用顶部工具栏增加本地化店铺选择器，固定顺序为：

1. `All stores / 全部店铺`；
2. `Brazil Main Store / 巴西主店`；
3. `Brazil Launch Store / 巴西新店`。

范围同步控制：

- Overview KPI 和趋势；
- Inventory P0/P1/P2/Monitor；
- Profit 和成本；
- Forecast；
- Action Sandbox；
- BP Library；
- Ask BizPulse。

Operator 的默认店铺使用已有服务器端 Settings 权威；Viewer 的选择只存在当前 Demo
会话，不写入持久业务数据。切换店铺时取消过期请求，清空未保存的 Action 模拟并
显示一次轻量提示，防止跨范围混用。

### 6.4 计算和预计算

Viewer 切换店铺不得触发全量重算。发布一个两店数据版本时预先生成三个分析范围：

- 全部店铺；
- 主店；
- 新店。

数量和金额类指标在全部店铺范围相加；ROAS、转化率、退款率、利润率、库存覆盖天数
等比例或派生指标必须根据合并后的分子、分母重新计算，不能平均两个店铺的结果。

BP Library 的单店范围过滤所有含 `store_id` 的表。商品目录、汇率和其他共享表继续
显示，并带 `Shared scope / 共享范围` 标签。未分配的共享费用只进入全部店铺利润；
单店利润明确显示 `Shared costs unallocated / 公共费用未分摊`，不自动平均。

## 7. 第二家低流量新店

### 7.1 身份与商品

- `store_id`：`SYNTH-STORE-02`；
- 显示名：`Brazil Launch Store / 巴西新店`；
- 开店日期：2026-07-08；
- 商品：共享主店目录，只上架 `SYNTH-SKU-001`、`SYNTH-SKU-003`、
  `SYNTH-SKU-006`。

普通 UI 不显示 `Synthetic`、`Demo data` 或安全分类 banner；内部 ID、manifest 和
导出审计可以继续保留既有合成数据边界。

### 7.2 行为模型

第二家店不是主店数据的简单复制或固定倍数：

- 广告曝光和访问量总体处于主店同期对应商品的 10%–20%；
- 每天允许零订单，订单量低且有离散波动；
- 广告花费较低，部分日期只有曝光/点击，没有归因订单；
- 转化率不稳定，但不故意制造持续异常；
- 有独立订单号、库存快照、入库批次、出库、退款、平台费用和履约成本；
- 初始库存较少，但不把全部 SKU 设计为缺货；
- 2026-07-08 之前显示 `Not opened yet / 尚未开店`，不是 `Missing data`。

生成器使用固定种子和稳定 ID 命名空间。相同 seed 每次产生相同文件、行数、manifest
和分析结果。测试固定验证流量比例、上架 SKU、开店日期、零订单日和聚合守恒。

## 8. Ask BizPulse 的店铺范围

Chat principal 不再固定第一店。每次 turn 固定记录：

- 精确 `dataset_version_id`；
- 一个或多个 `store_ids`；
- period 和 currency；
- Operator 或 Viewer 会话权威；
- prompt preset 与实际发送文本审计。

选择全部店铺时，AI 可以比较两店，但只能使用服务器已经返回的跨店确定性事实；选择
单店时不能引用另一店。回答 UI 显示数据集、店铺、期间和 evidence refs。切换店铺后
旧对话继续可读但带原范围标签，新 turn 使用新范围。

AI 不执行：

- 原始表格读取；
- schema discovery 或任意 SQL；
- 上传、发布、重算或外部动作；
- 新品互联网搜索；
- 权威 KPI、Forecast、Profit 或 Action 数值生成。

## 9. 真实 AI 模型与输出

### 9.1 模型

批准模型为固定 snapshot：

```text
gpt-5.4-nano-2026-03-17
reasoning.effort = low
```

不使用可漂移 alias，不自动切换到 GPT-5.4 mini，不使用已 deprecated 的 GPT-5
mini/nano 或 GPT-5.3 Chat。若 nano 资格测试失败，停止发布并回到用户决策，不进行
无提示的付费 fallback。

官方模型资料：

- <https://developers.openai.com/api/docs/models/gpt-5.4-nano>
- <https://developers.openai.com/api/reference/overview#authentication>

### 9.2 输出长度

`2,800` 是单次最大输出 token 上限，不是目标长度。Prompt 目标为：

- 普通回答 400–800 tokens；
- 月度报告 900–1,600 tokens；
- 只有必要时接近 2,800 tokens。

输出必须满足完整 schema 后才能展示。达到上限导致结构不完整时返回明确错误，不展示
残缺报告，不自动续写或重复付费调用。

### 9.3 Provider attempt 语义

- 点击 preset 只填入文本，不产生 provider attempt；
- 完全未修改的已注册月报模板可跳过规划调用，只进行一次回答调用；
- 自由提问最多进行一次规划调用和一次回答调用；
- 超时或 provider outcome unknown 不自动重试；
- 每次 attempt 记录 input、output、reasoning（provider 可用时）、状态和范围，但不
  记录 Secret。

## 10. Azure Secret、预算与上线

### 10.1 Secret 路径

```text
用户持有的 OpenAI project key
  → 部署进程临时环境变量 BIZPULSE_DEPLOY_OPENAI_API_KEY
  → Bicep secure parameter
  → Azure Container Apps secret: openai-api-key
  → app environment secretRef: OPENAI_API_KEY
  → OpenAI Responses API
```

Key 不得进入：

- 浏览器或 API response；
- Git、设计稿、实施计划或 launch 参数文件；
- shell history、测试 snapshot 或日志；
- Azure readback evidence 的明文投影。

用户不需要在 BizPulse Settings 页面输入 Key，也不应在聊天中发送 Key。Key 创建、
轮换和撤销由 OpenAI 项目持有人完成。

### 10.2 应用硬预算

应用使用第 2 节批准的六项硬限制。月度 token budget 统计 provider 返回的全部可计量
token；预算达到阈值后在调用前 fail closed。单次上限提高到 2,800 不改变每月
150,000 总预算，只允许一份报告在总预算内更完整。

OpenAI 项目用量/成本视图作为第二层观察，不替代应用硬限制：

- <https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage>

### 10.3 发布顺序

严格顺序为：

1. 本地仅使用 fake provider 完成去重、多店铺、范围和 AI 失败状态测试；
2. 使用真实 nano 对 12 个固定合成问题执行有界资格测试；
3. 生成新的不可变镜像 digest 和值完备 release package；
4. 先以 AI disabled 发布去重与多店铺 revision；
5. Hosted 验证非 AI 页面、Operator/Viewer 权限、三范围和数据版本；
6. 通过部署环境临时注入 Key，创建 AI-enabled 新 revision；
7. 只执行一次 Hosted 月报 smoke；
8. 核对范围、事实、evidence、token ledger 和 OpenAI 项目用量；
9. 保留上一健康 AI-disabled revision 作为立即回退目标。

12 个模型资格问题由两种语言 × 三个店铺范围 × 两种问题构成：月度销售报告和库存
风险解释。每条必须满足结构、范围、数值、引用和长度合同。

### 10.4 关闭与回滚

- 预算、限流或 provider 故障只关闭 Chat，不影响确定性页面和 Action Sandbox；
- 行为异常时先将 `BIZPULSE_AI_CHAT_ENABLED=false` 发布为新 revision；
- Key 泄露或无法解释的调用同时触发 OpenAI Key 撤销；
- 不重放旧上线包，不用旧部署 SHA 作为 changed-path baseline；
- 任何 rollback 都使用已验证的精确 revision/image，而不是模糊的“上一版”。

设计批准确认了最终 Azure Demo 目标，但不把本文变成包含 Secret 和精确资源值的
launch authorization。实际云端 mutation 仍须通过仓库现有 release-control、精确
目标 preflight 和值完备发布包。

## 11. 前端行为

### 11.1 导入质量

- Operator 上传预览增加去重和冲突摘要；
- Viewer 仍不能上传个人文件；
- 冲突阻止提交按钮并提供 CSV，不增加无行为按钮；
- 完全重复可继续提交，页面说明实际保留行数；
- 所有数字 UI 延续两位小数规则，导出和计算精度不变。

### 11.2 店铺范围

- 选择器支持 English / 中文、键盘和 screen reader；
- 当前范围始终可见，不藏在 Settings 内；
- 加载新范围时保留旧内容直到新内容成功，避免空白闪烁；
- 请求使用 generation fence，快速切换时旧 response 不能覆盖新范围；
- 无数据的新店历史显示“尚未开店”，不显示误导性零增长或错误。

### 11.3 AI 状态

Settings 只显示 AI 可用性、模型类别、预算/限流状态和权限说明，不显示 Key、Secret
名称或完整内部配置。Chat 分别本地化：

- unavailable；
- budget exhausted；
- rate limited；
- busy/concurrency reached；
- provider timeout；
- provider outcome unknown；
- insufficient evidence；
- response incomplete。

不使用预录答案冒充真实 AI，不把失败自动改写为成功文案。

## 12. 错误和失败边界

| 场景 | 行为 |
|---|---|
| 完全重复行 | 自动保留一行并增加去重计数 |
| 同键不同值 | 阻止整个新版本，展示冲突并允许下载 CSV |
| 多店表缺少店铺 | 要求 Operator 指定单店或补齐列；不猜测 |
| 非法/过期店铺范围 | 拒绝请求并回到该版本的安全默认范围 |
| 新店开店前期间 | 显示尚未开店，不伪造零值趋势 |
| 单店有未分配共享成本 | 明示排除，不平均分摊 |
| AI 预算耗尽 | 禁用发送；确定性页面继续工作 |
| AI 超时/结果未知 | 不自动重试，不重复收费 |
| AI 输出截断/结构错误 | 不展示残缺报告，记录受控失败 |
| Azure AI revision 不健康 | 回退精确 AI-disabled revision |

## 13. 测试与验收

### 13.1 去重

- 每个业务键角色至少覆盖完全重复、同键冲突和不同键保留；
- 覆盖同文件、跨 sheet、跨文件以及当前版本与新上传之间的重复；
- 覆盖数值/日期标准化后的相等；
- 冲突失败后数据版本、发布版本、分析和对象状态不变；
- 质量计数与冲突 CSV 行数、来源和字段一致；
- property-based 或等价组合测试证明去重幂等。

### 13.2 多店铺

- 生成器相同 seed 输出逐字节稳定；
- 新店只包含三个批准 SKU，2026-07-08 前无营业行；
- 广告流量处于批准区间并包含零订单日；
- 主店、新店、全部店铺的数量守恒；
- 比例 KPI 用合并分子/分母重算；
- 三范围的分析 artifact 与精确数据版本绑定；
- Viewer 切换范围不创建 canonical dataset、发布或全量分析行。

### 13.3 前端

- 顶部选择器控制全部七个产品区域；
- 中英文、键盘、窄屏和无横向页面溢出；
- 快速切换不会发生旧范围覆盖；
- Library 正确区分店铺表和共享表；
- Action 切换范围后清空未保存输入；
- 金额和普通小数显示最多两位，原始精度不变。

### 13.4 AI 与安全

- fake provider 覆盖六项预算、并发、超时、结果未知和截断；
- 浏览器 bundle、HTML、API response 和日志不包含 Key；
- provider input 不含原始表格、凭证、schema discovery 或任意 SQL；
- Chat scope 与选中的 dataset/store/period/currency 完全一致；
- 12 个真实 nano 资格问题全部通过；任一失败即停止 AI 发布；
- Hosted smoke 只执行一次且用量可在应用 ledger 和 OpenAI 项目中对应；
- disable/revoke 路径有演练证据。

## 14. 明确非目标

- 不移植旧 CAPTSONE 完整多店铺 Portfolio 系统；
- 不实现共享库存池、跨店调拨或共享成本自动分摊；
- 不实现长期店铺别名学习或模糊身份匹配；
- 不实现新品联网搜索、外部 marketplace API 或网络工具；
- 不训练、fine-tune 或“预训练”模型；
- 不让 Viewer 上传个人表格或触发大规模计算；
- 不让 AI 生成权威 KPI、Forecast、Profit 或 Action 数值；
- 不做自动模型 fallback、自动付费重试或无上限输出；
- 不把本地通过、镜像构建、Azure accepted、URL 可访问、Hosted verified 和
  Production ready 混为一谈。

## 15. 完成标准

只有同时满足以下条件，才可描述为本设计完成：

1. 重叠数据自动去重，冲突数据 fail closed，旧版本不变；
2. 主店、新店和全部店铺范围贯穿全部指定页面、计算、Action 和 AI；
3. 第二家店数据符合开店日期、三个 SKU、低流量和确定性约束；
4. Operator 现有上传、计算、发布和导出功能不回归；
5. Viewer 保持无上传、无发布、无大规模计算权限；
6. nano 资格测试全部通过，Key 只存在服务器 Secret 路径；
7. Azure 先验证 AI-disabled revision，再验证 AI-enabled revision；
8. Hosted 月报 smoke、预算 ledger、用量观察和回退证据完整；
9. 文档准确区分 Implemented、Locally verified、Deployed、Hosted verified、
   Azure Demo accepted 和 Production ready。
