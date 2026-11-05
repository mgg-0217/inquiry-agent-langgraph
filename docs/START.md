# 开工指南（START）

> **本文档是 PRD 的执行补充。** PRD 讲"做什么、为什么"，本文讲"从哪开始、怎么验证"。
> PRD 路径：`D:\dshWorkspace\inquiry-agent\docs\PRD.md`

---

## 0. 如果你是接手的新对话

**只需要给新对话一个文件路径，不用粘贴任何正文。**

```
读 D:\dshWorkspace\inquiry-agent\docs\START.md 全文，然后从「第 1 天」开始执行。
```

这一句就够。START.md 第 0 章会告诉新对话去读 PRD 的哪几章，第 3 章会告诉它每天做什么、怎么自检。

> **为什么不用粘贴 PRD 全文**：PRD 有 2100+ 行，全塞进上下文会挤占工作空间，而且 90% 的内容当天用不到。给路径让它按需读，效果更好。

如果需要更保险（怕新对话漏看），可以复制这段：

```
我要开始实现 inquiry-agent（外贸询盘 Agent）。

先读 D:\dshWorkspace\inquiry-agent\docs\START.md 全文，按第 0 章的指引
再读 PRD 的相关章节（第 0、7.1、7.2、7.3、7.3.1、7.7、15 章），
然后从「第 1 天」开始执行。

每天结束必须跑该天的自检命令，不通过不进下一天。
遇到设计问题查 PRD 第 12 章 ADR，不要自己重新发明。

【当前环境状态】
- 工作目录：D:\dshWorkspace\inquiry-agent
- 已有文件：docs/PRD.md、docs/START.md、scripts/start-mailpit.ps1、
           scripts/start-mailpit.cmd、scripts/check_qq_imap.py
- 尚未创建：backend/、frontend/、pyproject.toml
- Mailpit 已装好：D:\dshWorkspace\tools\mailpit\mailpit.exe（v1.32.0，SMTP/API 实测通过）
  启动：.\scripts\start-mailpit.cmd
- 真实邮箱：QQ 邮箱授权码尚未拿到（注册未满 14 天），第 11 天联调前需重新确认
- DeepSeek API Key：待确认

【三条硬约束】（详见 PRD 第 0 章）
A. 决策权交给模型；金额授权、名单命中、强制转人工由代码硬规则决定
B. 数字只能来自工具返回值；模型只组织语言，生成后必须 fact_check
C. 制裁名单用真实公开数据；内部数据用 fixture；付费数据用 Provider 占位

【已知环境坑】（详见 2.4 与第 5 节）
- 本机主机名含中文，smtplib 必须传 local_hostname="localhost"
- PowerShell ExecutionPolicy 限制，运行 .ps1 用 .cmd 包装器
- GitHub CDN 被 hosts 屏蔽，下载依赖走镜像时必须做 SHA256 校验
```

**新对话不需要读的 PRD 章节**：第 2 章（名词解释，除非不懂术语）、第 16 章（面试叙事）、第 17.2—17.4（附录杂项）。

---

## 0.1 已知排期风险

| 风险 | 影响 | 应对 |
|---|---|---|
| **QQ 邮箱注册未满 14 天**，拿不到 IMAP 授权码 | 第 11 天真实邮箱联调可能做不了 | ① 第 1—10 天完全不受影响；② 开工前先点一次"开启 IMAP"确认剩余天数；③ 实在不行用另一个 QQ 号或 Outlook 邮箱替代 |
| 未配 DeepSeek API Key | 第 1 天 `check_llm.py` 就卡住 | 开工前必须完成，充 10 元够跑几百次 |
| 依赖下载慢（GitHub 被墙） | pip / npm 可能失败 | 配置国内镜像源 |

---

## 1. 环境前置检查（5 分钟）

| 检查项 | 命令 | 期望 |
|---|---|---|
| Python | `python --version` | ≥ 3.11 |
| Node.js | `node --version` | ≥ 20 |
| Docker | `docker --version` | 有输出即可 |
| 端口占用 | `netstat -ano \| findstr "8000 5173 1025 8025"` | 无输出 = 空闲 |
| 工作目录 | `cd D:\dshWorkspace\inquiry-agent` | 目录已存在 |

**任何一项不满足就先处理，不要往下走。**

