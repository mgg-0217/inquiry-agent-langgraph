# 进度记录

> 每个模块完成后更新。模块划分按 `docs/START.md` 第 3 章的天数，用户逐模块验收。

## 模块 1 / 第 1 天：能收到信、能上界面 ✅（2026-10-29）

### 交付内容

| 层 | 文件 | 说明 |
|---|---|---|
| 配置 | `backend/app/config.py` | Pydantic Settings 读 `.env`，路径统一解析 |
| 数据 | `backend/app/db/models.py` | 3 张表：`customers` / `threads` / `messages`，带 `tenant_id` |
| 数据 | `backend/app/db/session.py` | engine + session，sqlite 外键/WAL |
| 邮件 | `backend/app/mail/base.py` | `MailProvider` 接口（`fetch_new` / `send`） |
| 邮件 | `backend/app/mail/parser.py` | MIME 解析：编码、正文、附件、`Message-ID` / `In-Reply-To` / `References` |
| 邮件 | `backend/app/mail/mailpit.py` | Mailpit HTTP API 拉原始 EML；SMTP 发信（`local_hostname="localhost"`） |
| 邮件 | `backend/app/mail/ingest.py` | 幂等入库、线程归并（引用头 → 主题+发件人兜底）、客户建档 |
| 接口 | `backend/app/api/inbox.py` | `GET /api/inbox`、`GET /api/threads/{id}`、`POST /api/inbox/sync` |
| 入口 | `backend/app/main.py` | FastAPI + 10s 轮询任务 + `/api/health` |
| 前端 | `frontend/src/views/InboxView.vue` | 工作台列表、KPI、状态筛选、搜索、邮件详情抽屉 |
| 脚本 | `scripts/send_test_mail.py` | 投递场景 A 测试询盘 |

### 自检结果

- `pytest backend/tests -v`：**15 passed**（14 单元 + 1 Mailpit 集成）
- `POST /api/inbox/sync` 重复调用：`fetched=0 created=0 duplicated=0`（幂等）
- 投递 → 工作台可见：接口返回客户 Carlos Mendoza、主题、`Message-ID`、时间；截图 `docs/shots/module1-inbox.png`、`docs/shots/module1-drawer.png`
- 搜索 `X200` 命中；「待审批」空状态正常
- 前端 `vue-tsc --noEmit` 通过

### 环境偏差与修正

| 项 | 发现 | 处理 |
|---|---|---|
| Mailpit IMAP | v1.32.0 **没有** IMAP 收信参数，`--imap` 直接报 unknown flag | 改用 HTTP API：`GET /api/v1/messages` + `GET /api/v1/message/{ID}/raw`；`start-mailpit.ps1` 去掉 IMAP 参数；`START.md` 已补「坑 4」 |
| Mailpit 单封删除 | 无 `DELETE` 单封端点，只能清空全部 | 集成测试改为**只读现有邮件**，不再发信，避免污染 Mailpit 与开发库 |
| sqlite 时区 | `DateTime(timezone=True)` 在 sqlite 丢时区 | 全库统一 UTC naive，API 输出补 `Z`；parser/ingest/模型已统一 |
| npm postinstall | 沙箱内 `spawn EPERM` | 前端依赖用 `npm install --ignore-scripts` 安装（esbuild 平台包已随依赖落盘） |

### 下一步（模块 2 / 第 2 天）

`AgentState` + 12 节点空实现 + 4 个条件分支 + 图编译 + happy path 测试。
关键检查：`clarify → END`（不能连回 `receive`）。

---

## 模块 2 / 第 2 天：图能跑通（假数据）✅（2026-10-29）

### 交付内容

| 文件 | 说明 |
|---|---|
| `backend/app/graph/state.py` | `AgentState`（含 `round` / `is_followup` / `our_previous_quote` / `client_previous_price`）+ 13 个 Pydantic 产物模型 |
| `backend/app/graph/nodes.py` | 12 个业务节点 + `archive` 的空实现，统一追加 `trace` / `step` |
| `backend/app/graph/edges.py` | 4 个条件分支（`after_triage` / `after_compliance` / `after_decide` / `after_approval`） |
| `backend/app/graph/build.py` | 按 PRD 7.7 组图 + SqliteSaver（自建连接，避开 context manager 坑） |
| `backend/tests/unit/test_graph_compiles.py` | 18 个测试：结构、happy path、分支、挂起恢复 |
| `backend/scripts/print_graph.py` | 打印节点/边/Mermaid，便于自检 |

### 自检结果

- `pytest backend/tests -q`：**33 passed**（15 模块 1 + 18 模块 2）
- `python backend/scripts/print_graph.py`：**13 个业务节点**，`clarify -> __end__`
- happy path：`receive → triage → resolve → recall → draft_plan → compliance → decide → dispatch → persist`（9 步）
- 议价轮（`is_followup=true` + `round≥2` + `is_price_negotiation=true`）：强制 `compose`，挂起在 `approval`
- `Command(resume=...)` 恢复成功；**换一个图实例 + 新 sqlite 连接**后仍能从挂起点继续（模拟进程重启）
- 轮次：首轮 `round=1`，`In-Reply-To` 回信 `round=2`

### 关键设计点（与 PRD 对齐）

