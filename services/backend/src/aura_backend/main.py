"""FastAPI application factory."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api import api_v1_router
from .config import get_settings
from .errors import install_exception_handlers
from .inference import get_provider_registry
from .inference.mock_provider import MockVideoGenerationProvider
from .inference.queue import get_queue
from .inference.worker import get_worker
from .inference.wan_provider import register_wan_provider
from .logging import configure_logging, get_logger
from .realtime.routes import router as realtime_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    configure_logging(s.log_level)
    log = get_logger("aura.bootstrap")
    log.info("aura_starting", version=__version__, env=s.env)

    from .db import init_db

    init_db()

    # Register providers based on configuration.
    registry = get_provider_registry()
    # Mock provider (primary for tests / offline demo)
    mock_provider = MockVideoGenerationProvider()
    registry.register(mock_provider)
    # Alias for legacy "fake" id (so old clients and default config keep working)
    try:
        fake_alias = MockVideoGenerationProvider()
        fake_alias.provider_id = "fake"  # type: ignore[attr-defined]
        registry.register(fake_alias)
    except Exception:
        pass

    # Register Wan local provider if configured
    if s.runpod_provider_default in ("wan-local", "wan"):
        from .inference.wan_provider import register_wan_provider
        from .inference.wan_config import WanModelConfig, WanGenerationConfig

        model_config = WanModelConfig()
        generation_config = WanGenerationConfig(
            num_inference_steps=s.generation_max_attempts,
            guidance_scale=7.5,
            motion_bucket_id=180,
            seed_policy="visitor_derived",
        )
        register_wan_provider(
            provider_id="wan-local",
            model_config=model_config,
            generation_config=generation_config,
        )

    log.info("providers_registered", ids=registry.list_ids())

    # Start the in-process worker by default for the prototype. Production
    # would run this as a separate container; here it's co-located.
    worker = get_worker()
    worker_task = asyncio.create_task(worker.run_forever())
    log.info("worker_started_inproc")

    # Start the realtime event relay that translates internal bus messages
    # into WS broadcasts.
    from .realtime.relay import install_relay

    unsubs = install_relay()

    # Start the hub's stale-connection sweeper.
    from .realtime.hub import get_hub as _get_hub

    hub = _get_hub()
    await hub.start()

    log.info("aura_ready")
    try:
        yield
    finally:
        log.info("aura_stopping")
        worker.request_stop()
        worker_task.cancel()
        for u in unsubs:
            try:
                u()
            except Exception:  # noqa: BLE001
                pass
        await hub.stop()
        for t in (worker_task,):
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass


def create_app() -> FastAPI:
    s = get_settings()
    # Fail fast if prod secrets are insecure
    warnings = s.validate_secrets()
    if warnings and s.env == "prod":
        # In prod, refuse to start with insecure defaults
        raise RuntimeError(f"Insecure configuration: {'; '.join(warnings)}")
    elif warnings:
        # In dev, just log
        from .logging import get_logger

        log = get_logger("aura.bootstrap")
        for w in warnings:
            log.warning("insecure_config", warning=w)

    app = FastAPI(
        title="AURA Backend",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if s.env != "prod" else None,
        redoc_url=None,
    )

    # Security headers (must be outermost to apply to all responses)
    from .middleware.security_headers import SecurityHeadersMiddleware

    app.add_middleware(SecurityHeadersMiddleware)

    # Rate limiting
    from .middleware.rate_limit import RateLimitMiddleware

    app.add_middleware(RateLimitMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_allow_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Kiosk-Token", "X-Requested-With"],
        max_age=600,
    )

    install_exception_handlers(app)
    app.include_router(api_v1_router)
    app.include_router(realtime_router)

    return app


app = create_app()