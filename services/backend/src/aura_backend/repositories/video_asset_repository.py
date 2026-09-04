"""VideoAsset repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..db.mappers import video_asset_to_domain, video_asset_to_row
from ..db.models import VideoAssetRow
from ..domain import VideoAsset
from .base import Repository


class VideoAssetRepository(Repository[VideoAsset]):
    def __init__(self, db: OrmSession) -> None:
        self._db = db

    def get(self, id: str) -> VideoAsset | None:
        row = self._db.get(VideoAssetRow, id)
        return video_asset_to_domain(row) if row else None

    def get_by_key(self, key: str) -> VideoAsset | None:
        row = self._db.execute(
            select(VideoAssetRow).where(VideoAssetRow.key == key)
        ).scalar_one_or_none()
        return video_asset_to_domain(row) if row else None

    def list(self) -> list[VideoAsset]:
        rows = self._db.execute(
            select(VideoAssetRow).order_by(VideoAssetRow.created_at.desc())
        ).scalars()
        return [video_asset_to_domain(r) for r in rows]

    def add(self, item: VideoAsset) -> VideoAsset:
        row = video_asset_to_row(item)
        self._db.add(row)
        self._db.flush()
        return video_asset_to_domain(row)

    def remove(self, id: str) -> None:
        row = self._db.get(VideoAssetRow, id)
        if row is not None:
            self._db.delete(row)