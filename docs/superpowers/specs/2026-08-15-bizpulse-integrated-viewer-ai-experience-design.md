# BizPulse NEWCaostone 一体化展示与 AI 交互设计

状态：已确认范围的修订稿，待用户复核

日期：2026-08-15（America/Chicago）

文档版本：1.1

目标仓库：`/Users/maxli/Desktop/NEWCaostone`

视觉参考：`/Users/maxli/Desktop/CAPTSONE`

## 1. 目的

本稿把 2026-08-15 已确认的视觉、Viewer、数据、AI 和交互决定整合为
一份可以直接进入实施计划的产品设计。目标是：

1. 把 CAPTSONE 已建立的产品视觉语言迁移到 NEWCaostone；
2. 保留 NEWCaostone 当前已经实现的业务功能、安全边界和证据链；
3. 把公共 Viewer 调整为低负载但有真实交互感的产品体验；
4. 把 Ask BizPulse 设为 Viewer 的主要可玩能力，并加入可见、可编辑的
   快捷提示词；
5. 让动作卡可以在会话内模拟，但不重新运行大规模分析；
6. 让 Operator 保留完整导入、计算、发布、导出和结果复盘能力；
7. 恢复以用户上传表格合并形成的 BP 标准资料库、设置页和保存视图；
8. 统一用户界面的数字精度、语言、登录文案和视觉质量；
9. 用信息密集、可逐层展开的经营总览和 P 级库存清单取代低信息量展示。

本稿只定义产品和实施边界。它不代表功能已经完成、已经部署、Azure
已经验收或已经达到 Production readiness。

## 2. 与既有设计的关系

本稿整合并补充以下既有文档：

- `docs/superpowers/specs/2026-08-13-newcaostone-demo-single-operator-design-v0.2.0.md`；
- `docs/superpowers/specs/2026-08-15-capstone-frontend-visual-migration-design.md`。

安全、会话隔离、服务端身份、确定性数值权威和人工批准原则仍由
`v0.2.0` 约束。CAPTSONE 视觉 token、无障碍、响应式和数字显示基础继续
沿用视觉迁移设计。

本稿在下列范围内覆盖较早的交互提案：

- Viewer 显示完整的上传入口外观和独立的 `Import demo data`；个人文件选择或
  拖放会明确提示不可用，只有内置 Demo 数据导入能够继续；
- `Import demo data` 只把当前 Viewer 会话绑定到共享、已经标准化和预计算的
  内置版本，不为每名 Viewer 复制资料或重跑大规模计算；
- Viewer 不触发导入、标准化、全量分析、预测或利润重算；
- Viewer 保留 Ask BizPulse 和会话级 Action Sandbox；
- 顶部不显示截图中的 `Synthetic Demo Data / 纯合成演示`、`Period
  unavailable / 期间不可用`、`v2`、`BRL` 胶囊组合；
- Ask BizPulse 快捷按钮采用“填入后由用户主动发送”，不采用自动发送；
- Operator 上传不要求勾选“纯合成数据”或数据授权确认框；
- 普通产品 UI 不显示 `Pinned`、schema、digest、hash 或无上下文的 `v1`；
- Operator 账户改名、改密码或多账户建设暂不纳入本稿。

## 3. 已确认决定

### 3.1 视觉与页面范围

- 范围采用此前选择的 **B**：公共欢迎页、登录页、Viewer 和 Operator
  应用共同改造。
- 视觉方向采用此前选择的 **A**：CAPTSONE Product Theater 延伸方案。
- 视觉迁移只复用色彩、排版、间距、卡片、图表、导航、状态和证据呈现，
  不把旧前端业务代码整包复制进 NEWCaostone。
- 登录页采用固定登录表单加定时多画面产品展示。
- `Operator sign in` 全部改为 `Sign in`；中文为 `登录`。
- 用户界面不显示 `Course Demo`、`Synthetic Demo Data`、`纯合成演示`
  等课程或技术实现用语。
- 所有可见导航和按钮必须有实际行为；尚未实现的伪入口不显示。

### 3.2 Viewer

- Viewer 在 Data Workspace 看到自定义上传区和 `Import demo data`。点击上传区
  或拖入个人文件只显示本地化的不可用说明，不读取或发送该文件；点击
  `Import demo data` 才绑定已经发布并预计算完成的三个月示例数据。
- Viewer 可以查看完整分析页面、证据、Ask BizPulse 和 Action Inbox。
- Viewer 可以查看由内置表格合并形成的只读 BP 资料库、数据覆盖和版本历史。
- Viewer 可以模拟 `Review`、`Adjust`、`Approve`、`Dismiss`。
- Viewer 不可以读取/发送个人文件，也不可以执行真实 import pipeline、字段映射、
  标准化、提交数据版本、发布版本、运行全量分析、重新预测、重新计算 Profit
  Bridge、导出正式文件或登记真实结果。`Import demo data` 只执行第 8 节定义的
  共享版本会话激活。
- Viewer 的 Chat、草稿和动作修改只属于当前会话，到期或主动结束后清理。

### 3.3 Operator

- Operator 保留当前完整数据工作流：上传、识别、字段映射、标准化、质量
  预览、原子提交、版本库、分析、预测、利润、行动卡、发布、导出和结果
  复盘。
- Operator 支持自定义中英文上传区、点击选择、多文件拖放、待上传队列、逐文件
  校验、移除和重试；上传流程没有任何“纯合成数据”或授权确认框。
- Operator 可上传其有权处理且符合格式约束的经营资料；前端不能用 Viewer 的
  Demo 限制阻断 Operator 的真实导入、计算或资料库工作流。
- Operator 的登录、CSRF、服务端授权、会话和持久化规则不因视觉迁移而
  弱化。
- 当前唯一登录名仍可为 `operator`。密码轮换、用户名变化和多账户属于
  后续独立安全任务。

### 3.4 AI

- Ask BizPulse 使用服务器端专用 OpenAI Key；浏览器永远看不到、输入、
  保存或记录 Key。
