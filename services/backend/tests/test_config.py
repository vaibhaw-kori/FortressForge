"""Configuration + logging tests."""

from __future__ import annotations

from aura_backend.config import Settings, reset_settings_cache
from aura_backend.logging import configure_logging, get_logger


def test_settings_defaults_loaded():
    s = Settings()
    assert s.env in {"dev", "production", "test"}
    assert s.backend_port > 0
    assert s.reel_policy  # JSON parses


def test_cors_list_parsed():
    s = Settings()
    assert isinstance(s.cors_allow_origins_list, list)
    assert all(isinstance(o, str) for o in s.cors_allow_origins_list)


def test_sqlite_detection():
    s = Settings(database_url="sqlite:///./x.db")
    assert s.is_sqlite is True
    s2 = Settings(database_url="postgresql://u:p@h/db")
    assert s2.is_sqlite is False


def test_log_level_normalized_to_upper():
    s = Settings(log_level="debug")
    assert s.log_level == "DEBUG"


def test_configure_logging_does_not_raise():
    configure_logging("WARNING")
    log = get_logger("test")
    assert log is not None


def test_reset_settings_cache_helper():
    import os

    os.environ["AURA_BACKEND_PORT"] = "12345"
    reset_settings_cache()
    s = Settings()
    assert s.backend_port == 12345
    del os.environ["AURA_BACKEND_PORT"]