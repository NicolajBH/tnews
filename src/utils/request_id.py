import uuid


def generate_request_id() -> str:
    """
    Generate a unique request ID

    Returns:
        str: A unique request ID in UUID4 format
    """
    return str(uuid.uuid4())


def get_request_id_from_headers(
    headers: dict, header_name: str = "X-Request-ID"
) -> str | None:
    """
    Extract request ID from headers if present

    Args:
        headers: The request headers
        header_name: The header name to check for request ID

    Returns:
        str or None: The request ID if found, None otherwise
    """
    return headers.get(header_name)
