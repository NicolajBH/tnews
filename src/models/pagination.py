from typing import Generic, List, TypeVar
from pydantic import BaseModel

T = TypeVar("T")


class PaginationInfo(BaseModel):
    has_more: bool
    next_cursor: str | None = None


class PaginatedResponse(BaseModel, Generic[T]):
    data: List[T]
    pagination: PaginationInfo