| 点 | 实现 |
|---|---|
| `clarify` 的等待性质 | `g.add_edge("clarify", END)`，不是 `interrupt`、不连回 `receive`（ADR-16） |
| `approval` 的等待性质 | 节点内 `interrupt(payload)`，由 `Command(resume=...)` 恢复 |
| 议价强制人工 | `after_decide` 先判断议价轮，**优先于**模型给的 `action`（ADR-17） |
| `trace` / `errors` | `Annotated[list, operator.add]`，只追加 |
| spam 阈值 | 取 `settings.spam_threshold`（0.85），低置信度不归档（ADR-11） |
| `archive → persist` | 归档也要写记忆，否则不知道被拒过 |
| checkpoint 序列化 | LangGraph 1.x 默认拒绝反序列化未注册的自定义类型，`build_serde()` 用 `allowed_msgpack_modules` 显式放行 AgentState 里的 16 个模型 |

### 下一步（模块 3 / 第 3 天）

8 个工具 + 统一返回契约 `{ok, data, code, retryable, message}`；
`ReplyStrategy` 三层约束（`resolve_price` + `guard`）。
必须通过「老客户达标 / 新客户 / 触成本线」三个用例。

---

## 模块 3 / 第 3 天：工具层 + 策略判断 ✅（2026-10-29）

### 交付内容

| 文件 | 说明 |
|---|---|
| `backend/app/tools/schema.py` | 统一返回契约 `{ok, data, code, retryable, message}` + 错误码 + 调用留痕 |
| `backend/app/tools/fixtures.py` | 产品目录、阶梯价/库存、演示客户画像（全部虚构，X200 价格与 PRD 17.1 一致） |
| `backend/app/tools/product.py` | `search_product` / `check_inventory` |
| `backend/app/tools/pricing.py` | `calc_price`：`tiers[] + applicable + target_matched_price + floor_price` |
| `backend/app/tools/customer.py` | `lookup_customer`（DB + 演示画像补齐空字段） |
| `backend/app/tools/compliance.py` | `screen_compliance`（名单未加载时 `list_loaded=false`，不谎称通过） |
| `backend/app/tools/comms.py` | `translate`（直通占位）/ `send_message`（DRY_RUN + 白名单）/ `schedule_followup`（Phase 2） |
| `backend/app/tools/registry.py` | 6 个读工具给模型、2 个写工具只给代码；导出 args_schema |
| `backend/app/strategy/schema.py` | `ReplyStrategy`（Layer 1 输出契约）+ `StrategyContext` |
| `backend/app/strategy/prompt.py` | Layer 2 判断原则（PRD 7.8.3 七条）+ 拼 messages |
| `backend/app/strategy/resolve.py` | Layer 3 `resolve_price()` + `guard()`（4 条硬规则） |
| `backend/app/strategy/node.py` | 调用封装、重试 1 次、失败兜底 `escalate` |

### 自检结果

- `pytest backend/tests -q`：**73 passed**（工具 29 + 策略 11 + 既有 33）
- `calc_price("X200", 500, "CIF")`：档位 `[380, 364, 350]`、总价 `175000`、`floor_price=338`，与 PRD 17.1 完全一致
- 三个必过用例：
  - 老客户达标（300 台 × $350，total 105000 未超授权）→ `stance=re_engage`、`mention_history=true`
  - 新客户（模型装熟）→ `guard` 强制 `mention_history=false`
  - 算价 $330 < floor $338 → `stance` 被改成 `escalate`
- **真实 DeepSeek 验证**（`backend/scripts/demo_strategy_live.py`）：
  - 场景 1 输出 `re_engage / mention_history=true / match_target`，最终价 350 ≥ floor 338
  - 场景 2 输出 `standard / mention_history=false / none`
- 工具返回契约、白名单拒发、DRY_RUN 不真发、`schedule_followup` 明确 NOT_IMPLEMENTED

### 环境发现（已处理）

**DeepSeek 不支持 `response_format: json_schema`**：`with_structured_output` 默认走 json_schema，
调用返回 `400 This response_format type is unavailable now`。
已改为 `method="function_calling"`（Function Calling 在此前 `verify_llm_key.py` 中已实测可用），
并保留"连续失败 2 次 → escalate 兜底"的降级路径（这次正好验证了兜底会生效）。

### 如实标注的能力边界

| 工具/能力 | 状态 |
|---|---|
| `screen_compliance` | 名单未加载：始终返回 `list_loaded=false`、`hits=[]`，**不能当放行依据**；第 5—6 天接 OFAC |
| `translate` | 直通占位（`provider=passthrough`），不伪造译文；第 5 天接 LLM |
| `schedule_followup` | Phase 2（PRD F9），返回 `NOT_IMPLEMENTED` |
| `send_message` | 已实现 DRY_RUN + 白名单；真实发信链路由第 11 天联调验证 |

### 下一步（模块 4 / 第 4 天）

`triage`（含 `is_negotiation`）+ `clarify` + 记忆写入/召回 + `resolve` 四级实体解析（L1 + L4）。
自检：`pytest backend/tests/unit/test_memory.py -v`，重点是证据校验、`no_response` 不归因、冲突取值。

---

## 模块 4 / 第 4 天：分诊 + 记忆 ✅（2026-10-29）

### 交付内容

