import asyncio
import json
import os
from contextlib import asynccontextmanager, AsyncExitStack
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI

from backend.repository import Repository
from backend.routers.ai import router
from ml.models.baseline import Baseline, Profile
from ml.tracing import Tracer

load_dotenv()


def create_app(repo=None, baseline=None):
    @asynccontextmanager
    async def lifespan(app):
        owned_repo = repo is None
        active_repo = repo or Repository(os.getenv("AI_DB_PATH", "var/ai.sqlite3"))
        if owned_repo and os.getenv("AI_PROFILE_PATH"):
            data = json.loads(Path(os.environ["AI_PROFILE_PATH"]).read_text(encoding="utf-8"))
            active_repo.seed([Profile.model_validate(p) for p in data])
        app.state.repo = active_repo
        app.state.generation_lock = asyncio.Lock()
        async with AsyncExitStack() as stack:
            if baseline is None:
                client = await stack.enter_async_context(httpx.AsyncClient())
                app.state.baseline = Baseline(client, Tracer())
            else:
                app.state.baseline = baseline
            try:
                yield
            finally:
                app.state.baseline.tracer.flush()
                if owned_repo:
                    active_repo.close()

    app = FastAPI(title="VKR AI baseline", lifespan=lifespan)
    app.include_router(router)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "ai-baseline"}

    return app


app = create_app()
