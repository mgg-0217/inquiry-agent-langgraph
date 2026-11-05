# Inquiry Agent（询盘管家）

外贸询盘接待 Agent：自己判断这封邮件该不该回、怎么回、要不要叫人。

- 需求与设计：[`docs/PRD.md`](docs/PRD.md)
- 开工与每日自检：[`docs/START.md`](docs/START.md)
- 进度记录：[`docs/PROGRESS.md`](docs/PROGRESS.md)

## 当前进度

**模块 1 / 第 1 天：能收到信、能上界面** ✅

Mailpit 投一封邮件 → 后端轮询解析入库 → 工作台列表可见，点开可看邮件正文与 `Message-ID`。

**模块 2 / 第 2 天：图能跑通（假数据）** ✅

13 个业务节点 + 4 个条件分支，happy path 能跑到 `persist`，`clarify → END`，`approval` 可 `interrupt` 挂起并跨实例恢复。

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\demo_happy_path.py   # 跑一条完整路径 + 一次挂起恢复
```

**模块 3 / 第 3 天：工具层 + 策略判断** ✅

8 个工具（6 读 2 写，统一 `{ok, data, code, retryable, message}` 契约）+ `ReplyStrategy` 三层约束（输出契约 / 判断原则 / 硬规则校验）。

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\demo_strategy_live.py   # 用真实 DeepSeek 跑老客户 / 新客户两种策略判断
```

**模块 4 / 第 4 天：分诊 + 记忆** ✅

LLM 分诊（垃圾 / 完整性 / 是否还价）+ 追问生成 + 四级实体解析（L1/L4）+ 长期记忆（证据校验、冲突取舍、召回记忆块）。数据库迁移改用 Alembic。

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\seed_demo.py            # 写入演示客户与历史
.\.venv\Scripts\python.exe scripts\show_memory.py carlos@acme-import.example
.\.venv\Scripts\python.exe scripts\demo_triage_live.py     # 真实模型分诊 + 记忆抽取
.\.venv\Scripts\python.exe scripts\demo_graph_live.py      # 端到端：新客户询盘 + 老客户还价
```

**模块 5 / 第 5—6 天：报价规划 + 合规** ✅

采购需求抽取 → ReAct 工具循环 → 代码重算报价 → 策略判断；OFAC SDN 真实名单（19,484 条）下载解析 + 实体消歧 + 阈值拦截。

```powershell
cd D:\dshWorkspace\inquiry-agent
.\backend\.venv\Scripts\python.exe scripts\fetch_sanctions.py --out backend/data/sanctions/ --insecure --load
cd backend
.\.venv\Scripts\python.exe scripts\demo_module5_live.py    # OFAC 命中 + 真实模型报价
```

**模块 6 / 第 7 天：决策 + 生成 + 审批闭环** ✅

模型建议 + 代码硬规则（超授权/合规/议价轮）→ 生成回复 → `fact_check`（拦截篡改与成本线泄露）→ 自动发或挂起审批 → `Command(resume)` 恢复 → 发送并写审计。

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/integration/test_full_flow.py -v
.\.venv\Scripts\python.exe scripts\demo_approval_live.py   # 超授权挂起 → 审批 → 发送
```

## 模块 7 / 第 8—10 天：前端 4 页 + 配套 API ✅

工作台（含模拟投递与捞回）、执行轨迹、审批台（改稿 + 4 动作）、客户记忆（事实纠正）全部可在页面上操作。

```powershell
# 打开 http://127.0.0.1:5173/inbox
# 顶部「模拟投递」A/B/C/D → 观察轨迹 → 到审批台批准/驳回/改稿
```

## 范围说明（个人项目裁剪）

按「没有真实公司数据、验证时自己发模拟邮件」的定位，以下明确不做：

- **内部资信评分**（需要真实历史交易数据）
- **出口管制**（BIS Entity List / ECCN，需要真实商品编码与最终用户信息）
- **真实邮箱 IMAP/SMTP 联调**：降级为 Mailpit 端到端自测

合规只做 **OFAC SDN 真实名单筛查**（19,484 条，可下载刷新）。
代码里没有资信/出口管制的占位实现，工具描述也不会声称能查这两项。
如果将来商用，需要补：真实邮箱联调、资信数据源、出口管制名单。

## 目录

```
backend/
  app/
    config.py          # Pydantic Settings（读 backend/.env）
    db/                # SQLAlchemy 模型与会话
    mail/              # MailProvider 抽象 + Mailpit 实现 + MIME 解析 + 入库
    graph/             # AgentState + 12 节点 + 4 条件分支 + 图构建 + prompts
    compliance/        # OFAC 名单加载 / 实体消歧 / 启动引导
    memory/            # 记忆抽取 / 证据校验写入 / 召回
    tools/             # 8 个工具（6 读 2 写）+ fixture + 注册
    strategy/          # ReplyStrategy + 判断原则 + resolve_price/guard
    llm/               # ChatOpenAI 封装 + structured output 兼容层
    api/               # FastAPI 路由（inbox 列表 / 线程详情 / 手动同步）
    main.py            # FastAPI 入口 + 邮件轮询
  scripts/             # 图结构打印、happy path 演示
  tests/               # pytest：单元 + 集成
  data/                # sqlite（不入库）
frontend/              # Vue 3 + Vite + Element Plus
scripts/               # Mailpit 启动、测试邮件投递
docs/                  # PRD / START / 进度 / 截图
```

## 启动（Windows PowerShell）

```powershell
cd D:\dshWorkspace\inquiry-agent

# 1. Mailpit（SMTP 1025 / Web 8025）
.\scripts\start-mailpit.cmd

# 2. 后端（8000）
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 3. 前端（5173）
cd ..\frontend
npm run dev
```

打开 <http://127.0.0.1:5173/inbox>。

## 投一封测试询盘

```powershell
cd D:\dshWorkspace\inquiry-agent
.\backend\.venv\Scripts\python.exe scripts\send_test_mail.py
```

10 秒内（轮询间隔 `IMAP_POLL_INTERVAL`）出现在工作台；页面每 10 秒自动刷新，也可以点「立即同步」。

## 测试

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/ -v
```

Mailpit 未启动时，集成测试自动跳过。

## 前端生产构建

```powershell
cd frontend
npm run build
```

若 `esbuild` 报 `Access is denied`（写系统临时目录被拒），先把 `TMP`/`TEMP` 指到工作区：

```powershell
$env:TMP="D:\dshWorkspace\.tmp"; $env:TEMP="D:\dshWorkspace\.tmp"
```

## 配置

复制 `backend/.env.example` 为 `backend/.env` 并填 `LLM_API_KEY`。
开发期 `MAIL_PROVIDER=mailpit`、`DRY_RUN=true`。