| 文件 | 说明 |
|---|---|
| `backend/app/db/models.py` | 新增 `customer_aliases` / `customer_facts` / `interactions`，`customers.is_new` |
| `backend/alembic/` + `alembic.ini` | **接入 Alembic**：初始迁移含 6 张表，应用启动自动 `upgrade head` |
| `backend/app/db/migrate.py` | `run_migrations()`（启动时执行） |
| `backend/app/db/seed.py` | PRD F2 演示客户种子（Acme / NewCo / Sanctioned），幂等 |
| `backend/app/llm/client.py` | ChatOpenAI 封装（温度/超时/重试） |
| `backend/app/llm/structured.py` | structured output 兼容层（`function_calling`） |
| `backend/app/graph/prompts/` | triage / clarify / persist 三个节点的 prompt |
| `backend/app/graph/triage.py` | L1 规则预过滤 + L2 LLM + L3 低置信度标记复核 |
| `backend/app/graph/clarify.py` | 追问生成（LLM + 模板兜底） |
| `backend/app/graph/resolve.py` | L1 邮箱精确 + L4 新建（`is_new=true`） |
| `backend/app/memory/schema.py` | 20 个 fact key 白名单 + 价格有效期 + 抽取契约 |
| `backend/app/memory/extractor.py` | LLM 抽取（失败返回空，不写脏数据） |
| `backend/app/memory/store.py` | 证据校验 + `no_response` 禁价格类 + 冲突 `superseded_by` |
| `backend/app/memory/recall.py` | 召回与冲突取值 + 记忆块拼装 |
| `backend/app/graph/nodes.py` | 5 个节点接真实实现（工厂注入 llm / session_factory） |
| `backend/scripts/` | `seed_demo.py` / `show_memory.py` / `demo_triage_live.py` / `demo_graph_live.py` |

### 自检结果

- `pytest tests -q`：**104 passed**（新增 27：记忆 13 + 分诊 10 + 解析 4）
- 记忆三个必过用例：
  - 证据不在原文 → 丢弃 + 日志 `证据不在原文，疑似编造`
  - `no_response` → 价格类 fact 被丢弃，`interactions.lost_reason=no_response`
  - 两条有效记录 → 只召回 `superseded_by IS NULL` 且 `created_at` 最新的一条
- 额外覆盖：价格类 `valid_until`、置信度差 >0.3 两条都给、过期不召回、写入幂等、旧记录被 supersede

### 真实模型验证（DeepSeek）

| 场景 | 结果 |
|---|---|
| 完整询盘 | `complete=true`，`confidence=0.95` |
| 信息不全（"send me your best price for water pumps"） | `complete=false`，missing=`[产品型号或规格, 数量, 目的港]`，追问草稿可直接用 |
| 垃圾邮件（12 个外链） | 规则命中 `is_spam=true`，不调模型 |
| 记忆抽取 | 9 条事实；`contact_name` 因证据不在正文被丢弃；`target_price` 从整句归一化为 `350` |
| 端到端老客户还价 | 召回 3 条事实 + 1 条 `price_high` 历史 → 强制 `compose` → 挂起 `approval` |

### 关键设计点

| 点 | 实现 |
|---|---|
| 证据校验 | 归一化后子串匹配；无证据 / 不在原文都丢弃并 warning |
| `no_response` | 即使证据有效，也禁止写 `target_price` / `historic_price` / `pending_quote` |
| 冲突 | 新值写入后把旧记录 `superseded_by` 指向新记录，不删除 |
| 价格类取值 | 强制归一化为纯数字（`"USD 350 CIF"` → `"350"`），否则丢弃 |
| 召回冲突 | 最新优先；旧记录置信度高 0.3 以上时两条都给模型 |
| LLM 失败 | 分诊保守放行 + `need_review=true`；记忆抽取返回空，不写脏数据 |
| 迁移 | Alembic 单一来源，`init_db` 不再 `create_all` |

### 如实标注的边界

| 项 | 状态 |
|---|---|
| `draft_plan` / `compliance` / `decide` | 仍是骨架假值，第 5—7 天替换 |
| L2 域名 / L3 公司名模糊匹配 | 未实现，当前只有 L1 + L4 |
| 议价邮件未写数量 | 会被 triage 判为不完整而追问；第 5 天用 `pending_quote` 补全上下文 |
| `pending_quote` 召回 | 表里已写入，但 `recall` 暂未拼进记忆块（第 5 天） |

### 下一步（模块 5 / 第 5—6 天）

`draft_plan` 接工具（search_product → check_inventory → calc_price → 策略判断）、
`compliance` 接 OFAC 真实名单 + 实体消歧，`scripts/fetch_sanctions.py`。

---

## 当前状态（2026-10-29 收工）

- 已完成：模块 1—4（收信 → 图骨架 → 工具/策略 → 分诊/记忆）
- 测试：`pytest backend/tests -q` → **104 passed**
- 服务：已全部停止（Mailpit / 后端 / 前端），端口 1025 / 8000 / 5173 / 8025 已释放
- 数据保留：`backend/data/inquiry.db`（3 封邮件 + 3 个种子客户 + 记忆事实）、`backend/data/mailpit.db`（3 封测试邮件）
- 明天启动：

```powershell
cd D:\dshWorkspace\inquiry-agent
.\scripts\start-mailpit.cmd

cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

cd ..\frontend
npm run dev
```

- 明天第一件事：模块 5（`draft_plan` 接工具 + `compliance` 接 OFAC）



---

## 模块 1—3 自查与修复（2026-10-29）

上线前专项自查，原则是「先实测复现，再修，再回归」。

### 发现并修复的问题