- AI 只能解释和组织确定性事实；不能成为数值、数据版本或操作执行权威。
- 快捷提示词按钮只把模板放入 Chat 输入框，用户可以修改，最后自己按
  `Send`。
- 点击快捷按钮本身不发请求、不占 AI 次数、不消耗 token。
- 最终目标展示环境需要 AI 可用；本设计不授权创建 Key、付费调用或部署。
- Settings 只显示 AI `已连接/未配置/暂不可用` 状态；Key 始终由服务器安全
  配置，不返回浏览器，也不在本稿中重复实现相邻任务的凭据能力。

### 3.5 数字显示

- BRL 金额固定显示两位小数。
- 普通小数、比率、天数和评分最多显示两位小数。
- 订单数、件数和要求整数的数量不显示小数。
- 百分比显示两位小数并保留正确量纲。
- 只在最终 UI 显示层舍入；数据库、API、Decimal 计算、公式、证据、导入
  预览和导出精度不变。

### 3.6 当前证据基线

本稿 1.1 修订时核对的活动实现快照为
`e7c47864cb987bd4f1b2cf9fdc6c22bcbead48c0`。该本地实现线已经包含统一暖色
Product Theater、三个月共享数据、Viewer/Operator 会话、Operator 导入和发布、
Overview、Sales、Inventory、Profit、确定性 Forecast、Profit Bridge、Ask
BizPulse 提示词草稿、月报工具和 Action Sandbox。它不等于本稿 1.1 新增体验
已经实现。

1.1 修订前的浏览器核对发现：Viewer 上传和 `Import demo data` 被旧约定移除；
Operator 上传仍要求“纯合成数据”并只有原生单文件 input；Overview 退化为四个
KPI 和空图表；Evidence 全部展开；桌面侧栏只显示缩写；当前前端没有 Settings
和 BP Library；库存使用单段大红图；`Pinned`、schema、digest 和 `v1` 暴露在
普通 UI。第 5、7、8、11 和 16 节把这些明确列为未实现修订，而不是把现有本地
验收误写成完成证据。

当前状态文档记录的 Azure 版本仍为 AI-disabled，且 Hosted 浏览器、容量、自然
过期、重启读回和回滚证据尚未全部完成。相邻任务可能继续推进该实现线，因此
实施计划必须重新读取最新 commit、状态、测试和部署权威，不能把上述快照当作
永久基线。

## 4. 方案选择

### 4.1 采用：统一产品壳 + 分权工作流 + BP 资料库 + 共享预计算 + 服务端 AI

该方案把系统分成五个清晰边界：

1. **产品壳**：复用 CAPTSONE 视觉语言，统一导航、语言、Evidence、响应式和
   Settings 入口，不复制旧业务实现；
2. **Viewer 激活层**：个人上传 fail-closed，`Import demo data` 只绑定共享发布
   版本和只读资料库；
3. **Operator 工作流层**：多文件队列、标准化、资料库版本、分析、发布和导出
   继续通过明确的授权 API；
4. **会话交互层**：每个 Viewer 只保存少量 Chat、偏好和 Action 覆盖记录；
5. **AI 层**：提示词预设、查询白名单、证据和预算均由服务器控制。

优点是保留真实产品流程感，同时避免为每名观众复制文件、数据和分析结果。

### 4.2 不采用：为每个 Viewer 复制三个月数据并重新计算

这会重复占用 PostgreSQL、Blob、CPU 和工作进程，且容易因为并发导入造成
超时。它不能给观众带来与成本相称的额外体验。

### 4.3 不采用：只在前端写一个自由提示词按钮

纯前端模板容易与服务器查询能力不一致。“生成本月销售报告”可能只命中
一个单指标工具，得到不完整报告，也难以固定数据期间和证据范围。

### 4.4 不采用：一次报告串行调用多个 AI Agent 或全量分析

多 Agent、多工具重算或重新读取原始文件会增加延迟、费用和失败点，不符合
Viewer 低负载目标。月报使用一个有界的预计算报告包和一次受控解释调用。

## 5. 视觉系统

### 5.1 视觉语言

继续采用 CAPTSONE 的工作台风格：

- 暖白页面背景 `#f6f5f1`；
- 白色数据卡片和细灰边框；
- 紫色 `#534ab7` 用于选择、焦点和主操作；
- 绿色、琥珀色和红色只表示业务状态；
- 56px 桌面导航轨和紧凑分析卡片；
- 8–10px 应用卡片圆角；
- 16–20px 欢迎页和登录页产品画面圆角；
- 图表优先展示业务关系，不使用无含义的装饰图。

### 5.2 应用骨架

桌面应用由以下区域组成：

1. 左侧可展开导航：桌面默认显示完整名称，紧凑状态保留图标或简称，并在
   hover 和键盘 focus 时显示完整本地化 tooltip；
2. 顶部页面标题、数据更新时间、语言选择和会话操作；
3. 必要时显示二级导航；
4. 紧凑 KPI、图表、表格和行动卡内容区；
5. 从右侧打开的统一证据抽屉。

保留六个主区域：

| 主区域 | 保留能力 |
|---|---|
| Data Workspace | Viewer Demo 导入和只读资料库；Operator 上传、Library、Exports |
| Today Overview | KPI、趋势、数据准备状态、异常和证据 |
| Sales & Advertising | 销售、广告、对比、趋势和 SKU 表现 |
| Inventory & Replenishment | 库存风险、补货与相关证据 |
| Profit & Cost | 成本、利润、Profit Bridge 和对账 |
| AI Decision Center | Ask BizPulse、New Product Forecast、Action Inbox |

`Product Opportunities`、`Favorites` 和 `Operating Advice` 在没有工作页面前
不显示为导航项。

语言选择在欢迎页、登录页以及进入后的 Viewer 和 Operator 中始终可发现。
桌面端显示 `English / 中文` 菜单，紧凑导航可以显示 `EN / 中`，但 accessible
name 和 tooltip 必须完整。选择保存到既有语言偏好，并立即重新渲染当前业务
页面、动态状态、上传区、错误和证据；不能只修改导航文字。