---

## 2. 一次性准备（约 30 分钟）

### 2.1 建目录

```powershell
cd D:\dshWorkspace\inquiry-agent
New-Item -ItemType Directory -Force -Path backend\app, backend\data, backend\tests, frontend, scripts | Out-Null
```

### 2.2 后端依赖

`backend/requirements.txt`：

```ini
# Agent
langgraph>=0.2.45
langchain-openai>=0.2.0
langchain-core>=0.3.0

# Web
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
pydantic>=2.9.0
pydantic-settings>=2.6.0
python-dotenv>=1.0.1

# DB
sqlalchemy>=2.0.36
alembic>=1.14.0

# Mail
imap-tools>=1.7.0

# Auth
bcrypt>=4.2.0
python-jose[cryptography]>=3.3.0

# Test
pytest>=8.3.0
pytest-asyncio>=0.24.0
httpx>=0.27.0
```

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> 若 PowerShell 报"禁止运行脚本"：`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`

### 2.3 前端脚手架

```powershell
cd D:\dshWorkspace\inquiry-agent
npm create vite@latest frontend -- --template vue-ts
cd frontend
npm install
npm i element-plus pinia vue-router axios echarts vue-echarts
```

### 2.4 邮件环境

#### 方案 A：Mailpit 原生 exe（**已选定，本机已装好并验证**）

| 项 | 值 |
|---|---|
| 版本 | **v1.32.0**（2026-10-22 发布，含安全修复） |
| 路径 | `D:\dshWorkspace\tools\mailpit\mailpit.exe` |
| 大小 | 26.75 MB（单文件，无需安装） |
| 校验 | SHA256 `16915767a6c95dca569336e8f561f91cf355e9a33c57b91deedcc10a4bba7fd4` **已验证通过** |
| 状态 | SMTP 收信 + HTTP API 已实测通过 |

**一键启动（推荐）**：

```powershell
cd D:\dshWorkspace\inquiry-agent
.\scripts\start-mailpit.cmd            # 启动
.\scripts\start-mailpit.cmd -Status    # 查看状态
.\scripts\start-mailpit.cmd -Stop      # 停止
```

启动后：

- Web UI：`http://localhost:8025`
- SMTP：`127.0.0.1:1025`
- HTTP API：`http://localhost:8025/api/v1`（拉信走这个，见下方「坑 4」）
- 数据：`backend/data/mailpit.db`（持久化，重启不丢信）

**手动启动**（不用脚本时）：

```powershell
D:\dshWorkspace\tools\mailpit\mailpit.exe `
  --smtp 127.0.0.1:1025 `
  --listen 127.0.0.1:8025 `
  --database D:\dshWorkspace\inquiry-agent\backend\data\mailpit.db
```

#### ⚠️ 本机实测踩到的 3 个坑（都已解决，记下来避免重踩）

**坑 1：GitHub 下载不通**

hosts 文件里有这些记录把 GitHub CDN 全指向了 `127.0.0.1`：

```
127.0.0.1 githubusercontent.com
127.0.0.1 raw.githubusercontent.com
127.0.0.1 objects.githubusercontent.com
...
```

`github.com` 本身能连，但 release 文件会 302 到 `objects.githubusercontent.com`，那个域名被墙死了。

**解决方式**：用镜像下载 + **SHA256 校验**。校验通过就证明文件是官方的，镜像不可信也没关系。

```python
# 用 Python 走 OpenSSL（curl 的 schannel 在本机会报 SEC_E_NO_CREDENTIALS）
MIRRORS = [
    "https://ghfast.top/" + UPSTREAM,
    "https://ghproxy.net/" + UPSTREAM,
    "https://gh-proxy.com/" + UPSTREAM,
]
# 下载后必须比对官方 SHA256
```

**坑 2：PowerShell ExecutionPolicy 阻止运行脚本**

现象：`cannot be loaded. The file ... is not digitally signed.`

**解决**：用 `.cmd` 包装器（已提供），它内部用 `-ExecutionPolicy Bypass`。

或者手动：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

**坑 3：本机中文计算机名导致 SMTP 发信失败** 🔴

本机主机名是中文（`中文主机名（示例）`），`smtplib` 的 EHLO 握手默认用本机 hostname，**ASCII 编码失败**：

```
UnicodeEncodeError: 'ascii' codec can't encode characters in position 5-10
```

**解决**：任何地方建 SMTP 连接都必须显式指定 `local_hostname`：

```python
# ❌ 报错
smtplib.SMTP("127.0.0.1", 1025)