| # | 问题 | 严重度 | 修复 |
|---|---|---|---|
| 1 | **前端不会自动刷新**：后端已入库，页面仍停在旧列表，模块 1 的「10 秒内出现在工作台」实际做不到 | 高 | `InboxView.vue` 加 10 秒静默轮询（页面不可见/正在请求时跳过），失败不打扰用户 |
| 2 | 未知路由 / 参数校验错误返回 Starlette 默认格式 `{"detail": ...}`，前端 interceptor 会当成功响应 | 高 | 统一 `StarletteHTTPException` / `RequestValidationError` / 未捕获异常响应为 `{code, message, data}` |
| 3 | `build_single_agent()` 默认每次新建 sqlite 连接且不关闭，接入 API 后每请求泄漏一个连接 | 高 | `get_default_checkpointer()` 进程内单例 + `close_default_checkpointer()`；lifespan 关闭时释放 |
| 4 | 轮询任务与「立即同步」并发时可能重复拉取同一封邮件；客户并发建档会误判为「重复邮件」而丢信 | 中 | `sync_inbox` 串行锁；`IntegrityError` 区分 Message-ID 冲突与客户冲突（后者重试一次） |
| 5 | 缺 `From` 的邮件会共用空邮箱客户，第二封必然撞唯一约束 | 中 | 用 Message-ID 派生占位发件人 `unknown-xxx@invalid` |
| 6 | `guard()` 重复执行会重复拼接审计说明（审批改稿后会再跑一次） | 低 | `_append_note()` 幂等追加 |
| 7 | `el-drawer` 没有关闭按钮，只能点遮罩 | 低 | 加右上角 ✕ + `max-width: 100vw` |
| 8 | Mailpit 没启动时每 10 秒打印完整 traceback | 低 | 降级为 `warning`，其它异常仍打堆栈 |
| 9 | `_find_thread` 的 90 天窗口用 aware datetime，与库内 naive 语义不一致 | 低 | 统一 naive UTC |

### 新增测试（73 → 77）

- `test_concurrent_sync_does_not_duplicate`：3 线程同时同步同一封邮件，最终只有 1 条
- `test_default_checkpointer_is_cached`：默认 checkpointer 必须复用
- `test_guard_is_idempotent_when_run_twice`：重复 guard 不重复追加 rationale
- `test_mail_without_from_uses_placeholder`：无 From 邮件使用占位发件人

### 实测记录

- 自动刷新：投递第三封 → **不刷新页面** → 15 秒内列表从 2 条变 3 条 ✅
- 接口一致性：`/api/unknown` → `{"code":404,...}`；`page_size=1000` → `{"code":422,...}`；有效 thread → 200 ✅
- 前端：`vue-tsc --noEmit` 通过；`vite build` 通过（1682 modules）
- 全量：`pytest tests -q` → **77 passed**

### 环境注意（记录，避免重踩）

- **Vite watcher 偶发漏更新**：改完文件后 dev server 仍返回旧编译结果，`touch` 一下文件（或重启 dev server）才生效。开发时如果「改了没反应」先怀疑这个。
- **esbuild 写系统临时目录被拒**：`vite build` 报 `Access is denied` 时，把 `TMP`/`TEMP` 指到工作区（`D:\dshWorkspace\.tmp`）再构建。

### 遗留欠账（不影响当前开发，上线前必须处理）

| 项 | 现状 | 计划 |
|---|---|---|
| Alembic 迁移 | 用 `create_all`，改已有表结构不会自动生效 | 第 4 天加 `interactions` / `customer_facts` 等新表时一并接入 |
| 前端包体积 | 单 chunk 1.05 MB（element-plus 全量引入） | 第 8—10 天做前端时按需引入 / manualChunks |
| 多 worker 部署 | 未验证（当前单进程，锁只在进程内） | 上线前补跨进程验证或换 Postgres |
| 真实邮箱 / OFAC | 按排期第 11 天 / 第 5—6 天 | 不变 |

---

## 模块 5 / 第 5—6 天：报价规划 + 合规 ✅（2026-10-30）

### 交付内容

| 文件 | 说明 |
|---|---|
| `backend/app/db/models.py` | 新增 `sanctions_entries`（参考数据，不带 tenant_id） |
| `backend/alembic/versions/..._sanctions_entries.py` | 迁移（启动自动 upgrade） |
| `backend/app/compliance/loader.py` | 解析 `sdn.csv` + `alt.csv`，JSON 缓存与 DB 读写，名称归一化/分词 |
| `backend/app/compliance/disambiguate.py` | 实体消歧：token 倒排候选 + 相似度 + 国别加成 + 停用词降权 |
| `backend/app/compliance/bootstrap.py` | 启动时若库为空自动从 `entries.json` 导入 |
| `backend/app/graph/prompts/inquiry.py` | 采购需求抽取 prompt |
| `backend/app/graph/draft_plan.py` | 采购需求抽取 → ReAct 工具循环 → **代码重算** → 策略判断 |
| `backend/app/graph/state.py` | 新增 `InquirySpec` |
| `backend/app/graph/nodes.py` | `draft_plan` / `compliance` 接真实实现（工厂注入） |
| `backend/scripts/fetch_sanctions.py`（仓库根 `scripts/`） | 下载 / 解析 / 导入名单 |
| `backend/scripts/demo_module5_live.py` | 第 5—6 天验收演示 |

### 自检结果

