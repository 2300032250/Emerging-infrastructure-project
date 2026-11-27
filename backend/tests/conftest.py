"""Pytest fixtures isolating each test run on a clean temporary SQLite database."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.main import app
from app.ml.predictor import predictor
from app.services.assessment_service import ensure_seeded_and_trained
from app.services.telemetry import runtime_state


@pytest.fixture()
def client(tmp_path):
    db_file = tmp_path / "test_maturity.db"
    test_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    TestingSessionLocal = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=test_engine)

    predictor.is_trained = False
    runtime_state.set_degraded(False, fault=None)
    runtime_state.errors_total = 0

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    db = TestingSessionLocal()
    ensure_seeded_and_trained(db)
    db.close()

    with TestClient(app) as tc:
        yield tc

    app.dependency_overrides.clear()
    test_engine.dispose()