### 5.3 顶部上下文

删除截图所示的一整排技术胶囊：

- 不显示 `Synthetic Demo Data / 纯合成演示`；
- 不显示没有解释价值的独立 `v2`；
- 不显示 `Period unavailable / 期间不可用`；
- 不把 `BRL` 单独放成悬浮胶囊。
- 不显示 `Pinned <hash>`、`synthetic.v1`、content digest、schema 名称或没有
  业务语境的 `Current v1`。

真正有用的上下文放到对应位置：

- 数据期间显示在页面标题、筛选器或报告标题中；
- 币种和单位显示在金额、表头或图表轴上；
- 数据版本只在 BP 资料库的“版本历史”中以 `数据版本 1` 等友好名称出现；
- hash、schema、digest 和内部 release ID 不进入常规产品 UI，只保留在后端、
  审计和开发诊断证据中；
- 当数据期间缺失时显示具体的安全错误，而不是常驻标签。

需要说明数据性质时，只使用 `Sample data / 示例数据`，放在帮助说明或证据
限制中；不在每个页面重复，也不使用 `Course Demo` 或 `纯合成演示`。
任何页面同样不得宣称真实市场、实时数据或 Production。

### 5.4 数字显示合同

| 类型 | UI 规则 | 示例 |
|---|---|---|
| BRL | 固定两位小数 | `R$ 1,234.50` |
| 金额变化 | 固定两位小数并显示符号 | `−R$ 42.10` |
| 订单、件数、整数数量 | 零位小数 | `168 units` |
| 普通小数、倍数、评分 | 最多两位小数 | `1.2×`, `0.99` |
| 比例型百分比 | 转换后固定两位小数 | `5.00%` |
| 天数与覆盖 | 最多两位小数 | `3.25 days` |
| 缺失、未知或无效 | 明确显示不可用 | `Unavailable` |

格式化只能根据字段的已知语义执行，不能靠字符串标签猜单位。AI 自然语言不
使用正则强行改小数；AI 卡片中的结构化事实使用统一 formatter。

### 5.5 Evidence 密度

- 每个页面的 Evidence 区默认收起，只显示按既有稳定顺序排列的前四条；
- 收起状态显示 Evidence 总数和 `展开全部 / Show all`；展开后提供
  `收起 / Show less`；
- 每条仍能打开统一右侧抽屉查看证据状态、计算基础和来源；
- Evidence 不因收起而丢失，键盘、屏幕阅读器和深链接行为保持可用；
- 图表的屏幕阅读器摘要使用 visually-hidden 样式，不能与可见 caption 重复
  出现两遍。

### 5.6 Today Overview 信息架构

当前只有四张指标卡且没有图表的 Overview 不满足本稿。新的 Overview 是分层
经营工作台，至少包括：

1. 店铺、期间、比较期间、币种和数据更新时间；
2. 销售、订单、ROAS、广告投入、贡献利润和库存风险 KPI；
3. 销售与广告趋势、利润变化等确有比较关系的分析图；
4. 数据覆盖/准备状态、成本和库存缺失提示；
5. 按 P 级排序的前四条紧急库存或补货事项；
6. 重点异常、待处理 Action 和 Ask BizPulse 入口。

图只在能表达趋势、比较、构成变化或驱动关系时出现。单一非零分类不得用一张
大面积图重复一个数字。

### 5.7 Inventory & Replenishment 主视图

库存风险分布的大红色单段图删除。主视图恢复确定性 P 级列表：

- `P0`：已经缺货、已经错过最晚下单日，或预计在补货 lead time 内缺货；
- `P1`：需要在当前 review cycle 内下单；
- `P2`：未来需要补货但不紧急；
- `Monitor`：目前无需补货，继续观察；
- `Unavailable/Excluded`：证据不足或明确排除，不能伪装成低风险。

列表默认按 `P0 -> P1 -> P2 -> Monitor -> Unavailable` 排序，同级按覆盖天数
升序和稳定 SKU 顺序排列。顶部显示各级数量并提供筛选。每行或卡片只展示
SKU、商品名、可用库存、日均销量、当前/预计覆盖天数、预计缺货日、建议补货
量、优先级原因、Evidence 和 `模拟处理`。Overview 只显示最紧急的前四条并
链接到完整列表。

### 5.8 Settings

恢复一个精简但真实工作的 Settings 页面，不照搬旧页面的技术外壳：

| 设置 | Viewer | Operator |
|---|---|---|
| 语言、侧栏显示 | 当前会话或本地偏好 | 持久个人偏好 |
| 默认店铺、期间、比较期间 | 当前会话 | 持久个人偏好 |
| 报告币种、时区 | 只读 Demo 默认值 | 可维护报告默认值 |
| Overview KPI 显示与排序 | 当前会话 | 持久个人偏好 |
| Today / Action 保存视图 | 会话内临时 | 创建、应用、改名、更新和删除 |
| 月度收入、订单、ROAS、利润目标 | 只读示例 | 创建修订、恢复和归档 |
| AI 状态 | 显示可用性 | 显示连接状态，不显示 Key |

两位小数是全局显示合同，不作为用户设置。Operator 用户名、密码修改和多账户
仍不进入本轮。

## 6. 公共欢迎页与登录页

### 6.1 公共欢迎页

`/` 是产品介绍和 Viewer 入口，不是登录表单。

- 左侧展示品牌、价值主张、简短说明和两个动作；
- 右侧展示四页 Product Theater；
- 主动作：`Explore BizPulse / 体验 BizPulse`；
- 次动作：`Sign in / 登录`；
- 不出现 `Course Demo`、`Operator sign in` 或技术环境名称；
- 不使用真实产品照片、真实业务截图或外部图片 CDN。

建议标题：

> See the signal. Decide with evidence.

### 6.2 登录页

`/login` 使用两栏布局：