- `pytest tests -q`：**122 passed**（新增 19：合规 12 + 报价 7）
- 名单数据：**19,484 条 SDN**，其中 **9,963 条带别名**
- 真实命中（真实公开数据）：
  - `BANCO NACIONAL DE CUBA` → 1.00，`OFAC SDN #306`
  - `BNC`（别名）→ 1.00，`OFAC SDN #306（别名命中：BNC）`
  - `Acme Import S.L.` → 未命中
  - `NewCo Trading` → 0.70（低于 0.75 复核阈值，放行）
- 真实模型报价（老客户 500 台 X200，记忆 target=350）：
  - 节点摘要：`采用 ReAct 算价结果：X200 × 500 CIF $350.0`
  - 报价：单价 350 / 总价 175,000 / 成本线 338 / 目标价匹配 350 / 有效期 2026-11-06
  - 策略：`stance=escalate`、`mention_history=true`、`price_adjustment=volume_tier`，rationale 同时说明「价格已到位应再激活」与「超授权强制升级」
  - 库存：available=true，lead_time 35 days

### 关键设计点

| 点 | 实现 |
|---|---|
| 数字只来自工具 | ReAct 让模型自主调工具，但最终报价由代码重新调用 `calc_price`；仅当 SKU/数量都对得上才采用模型的算价结果 |
| 制裁宁可错杀 | 名单未加载 → `need_review`（不宣称通过）；≥0.95 reject，≥0.75 转人工 |
| 防误杀 | 只共享通用词（TRADING/IMPORT 等）时相似度封顶 0.7，低于复核阈值 |
| 可追溯 | 每条命中输出「名单名 + 条目号 + 匹配分」，落 `Verdict.evidence` |
| 性能 | token 倒排 + `real_quick_ratio` 预筛；19k 条全量比对 <1s，常规查询 <0.1s |

### 环境注意

- **本机 TLS 被本地代理拦截**（自签名证书）：OFAC 下载需要 `--insecure`，因此下载后必须看脚本打印的 SHA256 与条目数做内容校验。

### 如实标注的边界

| 项 | 状态 |
|---|---|
| 内部资信评分（L2） | 未实现（F6 三层数据里的第二层，第 7 天 decide 前可补，或 Phase 3） |
| 出口管制（BIS Entity List / ECCN） | 未实现，当前只做 OFAC SDN |
| 地址/国别加权 | SDN 公开数据无结构化地址，当前用「名称/别名 max + 国别加成」，未用 PRD 的 0.4/0.3/0.2/0.1 全权重 |
| 演示场景 D | 需要用真实被制裁实体名（如 BANCO NACIONAL DE CUBA）才能命中；虚构名不会命中真实名单 |
| `decide` / `compose` / `approval` / `dispatch` | 仍是骨架，第 7 天替换 |

### 下一步（模块 6 / 第 7 天）

`decide`（含议价强制 escalate + 超授权）+ `compose`（fact_check）+ `approval`（interrupt）+ `dispatch`。
自检：`tests/integration/test_full_flow.py`，重点是超授权挂起、重启恢复、议价轮强制审批。

---

## 模块 6 / 第 7 天：决策 + 生成 + 审批闭环 ✅（2026-10-30）

### 交付内容

| 文件 | 说明 |
|---|---|
| `backend/app/graph/prompts/decide.py` | 决策建议 prompt |
| `backend/app/graph/decide.py` | 模型建议 + 代码硬规则（超授权 / 合规复核 / 分诊复核 / 议价轮 / 无报价） |
| `backend/app/graph/prompts/compose.py` | 回复生成 prompt（facts 隔离 + 历史开关） |
| `backend/app/graph/fact_check.py` | 金额/百分比/交期校验，拦截篡改与成本线泄露 |
| `backend/app/graph/compose.py` | 生成 → fact_check → 失败重写一次 → 仍失败转审批 |
| `backend/app/graph/nodes.py` | `decide` / `compose` / `dispatch` 接真实实现；dispatch 写 `audit_logs` 并更新 thread 状态 |
| `backend/app/graph/edges.py` | 新增 `after_compose` |
| `backend/app/db/models.py` | 新增 `audit_logs` + 迁移 |
| `backend/tests/integration/test_full_flow.py` | 6 个集成用例 |

### 自检结果

- `pytest tests -q`：**154 passed**（新增 28：fact_check 8 + decide 10 + compose 4 + full_flow 6）
- 三个必过项：
  - 超授权（175,000 > 150,000）→ 挂起 `approval`，不自动发
  - 进程重启（新图实例 + 新 sqlite 连接）→ `Command(resume=approve)` 恢复并继续 `dispatch → persist`
  - 议价轮（`round=2` + `is_negotiation`）→ 强制 `approval`
- 额外覆盖：驳回 → `archive → persist`（驳回也写记忆）；fact_check 失败 → 不自动发、转审批
- 真实模型跑通：`decide` 因超授权 escalate → `compose` 生成 → 挂起 → `resume approve` → `dispatch`（DRY_RUN）→ `persist`

### 两个重要修正（都在自查/实测中发现）

| 问题 | 说明 | 处理 |
|---|---|---|
| **PRD 7.7 的图有缺口** | 原图 `decide(auto_reply) → dispatch`，但自动回复也必须先生成正文和 fact_check，否则会发空邮件 | 改为 `decide → compose`，再由 `after_compose` 按 `decision + fact_check_ok` 分流：通过且 auto_reply → dispatch，否则 → approval |
| **checkpoint 白名单模块路径错误** | `ReplyStrategy` 第 3 天移到了 `app.strategy.schema`，白名单仍写 `app.graph.state`，恢复时被拒绝反序列化（`Blocked deserialization`） | 白名单改为真实模块路径，并加测试断言「resume 后 strategy 仍在」 |

