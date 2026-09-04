"""Test fixtures: isolated DB per session, fresh app per test."""

from __future__ import annotations

import os

# Set test env BEFORE any aura_backend import.
os.environ["AURA_DATABASE_URL"] = "sqlite:///:memory:"
os.environ["AURA_LOG_LEVEL"] = "WARNING"
os.environ["AURA_RUNPOD_API_KEY"] = ""
os.environ["AURA_QUEUE_ENABLED"] = "false"
os.environ["AURA_CORS_ALLOW_ORIGINS"] = "*"
os.environ["AURA_ENV"] = "test"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import sessionmaker

from aura_backend.config import get_settings, reset_settings_cache
from aura_backend.db import get_db, reset_engine
from aura_backend.db.models import Base
from aura_backend.main import create_app


@pytest.fixture()
def in_memory_engine():
    """In-memory SQLite engine + session factory shared by all tests in a
    single test function. Module-level engine + SessionLocal are rebound
    so `session_scope()` and `get_engine()` return this engine.
    """
    import aura_backend.db as db_module

    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=eng)
    factory = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    db_module._engine = eng
    db_module._SessionLocal = factory
    yield eng
    eng.dispose()
    db_module._engine = None
    db_module._SessionLocal = None


@pytest.fixture(autouse=True)
def _isolate_state(in_memory_engine):
    """Reset cached singletons + register mock providers."""
    from aura_backend.events import bus as _bus
    from aura_backend.inference.mock_provider import MockVideoGenerationProvider
    from aura_backend.inference.providers.base import get_provider_registry
    from aura_backend.realtime.hub import reset_hub
    from aura_backend.realtime.relay import install_relay, uninstall_relay

    reset_settings_cache()
    reset_hub()
    # Re-install relay handlers on fresh hub/bus
    uninstall_relay()
    reg = get_provider_registry()
    reg.unregister("mock")
    reg.unregister("fake")
    mock = MockVideoGenerationProvider()
    reg.register(mock)
    fake_alias = MockVideoGenerationProvider()
    fake_alias.provider_id = "fake"  # type: ignore[misc]
    reg.register(fake_alias)
    install_relay()
    # Clear in-process bus subscribers between tests.
    _bus._subs.clear()  # noqa: SLF001 - test reset
    yield
    reset_engine()


@pytest.fixture()
def engine(in_memory_engine):
    return in_memory_engine


@pytest.fixture()
def session_factory(in_memory_engine):
    return sessionmaker(bind=in_memory_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def db_session(session_factory):
    s = session_factory()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def app(in_memory_engine, session_factory):
    """FastAPI app with DB dependency overridden to use the in-memory engine."""
    reset_settings_cache()
    app = create_app()

    def _override_get_db():
        s = session_factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_get_db
    yield app
    app.dependency_overrides.clear()


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def settings():
    reset_settings_cache()
    return get_settings()