- 一侧为位置固定、不会随轮播移动的登录表单；
- 一侧为较紧凑的 Product Theater；
- 页面标题、按钮和公共入口统一使用 `Sign in / 登录`；
- 字段显示名使用 `Account / 账户` 与 `Password / 密码`；
- 保留原有 autocomplete、提交、错误、安全 cookie 和重定向行为；
- 手机端先展示定高产品画面，再展示登录表单，避免布局跳动。

### 6.3 四页定时展示

公共欢迎页与登录页复用同一个控制器和同一组本地资源：

1. Today Overview：销售、广告、利润趋势和优先信号；
2. Profit Bridge：期间变化和对账状态；
3. Inventory & Forecast：库存风险和 7/30/90 天范围；
4. Ask BizPulse：问题、证据化回答、限制和下一步行动。

行为规则：

- 每 6 秒切换；
- 支持箭头、进度点、键盘和触控滑动；
- hover、键盘焦点、手动操作或页面不可见时暂停；
- 手动切换后重新开始计时；
- 动画只用淡入淡出、小幅平移、轻微渐变和进度；
- `prefers-reduced-motion` 下停止自动播放和透视效果；
- JavaScript 或后续图片失败时，第一张静态画面和入口仍可使用；
- 四张共享 SVG/WebP 总预算原则上不超过 500 KiB。

## 7. 三个月内置数据设计

### 7.1 数据范围

Viewer 使用一个版本化、不可变、共享的三个月展示数据版本。首个版本覆盖
三个完整自然月，建议为 `2026-05-01—2026-07-31`，以现有 2026 年 7 月
文件为基准，5 月和 6 月由同一确定性生成规则补齐。

三个月足以展示：

- 月度环比；
- 销售和广告趋势；
- SKU 排名和变化；
- 库存消耗与补货风险；
- 成本、利润和 Profit Bridge；
- AI 月报和行动建议。

如果 FIFO 或期初库存需要更早批次，只增加早于 5 月的最小收货批次，不把
更多月份的完整日销售复制到 Viewer。

### 7.2 复用现有文件

数据建设优先复用用户提供的七份文件：

- `bizpulse_demo_daily_sales_performance_20260701-20260731.xlsx`；
- `bizpulse_demo_inventory_reported_velocity_20260702-20260731.xlsx`；
- `bizpulse_demo_inventory_snapshot_20260731.xlsx`；
- `bizpulse_demo_operations.xlsx`；
- `bizpulse_demo_overall_advertising_20260701-20260731.csv`；
- `bizpulse_demo_sales_by_variant_20260701-20260731.xlsx`；
- `bizpulse_demo_sales.csv`。

实施前先确定每个 source role 的唯一权威文件。`bizpulse_demo_sales.csv` 如果
与日销售或 variant 文件重复，只作为兼容/生成来源，不作为第二份事实输入。

### 7.3 只新增一个成本工作簿

为了补齐成本并减少文件数量，新增一个可复用工作簿：

`bizpulse_demo_costs.xlsx`

建议包含三个 sheet：

| Sheet | 最小字段 | 用途 |
|---|---|---|
| `sku_costs` | SKU、variant、币种、生效日期、产品成本、头程/落地成本 | 单位成本与期间成本 |
| `inventory_receipts` | 收货日期、SKU、批次数量、单位落地成本 | FIFO、期初库存和补货现金 |
| `platform_fees` | 生效日期、店铺/平台、佣金率、履约费、支付费 | 利润和费用解释 |

所有 SKU、日期、数量和币种必须能与现有销售、库存和 operations 文件确定性
关联。不能用零成本填空，也不能为了让利润好看而反向调整成本。

### 7.4 共享与预计算

数据只保存一份：

```text
版本化源文件/生成种子
  -> 一次导入、标准化和质量验证
  -> 一个不可变发布版本
  -> 预计算 Sales、Ads、Inventory、Profit、Forecast、Action 基线
  -> 所有 Viewer 只读同一发布版本
```

每个 Viewer 会话不复制 Excel、CSV、标准化行、分析快照或 Blob。会话只保存：

- 会话和固定发布版本标识；
- 有界 Chat turn；
- 有界 Action simulation 覆盖记录；
- 必要的幂等、限流和清理元数据。

这使“几个月数据”主要占用一次持久化空间，而不是随观众人数倍增。

### 7.5 BP 标准资料库

Data Workspace 恢复三个一等子页面：`Upload / Library / Exports`。Library
不是原始文件清单，而是用户表格经过识别、映射、标准化和合并后形成的 BP
权威资料库：

```text
一个或多个 CSV/XLS/XLSX
  -> source role 识别与字段映射
  -> 质量校验和标准化候选
  -> 按店铺、SKU、日期和币种合并
  -> 不可变 BP 数据版本
  -> 分析、Evidence、AI read model 和 Exports
```

资料库至少显示报表类型、来源文件、店铺/SKU/期间覆盖、行数、质量和缺失、
当前友好版本、历史版本、预览、provenance、关联分析/Evidence 和导出。原始上传
仍是临时处理输入；长期保留的是标准化数据版本、分析产物、证据和导出。

Viewer 的 Library 使用内置 Demo manifest，完整只读；Operator 的 Library
来自实际上传并允许版本管理、发布和导出。Viewer 和 Operator 的分析页面都
必须读取各自明确选择的数据版本，不能继续显示与当前资料库无关的冻结 seed。

## 8. Viewer 体验和权限

### 8.1 进入流程

```text
Explore BizPulse
  -> 创建独立、到期的 Viewer 会话
  -> 进入 Data Workspace
  -> 个人文件上传入口可见但不可用于 Viewer
  -> 点击 Import demo data
  -> 会话绑定当前共享三个月发布版本和只读 BP 资料库
  -> 进入 Today Overview
  -> 查看分析、证据、Ask BizPulse 和 Action Sandbox
```

`Import demo data` 是真实、幂等的会话激活操作，不是假按钮；它不得复制数据或
触发大规模分析。界面显示 `正在准备 Demo workspace / Preparing demo
workspace` 和实际完成状态，不能虚构“重新计算中”。完成后读取已经预计算的
Sales、Ads、Inventory、Profit、Forecast、Action 和 Evidence。

