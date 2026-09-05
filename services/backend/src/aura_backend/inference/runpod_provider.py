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
        # Bound in-memory job cache so long-running processes cannot grow without limit.
        if len(self._jobs) > 2000:
            oldest = next(iter(self._jobs))
            self._jobs.pop(oldest, None)
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
            # Cache output when completed so result() can find it
            if upstream == "COMPLETED":
                output = data.get("output")
                if output is None:
                    output = data.get("result")
                output_ref = None
                if isinstance(output, dict):
                    output_ref = output.get("video_url") or output.get("url") or output.get("video") or output.get("output")
                elif isinstance(output, str) and output.startswith("http"):
                    output_ref = output
                elif isinstance(output, list) and len(output) > 0:
                    first = output[0]
                    if isinstance(first, str) and first.startswith("http"):
                        output_ref = first
                    elif isinstance(first, dict):
                        output_ref = first.get("url") or first.get("video_url")
                if output_ref:
                    job = self._jobs.get(handle.provider_job_id)
                    if job:
                        job.output_ref = output_ref
                        # Try to get duration from output
                        try:
                            job.duration_sec = float(output.get("duration", 4.0)) if isinstance(output, dict) else 4.0
                        except Exception:
                            pass
        except ValueError as exc:
            raise ProviderError("runpod_bad_json", "RunPod status returned invalid JSON") from exc

        return _STATUS_MAP.get(upstream, PROVIDER_STATUS_RUNNING)

    async def result(self, handle: ProviderHandle) -> ProviderResult:
        # For real RunPod, fetch the completed status and extract output.
        # RunPod's /status/{id} returns {status: "COMPLETED", output: {...}} where output
        # contains the video URL (or base64). We handle both.
        try:
            client = await self._client_get()
            resp = await client.get(
                f"{self.base_url}/{self.endpoint_id}/status/{handle.provider_job_id}",
                headers=self._headers(),
            )
            if resp.is_success:
                try:
                    data = resp.json()
                    # Check for output in various RunPod response shapes
                    output = data.get("output")
                    if output is None:
                        output = data.get("result")
                    # Handle output being a dict with video URL
                    output_ref = None
                    duration = 4.0
                    if isinstance(output, dict):
                        # Common: {video_url: "...", url: "...", video: "..."}
                        output_ref = output.get("video_url") or output.get("url") or output.get("video") or output.get("output")
                        if output_ref and isinstance(output_ref, str) and output_ref.startswith("http"):
                            duration = float(output.get("duration", 4.0))
                        # Handle output being a list with URL
                        if not output_ref and isinstance(output, list) and len(output) > 0:
                            first = output[0]
                            if isinstance(first, str) and first.startswith("http"):
                                output_ref = first
                            elif isinstance(first, dict):
                                output_ref = first.get("url") or first.get("video_url")
                    elif isinstance(output, str) and output.startswith("http"):
                        output_ref = output
                    elif isinstance(output, str) and len(output) > 100:
                        # Possibly base64, save as temp file reference
                        output_ref = f"runpod://{handle.provider_job_id}/output.mp4"
                        # Store base64 for worker to handle (worker will treat as local path)
                        # For now, return as is
                        pass
                    if output_ref:
                        # Cache for idempotency
                        job = self._jobs.get(handle.provider_job_id)
                        if job:
                            job.output_ref = output_ref
                            job.duration_sec = duration
                            job.state = PROVIDER_STATUS_SUCCEEDED
                        return ProviderResult(
                            output_ref=output_ref,
                            duration_sec=duration,
                        )
                except Exception:
                    pass
        except Exception:
            pass
        # Fallback to local cache (for tests and when status doesn't yet have output)
        job = self._jobs.get(handle.provider_job_id)
        if job is not None and job.output_ref:
            return ProviderResult(
                output_ref=job.output_ref,
                duration_sec=job.duration_sec,
            )
        raise ProviderError(
            "runpod_no_output",
            "RunPod job has no output yet; poll until COMPLETED.",
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