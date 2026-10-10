"""B1 health-only application. Real startup failures never select a stub."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from b2_core.contracts import Engine, Health
from .stub import StubEngine


logger = logging.getLogger(__name__)


def _ready_health(engine: Engine, mode: str) -> Health:
    """Validate explicit metadata before claiming an engine is ready."""
    is_mock = getattr(engine, "is_mock", None)
    if type(is_mock) is not bool:
        raise ValueError("engine.is_mock must explicitly be a bool")
    if mode == "real" and is_mock is not False:
        raise ValueError("real mode requires engine.is_mock=False")
    model_version = getattr(engine, "model_version", None)
    if not isinstance(model_version, str) or not model_version.strip():
        raise ValueError("engine.model_version must be a nonempty string")
    if not callable(getattr(engine, "generate", None)):
        raise ValueError("engine.generate must be callable")
    return Health(
        status="ok",
        model_ready=True,
        is_mock=is_mock,
        model_version=model_version,
    )


def create_app(
    *,
    mode: str | None = None,
    config_path: str | None = None,
    engine: Engine | None = None,
    engine_factory: Callable[[], Engine] | None = None,
) -> FastAPI:
    """Create the API; engine initialization happens once at startup.

    ``engine`` and a no-argument ``engine_factory`` are mutually exclusive
    injection points for integration and protocol tests. Neither bypasses
    metadata validation, including real mode's explicit non-mock declaration.
    """
    selected_mode = os.getenv("B2_MODE", "stub") if mode is None else mode
    if selected_mode not in ("stub", "real"):
        raise ValueError("B2_MODE must be 'stub' or 'real'")
    if engine is not None and engine_factory is not None:
        raise ValueError("provide either engine or engine_factory, not both")
    selected_config = (
        os.getenv("B2_MODEL_CONFIG", "weights/inference_config.json")
        if config_path is None
        else config_path
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if not application.state.initialized:
            # A failed real initialization also counts as attempted: health
            # requests cannot cause retries, model reloads, or a mock fallback.
            application.state.initialized = True
            try:
                if engine is not None:
                    candidate = engine
                elif engine_factory is not None:
                    candidate = engine_factory()
                elif selected_mode == "stub":
                    candidate = StubEngine()
                else:
                    from b2_core.model import ModelEngine

                    candidate = ModelEngine(selected_config)
                ready_health = _ready_health(candidate, selected_mode)
            except Exception as exc:
                application.state.initialization_error = (
                    f"{type(exc).__name__}: {exc}"
                )
                logger.exception(
                    "Engine initialization failed in %s mode; health remains degraded",
                    selected_mode,
                )
            else:
                application.state.engine = candidate
                application.state.health = ready_health
        yield

    application = FastAPI(
        title="伴学 B1 健康检查",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.initialized = False
    application.state.engine = None
    application.state.initialization_error = None
    application.state.health = Health(
        status="degraded",
        model_ready=False,
        is_mock=selected_mode == "stub",
        model_version="unavailable",
    )

    @application.get("/health", response_model=Health)
    async def health() -> Health:
        return application.state.health

    return application


# Importing this ASGI object creates routes only. Lifespan owns model loading.
app = create_app()
