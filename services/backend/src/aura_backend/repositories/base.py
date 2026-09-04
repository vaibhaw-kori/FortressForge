"""Abstract base repository. Defines the contract every repository honors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

T = TypeVar("T")


class Repository(ABC, Generic[T]):
    """Generic CRUD contract for domain aggregates."""

    @abstractmethod
    def get(self, id: str) -> T | None: ...

    @abstractmethod
    def list(self) -> list[T]: ...

    @abstractmethod
    def add(self, item: T) -> T: ...

    @abstractmethod
    def remove(self, id: str) -> None: ...