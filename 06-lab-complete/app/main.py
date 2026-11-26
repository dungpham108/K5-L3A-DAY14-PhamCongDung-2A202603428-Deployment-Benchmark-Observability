"""
Production AI Agent — Part 6 Final Project

Luồng của POST /ask:
    verify_api_key (401) → check_rate_limit (429) → check_budget (402)
    → gọi LLM → record_cost → trả lời

Kiểm tra:
    python check_production_ready.py
"""
import json
import logging
import signal
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_tokens, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask


# ─────────────────────────────────────────────────────────
# Structured logging (tiêu chí 10): mỗi dòng log là 1 JSON object
# ─────────────────────────────────────────────────────────
_RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Các field truyền qua extra={...} được đưa thẳng vào JSON
        payload.update({k: v for k, v in vars(record).items() if k not in _RESERVED})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(JsonFormatter())
logging.basicConfig(level=settings.log_level, handlers=[_handler], force=True)
logger = logging.getLogger("agent")


# ─────────────────────────────────────────────────────────
# Graceful shutdown (tiêu chí 11)
# uvicorn đã tự xử lý SIGTERM: ngừng nhận kết nối mới, chờ request đang chạy xong rồi thoát.
# Ta chỉ "móc" thêm 1 dòng log rồi GỌI LẠI handler cũ của uvicorn.
# ─────────────────────────────────────────────────────────
def _install_sigterm_logger() -> None:
    previous = signal.getsignal(signal.SIGTERM)

    def _on_sigterm(signum, frame):
        logger.info("sigterm received, draining in-flight requests", extra={"event": "sigterm"})
        if callable(previous):
            previous(signum, frame)

    try:
        signal.signal(signal.SIGTERM, _on_sigterm)
    except ValueError:
        pass  # không ở main thread (vd chạy trong test client) → bỏ qua


@asynccontextmanager
async def lifespan(app: FastAPI):
    # uvicorn cài handler SIGTERM trước khi chạy lifespan → lúc này getsignal trả về handler của nó
    _install_sigterm_logger()
    logger.info("startup", extra={"event": "startup", "environment": settings.environment,
                                  "redis": redis_healthy()})
    yield
    logger.info("shutdown complete", extra={"event": "shutdown"})


app = FastAPI(title="Production AI Agent", lifespan=lifespan,
              docs_url=None if settings.environment == "production" else "/docs")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("unhandled error", extra={"event": "error", "path": request.url.path})
        # Không lộ stack trace ra client
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})
    logger.info("request", extra={
        "event": "request", "method": request.method, "path": request.url.path,
        "status": response.status_code, "ms": round((time.perf_counter() - start) * 1000, 1),
    })
    return response


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: Optional[str] = Field(default=None, max_length=100)


@app.get("/health")
def health():
    """Liveness: process còn sống là 200 — KHÔNG phụ thuộc Redis."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness: chỉ nhận traffic khi Redis (nơi chứa state) dùng được."""
    if not redis_healthy():
        return JSONResponse(status_code=503, content={"status": "not ready", "redis": "down"})
    return {"status": "ready", "redis": "ok"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)          # 429 nếu vượt RATE_LIMIT_PER_MINUTE
    check_budget()                     # 402 nếu hết DAILY/MONTHLY budget

    answer = llm_ask(body.question)

    input_tokens, output_tokens = estimate_tokens(body.question), estimate_tokens(answer)
    cost = record_cost(input_tokens, output_tokens)
    logger.info("llm call", extra={"event": "llm_call", "user_id": body.user_id,
                                   "input_tokens": input_tokens, "output_tokens": output_tokens,
                                   "cost_usd": round(cost, 8)})
    return {"question": body.question, "answer": answer,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                      "cost_usd": round(cost, 8)}}
