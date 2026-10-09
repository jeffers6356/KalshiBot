import asyncio
import base64
from typing import Any, Dict, List, Optional

import httpx2 as httpx

from js import Date, TextEncoder, Uint8Array, crypto
from pyodide.ffi import to_js


BASE_URL = "https://external-api.kalshi.com/trade-api/v2"

DEFAULT_PAGE_SIZE = 200
DEFAULT_MAX_PAGES = 20
DEFAULT_RETRIES = 3

SIGNING_PREFIX = "/trade-api/v2"


class KalshiAPIError(Exception):
    """Raised when the Kalshi API request fails."""


class KalshiClient:
    """
    Lightweight asynchronous Kalshi API client.

    Supports authenticated RSA-PSS/SHA-256 requests using
    Cloudflare Python Workers + WebCrypto.
    """

    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: float = 20.0,
        retries: int = DEFAULT_RETRIES,
        api_key_id: Optional[str] = None,
        private_key_pem: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.retries = retries
        self.api_key_id = api_key_id
        self.private_key_pem = private_key_pem

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

    async def _sign_request(
        self,
        method: str,
        path: str,
    ) -> Dict[str, str]:

        if not self.api_key_id or not self.private_key_pem:
            return {}

        # Kalshi requires Unix time in milliseconds.
        timestamp = str(int(Date.now()))

        # Remove query parameters.
        path_without_query = path.split("?")[0]

        # Kalshi signs the COMPLETE API path, including /trade-api/v2.
        signing_path = (
            SIGNING_PREFIX
            + path_without_query
        )

        message = (
            timestamp
            + method.upper()
            + signing_path
        )

        # Extract the base64 DER key material from PEM.
        pem_lines = [
            line.strip()
            for line in self.private_key_pem.strip().splitlines()
            if not line.strip().startswith("-----")
        ]

        der_base64 = "".join(pem_lines)
        key_bytes = base64.b64decode(der_base64)

        # Convert Python bytes -> JavaScript Uint8Array -> ArrayBuffer.
        key_array = Uint8Array.new(
            to_js(list(key_bytes))
        )

        key_data = key_array.buffer

        # Convert message to a JavaScript Uint8Array.
        encoder = TextEncoder.new()
        message_array = encoder.encode(message)

        # Import RSA private key.
        key = await crypto.subtle.importKey(
            "pkcs8",
            key_data,
            to_js({
                "name": "RSA-PSS",
                "hash": "SHA-256",
            }),
            False,
            to_js(["sign"]),
        )

        # Sign with RSA-PSS using SHA-256.
        signature = await crypto.subtle.sign(
            to_js({
                "name": "RSA-PSS",
                "saltLength": 32,
            }),
            key,
            message_array,
        )

        # Convert JavaScript ArrayBuffer -> Python bytes -> base64.
        signature_array = Uint8Array.new(signature)
        signature_bytes = bytes(
            signature_array.to_py()
        )

        encoded_signature = base64.b64encode(
            signature_bytes
        ).decode("ascii")

        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": encoded_signature,
        }

    async def _get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        url = f"{self.base_url}/{path.lstrip('/')}"

        last_error = None

        for attempt in range(self.retries + 1):

            try:
                auth_headers = await self._sign_request(
                    "GET",
                    path,
                )

                response = await self.client.get(
                    url,
                    params=params,
                    headers=auth_headers,
                )

                if (
                    response.status_code == 429
                    or response.status_code >= 500
                ):
                    if attempt < self.retries:
                        delay = 1.0 * (2 ** attempt)
                        await asyncio.sleep(delay)
                        continue

                if response.status_code >= 400:
                    body = response.text[:1000]

                    raise KalshiAPIError(
                        f"Kalshi API returned HTTP "
                        f"{response.status_code}: {body}"
                    )

                return response.json()

            except KalshiAPIError:
                raise

            except Exception as exc:
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
        status: Optional[str] = "open",
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:

        params: Dict[str, Any] = {
            "limit": min(limit, 200),
        }

        if status:
            params["status"] = status

        if cursor:
            params["cursor"] = cursor

        return await self._get(
            "/markets",
            params=params,
        )

    async def markets(
        self,
        status: Optional[str] = "open",
        limit: int = DEFAULT_PAGE_SIZE,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> Dict[str, Any]:

        all_markets: List[Dict[str, Any]] = []
        cursor = None

        for _ in range(max_pages):

            data = await self.markets_page(
                status=status,
                limit=limit,
                cursor=cursor,
            )

            all_markets.extend(
                data.get("markets", [])
            )

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

        params: Dict[str, Any] = {
            "limit": min(limit, 200),
        }

        if cursor:
            params["cursor"] = cursor

        if ticker:
            params["ticker"] = ticker

        return await self._get(
            "/markets/trades",
            params=params,
        )

    async def trades(
        self,
        limit: int = DEFAULT_PAGE_SIZE,
        max_pages: int = DEFAULT_MAX_PAGES,
        ticker: Optional[str] = None,
    ) -> Dict[str, Any]:

        all_trades: List[Dict[str, Any]] = []
        cursor = None

        for _ in range(max_pages):

            data = await self.trades_page(
                limit=limit,
                cursor=cursor,
                ticker=ticker,
            )

            all_trades.extend(
                data.get("trades", [])
            )

            cursor = data.get("cursor")

            if not cursor:
                break

        return {
            "trades": all_trades,
            "cursor": cursor or "",
        }

    async def health_check(self) -> bool:

        data = await self.markets_page(
            status="open",
            limit=1,
        )

        return "markets" in data
