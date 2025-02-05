import socket
import ssl
import json
import array
from urllib.parse import urlencode


class NewsAPIClient:
    def __init__(self, api_key) -> None:
        self.api_key = api_key
        self.host = "newsapi.org"
        self.base_path = "/v2/top-headlines"

    def calculate_checksum(self, data):
        """Implement a simpe 16-bit Internet checksum"""
        if len(data) % 2 == 1:
            data += b"\0"

        words = array.array("H", data)
        checksum = 0

        for word in words:
            checksum += word
            checksum = (checksum & 0xFFFF) + (checksum >> 16)

        checksum = ~checksum & 0xFFFF
        return checksum

    def verify_checksum(self, data, received_checksum):
        """
        Verifies received data against checksum.
        Returns True if valid, False if corrupted.
        """
        calculate_checksum = self.calculate_checksum(data)
        return calculate_checksum == received_checksum

    def fetch_headlines(self, country_code="us"):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        port = 443

        try:
            context = ssl.create_default_context()
            sock.connect((self.host, port))
            ssl_sock = context.wrap_socket(sock, server_hostname=self.host)

            params = urlencode({"country": country_code})

            request = (
                f"GET {self.base_path}?{params} HTTP/1.1\r\n"
                f"Host: {self.host}\r\n"
                f"X-Api-Key: {self.api_key}\r\n"
                "User-Agent: PythonSocket\r\n"
                "Accept: application/json\r\n"
                "Connection: close\r\n"
                "\r\n"
            )
            ssl_sock.sendall(request.encode())
            chunks = []
            while True:
                chunk = ssl_sock.recv(4096)
                if not chunk:
                    break

                chunk_checksum = self.calculate_checksum(chunk)
                chunks.append((chunk, chunk_checksum))

            valid_chunks = []
            for chunk, chunk_checksum in chunks:
                if self.verify_checksum(chunk, chunk_checksum):
                    valid_chunks.append(chunk)
                else:
                    print("Warning: Corrupted chunk detected (checksum mismatch)")
            response = b"".join(valid_chunks).decode()
            headers, body = response.split("\r\n\r\n", 1)

            try:
                json_start = body.find("{")
                if json_start >= 0:
                    json_content = body[json_start:]
                    data = json.loads(json_content)

                    print("\nTop Headlines:")
                    print("=" * 50)
                    for article in data["articles"]:
                        print(f"\nTitle: {article['title']}")
                        print(f"Source: {article['source']['name']}")
                        print(f"Description: {article['description']}")

                    return data
                else:
                    print("No JSON content found in response")
                    return None
            except json.JSONDecodeError as e:
                print(f"Failed to parse JSON: {e}")
                print("Response body:", body)
                return None
        except Exception as e:
            print("Error:", e)
            return None

        finally:
            sock.close()
            print("\nConnection closed")


if __name__ == "__main__":
    API_KEY = "dc0a81d576cb4e058c62c285a16bf7a7"
    client = NewsAPIClient(API_KEY)
    client.fetch_headlines()
