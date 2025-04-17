from typing import Optional, List, TypeVar, Generic
from pydantic import BaseModel


T = TypeVar("T")


class PaginationInfo(BaseModel):
    """
    Information about pagination results with degradation status

    Attributes:
        has_more: Whether there are more items available
        next_cursor: Cursor to get the next page of results
        is_degraded: Whether the service is operating in degraded mode
        fallback_used: Whether fallback data was used instead of primary source
    """

    has_more: bool
    next_cursor: Optional[str] = None
    is_degraded: bool = False
    fallback_used: bool = False


class PaginationParams(BaseModel):
    """
    Parameters for pagination requests

    Attributes:
        cursor: Pagination cursor for fetching next page
        limit: Maximum number of items to return
    """

    cursor: Optional[str] = None
    limit: int = 20


class PaginatedResponse(BaseModel, Generic[T]):
    """
    Generic model for paginated responses

    Attributes:
        items: List of items in the current page
        pagination: Pagination information
    """

    items: List[T]
    pagination: PaginationInfo
