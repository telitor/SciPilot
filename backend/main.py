import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import (
    handle_terminal_research_job_failure,
    process_research_job,
    router,
)
from services.research_job_service import run_research_job_worker
from services.supabase_service import SupabaseConfigurationError


def _job_worker_enabled() -> bool:
    return os.getenv("RESEARCH_JOB_WORKER_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop_event = asyncio.Event()
    worker_task: asyncio.Task | None = None
    if _job_worker_enabled():
        worker_task = asyncio.create_task(
            run_research_job_worker(
                process_research_job,
                stop_event=stop_event,
                terminal_failure_handler=handle_terminal_research_job_failure,
            )
        )
    try:
        yield
    finally:
        stop_event.set()
        if worker_task is not None:
            await worker_task


app = FastAPI(
    title="SciPilot Backend",
    version="1.0.0",
    description="Authenticated data and agent gateway for the SciPilot frontend.",
    lifespan=lifespan,
)

origins = [
    item.strip()
    for item in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.exception_handler(SupabaseConfigurationError)
async def supabase_configuration_error(_, exc: SupabaseConfigurationError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "SciPilot Backend",
        "api": "/api/v1",
        "docs": "/docs",
    }
