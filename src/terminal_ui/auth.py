import os
import json
import httpx
from datetime import datetime, timedelta

from core.logging import LogContext, setup_logging


class AuthManager:
    """Handles authentication and token management"""

    def __init__(self):
        setup_logging()
        self.logger = LogContext("auth_manager")
        self.access_token = None
        self.refresh_token = None
        self.token_expiry = None
        self.token_file = os.path.expanduser("~/.terminal_news_tokens.json")

    async def authenticate(self, username=None, password=None):
        """Authenticate with API"""
        if self.load_tokens():
            if self.is_token_valid() or await self.refresh_access_token():
                return True

        if not username or not password:
            return False

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "http://127.0.0.1:8000/api/v1/auth/login",
                    json={"username": "testuser", "password": "Testpass123"},
                )
                if response.status_code == 200:
                    data = response.json()
                    self.access_token = data["access_token"]
                    self.refresh_token = data["refresh_token"]
                    self.token_expiry = datetime.now() + timedelta(minutes=30)
                    self.save_tokens()
                    return True
                else:
                    return False

        except Exception as e:
            print(f"Authentication error: {str(e)}")
            return False

    def is_token_valid(self):
        if not self.access_token or not self.token_expiry:
            return False
        return datetime.now() + timedelta(seconds=30) < self.token_expiry

    async def refresh_access_token(self):
        if not self.refresh_token:
            return False

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "http://127.0.0.1:8000/api/v1/auth/refresh",
                    json={"refresh_token": self.refresh_token},
                )
                if response.status_code == 200:
                    data = response.json()
                    self.access_token = data["access_token"]
                    self.refresh_token = data["refresh_token"]
                    self.token_expiry = datetime.now() + timedelta(minutes=30)
                    self.save_tokens()
                    return True
                else:
                    self.clear_tokens()
                    return False
        except Exception:
            return False

    def get_auth_header(self):
        if self.access_token:
            return {"Authorization": f"Bearer {self.access_token}"}
        return {}

    def load_tokens(self):
        """Load tokens from file"""
        try:
            if os.path.exists(self.token_file):
                with open(self.token_file, "r") as f:
                    data = json.load(f)

                self.access_token = data.get("access_token")
                self.refresh_token = data.get("refresh_token")

                expiry_str = data.get("token_expiry")
                if expiry_str:
                    self.token_expiry = datetime.fromisoformat(expiry_str)

                return bool(self.access_token and self.refresh_token)
            return False
        except Exception:
            return False

    def clear_tokens(self):
        self.access_token = None
        self.refresh_token = None
        self.token_expiry = None

        if os.path.exists(self.token_file):
            try:
                os.remove(self.token_file)
            except Exception:
                pass

    def save_tokens(self):
        """Save tokens to file"""
        data = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_expiry": self.token_expiry.isoformat()
            if self.token_expiry
            else None,
        }

        try:
            with open(self.token_file, "w") as f:
                json.dump(data, f)
            os.chmod(self.token_file, 0o600)
        except Exception:
            pass
