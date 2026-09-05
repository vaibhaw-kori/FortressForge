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
        # NOTE: generation_max_attempts is the RETRY count — never use it as
        # diffusion steps (that would render garbage). 1.3B 480P default: 24.
        generation_config = WanGenerationConfig(
            num_inference_steps=24,
            guidance_scale=7.0,
            motion_bucket_id=160,
            seed_policy="visitor_derived",
        )
        register_wan_provider(
            provider_id="wan-local",
            model_config=model_config,
            generation_config=generation_config,
        )

    # Register RunPod provider if configured (keeps mock registered for fallback)
    # AI_PROVIDER=mock -> mock (default, local), AI_PROVIDER=runpod -> runpod (real GPU)
    if s.runpod_provider_default in ("runpod", "runpod-mock", "sdxl", "svd", "animatediff"):
        try:
            from .inference.runpod_provider import RunPodVideoGenerationProvider

            # Use the single endpoint config for now (mock provider's endpoint id is used as RunPod endpoint id)
            # In production, map experience_id -> endpoint_id via config
            endpoint_id = s.runpod_endpoint or s.runpod_endpoint_fake or "mock"
            # Only register if we have an endpoint and it's not the mock placeholder
            if endpoint_id and endpoint_id not in ("mock", "fake"):
                runpod_provider = RunPodVideoGenerationProvider(
                    provider_id="runpod",
                    endpoint_id=endpoint_id,
                    api_key=s.runpod_api_key,
                )
                registry.register(runpod_provider)
                # Also alias "runpod" as the default for GenerationService
                log.info("runpod_provider_registered", endpoint_id=endpoint_id)
            elif s.runpod_api_key and endpoint_id in ("mock", "fake"):
                # For local testing with mock endpoint but real key, still register runpod with mock endpoint
                # so the switch AI_PROVIDER=runpod can be tested without a real endpoint
                runpod_provider = RunPodVideoGenerationProvider(
                    provider_id="runpod",
                    endpoint_id=endpoint_id,
                    api_key=s.runpod_api_key,
                )
                registry.register(runpod_provider)
                log.info("runpod_provider_registered_mock_endpoint", endpoint_id=endpoint_id)
        except Exception as exc:
            log.warning("runpod_provider_failed", error=str(exc))

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
        # Close pooled HTTP clients held by providers (RunPod) to avoid
        # connection / file-descriptor leaks across reloads.
        try:
            for pid in registry.list_ids():
                prov = registry.get(pid)
                aclose = getattr(prov, "aclose", None)
                if callable(aclose):
                    await aclose()
        except Exception:
            pass
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