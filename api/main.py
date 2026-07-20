from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
load_dotenv(ROOT / ".env", override=True)

logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("accelerate").setLevel(logging.ERROR)
logging.getLogger("torch").setLevel(logging.ERROR)
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

from api.config import CORS_ORIGINS  # noqa: E402
from api.db.database import init_db  # noqa: E402
from api.routes import auth, chat, sessions  # noqa: E402
from src.tools.mcp_client import close_mcp_client_sessions  # noqa: E402
from src.workflow import build_workflow  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    app.state.workflow = build_workflow()
    yield
    await close_mcp_client_sessions()
    app.state.workflow = None


app = FastAPI(
    title="Financial MCP Agent API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(chat.router, prefix="/api")


@app.get("/")
def root():
    return {
        "message": "Financial MCP Agent API",
        "ui": "http://localhost:3000/login",
        "health": "/api/health",
    }


@app.get("/api/health")
def health():
    return {"status": "ok"}
