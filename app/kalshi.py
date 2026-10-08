import os
import httpx

BASE_URL = os.getenv("KALSHI_BASE_URL", "https://external-api.kalshi.com/trade-api/v2")


class KalshiClient:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=20)

    async def close(self):
        await self.client.aclose()

    async def markets(self, status="open", limit=1000):
        r = await self.client.get(f"{BASE_URL}/markets", params={"status": status, "limit": limit})
        r.raise_for_status()
        return r.json()

    async def trades(self, limit=1000, ticker=None):
        params = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        r = await self.client.get(f"{BASE_URL}/markets/trades", params=params)
        r.raise_for_status()
        return r.json()
