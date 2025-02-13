from pydantic import BaseModel
from typing import Dict


class HTTPHeaders(BaseModel):
    status_line: str
    headers: Dict[str, str]

    @classmethod
    def from_bytes(cls, header_data: bytes) -> "HTTPHeaders":
        header_lines = header_data.split(b"\r\n")
        headers = {}
        status_line = header_lines[0].decode()

        for line in header_lines[1:]:
            if b": " in line:
                key, value = line.decode().split(": ", 1)
                headers[key.strip()] = value.strip()

        return cls(status_line=status_line, headers=headers)
