"""RunPod serverless client (mirror of backend module)."""

from __future__ import annotations

import uuid

import httpx

from .base import VideoGenProvider
from .contracts import ProviderHandle, ProviderInput, ProviderResult


class RunPodProvider(VideoGenProvider):
    def __init__(self, provider_id: str, endpoint_id: str, api_key: str, base_url: str) -> None:
        self.provider_id = provider_id
        self.endpoint_id = endpoint_id
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def submit(self, payload: ProviderInput) -> ProviderHandle:
        body = {"input": payload.__dict__}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        async with httpx.AsyncClient(timeout=30.0) as c:
            try:
                r = await c.post(
                    f"{self.base_url}/{self.endpoint_id}/run", json=body, headers=headers
                )
                r.raise_for_status()
                provider_job_id = (r.json().get("id") or uuid.uuid4().hex)
            except httpx.HTTPError:
                provider_job_id = uuid.uuid4().hex
        return ProviderHandle(provider_id=self.provider_id, provider_job_id=provider_job_id)

    async def poll(self, handle: ProviderHandle) -> str:
        async with httpx.AsyncClient(timeout=30.0) as c:
            try:
                r = await c.get(
                    f"{self.base_url}/{self.endpoint_id}/status/{handle.provider_job_id}",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                r.raise_for_status()
                return (r.json().get("status") or "IN_QUEUE").lower()
            except httpx.HTTPError:
                return "in_queue"

    async def result(self, handle: ProviderHandle) -> ProviderResult:
        return ProviderResult(output_ref=handle.provider_job_id, duration_sec=0.0)

    async def cancel(self, handle: ProviderHandle) -> None:
        async with httpx.AsyncClient(timeout=10.0) as c:
            try:
                await c.post(
                    f"{self.base_url}/{self.endpoint_id}/cancel/{handle.provider_job_id}",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
            except httpx.HTTPError:
                pass