### 8.2 Viewer 可执行动作

- 浏览六个主区域及其已支持子页面；
- 点击 `Import demo data` 并查看只读 BP 资料库；
- 切换合法筛选条件；
- 打开证据抽屉；
- 使用 Ask BizPulse；
- 创建会话内行动草稿；
- 对 Action Card 执行 `Review`、`Adjust`、`Approve`、`Dismiss`；
- 修改允许的补货数量和广告预算；
- 重置本会话模拟。

### 8.3 Viewer 禁止动作

- 读取、解析、发送或保存 Viewer 自己选择/拖入的文件；
- 字段映射、标准化、质量提交或数据版本 commit；
- 运行或重跑销售、广告、库存、利润、Forecast 或 Profit Bridge；
- 发布公共版本；
- 下载正式采购/广告执行文件；
- 写入 Operator Action Card；
- 记录真实 outcome；
- 调用外部平台或执行真实业务操作。

Viewer 的上传入口是一个有意保留的产品边界说明：点击选择或拖放时，本地立即
显示 `Demo Viewer 不支持上传自己的文件 / Personal uploads are unavailable
in Viewer`，不读取文件内容、不建立 FormData、不调用 Operator API。旁边的
`Import demo data / 导入 Demo 数据` 是唯一可继续的导入动作。

### 8.4 上传控件和双语规则

- 隐藏浏览器原生 file input 的可见外观，使用自定义、可键盘操作的上传区；
- 英文：`Drag CSV/XLS/XLSX files here, or choose files`；
- 中文：`拖拽 CSV/XLS/XLSX 文件到这里，或选择文件`；
- 正常情况完整支持中英文；若 catalog 意外缺键，固定回退英文，不能回退到
  浏览器/操作系统产生的混合语言；
- Operator 可一次选择或拖入一个或多个文件，先进入待上传队列；
- 队列显示文件名、大小、类型校验、状态、进度、移除和安全重试；
- 拖放只负责选择，不静默开始网络上传；用户执行明确的上传动作后才发送；
- 上传区、按钮、校验、进度和错误只显示当前选择语言，不把中英文拼在一起；
- 上传流程没有“纯合成数据”确认，也没有“我确认有权处理数据”确认框。

## 9. Action Sandbox

### 9.1 原则

Action Sandbox 提供真实交互手感，但它不是第二套分析系统。服务器的原始
建议、证据、预测和影响值保持不可变；Viewer 修改只形成当前会话的覆盖层。

### 9.2 允许的轻量估算

`Adjust` 后可以即时显示下列白名单估算：

- `采购现金估算 = 模拟数量 × 已加载单位成本`；
- `预算变化 = 模拟预算 − 基线预算`；
- 当预计算日销量可用时，`新增覆盖天数 = 模拟数量 ÷ 预计算日销量`。

所有结果标记为 `Simulation estimate / 模拟估算`。它们只能读取页面已加载的
权威标量或一个有界读模型，不扫描数据库、不读取原始文件、不调用 AI，也不
触发完整分析。

如果单位成本、币种或日销量缺失，显示 `Unavailable`，不能使用零值替代。

### 9.3 不允许的重计算

Action 修改不会更新：

- Today Overview KPI；
- Sales & Advertising 趋势；
- Inventory 分析权威结果；
- 确定性 Forecast；
- Profit 或 Profit Bridge；
- Action Card 原始影响和证据；
- Operator 或其他 Viewer 的任何状态。

### 9.4 生命周期

每条 Viewer 覆盖记录包含 session、action、command、修改字段、时间和基线
revision。页面以 `My simulation / 我的模拟` 展示历史。会话结束、到期或版本
失效时清理全部覆盖记录和未保存 Chat。

## 10. Ask BizPulse 快捷提示词

### 10.1 页面布局

Ask BizPulse 继续位于 AI Decision Center 的默认子页面。Chat composer 从上到
下包括：

1. `Quick tasks / 快捷任务`；
2. 快捷提示词按钮；
3. 可编辑多行输入框；
4. `Send / 发送`；
5. 配额、错误或进行中状态；
6. 当前会话回答历史。

首批按钮：

- `Generate this month's sales report / 生成本月销售报告`；
- `Explain profit changes / 分析利润变化原因`；
- `Find inventory risks / 查找库存风险`；
- `Summarize advertising performance / 总结广告表现`；
- `Summarize the 30-day forecast / 总结未来 30 天预测`；
- `Prioritize next actions / 给出下一步行动建议`。

桌面端使用两到三列的紧凑按钮网格，手机端改为单列或可换行布局。按钮是标准
`button`，不是不可聚焦的标签胶囊。

### 10.2 采用的交互 A

点击按钮时：

1. 从服务端返回的版本化目录取得对应模板；
2. 把完整模板填入输入框；
3. 把焦点移动到模板末尾；
4. 不自动发送；
5. 不调用 AI、不增加 attempt、不消耗 token；
6. 用户可修改后自己点击 `Send`。

输入框已经有未发送文字时，不静默覆盖。页面显示 `Replace current draft? /
替换当前草稿？`，只有用户确认后才替换。

### 10.3 模板示例

“生成本月销售报告”的中文模板：

> 请根据当前数据版本所覆盖的月份生成销售报告。包括净销售额、订单量、
> 销量、广告表现、主要变化、重点 SKU、异常与风险、数据限制，以及下一步
> 行动建议。所有数字必须引用现有证据；缺失信息必须明确说明，不得补造。

英文模板具有相同语义。UI 只填入当前选择语言的版本，避免在一次请求中重复
发送双语文本。

### 10.4 服务端提示词目录

快捷模板不是前端散落的字符串。服务器提供一个有版本的只读目录，每项至少
包含：

- `id`；
- 本地化 `label`；
- 本地化 `template`；
- `template_version`；
- 合法 context kind；
- 对应的确定性查询/报告意图；
- 输入长度和可用状态。

