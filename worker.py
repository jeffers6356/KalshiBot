```python
from fastapi import Request
from fastapi.responses import Response
from workers import WorkerEntrypoint

import asgi

from app.main import app


# Remove the root route so the frontend catch-all can serve
# the dashboard from Cloudflare Workers Static Assets.
app.router.routes = [
    route
    for route in app.router.routes
    if getattr(route, "path", None) != "/"
]


@app.get("/{path:path}")
async def frontend(path: str, request: Request):
    env = request.scope["env"]
    asset_url = f"https://assets.local/{path}"

    response = await env.ASSETS.fetch(asset_url)
    body = await response.bytes()

    return Response(
        content=body,
        status=response.status,
        headers=dict(response.headers),
    )


class Default(WorkerEntrypoint):

    async def fetch(self, request):
        return await asgi.fetch(
            app,
            request,
            self.env,
        )

    async def scheduled(self, controller, env, ctx):
        """
        Run the Kalshi data collector from the Cloudflare Cron trigger.

        Cron schedule:
            */5 * * * *

        This invokes the same collection logic exposed by
        POST /api/collect, but without requiring an external HTTP request.
        """

        if controller.cron != "*/5 * * * *":
            return

        from app.kalshi import KalshiClient
        from app.db import D1Database

        api_key_id = env.KALSHI_API_KEY_ID
        private_key_pem = env.KALSHI_PRIVATE_KEY

        db = D1Database(env.DB)

        async with KalshiClient(
            api_key_id=api_key_id,
            private_key_pem=private_key_pem,
        ) as client:

            markets = await client.markets(
                status="open",
                page_size=200,
                max_pages=1,
            )

            trades = await client.trades(
                limit=200,
                max_pages=1,
            )

        markets_fetched = 0
        markets_updated = 0
        trades_fetched = 0
        new_trades = 0
        duplicate_trades = 0

        for market in markets.get("markets", []):
            ticker = market.get("ticker")

            if not ticker:
                continue

            await db.execute(
                """
                INSERT INTO markets (
                    ticker,
                    title,
                    status,
                    yes_bid,
                    yes_ask,
                    last_price,
                    volume,
                    volume_24h,
                    updated_time
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)

                ON CONFLICT(ticker) DO UPDATE SET
                    title = excluded.title,
                    status = excluded.status,
                    yes_bid = excluded.yes_bid,
                    yes_ask = excluded.yes_ask,
                    last_price = excluded.last_price,
                    volume = excluded.volume,
                    volume_24h = excluded.volume_24h,
                    updated_time = excluded.updated_time
                """,
                [
                    ticker,
                    market.get("title"),
                    market.get("status"),
                    float(market.get("yes_bid_dollars") or 0),
                    float(market.get("yes_ask_dollars") or 0),
                    float(market.get("last_price_dollars") or 0),
                    float(market.get("volume_fp") or 0),
                    float(market.get("volume_24h_fp") or 0),
                    market.get("updated_time"),
                ],
            )

            markets_fetched += 1
            markets_updated += 1

        for trade in trades.get("trades", []):
            trade_id = trade.get("trade_id")

            if not trade_id:
                continue

            trades_fetched += 1

            existing = await db.first(
                """
                SELECT trade_id
                FROM trades
                WHERE trade_id = ?
                """,
                [trade_id],
            )

            if existing:
                duplicate_trades += 1
                continue

            await db.execute(
                """
                INSERT INTO trades (
                    trade_id,
                    ticker,
                    count,
                    yes_price,
                    no_price,
                    side,
                    created_time,
                    is_block_trade
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    trade_id,
                    trade.get("ticker"),
                    float(trade.get("count_fp") or 0),
                    float(trade.get("yes_price_dollars") or 0),
                    float(trade.get("no_price_dollars") or 0),
                    trade.get("taker_side"),
                    trade.get("created_time"),
                    int(bool(trade.get("is_block_trade"))),
                ],
            )

            new_trades += 1

        print(
            "KalshiBot scheduled collection:",
            {
                "markets_fetched": markets_fetched,
                "markets_updated": markets_updated,
                "trades_fetched": trades_fetched,
                "new_trades": new_trades,
                "duplicate_trades": duplicate_trades,
            },
        )
```
