"""VideoAsset value object."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class VideoCodec(str, Enum):
    H264 = "h264"
    H265 = "h265"
    VP9 = "vp9"
    AV1 = "av1"


@dataclass(frozen=True)
class VideoAsset:
    """Reference to a generated or curated video artifact.

    Holds metadata only; the actual bytes live in object storage.
    """

    key: str
    url: str
    duration_sec: float
    codec: VideoCodec = VideoCodec.H264
    size_bytes: int | None = None
    width: int | None = None
    height: int | None = None
    fps: int | None = None
    checksum_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("VideoAsset.key required")
        if not self.url:
            raise ValueError("VideoAsset.url required")
        if self.duration_sec <= 0:
            raise ValueError("VideoAsset.duration_sec must be > 0")