# ✅ 正确
smtplib.SMTP("127.0.0.1", 1025, local_hostname="localhost")
```

> 这个坑会出现在 `MailProvider.send()` 里，写代码时别忘了。

**坑 4：Mailpit v1.32.0 不支持 IMAP** 🟡

实测 `mailpit.exe --help` 里**没有** `--imap` / `--pop3` 之外的 IMAP 收信参数，传入 `--imap` 会直接
`Error: unknown flag: --imap` 退出。文档里"IMAP 端口 2114"的描述在这个版本上不成立。

**解决**：Mailpit 模式下**改用 HTTP API 拉原始邮件**：

```
GET /api/v1/messages                  # 列表（含 ID、MessageID、Created）
GET /api/v1/message/{ID}/raw          # 原始 EML（注意是 /raw，不是 .eml）
```

后端 `app/mail/mailpit.py` 已按此实现，并复用 `app/mail/parser.py` 的同一套 MIME 解析，
真实邮箱（第 11 天）的 IMAP 实现也会走同一个 parser。

#### 方案 B：Docker（以后装了可以切）

```yaml
# docker-compose.yml
services:
  mailpit:
    image: axllent/mailpit
    container_name: inquiry-mailpit
    ports:
      - "1025:1025"
      - "8025:8025"
    volumes:
      - ./backend/data/mailpit:/data
    restart: unless-stopped
```

```powershell
docker compose up -d
```

**注意**：Docker 和 exe **二选一**，同时开会抢 1025/8025 端口。

#### 方案 C：什么都不装（第 1—3 天可以这样）

用注入接口造邮件：

```powershell
curl -X POST http://localhost:8000/api/simulate/inbound -H "Content-Type: application/json" -d '{"scenario":"A"}'
```

配合 `DRY_RUN=true`，发送只写日志不真发。

> **建议节奏**：第 1—3 天用 C（最快看到效果），第 4 天起切到 A（已装好，直接用脚本启动）。
>
> **⚠️ 注意**：Mailpit 只是本地邮件模拟环境，**它不能替代真实邮箱**。第 11 天的真实邮箱联调（IMAP/SMTP）照样必须做，见 F1.1。

### 2.5 API Key

`backend/.env`（从 `.env.example` 复制）：

```ini
DEEPSEEK_API_KEY=sk-你的真实key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DATABASE_URL=sqlite:///./data/inquiry.db
MAIL_PROVIDER=mailpit
DRY_RUN=true
SMTP_HOST=localhost
SMTP_PORT=1025
SMTP_FROM=sales@example.com
AUTH_SECRET_KEY=dev-only-change-me
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=
AGENT_MODE=single
MAX_STEPS=15
MAX_TURNS=8
SPAM_THRESHOLD=0.85
SANCTION_REJECT_THRESHOLD=0.95
SANCTION_REVIEW_THRESHOLD=0.75
QUOTE_VALID_DAYS=7
AUTO_REPLY_LIMIT=150000
DEFAULT_INCOTERM=FOB
```

#### 2.5.1 提前准备测试邮箱（第 11 天要用）

**现在就做，别等到第 11 天**：

| 准备项 | 说明 |
|---|---|
| 一个专用测试邮箱 | QQ / 163 都行，**不要用工作邮箱或会收到真实客户信的邮箱** |
| 开启 IMAP/SMTP | 网页版邮箱 → 设置 → 账户 → 开启 POP3/IMAP/SMTP 服务 |
| 生成授权码 | 就是 `.env` 里的 `IMAP_PASSWORD`，**不是登录密码** |
| 另一个收件邮箱 | 联调发信时用，也由你控制 |

**QQ 邮箱开启步骤**：

1. 打开 `mail.qq.com` 登录
2. 右上角「设置」→「账号」标签
3. 找到「POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务」
4. 「IMAP/SMTP服务」点「开启」
5. 手机短信 / QQ安全中心验证
6. 拿到 **16 位授权码**，立刻复制保存（只显示一次）

常见服务商参数：

| 服务商 | IMAP | SMTP |
|---|---|---|
| QQ 邮箱 | `imap.qq.com:993` (SSL) | `smtp.qq.com:465` (SSL) |
| 163 邮箱 | `imap.163.com:993` (SSL) | `smtp.163.com:465` (SSL) |
| 腾讯企业邮 | `imap.exmail.qq.com:993` | `smtp.exmail.qq.com:465` |
| Gmail | `imap.gmail.com:993` | `smtp.gmail.com:587` (STARTTLS) |

> 以服务商官方文档为准。

**拿到授权码后立刻验证**（不用等到第 11 天）：

```powershell
cd D:\dshWorkspace\inquiry-agent
python scripts/check_qq_imap.py 你的邮箱@qq.com 你的16位授权码
```

期望输出：

```
ID 命令已发送（QQ 邮箱必需）
✅ 登录成功
✅ 进入 INBOX，邮件总数: 3
最近 3 封邮件：
  - 主题  : ...
    发件人: ...