### 真实模型验证（DeepSeek）

第一次生成的回复引用了历史价格 `$364 / $380`，被 `fact_check` 判定「金额不在报价单内」→ 重写一次后通过。这正是事实校验存在的意义。

### 如实标注的边界

| 项 | 状态 |
|---|---|
| `POST /api/threads/{id}/resume` | 未实现（图已支持 `Command(resume=...)`，HTTP 入口留到模块 7 前端一起做） |
| `POST /api/simulate/inbound` | 未实现（同上） |
| 审批台 UI / 工单列表 | 模块 7（第 8—10 天） |
| `modify` 动作 | 图已支持（→ compose 重写），但人工改稿的二次校验入口在 API 层，随前端一起做 |
| 资信评分 / 出口管制 | 仍未实现（见模块 5 边界） |

### 下一步（模块 7 / 第 8—10 天）

前端 4 页：询盘工作台（含已拦截列表 + 捞回）、执行轨迹、审批台、客户记忆；
配套 API：`/api/threads/{id}/resume`、`/api/threads/{id}/trace`、`/api/customers/{id}/memory`、`/api/simulate/inbound`。

---

## 审批链路自查（2026-10-30）

逐条走审批流程时发现 8 个问题，全部已修并补测试。

| # | 问题 | 后果 | 修复 |
|---|---|---|---|
| 1 | **人工改稿后发送的仍是原草稿**（`edited_reply` 只记在 Approval 里，dispatch 仍读旧 `reply_final`） | 审批台的核心功能失效，业务员改的措辞不会生效 | approval 节点校验并更新 `reply_final`，dispatch 发送编辑后的内容 |
| 2 | **非法/缺失的审批动作默认按「批准」处理**（`payload.get("action", "approve")`） | 任何错误调用都会直接发信 | 动作白名单校验，非法/缺失一律按驳回 |
| 3 | **`reassign` 被当成 approve 直接发送** | 「转他人」会变成「立即发信」 | `reassign → approval` 重新挂起，等新审批人 |
| 4 | 审批动作不写审计日志（PRD 要求四种动作都留痕） | 无法追溯谁批的 | approval 节点写 `audit_logs` |
| 5 | 挂起时不更新 `threads.status = waiting_approval` | 审批台无法按状态筛选、KPI 永远为 0 | 挂起时幂等设置状态 |
| 6 | 空回复能通过 fact_check（没有数字就没有冲突） | 可能自动发出空邮件 | 空回复重试一次，仍空则按失败转审批 |
| 7 | 阶梯价被 fact_check 误拦（回复提「500 台可进 $350 档」时 364 被判违规） | `volume_tier` 策略无法表达 | 允许 `quote.tiers` 里的合法档位价 |
| 8 | fact_check 漏检「305 USD」这种数字在前的格式 | 篡改价格可绕过校验 | 补正则，并加回归测试 |

### 修复后的测试

- `pytest tests -q`：**164 passed**（新增 10：审批动作 6 + fact_check 3 + 空回复 1）
- 覆盖：改稿通过并发送、改稿改错价不发送（退回重写）、非法动作驳回、reassign 再次挂起、审批/发送都有审计、空回复不自动发、阶梯价允许但非档位价仍拦截

### 仍然存在的边界

| 项 | 状态 |
|---|---|
| 并发 resume 同一 thread | 未加锁（单用户场景低风险），API 层实现时补 |
| `POST /api/threads/{id}/resume` | 未实现，模块 7 与审批台一起做 |
| 审批台展示 | 模块 7 |

---

## 范围裁剪（2026-10-30，用户决定）

个人项目、没有真实公司数据，以下三项明确不做或降级：

| 项 | PRD 要求 | 决定 | 理由 |
|---|---|---|---|
| 内部资信评分（F6 L2） | 合作年限 + 付款准时率 + 订单量加权 → A/B/C/D | **不做** | 需要真实历史交易数据，个人项目没有 |
| 出口管制（BIS Entity List / ECCN） | F6 L1 的一部分 | **不做** | 依赖真实商品编码与最终用户信息；对演示无增量 |
| 真实邮箱 IMAP/SMTP 联调（第 11 天 8 项） | 必须 | **降级为 Mailpit 端到端自测** | 验证时自己发模拟邮件，不碰真实客户邮箱 |

### 对验收口径的影响

| PRD 第 14 章条目 | 调整后 |
|---|---|
| 真实邮箱联调 8 项全过 | 改为「Mailpit 下收信/解析/线程归并/发送链路可用」 |
| `SEND_WHITELIST` 生效 | 保留（已有单测），但验证环境是 Mailpit |
| 制裁名单命中 OFAC 真实条目 | 保留（已达成） |
| 资信评分 / 出口管制 | 标记为 N/A（不在范围） |

> 如果将来要商用，仍需补：真实邮箱联调、资信数据源、出口管制名单。

### 代码现状（确保没有"假装修过"）

