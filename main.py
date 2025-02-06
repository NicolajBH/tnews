import socket
import ssl
import json
from urllib.parse import urlencode
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple


# TODO refactor fetch_headlines
# TODO try to use reuters api


@dataclass
class HTTPResponse:
    status_code: int
    headers: dict
    body: str


class NewsAPIClient:
    def __init__(self, api_key) -> None:
        self.timeout = 10
        self.api_key = api_key

    def create_socket(self) -> socket.socket:
        """Return a TCP socket with timeout"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        return sock

    def resolve_host(self, url: str) -> Tuple[str, int, str]:
        """
        Resolve host from URL and return a tuple of (host, port, path)
        """
        if "://" in url:
            url = url.split("://")[1]
        if "/" in url:
            host, path = url.split("/", 1)
            path = "/" + path
        else:
            host = url
            path = "/"
        if ":" in host:
            host, port = host.split(":")
            port = int(port)
        else:
            port = 443

        return host, port, path

    def wrap_socket(self, sock: socket.socket, host: str) -> ssl.SSLSocket:
        """Wraps socket with SSL/TLS layer"""
        context = ssl.create_default_context()
        return context.wrap_socket(sock, server_hostname=host)

    def send_request(
        self,
        sock: ssl.SSLSocket,
        host: str,
        path: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        Send HTTP request
        """
        params = urlencode({"country": "us", "apiKey": self.api_key})
        request = (
            f"{method} {path}?{params} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "User-Agent: PythonSocket\r\n"
            "Accept: application/json\r\n"
            "Connection: close\r\n"
        )
        if headers:
            for key, value in headers.items():
                request += f"{key}: {value}\r\n"

        request += "\r\n"
        sock.sendall(request.encode())

    def receive_response(self, sock: socket.socket) -> HTTPResponse:
        """
        Receive and parse HTTP response
        """
        chunks = []
        while True:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            except socket.timeout:
                print("Socket timeout")
                break

        response = b"".join(chunks).decode()

        try:
            headers_raw, body = response.split("\r\n\r\n", 1)
        except ValueError:
            raise ValueError("Invalid HTTP Response format")

        headers_lines = headers_raw.split("\r\n\r\n", 1)
        status_line = headers_lines[0]
        try:
            status_code = int(status_line.split()[1])
        except (IndexError, ValueError):
            raise ValueError(f"Invalid status line: {status_line}")

        headers = {}
        for line in headers_lines[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip()] = value.strip()

        return HTTPResponse(status_code, headers, body)

    def fetch_headlines(self) -> Optional[Dict[str, Any]]:
        """
        Fetch headlines and return parsed JSON response
        """
        sock = None
        ssl_sock = None

        try:
            host, port, path = self.resolve_host("newsapi.org/v2/top-headlines")
            sock = self.create_socket()
            sock.connect((host, port))
            ssl_sock = self.wrap_socket(sock, host)

            self.send_request(ssl_sock, host, path)
            response = self.receive_response(ssl_sock)

            print(f"Status code: {response.status_code}")
            if response.status_code != 200:
                print(f"Error response: {response.body}")
                return None

            try:
                json_start = response.body.find("{")
                if json_start >= 0:
                    json_content = response.body[json_start:]
                    data = json.loads(json_content)
                    return data
                else:
                    print("No JSON content found in response")
                    return None
            except json.JSONDecodeError as e:
                print(f"Failed to parse JSON: {e}")
                return None

        except Exception as e:
            print(f"Error: {e.__class__.__name__}: {e}")
            return None
        finally:
            if sock:
                sock.close()
            if ssl_sock:
                ssl_sock.close()


if __name__ == "__main__":
    API_KEY = "dc0a81d576cb4e058c62c285a16bf7a7"
    client = NewsAPIClient(API_KEY)
    response = client.fetch_headlines()
    if response:
        print("\nTop Headlines")
        print("=" * 50)
        for article in response.get("articles", []):
            print(f"\nTitle: {article.get('title')}")
            print(f"Source: {article.get('source', {}).get('name')}")
            print(f"Description: {article.get('description')}")
