import httpx


class SubscriptionManager:
    _instance = None
    all_feeds = None
    my_feeds = None
    auth_manager = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, auth_manager=None):
        if auth_manager:
            self.auth_manager = auth_manager

    async def fetch_subscription_data(self):
        if not self.auth_manager:
            return
        if not self.auth_manager.is_token_valid():
            success = await self.auth_manager.refresh_access_token()
            if not success:
                success = await self.auth_manager.authenticate()
                if not success:
                    return
        auth_headers = self.auth_manager.get_auth_header()
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "http://127.0.0.1:8000/api/v1/my", headers=auth_headers
            )
            self.my_feeds = response.json()

            response = await client.get(
                "http://127.0.0.1:8000/api/v1/feeds", headers=auth_headers
            )
            self.all_feeds = response.json()
        return True

    async def subscribe(self, source, feed):
        if not self.auth_manager:
            return
        if not self.auth_manager.is_token_valid():
            success = await self.auth_manager.refresh_access_token()
            if not success:
                success = await self.auth_manager.authenticate()
                if not success:
                    return
        auth_headers = self.auth_manager.get_auth_header()
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"http://127.0.0.1:8000/api/v1/subscribe/{source}/{feed}",
                headers=auth_headers,
            )
            return response.status_code

    async def unsubscribe(self, source, feed):
        if not self.auth_manager:
            return
        if not self.auth_manager.is_token_valid():
            success = await self.auth_manager.refresh_access_token()
            if not success:
                success = await self.auth_manager.authenticate()
                if not success:
                    return
        auth_headers = self.auth_manager.get_auth_header()
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"http://127.0.0.1:8000/api/v1/unsubscribe/{source}/{feed}",
                headers=auth_headers,
            )
            return response.status_code