✅ IMAP 验证全部通过
```

> **QQ / 163 邮箱有个必踩的坑**：登录后必须发送 `ID` 命令，否则 `SELECT` 会报
> `Unsafe Login. Please contact kefu@188.com for help`。
> `scripts/check_qq_imap.py` 和后续的 `MailProvider` 实现里都已经处理了这件事。

#### 2.5.2 验证 Key 可用

```python
# backend/check_llm.py
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()
llm = ChatOpenAI(
    model=os.getenv("DEEPSEEK_MODEL"),
    base_url=os.getenv("DEEPSEEK_BASE_URL"),
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    temperature=0,
)
print(llm.invoke("回复三个字：通了").content)
```

```powershell
cd backend
python check_llm.py
# 期望输出类似：通了
```

> **这一步不通，后面全是白做。** 先解决 Key / 网络 / 余额问题。

---

## 3. 执行顺序（按天，每天必须通过自检）

### 第 1 天：能收到信、能上界面

**目标**：Mailpit 投一封邮件 → 10 秒内出现在工作台列表里。

**任务**：

1. `app/config.py`——Pydantic Settings 读 `.env`
2. `app/db/models.py`——先只建 3 张表：`customers`、`threads`、`messages`
3. `app/db/session.py`——SQLAlchemy engine + session
4. `app/mail/base.py`——`MailProvider` 接口（`fetch_new()` / `send()`）
5. `app/mail/mailpit.py`——从 Mailpit HTTP API 拉原始 EML（`GET /api/v1/messages` + `GET /api/v1/message/{ID}/raw`，见 2.4 坑 4）
6. `app/mail/parser.py`——MIME 解析，抽出 `Message-ID` / `In-Reply-To` / 正文 / 附件
7. `app/api/inbox.py`——`GET /api/inbox` 返回列表
8. `app/main.py`——FastAPI 入口 + 定时轮询任务
9. 前端：`/inbox` 页面 + axios 调接口 + Element Plus 表格

**自检**：

```powershell
# 1. 投一封测试邮件
python scripts/send_test_mail.py

# 2. 浏览器打开 http://localhost:8025 确认邮件在 Mailpit 里

# 3. 等 10 秒，查接口
curl http://localhost:8000/api/inbox

# 4. 浏览器打开 http://localhost:5173/inbox，确认表格里能看到这封信
```

**通过标准**：界面能看到邮件、主题、发件人、时间，且 `Message-ID` 已入库。

> ✅ **v1.32.0 没有 IMAP**，第 1 天已用 Mailpit HTTP API 拉信（见 2.4 坑 4）；
> `POST /api/simulate/inbound`（第 2 天起做）是直接调图的开发入口，不依赖邮件协议。

---

### 第 2 天：图能跑通（假数据）

**目标**：`python -m app.graph.build` 能编译出图，用假 state invoke 一遍不报错。

**任务**：

1. `app/graph/state.py`——`AgentState`（照 PRD 7.1 抄全，**包括 `round` / `is_followup` 那 4 个字段**）
2. `app/graph/nodes.py`——12 个节点空实现，每个 `return {}` 或返回固定假值
3. `app/graph/edges.py`——4 个条件分支
4. `app/graph/build.py`——照 PRD 7.7 组图
5. 加一条 happy path 测试：假邮件 → 走完 → 到 `persist`

**自检**：

```powershell
pytest backend/tests/unit/test_graph_compiles.py -v
# 期望：图能编译、能跑通一次完整路径

