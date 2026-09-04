"""ReelItem value object."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from .enums import ReelItemKind


@dataclass
class ReelItem:
    """An entry in the Display 2 reel playlist.

    Two kinds:
    - curated: preloaded designer content
    - generated: AI-generated visitor video
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    kind: ReelItemKind = ReelItemKind.CURATED
    src: str = ""
    title: str | None = None
    duration_sec: float = 4.0
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.src:
            raise ValueError("ReelItem.src required")
        if self.duration_sec <= 0:
            raise ValueError("ReelItem.duration_sec must be > 0")
        if isinstance(self.kind, str):
            self.kind = ReelItemKind(self.kind)