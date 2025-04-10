import hashlib
import json
from typing import Any, Dict, List


def generate_etag(data: Any, salt: str = "") -> str:
    """
    Generate an ETag for the given data

    Args:
        data: The data to generate an etag for
        salt: Optional salt to add to the hash (can be used for versioning)

    Returns:
        A string containing the ETag
    """
    if isinstance(data, (dict, list)):
        content = json.dumps(data, sort_keys=True)
    else:
        content = str(data)

    if salt:
        content = f"{content}:{salt}"

    etag_hash = hashlib.md5(content.encode()).hexdigest()
    return f'"{etag_hash}"'


def extract_etag_header(headers: Dict[str, str], header_name: str) -> str | None:
    """
    Extract and normalize ETag from HTTP headers

    Args:
        headers: HTTP headers dictionary
        header_name: The header name to extract (If-None-Match or If-Match)

    Returns:
        The extracted ETag value or None if not present
    """
    etag = headers.get(header_name)

    if not etag:
        return None

    if etag.startswith("W/"):
        etag = etag[2:]

    if etag.startswith('"') and etag.endswith('"'):
        etag = etag[1:-1]

    return etag


def is_etag_match(current_etag: str, client_etag: str) -> bool:
    """
    Check if the current ETag matches the client ETag

    Args:
        current_etag: The current ETag on the server
        client_etag: The ETag provided by the client

    Returns:
        True if the ETags match, False otherwise
    """
    if current_etag.startswith('"') and current_etag.endswith('"'):
        current_etag = current_etag[1:-1]

    if client_etag.startswith('"') and client_etag.endswith('"'):
        client_etag = client_etag[1:-1]

    return current_etag == client_etag