- 没有任何资信评分/出口管制实现，也没有占位函数声称能查
- 工具描述已从「制裁名单与出口管制筛查」改为「制裁名单筛查（OFAC SDN）」，避免模型误以为能查出口管制
- `customers.credit_score / credit_grade` 字段保留但恒为 `NULL`（预留，未接入）
- 策略 prompt 第 5 条改为「无法判断资信时倾向 escalate，不要自行承诺账期」
- `graph/nodes.py`、`tools/compliance.py` 的 docstring 已注明范围

---

## 模块 7 / 第 8—10 天：前端 4 页 + 配套 API ✅（2026-10-30）

### 交付内容

**API 层**

| 文件 | 接口 |
|---|---|
| `app/api/threads.py` | `GET /api/threads/{id}/trace`、`POST .../resume`、`POST .../restore`、`PATCH ...`（改绑）、`POST .../confirm-customer` |
| `app/api/customers.py` | `GET /api/customers`、`GET /api/customers/{id}`、`GET .../memory`、`PATCH .../facts/{fact_id}` |
| `app/api/simulate.py` | `POST /api/simulate/inbound`（场景 A/B/C/D）、`POST /api/simulate/reply` |
| `app/api/metrics.py` | `GET /api/metrics` |
| `app/graph/runtime.py` | 进程内缓存编译后的图实例 |

**前端**

| 文件 | 页面 |
|---|---|
| `views/InboxView.vue` | 工作台：KPI + 列表 + 状态筛选 + 模拟投递（A/B/C/D）+ 轨迹入口 + 已归档捞回 |
| `views/TraceView.vue` | 执行轨迹：节点时间线 + 运行信息 + 记忆注入 |
| `views/ApprovalsView.vue` | 审批台：待审批列表 + 报价/合规/策略/决策 + 草稿编辑 + 4 个动作 |
| `views/CustomersView.vue` | 客户列表 |
| `views/CustomerMemoryView.vue` | 客户记忆：画像 + 事实表（改值/失效）+ 记忆块 + 交互时间线 + 线索 |
| `api/{threads,customers,simulate}.ts`、`utils/format.ts` | 前端 API 客户端与格式化 |

### 实测（真实模型 + 真实数据）

| 场景 | 结果 |
|---|---|
| 模拟场景 A（500 台超授权） | 8 节点执行 → `waiting_approval` 挂起 → 审批台可见 |
| 审批台批准 | `approve → dispatch(DRY_RUN) → persist`，thread 变 `replied`，audit 写入 `approval` + `dispatch` |
| 模拟场景 C（信息不全） | `receive → triage → clarify`，追问草稿生成 |
| 模拟场景 B（垃圾） | 规则命中 → `archive` → thread `archived_spam`，工作台「已归档」可见 |
| 捞回 | `/restore` 把状态改回 `received` 并重跑图（跳过 spam 判定），最终进入审批 |
| 轨迹页 | 节点时间线、决策理由、记忆注入全部展示 |
| 客户记忆页 | 事实表可改值/失效，记忆块与交互时间线正常 |

### 本轮修复的问题

| # | 问题 | 修复 |
|---|---|---|
| 1 | `base.css` 缺 `.card/.timeline/.profile/.tags/.kv/.two-col/.three-col` 等整组样式，新页面布局错乱（标签挤一行、三列变单列） | 从设计基线补齐样式 |
| 2 | **`archive` 节点不更新 `threads.status`**，垃圾归档后「已归档」看不到、捞回无从谈起 | 改为 `make_archive_node`，按 comply/reject/spam 写终态 |
| 3 | `simulate/inbound` 同主题同发件人会被线程归并到旧 thread 并复用旧 checkpoint | 主题追加短标记 `[#xxxxxx]`，每次模拟独立线程 |
| 4 | Vite watcher 监听写入工具的临时目录触发 `EBUSY`，dev server 崩溃 | `server.watch.ignored` 忽略 `*.tmpdir` / `*.tmp` |
| 5 | facts 表在窄列里 5 列挤爆（有效期被截断） | 精简为 3 列，置信度/有效期并入值下方 |

### 自检

- `pytest tests -q`：**164 passed**
- `vue-tsc --noEmit`：通过
- 前端页面：4 页均实测渲染 + 交互（截图见 `docs/shots/module7-*.png`）

### 如实标注的边界

| 项 | 状态 |
|---|---|
| 登录页 `/login` | 未做（单用户本地开发不需要，PRD ADR-09 的认证留到需要时） |
| 前端单测 | 无（当前用类型检查 + 手工/截图验证；Phase 2 评测时补） |
| 评测集页 / 运行日志页 | 侧栏置灰，未实现 |
| 审批台「转他人」 | 图支持 reassign（重新挂起），但没有审批人列表/通知 |
| 真实邮箱 | 按范围裁剪，Mailpit 自测 |

### 下一步

- 第 11 天原计划的真实邮箱联调按范围裁剪为 Mailpit 自测
- 第 12 天：回归 + 验收清单（按裁剪后的口径）
- 之后可选：评测集（Phase 2）、登录、前端单测

---

## 第 11 天：真实邮箱联调（进行中，2026-10-30）

### 已完成

- QQ 邮箱 IMAP/SMTP 接入（`backend/app/mail/imap.py`）
  - `ID` 命令（QQ/163 必需）
  - **UID 基线**：首次连接记录 `UIDNEXT`，只拉之后的新邮件；基线绑定「邮箱地址 + UIDVALIDITY」，换邮箱自动重建
  - 解析复用 `parser.parse_raw_email`
  - 发信走 SMTP 465 SSL