python -c "from app.graph.build import build_single_agent; g = build_single_agent(); print(g.get_graph().nodes.keys())"
# 期望：能看到 13 个节点名
```

**关键检查**：

```python
# 必须是 clarify → END，不能是 clarify → receive
assert "receive" not in [e[1] for e in graph.get_graph().edges
                         if e[0] == "clarify"]
```

---

### 第 3 天：工具层 + 策略判断（可并行）

**目标**：8 个工具能用假数据调通；`ReplyStrategy` 能产出结构化结果。

**任务 A（工具）**：

- `app/tools/schema.py`——统一返回契约 `{ok, data, code, retryable, message}`
- `app/tools/product.py` / `pricing.py` / `customer.py` / `compliance.py` / `comms.py`
- `calc_price` **必须返回 `tiers[] + applicable + target_matched_price + floor_price`**（PRD F5）

**任务 B（策略，可脱库）**：

- `app/strategy/schema.py`——`ReplyStrategy`（PRD 7.8.2）
- `app/strategy/prompt.py`——判断原则（PRD 7.8.3）
- `app/strategy/resolve.py`——`resolve_price()` + `guard()`（PRD 7.8.4）
- `app/strategy/node.py`——调用封装 + 重试兜底

**自检 A**：

```powershell
pytest backend/tests/unit/test_tools.py -v
```

**自检 B**（这条最重要，它决定项目能不能成立）：

```powershell
pytest backend/tests/unit/test_strategy.py -v
```

必须通过的 3 个用例：

| 用例 | 输入 | 期望 |
|---|---|---|
| 老客户达标 | 记忆含 `target_price=350`、算价 $350 | `stance=re_engage`, `mention_history=true` |
| 新客户 | 空记忆 | `mention_history=false` |
| 触成本线 | 算价 $330、floor $338 | `stance` 被改成 `escalate` |

---

### 第 4 天：分诊 + 记忆

**任务**：

1. `triage` 节点——垃圾判定 + 完整性判定 + **`is_negotiation` 判定**
2. `clarify` 节点——生成追问，`END`
3. `memory/store.py`——`persist()` + 证据校验
4. `memory/recall.py`——`recall()` 拼记忆块
5. `resolve` 节点——四级实体解析（先只做 L1 邮箱精确 + L4 新建）

**自检**：

```powershell
pytest backend/tests/unit/test_memory.py -v
```

必须通过：

| 用例 | 期望 |
|---|---|
| 证据不在原文 | 该 fact 被丢弃，日志有警告 |
| `no_response` 场景 | `lost_reason=no_response`，不进 facts 的 price 类 |
| 冲突取值 | 两条有效记录，只召回 `superseded_by IS NULL` 的最新一条 |

---

### 第 5—6 天：报价 + 合规

**任务**：

- `draft_plan` 节点（ReAct + 工具循环 + 区分首轮/议价）
- `compliance` 节点 + OFAC 名单下载解析 + 实体消歧
- `scripts/fetch_sanctions.py`

**自检**：

```powershell
python scripts/fetch_sanctions.py --out backend/data/sanctions/
pytest backend/tests/unit/test_compliance.py -v
```

必须通过：能命中 OFAC 真实条目并给出 `evidence`（名单名称 + 条目号 + 匹配分）。

---

### 第 7 天：决策 + 生成 + 审批

**任务**：

- `decide` 节点（含**议价强制 escalate**）
- `compose` 节点 + `fact_check`
- `approval` 节点（`interrupt`）+ `dispatch`

**自检**：

```powershell
pytest backend/tests/integration/test_full_flow.py -v
```

必须通过：

| 用例 | 期望 |
|---|---|
| 超授权 | 挂起在 `approval`，`state.next` 指向待审 |
| 进程重启后恢复 | `Command(resume={"action":"approve"})` 能继续到 `dispatch` |
| 议价轮 | `round=2` + 还价 → 强制进审批 |

---

### 第 8—10 天：前端 4 页

按 PRD 15 章的页面级工时：

| 页面 | 工时 |
|---|---|
| 询盘工作台（含已拦截列表 + 捞回按钮） | 1 天 |
| 执行轨迹（时间线 + 工具展开） | 0.75 天 |
| 审批台（编辑 + 二次校验 + 4 个动作） | 1 天 |
| 客户记忆（事实表 + 纠正 + 改绑） | 0.5 天 |

**自检**：手工走一遍四个场景（A/B/C/D），每一步界面都有对应展示。

---

### 第 11 天：真实邮箱联调（**不能省**）

> **为什么单独一天**：Mailpit 只是本地模拟，它能跑通不代表能对接真实邮箱。SSL、编码、附件、超时、限流全都不一样。**不验证就演示，等于赌**。

**要做的事**：

1. `.env` 切换到真实邮箱：

```ini
MAIL_PROVIDER=imap
IMAP_HOST=imap.qq.com
IMAP_PORT=993
IMAP_USER=你的测试邮箱@qq.com
IMAP_PASSWORD=授权码
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SEND_WHITELIST=你自己控制的另一个邮箱@example.com
IMAP_POLL_INTERVAL=30
DRY_RUN=true          # 先 true，验到最后一项再改 false
```

2. 实现 `app/mail/imap.py`（`MailProvider` 的第二个实现）
3. 跑 F1.3 的 **8 项联调清单**

**8 项联调清单**：

| # | 验证项 | 怎么验 | 通过标准 |
|---|---|---|---|
| 1 | 收信 | 用另一个邮箱给测试邮箱发一封 | 10 秒内出现在工作台 |
| 2 | 解析 | 检查主题/正文/发件人 `Message-ID` | 全部正确 |
| 3 | 线程归并 | 在邮件客户端里点"回复" | 归到同一 thread |
| 4 | 发信 | `DRY_RUN=false` 后让 Agent 回复 | 真实邮箱里收到 |
| 5 | 会话串联 | 在客户端看这封回复 | 串成同一对话 |
| 6 | 幂等 | 重启服务，重新拉取 | 不重复建 thread |
| 7 | 编码 | 发中文主题 + 带附件的邮件 | 不乱码 |
| 8 | 反垃圾 | 看是否进垃圾箱 | 大概率正常，偶发可接受 |

**自检**：

```powershell
pytest backend/tests/integration/test_imap_provider.py -v
```

**通过标准**：8 项全过。有任何一项不过，**第 12 天不能算完成**，必须先修。

**注意**：第 4 项会真发邮件，所以：
- 必须配 `SEND_WHITELIST`，只给自己控制的地址发
- 验完立刻把 `DRY_RUN` 改回 `true`

---

### 第 12 天：回归 + 验收

跑 PRD 第 14 章的 **全部验收项**，逐条打勾。有一条不过就不算完成。

**特别注意这两条**（容易被跳过）：

- [ ] 真实邮箱 8 项联调全过
- [ ] `SEND_WHITELIST` 生效：给非白名单地址发信被拦截

**演示前最后检查**：

| 检查项 | 说明 |
|---|---|
| 演示用哪个邮箱 | 应该是真实邮箱，Mailpit 作为降级备份 |
| `DRY_RUN` 状态 | 演示要真发，应为 `false` |
| `SEND_WHITELIST` | 确认只包含你要演示的收件地址 |
| 录屏备份 | **提前录一段完整流程**，网络挂了能顶 |
| 降级预案 | 现场出问题时，`.env` 切 `MAIL_PROVIDER=mailpit` 继续讲 |

---

## 4. 每天收工前的固定动作

```powershell
# 1. 全量测试
pytest backend/tests/ -v

