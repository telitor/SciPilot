import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import router
from services.supabase_service import SupabaseConfigurationError

app = FastAPI(
    title="SciPilot Backend",
    version="1.0.0",
    description="Authenticated data and agent gateway for the SciPilot frontend.",
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