客户端保存本次选择的 preset ID 和 template version。发送时同时提交用户实际
可见的文字：

- 模板未修改：服务器验证 ID、版本和模板摘要后使用固定安全计划；
- 模板被修改：服务器把它作为普通自由问题，继续通过现有白名单 planner；
- ID、版本、内容或 context 不一致：失败关闭，不猜测意图。

历史记录显示用户实际发送的文字，不能只显示隐藏 ID。

### 10.5 月度销售报告包

当前 Chat 一次只允许一个注册查询计划，因此“本月销售报告”不能依靠模型随意
串联多个查询。增加一个只读、有界的月报 read model，读取已经完成的快照：

- 实际数据期间和币种；
- 净销售额、订单、销量和 AOV；
- 广告支出及当前已有的效率指标；
- 日趋势和上期对比；
- Top/Bottom SKU；
- 已有异常、数据覆盖和限制；
- 与这些事实直接相关的 Action 基线。

该 read model 不重新导入、不重新标准化、不重新计算分析，只组合当前发布版本
的预计算事实。它受只读事务、statement timeout、最大事实数、最大证据数和
响应大小限制。

AI 只把报告包组织为：

1. Executive summary；
2. KPI 摘要；
3. 趋势和广告表现；
4. SKU 亮点与风险；
5. 数据限制；
6. 有证据的下一步行动建议。

报告标题使用发布版本实际期间，例如 `2026 年 7 月销售报告`，不能把系统日期
所在月份误当成数据月份。

### 10.6 AI Key、费用与失败边界

- Key 只存在于服务器端 secret；
- 浏览器只得到 `available/unavailable`、有界配额状态和安全错误；
- 同一会话同时最多一个进行中请求；
- 使用服务器端分钟、日、月、token、费用和全局并发上限；
- 不使用静态假回答冒充成功；
- AI 不可用时，确定性看板和 Action Sandbox 继续工作；
- AI 不可用时，快捷按钮、输入框和发送按钮保持可辨认但禁用，并显示一个明确
  原因；它们不能表现得像可以点击但没有反应；
- 超时、预算、限流、证据不足和 provider outcome unknown 有不同提示；
- 只有 `Send` 成功进入请求流程后才计入 attempt。

## 11. Operator 完整工作流

Operator 的主流程保持：

```text
Sign in
  -> 点击选择或拖放多个文件到队列
  -> 上传文件
  -> 识别 source role 与字段映射
  -> 标准化和质量预览
  -> 合并并原子提交 BP 资料库版本
  -> 运行确定性分析/Forecast/Profit Bridge
  -> 复核证据和 Action Card
  -> 发布 Viewer 使用的版本
  -> 导出人工复核文件
  -> 登记 outcome 与复盘
```

Operator 上传接受应用明确支持的 CSV/XLS/XLSX source role。浏览器先做类型和
大小提示，服务器仍执行权威媒体类型、大小、内容、映射和质量验证。每个文件
保留独立状态，但同一个工作流可以把互补 source role 合并为一个 BP 资料库
版本。任何单文件失败都必须指出文件和原因，不能把整批失败只显示为一个
`REQUEST_FAILED`。

Operator 可以导入其有权处理的经营资料；本稿不把“纯合成数据”设为运行条件，
也不增加前端确认框。真实数据的组织政策、隐私通知和部署合规属于独立治理，
不能用一个没有实际保护作用的 checkbox 替代。

视觉迁移不得用 Viewer 的低负载限制削弱 Operator 功能。Viewer 只有个人上传
边界提示和内置 Demo 激活；字段映射、标准化、计算、发布、正式导出等控件应在
Operator 的 Data Workspace 中完整保留。

提交新资料库版本后，Operator 必须能够对该精确版本执行并看到真实状态：

- Sales & Advertising analysis；
- Inventory risk 和 P 级 Replenishment；
- Operating Profit 和 Profit Bridge；
- 7/30/90 天 Forecast；
- Action Card 生成/复核；
- 发布、导出和 outcome。

页面不能只暴露已有 API 而没有调用入口，也不能让 Forecast 继续绑定旧发布版本
从而阻塞新版本计算。发布前应明确列出缺少的计算；成功后各页面读取新发布版本。

## 12. 数据流与负载模型

```text
                 Operator 准备或系统内置版本
源文件 -> BP 标准资料库 -> 不可变发布版本 -> 预计算事实/图表/行动基线
                                      |
                        +-------------+-------------+
                        |                           |
              Import demo data A          Import demo data B
                   Viewer Session A            Viewer Session B
                   Chat + overlays             Chat + overlays
                        |                           |
                   到期后清理                    到期后清理
```

负载控制原则：

- 三个月源数据、标准化数据和分析结果各保存一套权威版本；
- Viewer 只读共享数据，不为每个 session 生成数据库副本或 Blob 副本；
- Action 编辑只做 O(1) 白名单算术；
- AI 月报读取有界预计算事实，不扫描原始数据；
- Chat 和覆盖记录有数量、大小、并发和生命周期上限；
- 会话清理删除临时状态，不删除公共发布版本和 Operator 记录；
- 容量验收至少覆盖当前展示目标的 15 个并发 Viewer，并确认无数据复制、
  无大规模计算排队和无跨会话泄漏。该门槛不是 Production 容量声明。

## 13. 语言、文案和按钮规则

- 英文和中文为完整 catalog，不再把两种语言永久拼在同一句 UI 文案中；
- 切换语言会更新欢迎页、登录页、应用、动态状态、错误、图表说明、提示词和
  无障碍名称；
- `Sign in` 取代 `Operator sign in`；
- `Explore BizPulse` 取代课程化的 Demo 入口文案；
- 不显示 `Course Demo`；
- 不显示 `Synthetic Demo Data / 纯合成演示`；
- 在确有解释需要时使用低频 `Sample data / 示例数据`；
- 服务端的结构化数据边界使用稳定 limitation code，前端将其本地化为
  `Sample data / 示例数据`；不能把历史内部字符串 `Synthetic Demo data only`
  直接展示给用户，也不能用正则改写任意 AI prose；
