"""FastAPI entrypoint with startup configuration validation and DB/ML bootstrapping."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import settings, validate_startup_config
from app.db import SessionLocal, init_db
from app.services.assessment_service import ensure_seeded_and_trained


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_startup_config(settings)
    init_db()
    db = SessionLocal()
    try:
        ensure_seeded_and_trained(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.config_version,
    description=(
        "CLOUD-225 | Batch C2C-95 — Emerging Infrastructure Project Maturity Assessment "
        "for Adoption Decisions based on maintenance sustainability independent of popularity."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
