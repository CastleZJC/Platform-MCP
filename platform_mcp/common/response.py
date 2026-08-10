"""统一响应模型"""

from __future__ import annotations

import time
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ResponseBase(BaseModel, Generic[T]):
    code: int = 0
    message: str = "success"
    data: T | None = None
    trace_id: str | None = None
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))


class PageResult(BaseModel, Generic[T]):
    items: list[T] = []
    total: int = 0
    page: int = 1
    page_size: int = 20
    total_pages: int = 0

    @classmethod
    def create(cls, items: list[T], total: int, page: int, page_size: int) -> PageResult[T]:
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
        return cls(items=items, total=total, page=page, page_size=page_size, total_pages=total_pages)
