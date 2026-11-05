"""FastAPI 入口：应用装配 + 邮件轮询后台任务。"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import customers, inbox, metrics, simulate, threads
from app.api.common import fail, ok
from app.compliance.bootstrap import ensure_sanctions_loaded
from app.config import settings
from app.db.migrate import run_migrations
from app.db.models import Thread
from app.db.session import session_scope
from app.graph.build import CHECKPOINT_FILE, close_default_checkpointer
from app.graph.process import process_thread
from app.mail.factory import build_provider
from app.mail.ingest import sync_inbox
from app.mail.mailpit import MailpitError
from app.monitor import load_health, record_failure, record_success
from app.tools.compliance import get_index

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("inquiry")


def _sync_once() -> None:
    with session_scope() as session:
        report = sync_inbox(session, build_provider())
    # 新邮件入库后自动跑一次 Agent（真实 IMAP 收信也走这里）
    for thread_id in report.touched_thread_ids:
        try:
            process_thread(thread_id)
        except Exception:  # noqa: BLE001
            logger.exception("自动处理线程失败 thread_id=%s", thread_id)


async def _poll_loop(stop: asyncio.Event) -> None:
    interval = max(3, settings.imap_poll_interval)
    logger.info("邮件轮询启动，间隔 %ss，provider=%s", interval, settings.mail_provider)
    while not stop.is_set():
        try:
            await asyncio.to_thread(_sync_once)
            record_success()
        except MailpitError as exc:
            # 开发期 Mailpit 经常没开，只提示、不打堆栈刷屏
            logger.warning("邮件轮询暂不可用：%s", exc)
            record_failure(str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("邮件轮询失败")
            record_failure(str(exc))
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
    logger.info("邮件轮询已停止")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    run_migrations()
    ensure_sanctions_loaded()
    get_index()  # 预热制裁索引，避免首个询盘请求等待 1s 构建
    stop = asyncio.Event()
    task = asyncio.create_task(_poll_loop(stop))
    try:
        yield
    finally:
        stop.set()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        close_default_checkpointer()


app = FastAPI(title="Inquiry Agent API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(inbox.router)
app.include_router(threads.router)
app.include_router(customers.router)
app.include_router(simulate.router)
app.include_router(metrics.router)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_request: Request, exc: StarletteHTTPException):
    """覆盖路由 404 / 405 与业务里 raise 的 HTTPException，统一响应格式。"""
    return JSONResponse(
        status_code=exc.status_code,
        content=fail(exc.status_code, str(exc.detail)),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request: Request, exc: RequestValidationError):
    """参数校验失败也必须走统一响应格式，否则前端 interceptor 会把错误当成功。"""
    logger.warning("参数校验失败：%s", exc.errors())
    return JSONResponse(
        status_code=422,
        content=fail(422, "参数校验失败", data=jsonable_encoder(exc.errors())),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("未捕获异常：%s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content=fail(500, "服务内部错误"))


@app.get("/api/health")
def health():
    db_ok = True
    try:
        with session_scope() as session:
            session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False

    monitor = {"last_sync_at": None, "last_ok_at": None, "consecutive_failures": 0,
               "alert_active": False, "last_alert_at": None, "last_error": None}
    waiting = 0
    checkpoint_rows = 0
    db_size_mb = None
    try:
        monitor = load_health()
        with session_scope() as session:
            waiting = (
                session.query(Thread).filter(Thread.status == "waiting_approval").count()
            )
        if settings.database_file.exists():
            db_size_mb = round(settings.database_file.stat().st_size / 1024 / 1024, 2)
    except Exception:  # noqa: BLE001
        pass

    # checkpointer 存在独立的 data/checkpoints.db
    checkpoint_rows = 0
    checkpoint_db_mb = None
    try:
        if CHECKPOINT_FILE.exists():
            checkpoint_db_mb = round(CHECKPOINT_FILE.stat().st_size / 1024 / 1024, 2)
            conn = sqlite3.connect(str(CHECKPOINT_FILE))
            try:
                checkpoint_rows = (
                    conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
                )
            finally:
                conn.close()
    except Exception:  # noqa: BLE001
        checkpoint_rows = 0

    return ok(
        {
            "status": "ok" if db_ok else "degraded",
            "db": db_ok,
            "mail_provider": settings.mail_provider,
            "dry_run": settings.dry_run,
            "llm_configured": bool(settings.llm_api_key),
            "agent_mode": settings.agent_mode,
            **monitor,
            "waiting_approval": waiting,
            "checkpoint_rows": checkpoint_rows,
            "checkpoint_db_mb": checkpoint_db_mb,
            "db_size_mb": db_size_mb,
        }
    )
