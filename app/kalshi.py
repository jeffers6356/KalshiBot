import os
import asyncio
from typing import Any, Dict, List, Optional

import httpx2 as httpx


BASE_URL = os.getenv(
    "KALSHI_BASE_URL",
    "https://external-api.kalshi.com/trade-api/v2",
)

# Kalshi currently supports paginated public API responses.
# Keep this comfortably below the documented maximum.
DEFAULT_PAGE_SIZE = int(os.getenv("KALSHI_PAGE_SIZE", "200"))

# Safety limits so a bad cursor/API response cannot cause an infinite loop.
DEFAULT_MAX_PAGES = int(os.getenv("KALSHI_MAX_PAGES", "20"))

# Number of retries for temporary failures.
DEFAULT_RETRIES = int(os.getenv("KALSHI_RETRIES", "3"))


class KalshiAPIError(Exception):
    """Raised when the Kalshi API request ultimately fails."""


class KalshiClient:
    """
    Lightweight asynchronous client for Kalshi's public API.

    This version intentionally focuses on public market/trade data.
    Authentication is not required for these endpoints.
    """

    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: float = 20.0,
        retries: int = DEFAULT_RETRIES,
    ):
        self.base_url = base_url.rstrip("/")
        self.retries = retries

        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Accept": "application/json",
                "User-Agent": "KalshiBot/0.1",
            },
        )

    async def close(self):
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def _get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        last_error = None

        for attempt in range(self.retries + 1):
            try:
                response = await self.client.get(url, params=params)
    
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < self.retries:
                        delay = 1.0 * (2 ** attempt)
                        await asyncio.sleep(delay)
                        continue
    
                if response.status_code >= 400:
                    body = response.text[:1000]
                    raise KalshiAPIError(
                        f"Kalshi API returned HTTP {response.status_code}: "
                        f"{body}"
                    )
    
                return response.json()
    
            except KalshiAPIError:
                raise
    
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
    
                if attempt < self.retries:
                    delay = 1.0 * (2 ** attempt)
                    await asyncio.sleep(delay)
                    continue
    
                break
    
        raise KalshiAPIError(
            f"Kalshi API request failed: {url}. "
            f"Last error: {last_error}"
        ) from last_error

    async def markets_page(
        self,
        status: str = "open",
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Retrieve one page of markets.
        """
        params: Dict[str, Any] = {
            "status": status,
            "limit": min(limit, 200),
        }

        if cursor:
            params["cursor"] = cursor

        return await self._get("/markets", params=params)

    async def markets(
        self,
        status: str = "open",
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> Dict[str, Any]:
        """
        Retrieve multiple pages of markets.

        Returns the same general structure as the Kalshi API:

            {
                "markets": [...],
                "cursor": ""
            }
        """
        all_markets: List[Dict[str, Any]] = []
        cursor: Optional[str] = None

        for _ in range(max_pages):
            data = await self.markets_page(
                status=status,
                limit=page_size,
                cursor=cursor,
            )

            page_markets = data.get("markets", [])
            all_markets.extend(page_markets)

            cursor = data.get("cursor")

            if not cursor:
                break

        return {
            "markets": all_markets,
            "cursor": cursor or "",
        }

    async def trades_page(
        self,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: Optional[str] = None,
        ticker: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Retrieve one page of public market trades.

        If ticker is supplied, only trades for that market are returned.
        """
        params: Dict[str, Any] = {
            "limit": min(limit, 200),
        }

        if cursor:
            params["cursor"] = cursor

        if ticker:
            params["ticker"] = ticker

        return await self._get("/markets/trades", params=params)

    async def trades(
        self,
        limit: int = DEFAULT_PAGE_SIZE,
        ticker: Optional[str] = None,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> Dict[str, Any]:
        """
        Retrieve multiple pages of public trades.

        The optional ticker argument allows us to collect trades for
        a specific market instead of the exchange-wide trade feed.
        """
        all_trades: List[Dict[str, Any]] = []
        cursor: Optional[str] = None

        for _ in range(max_pages):
            data = await self.trades_page(
                limit=limit,
                cursor=cursor,
                ticker=ticker,
            )

            page_trades = data.get("trades", [])
            all_trades.extend(page_trades)

            cursor = data.get("cursor")

            if not cursor:
                break

        return {
            "trades": all_trades,
            "cursor": cursor or "",
        }

    async def health_check(self) -> bool:
        data = await self.markets_page(status="open", limit=1)
        return "markets" in data
