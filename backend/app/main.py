from __future__ import annotations

import asyncio
import sys

# uvicorn's --reload file-watcher supervisor forces
# WindowsSelectorEventLoopPolicy for its own process on Windows, and the
# reloaded worker process inherits that policy. SelectorEventLoop cannot
# create subprocesses on Windows at all -- asyncio.create_subprocess_exec
# (used by preprocessing/pipeline.py to run ffprobe/ffmpeg) always raises
# NotImplementedError under it, regardless of which command is run. Force
# the Proactor policy back explicitly, before anything else touches
# asyncio, so it overrides what the reloader set for this process.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.api.routes import router
from app.db.session import init_db
from app.config import ensure_runtime_directories

@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_runtime_directories()
    await init_db()
    yield

app = FastAPI(title="FactFlow API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # The backend currently uses no browser cookie/session credentials. A
    # wildcard origin with credentials is invalid for browser CORS clients.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)