- 机器 error code、hash、版本 ID、证据 alias 和 source value 不翻译；
- hash、schema、digest、`Pinned` 和内部版本 ID 不在常规 UI 显示；
- 除上传边界的明确例外外，禁止权限的 Operator 写按钮在 Viewer 中隐藏；
- Viewer 上传入口可见且点击/拖放后立即给出明确说明，是经确认的产品边界，
  不是没有反应的死按钮；
- 由于环境故障而暂时不可用的合法按钮可以禁用，但必须说明原因。

## 14. 错误与降级状态

| 场景 | 体验 |
|---|---|
| Viewer 会话创建失败 | 留在欢迎页，显示安全重试，不进入空工作台 |
| Viewer 会话到期 | 清理本地临时状态并返回欢迎页 |
| Viewer 选择或拖入个人文件 | 不读取、不发送；就地说明 Viewer 个人上传不可用 |
| Import demo data 失败 | 保留 Data Workspace，显示安全重试，不展示假 KPI |
| Operator 某个文件不合法 | 在队列中标出该文件、稳定错误原因和可重试/移除动作 |
| 预载版本不可用 | 不展示假 KPI；显示明确版本不可用状态 |
| 图表事实部分缺失 | 保留 partial/unknown，不补零 |
| Action 估算缺少成本或速度 | 显示 `Unavailable`，保留基线建议 |
| AI 未启用 | Chat 输入和发送不可用；确定性页面与 Action Sandbox 可用 |
| AI 限流或预算用尽 | 显示对应状态，不自动重试、不绕过预算 |
| AI 超时或结果不确定 | 不重复收费式重试；显示安全结果状态 |
| 月报证据不足 | 返回具体缺失项和可用报告范围，不补造数字 |
| 快捷模板目录失败 | 保留自由输入；不显示损坏按钮 |
| 轮播资源失败 | 展示第一张静态画面，不影响进入或登录 |
| 登录失败 | 保留字段与焦点，使用统一安全错误，不暴露账号存在性 |

## 15. 无障碍与响应式

- 所有交互目标至少 42px；
- 图标按钮具有可见 tooltip、accessible name 和 focus ring；
- 状态不只依赖颜色；
- 轮播支持 reduced motion、键盘和暂停；
- 自动切换不抢焦点、不重复朗读；
- Chat 快捷按钮可按 Tab 访问，填入后焦点进入 textarea；
- 上传 drop zone 可用键盘触发，drag enter/leave/drop 状态不只靠颜色；
- 侧栏在紧凑状态为每个入口提供 hover/focus tooltip 和完整 accessible name；
- 替换草稿确认可以用键盘完成并恢复焦点；
- Evidence drawer 打开后约束焦点，Escape 关闭，并把焦点还给触发按钮；
- 图表提供使用相同两位小数规则的文本摘要；
- Evidence 默认四条、展开和收起状态可被辅助技术识别；
- 820px 以下 KPI 变两列，560px 以下变一列；
- 390px 宽度不得产生阻塞性横向滚动；长表使用标记清晰的横向滚动区。

## 16. 验证设计

### 16.1 静态与单元测试

- 用户可见源码中没有 `Operator sign in`、`Course Demo`、`Synthetic Demo
  Data` 或 `纯合成演示`；
- 欢迎页和登录页共享一个 6 秒轮播控制器；
- 语言 catalog 双向完整；
- Viewer 和 Operator 应用内始终存在可发现的语言选择，切换会重新渲染当前页；
- 数字 formatter 覆盖 BRL、整数、普通小数、百分比、天数、负值、null、
  NaN 和超高精度源值，并证明原始值不变；
- Viewer 存在上传 affordance 和 `Import demo data`；个人文件路径不读取文件、
  不建立上传 body 且不访问 Operator routes；
- Viewer 的 `Import demo data` 只执行会话绑定，不创建数据版本、分析或 Blob；
- 上传区不包含任何 synthetic/authorization confirmation checkbox；
- Operator 数据源支持多文件队列并保留 upload/import/commit/publish/export/
  outcome 命令；
- Evidence 默认只渲染前四条，展开/收起不改变完整集合；
- 普通 UI 不含 `Pinned`、schema、digest 或 hash 文案；
- Overview 不允许四 KPI 加空 charts 的退化完成态；
- Inventory 在单一风险分类时不生成单段分布图，并按确定性 P 级稳定排序；
- Settings 覆盖语言、范围默认值、KPI 顺序、保存视图、目标和 AI 状态权限；
- Action Sandbox 只计算批准的三个公式，不发送分析或 AI 请求；
- 会话 A 的 Action/Chat 不能被会话 B 读取；
- 快捷按钮点击后填入输入框但 `submitChatTurn` 调用次数仍为零；
- 输入框非空时不能静默覆盖；
- 用户按 Send 后发送可见文本、preset ID 和版本；
- 未改模板采用固定安全计划，已改模板采用白名单 planner；
- 月报绑定数据版本实际期间，并只读取预计算报告包；
- AI 不可用、预算、限流、超时、证据不足和 outcome unknown 分别测试；
- 所有可见导航均能到达工作页面。

### 16.2 数据与 API 测试

- 三个月数据主键、日期、SKU、币种和 source role 一致；
- 成本工作簿的 SKU 和有效期覆盖需要计算的销售与库存；
- FIFO 期初收货批次可重放且总量守恒；
- 重复 sales 文件不会被双重计入；
- 同一 seed 重建得到相同 canonical hash 和相同预计算结果；
- 月报 read model 在只读事务和有界响应内运行；
- Viewer 不能构造请求访问 Operator 导入、发布或导出；
- Viewer Demo 激活和 15 个并发会话不重复标准化行、版本、分析或 Blob；
- Operator 新提交版本能够运行 Sales、Inventory/P priority、Profit Bridge、
  Forecast 和 Action 计算，并在发布后由页面读取；