- 轮询收信后**自动进图**（`app/graph/process.py`），不再只入库
- 真实闭环跑通：
  - 收信 → 入库 → 自动处理（triage → resolve → recall → draft_plan → compliance → decide → compose → 审批/自动回复）
  - 审批后 SMTP 真发（audit `dry_run=false, ok=true`）
  - 外发邮件写入 `messages`（`direction=outbound`）
- 前端：工作台「处理 / 重试」「关闭」「捞回」、审批台、轨迹、客户记忆

### 联调中修复的真实问题

| # | 问题 | 修复 |
|---|---|---|
| 1 | 换邮箱后基线串号（旧邮箱 UID 839 用到新邮箱，永远收不到信） | 基线绑定邮箱 + UIDVALIDITY，不匹配自动重建 |
| 2 | Microsoft 出站的畸形 `Message-ID`（`<[...@microsoft.com]>`）让 Python header 解析崩 | 改用 `raw_items()` 读原始头，加回归测试 |
| 3 | `archive` 节点不更新 `threads.status` | 按 comply/reject/spam 写终态 |
| 4 | 外发邮件不写 `messages` | dispatch 成功后写入 outbound |
| 5 | `clarify` 只生成追问草稿、没真发 | clarify 真发 + 写 outbound + 审计 |
| 6 | FOB 询盘被误判"缺目的港"（FOB 只需装运港） | triage prompt 按贸易术语判断 |
| 7 | 议价轮一律转人工，导致「数量 30→150 问优惠」不能自动回 | 改为「只有客户目标价低于本次报价才转人工」，阶梯价内自动回 |

### 待办

| 项 | 状态 |
|---|---|
| 第 12 天验收清单（PRD 第 14 章） | ✅ 已完成，见 `docs/验收清单.md` |
| triage 回信结合线程历史（老客户回信被重复追问） | ⬜ 未做 |
| 实体解析 L2 域名 / L3 公司名（现在只认邮箱） | ⬜ 未做 |
| 前端「改绑客户」「确认解析」入口 | ⬜ 未做 |
| `DRY_RUN` | ✅ `true` |
| 第 11 天 8 项联调补测（中文主题、附件、会话串联、IMAP 幂等） | ✅ 已完成，见 `docs/联调清单.md`（会话串联 7/8） |
| 评测集（Phase 2） | ⬜ 未做 |

### 安全

- 授权码只写进 `backend/.env`（已在 `.gitignore`），不入库、不进文档
- 联调结束后建议去 QQ 邮箱重置一次授权码

---

## 当前状态总览（2026-11-02）

| 阶段 | 内容 | 状态 |
|---|---|---|
| 模块 1（Day 1） | 收信 + 工作台 | ✅ |
| 模块 2（Day 2） | 图跑通（假数据） | ✅ |
| 模块 3（Day 3） | 工具层 + 策略 | ✅ |
| 模块 4（Day 4） | 分诊 + 记忆 | ✅ |
| 模块 5（Day 5—6） | 报价 + 合规 | ✅ |
| 模块 6（Day 7） | 决策 + 生成 + 审批 | ✅ |
| 模块 7（Day 8—10） | 前端 4 页 + API | ✅ |
| 第 11 天 | 真实邮箱联调 | ✅ 7/8（会话串联 Agent→客户待端到端） |
| 第 12 天 | 回归 + 验收清单 | ✅ 30 通过 / 3 部分 / 1 未通过 |

- 测试：`165 passed, 1 skipped`
- 联调清单：[`docs/联调清单.md`](联调清单.md)
- 验收清单：[`docs/验收清单.md`](验收清单.md)
- 当前 `MAIL_PROVIDER=imap`，`DRY_RUN=true`
- 截图：`docs/shots/`（module1—7、real-mail-*、trace-tool-calls 等）

### 第 12 天新增/修复

| # | 项 | 说明 |
|---|---|---|
| 1 | 轨迹记录工具调用 | `Step.tool_calls` 由 `draft_plan` 写入（ReAct 的 6 次调用），轨迹页展示工具名与参数（截图 `trace-tool-calls.png`） |
| 2 | 场景 D 不命中真实制裁 | `trading@sanctioned-example.com` 被 seed 成虚构客户「Sanctioned Trading」，遮住了 `BANCO NACIONAL DE CUBA`；改独立邮箱后命中 `OFAC SDN #306 · 1.00` → `archived_compliance` |
| 3 | IMAP 幂等统计 | provider 不再按 known 过滤，由入库层判重；同步成功后把基线推进到 `UIDNEXT`。实测 `fetched=13, duplicated=13, created=0` |
| 4 | PRD 议价口径 | ADR-17 与验收项同步为「客户目标价低于本次报价才转人工」 |

### 剩余待办

| 项 | 状态 |
|---|---|
| triage 回信结合线程历史（老客户回信被重复追问） | ⬜ 中优先级 |
| 实体解析 L2 域名 / L3 公司名 + 前端确认/否认入口 | ⏸️ **用户决定不做**（接受"只认邮箱"缺口，2026-11-02） |
| 议价不重复报规格（补断言测试） | ⬜ 低 |
| 会话串联 Agent→客户端到端（需第二邮箱授权码） | ⬜ 待用户 |
| 评测集（Phase 2） | ⬜ 未做 |
| 多 Agent（Phase 2） | ⬜ 未做（ADR-02 明确 Phase 2） |










