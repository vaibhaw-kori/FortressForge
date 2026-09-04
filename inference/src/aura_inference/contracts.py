"""Inference contracts (mirror of backend.provider_ai.base)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderInput:
    session_id: str
    job_id: str
    theme_id: str
    capture_ref: str
    prompt: str = ""
    duration_sec: float = 4.0
    fps: int = 12


@dataclass(frozen=True)
class ProviderHandle:
    provider_id: str
    provider_job_id: str


@dataclass
class ProviderResult:
    output_ref: str
    duration_sec: float