# 2. 类型检查（可选但强烈建议）
mypy backend/app --ignore-missing-imports

# 3. 启动一遍，确认能起来
uvicorn app.main:app --reload --port 8000
```

**任何一条挂了，当天不往下推进。** 欠账会在第 10 天集中爆发。

---

## 5. 最容易翻车的 10 个点（提前记住）

| # | 坑 | 症状 | 修法 |
|---|---|---|---|
| 1 | `clarify` 写成 `→ receive` | 追问后流程不再动 | 必须 `→ END`，回信时同 thread 重新 `invoke` |
| 2 | `SqliteSaver.from_conn_string()` 直接传给 `compile` | 启动报 `contextmanager` 错误 | 手动建 `conn` + `SqliteSaver(conn)` |
| 3 | 把记忆写进 checkpointer | 换个 thread 记忆就没了 | 写业务表，按 `customer_id` 查 |
| 4 | 模型自己算总价 | 报价对不上 | 数字只从 `calc_price` 取，生成后 `fact_check` |
| 5 | `no_response` 当成 `price_high` | Agent 反复自动降价 | 两个枚举值分开，`no_response` 不许进价格类 fact |
| 6 | 人工编辑后直接发 | 改错数字没人拦 | 编辑后强制再跑一次 `fact_check` |
| 7 | 新客户 `mention_history=true` | "上次您提到…"穿帮 | `guard()` 强制置 false |
| 8 | 判 spam 阈值太低 | 真询盘被归档 | 自动归档阈值 ≥ 0.85，且支持捞回 |
| 9 | **只跑 Mailpit 就交付** | 演示当天发现连不上真实邮箱 | 第 11 天必须完成 8 项真实邮箱联调 |
| 10 | **SMTP 不指定 `local_hostname`** | 本机中文计算机名导致 `UnicodeEncodeError: 'ascii' codec can't encode` | 一律 `smtplib.SMTP(host, port, local_hostname="localhost")` |

