"""RunPod provider skeleton.

This module implements the HTTP-only contract (POST /run, GET /status/{id},
POST /cancel/{id}) but does not assume any particular model: the actual
inference payload + result schema are deferred to the model integration
milestone.

Real RunPod endpoints, headers, and error semantics are documented at
https://docs.runpod.io/. The HTTP calls below are deliberately tolerant:
on any network error we surface a ProviderError and let the worker
decide whether to retry. This matches the brief: "Do NOT implement the
actual RunPod integration yet."
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..errors import ProviderAuthError, ProviderError, ProviderTimeoutError
from .providers.base import (
    PROVIDER_STATUS_FAILED,
    PROVIDER_STATUS_QUEUED,
    PROVIDER_STATUS_RUNNING,
    PROVIDER_STATUS_SUCCEEDED,
    ProviderHandle,
    ProviderInput,
    ProviderResult,
    VideoGenerationProvider,
)


@dataclass
class _RunPodJob:
    handle: ProviderHandle
    payload: ProviderInput
    state: str = PROVIDER_STATUS_QUEUED
    output_ref: str | None = None
    duration_sec: float = 0.0


_STATUS_MAP: dict[str, str] = {
    "IN_QUEUE": PROVIDER_STATUS_QUEUED,
    "IN_PROGRESS": PROVIDER_STATUS_RUNNING,
    "COMPLETED": PROVIDER_STATUS_SUCCEEDED,
    "FAILED": PROVIDER_STATUS_FAILED,
    "CANCELLED": PROVIDER_STATUS_FAILED,
    "TIMED_OUT": PROVIDER_STATUS_FAILED,
}


class RunPodVideoGenerationProvider(VideoGenerationProvider):
    def __init__(
        self,
        provider_id: str,
        endpoint_id: str,
        api_key: str,
        base_url: str = "https://api.runpod.ai/v2",
        timeout_sec: float = 30.0,
    ) -> None:
        if not endpoint_id:
            raise ValueError("RunPodVideoGenerationProvider requires an endpoint_id")
        self.provider_id = provider_id
        self.endpoint_id = endpoint_id
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._timeout_sec = timeout_sec
        self._jobs: dict[str, _RunPodJob] = {}
        self._client: httpx.AsyncClient | None = None

    async def _client_get(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout_sec)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ProviderAuthError(
                "runpod_no_api_key",
                "RunPod API key is not configured (AURA_RUNPOD_API_KEY).",
            )
        return {"Authorization": f"Bearer {self.api_key}"}

    async def submit(self, payload: ProviderInput) -> ProviderHandle:
        body: dict[str, Any] = {
            "input": {
                "job_id": payload.job_id,
                "session_id": payload.session_id,
                "experience_id": payload.experience_id,
                "capture_ref": payload.capture_ref,
                "prompt": payload.prompt,
                "negative_prompt": payload.negative_prompt,
                "duration_sec": payload.duration_sec,
                "fps": payload.fps,
                "resolution": payload.resolution,
                "aspect_ratio": payload.aspect_ratio,
                "model_params": payload.model_params,
            }
        }
        if payload.idempotency_key:
            body["idempotency_key"] = payload.idempotency_key

        try:
            client = await self._client_get()
            resp = await client.post(
                f"{self.base_url}/{self.endpoint_id}/run",
                json=body,
                headers=self._headers(),
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("runpod_submit_timeout", str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("runpod_submit_failed", str(exc)) from exc

        if resp.status_code in (401, 403):
            raise ProviderAuthError("runpod_auth", f"RunPod rejected credentials ({resp.status_code})")
        if resp.status_code >= 500:
            raise ProviderError("runpod_submit_5xx", f"RunPod 5xx ({resp.status_code})")
        if not resp.is_success:
            raise ProviderError(
                "runpod_submit_http",
                f"RunPod submit HTTP {resp.status_code}: {resp.text[:200]}",
            )

        try:
            data = resp.json()
            provider_job_id = str(data.get("id") or uuid.uuid4().hex)
        except ValueError as exc:
            raise ProviderError("runpod_bad_json", "RunPod submit returned invalid JSON") from exc

        handle = ProviderHandle(provider_id=self.provider_id, provider_job_id=provider_job_id)
        self._jobs[provider_job_id] = _RunPodJob(handle=handle, payload=payload)
        return handle

    async def status(self, handle: ProviderHandle) -> str:
        try:
            client = await self._client_get()
            resp = await client.get(
                f"{self.base_url}/{self.endpoint_id}/status/{handle.provider_job_id}",
                headers=self._headers(),
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("runpod_poll_timeout", str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("runpod_poll_failed", str(exc)) from exc

        if resp.status_code in (401, 403):
            raise ProviderAuthError("runpod_auth", f"RunPod rejected credentials ({resp.status_code})")
        if resp.status_code >= 500:
            raise ProviderError("runpod_poll_5xx", f"RunPod 5xx ({resp.status_code})")
        if not resp.is_success:
            raise ProviderError(
                "runpod_poll_http",
                f"RunPod poll HTTP {resp.status_code}: {resp.text[:200]}",
            )

        try:
            data = resp.json()
            upstream = str(data.get("status") or "IN_QUEUE").upper()
        except ValueError as exc:
            raise ProviderError("runpod_bad_json", "RunPod status returned invalid JSON") from exc

        return _STATUS_MAP.get(upstream, PROVIDER_STATUS_RUNNING)

    async def result(self, handle: ProviderHandle) -> ProviderResult:
        job = self._jobs.get(handle.provider_job_id)
        if job is None or not job.output_ref:
            raise ProviderError(
                "runpod_no_output",
                "RunPod job has no output yet; poll until COMPLETED.",
            )
        return ProviderResult(
            output_ref=job.output_ref,
            duration_sec=job.duration_sec,
        )

    async def cancel(self, handle: ProviderHandle) -> None:
        try:
            client = await self._client_get()
            await client.post(
                f"{self.base_url}/{self.endpoint_id}/cancel/{handle.provider_job_id}",
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            raise ProviderError("runpod_cancel_failed", str(exc)) from exc

    async def healthcheck(self) -> bool:
        if not self.api_key:
            return False
        try:
            client = await self._client_get()
            resp = await client.get(
                f"{self.base_url}/{self.endpoint_id}/health",
                headers=self._headers(),
            )
            return resp.is_success
        except httpx.HTTPError:
            return False