- BP Library 能从多个 source role 生成不可变合并版本，并提供覆盖、质量、
  预览和 provenance；
- Viewer 结束/到期只删除当前 Chat 和 simulation overlays。

### 16.3 浏览器验收

在 1280px、820px 和 390px 验证：

- 欢迎页、登录页、四张产品画面、自动/手动轮播和 reduced motion；
- `Sign in` 文案、登录表单稳定性和安全错误；
- Viewer 六个主区域、只读 BP Library、默认四条 Evidence、Ask BizPulse 和
  Action Sandbox；
- Viewer 上传入口可点击和接收 drop 事件但不读取/发送个人文件；
- Viewer `Import demo data` 能激活共享资料并进入 Overview；
- Viewer 不出现字段映射、commit、重算、发布、正式导出和 outcome 控件；
- Operator 可点击选择/拖放多个文件，队列、识别、映射、标准化、合并、计算、
  资料库、发布、导出和 outcome 主流程完整工作；
- Settings 在 Viewer/Operator 权限下分别可用；
- 左侧导航桌面显示全称，紧凑状态显示本地化 hover/focus tooltip；
- Inventory 以 P0/P1/P2/Monitor 列表为主，Overview 只显示前四条紧急事项；
- 六个快捷提示词填入、修改、替换草稿、手动发送和回答；
- “生成本月销售报告”使用实际发布期间；
- Action 调整数值只改变 `My simulation`，刷新/到期行为符合会话合同；
- UI 数值不出现超过两位的非必要小数，原始/API/导出精度不变；
- 常规 UI 不出现 `Pinned`、hash、schema、digest、无语境 `v1`、重复图表摘要
  或中英文拼接文案；
- 无死按钮、意外横向滚动、外部图片请求、console error 或跨会话数据。

### 16.4 容量验收

- 15 个并发 Viewer 固定到同一共享发布版本；
- 数据库/Blob 中不产生 15 份源文件、标准化行或分析快照；
- 同时执行 Action 调整不触发分析 worker；
- AI 请求遵守一会话一 in-flight 和全局预算；
- 会话结束与自然过期后临时行能够清理；
- 重启后公共发布版本保持，临时会话按既定合同恢复或失效；
- 测试结果只证明当前展示容量，不外推为 Production 容量。

## 17. 建议实施批次

后续实施计划按以下顺序拆分：

1. 修正文案、应用内语言、导航全称/tooltip、Evidence 折叠和上传控件基础；
2. Viewer `Import demo data` 会话激活、个人上传拒绝和只读 BP Library；
3. Operator 多文件上传、BP 合并资料库、计算编排、发布和导出闭环；
4. 高密度 Overview、P 级 Inventory 列表和有意义的分析图；
5. Settings、保存视图、目标和 AI 状态；
6. 既有 Product Theater、Chat presets、Action Sandbox 的回归与统一验收；
7. Viewer/Operator 浏览器验收、容量测试、变更路径验证和文档收口。

每一批都要从最新实现 commit 刷新基线，先写失败测试，再实现，并把本地通过、
提交、部署、Hosted 验收和 Production 状态分开报告。

## 18. 非目标

本稿不包括：

- 读取、展示、重设或发送 Operator 明文密码；
- 新增第二个 Operator、自助注册、团队、角色或多租户账户系统；
- 允许 Viewer 读取、发送或处理自己的上传文件；
- 为 Viewer 的 `Import demo data` 重复创建数据、版本、分析或 Blob；
- 为每个 Viewer 重跑全量计算；
- 用 AI 生成或修改权威 KPI、Forecast、Profit 或证据；
- 让 Action Sandbox 执行真实采购、广告或平台写入；
- 真实客户数据、实时市场数据或真实商品图片；
- `Product Opportunities`、`Favorites`、`Operating Advice` 的占位页面；
- 复制整个 CAPTSONE 前端并覆盖 NEWCaostone 功能；
- 在本设计阶段创建 OpenAI Key、读取现有 Key、付费调用、修改 Azure、部署、
  发布或宣称 Production。

## 19. 完成定义

只有同时满足以下条件，才可以把本稿对应的产品改造称为“本地实现完成”：

1. 欢迎页、登录页、Viewer 与 Operator 使用统一 CAPTSONE 视觉语言；
2. 登录页四页定时展示高级、稳定、可控且无障碍；
3. 所有公共文案使用 `Sign in`，应用内语言切换完整工作，并移除课程化、
   `Pinned`、hash、schema、digest 和截图中的技术标签；
4. 三个月数据和成本数据只有一份共享权威，所有 Viewer 读取同一预计算版本；
5. Viewer 能从 Data Workspace 点击 `Import demo data` 激活共享数据；个人文件
   选择和拖放得到明确说明且不会被读取或发送；
6. Viewer 能使用完整分析读取、只读 BP Library、AI 和会话级 Action Sandbox，
   但不能执行真实导入或重算；
7. Operator 的多文件导入、标准化、合并资料库、计算、发布、导出和 outcome
   完整可用；
8. Overview 恢复经营信息密度，Inventory 以 P0/P1/P2/Monitor 列表为主，
   Evidence 默认四条并可展开；
9. Settings 按 Viewer/Operator 权限提供语言、默认范围、KPI、保存视图、目标和
   AI 状态；
10. 快捷提示词按钮只填入可编辑模板，用户主动 Send 后才发起 AI；
11. 月报使用实际数据期间和有界预计算证据；
12. Viewer Action 只显示轻量模拟估算，不改变任何权威结果；
13. 所有用户可见数字遵守两位小数显示合同；
14. 权限、隔离、配额、错误、无障碍、响应式、浏览器和容量测试通过；
15. 文档清楚区分本地实现、Git 提交、部署、Hosted 验收和 Production。

Azure 展示验收仍需要单独、明确授权的发布流程证明：准确构建已部署、服务器
端 AI Key 与预算安全配置、Ask BizPulse 真正可用、浏览器验收通过、Viewer
隔离和清理有效。本文档和本地测试不能替代这些证据。