---

## 6. 不要做的事

- ❌ 不要在第 1 天就想把 12 个节点全写完
- ❌ 不要在 PRD 没写清楚的地方自己发明设计（先查第 12 章 ADR，查不到就问）
- ❌ 不要跳过自检直接进下一天
- ❌ 不要把 API Key 提交到 git
- ❌ 不要在没有 `fact_check` 的情况下让 Agent 自动发邮件
- ❌ 不要先做前端再验证后端（链路没通，前端只是空壳）

---

## 7. 出了问题时

| 问题 | 看哪里 |
|---|---|
| 不知道某个设计为什么这么定 | PRD 第 12 章 ADR（17 条） |
| 不确定记忆该存什么 | PRD F3.6（fact key 清单）+ F3.7（该记什么） |
| 不确定策略判断边界 | PRD 7.8（三层约束） |
| 不确定某个流程怎么走 | PRD 7.2（节点表）+ 7.3（条件分支）+ 7.3.1（轮次） |
| 不知道演示数据长什么样 | PRD 17.1（场景 A/B/C/D + M1/M2/M3） |
| 验收标准是什么 | PRD 第 14 章（51 条 checkbox） |

---

## 8. 第一天开始前，确认这四件事

- [x] **DeepSeek API Key 已验证**：`python scripts/verify_llm_key.py` 三项全过（基础对话 / Function Calling / temperature=0 一致性）—— **已完成 ✅**
- [x] **Mailpit 已装好**：`.\scripts\start-mailpit.cmd` 能起来，`http://localhost:8025` 有界面 —— **已完成 ✅**
- [x] **Backend 依赖已装齐**：`backend/.venv` 已建，`requirements.lock.txt` 77 个包 —— **已完成 ✅**
- [ ] **QQ 邮箱授权码**（第 11 天真实邮箱联调才需要，注册未满 14 天，抽空去点一次确认剩余天数）

**前三项已就绪，可以直接从第 1 天开工。**

## 8.1 已就绪环境清单（2026-10-29 实测）

| 组件 | 版本 / 路径 | 状态 |
|---|---|---|
| Python | 3.11.9 | ✅ |
| venv | `backend/.venv` | ✅ |
| LangGraph | **1.2.18** | ✅ |
| langgraph-checkpoint-sqlite | 3.1.2 | ✅ |
| langchain-openai | 1.7.3 | ✅ |
| Pydantic | 2.14.1 | ✅ |
| FastAPI | 0.162.0 | ✅ |
| SQLAlchemy | 2.1.6 | ✅ |
| Mailpit | v1.32.0 @ `D:\dshWorkspace\tools\mailpit\` | ✅ |
| DeepSeek Key | 已验证 3 项能力 | ✅ |
| QQ 授权码 | — | ⬜ 待办 |

**已知版本差异**：LangGraph 1.x 把 SQLite checkpointer 拆成独立包，必须 `pip install langgraph-checkpoint-sqlite`。导入路径 `from langgraph.checkpoint.sqlite import SqliteSaver` 和用法 `SqliteSaver(conn)` 与旧版一致。
