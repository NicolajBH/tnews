import base64
import json
from datetime import datetime
from typing import Dict, Tuple, Any


def encode_cursor(pub_date: datetime, article_id: int) -> str:
    """
    Encode a cursor from a publication date and article ID

    Args:
        pub_date: The publication date of the article
        article_id: The ID of the article

    Returns:
        A base64 encoded string representing the cursor
    """
    cursor_data = {
        "p": pub_date.isoformat(),
        "id": article_id,
    }
    cursor_json = json.dumps(cursor_data)
    return base64.b64encode(cursor_json.encode("utf-8")).decode("utf-8")


def decode_cursor(cursor: str) -> Tuple[datetime, int]:
    """
    Decode a cursor into a publication date and article ID

    Args:
        cursor: The base64 encoded encoded cursor string

    Returns:
        A tuple of (publication_date, article_id)

    Raises:
        ValueError: If the cursor is invalid
    """
    try:
        cursor_json = base64.b64decode(cursor.encode("utf-8")).decode("utf-8")
        cursor_data = json.loads(cursor_json)

        pub_date = datetime.fromisoformat(cursor_data["p"])
        article_id = cursor_data["id"]

        return pub_date, article_id

    except Exception as e:
        raise ValueError(f"Invalid cursor format: {str(e)}")


def get_pagination_info(items: list, limit: int, has_more: bool) -> Dict[str, Any]:
    """
    Generate pagination information for the response.

    Args:
        items: The list of items in the current page
        limit: The requested limit
        has_more: Whether there are more items after this page

    Returns:
        A dictionary with pagination information
    """
    pagination = {
        "has_more": has_more,
    }

    if has_more and items:
        from src.models.db_models import Articles

        last_item = items[-1]
        if isinstance(last_item, Articles):
            pagination["next_cursor"] = encode_cursor(last_item.pub_date, last_item.id)

    return pagination
