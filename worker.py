from fastapi import Request
from fastapi.responses import Response
from workers import WorkerEntrypoint, asgi

from app.main import app


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


asgi_app = asgi.entrypoint(app)


class Default(WorkerEntrypoint):

    async def fetch(self, request):
        return await asgi_app.fetch(
            request,
            self.env,
            self.ctx,
        )

    async def scheduled(self, controller, env, ctx):
        from app.kalshi import KalshiClient
        from app.db import D1Database

        client = KalshiClient(
            api_key_id=getattr(
                env,
                "KALSHI_API_KEY_ID",
                None,
            ),
            private_key_pem=getattr(
                env,
                "KALSHI_PRIVATE_KEY",
                None,
            ),
        )

        try:
            markets = await client.markets(
                status="open",
                page_size=200,
                max_pages=1,
            )

            trades = await client.trades(
                limit=200,
                max_pages=1,
            )

            db = D1Database(env.DB)

            for market in markets.get("markets", []):
                ticker = market.get("ticker")

                if not ticker:
                    continue

                await db.execute(
                    """
                    INSERT INTO markets(
                        ticker,
                        title,
                        status,
                        yes_bid,
                        yes_ask,
                        last_price,
                        volume,
                        volume_24h,
                        updated_at
                    )
                    VALUES(?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(ticker) DO UPDATE SET
                        title=excluded.title,
                        status=excluded.status,
                        yes_bid=excluded.yes_bid,
                        yes_ask=excluded.yes_ask,
                        last_price=excluded.last_price,
                        volume=excluded.volume,
                        volume_24h=excluded.volume_24h,
                        updated_at=excluded.updated_at
                    """,
                    [
                        ticker,
                        market.get("title"),
                        market.get("status"),
                        float(
                            market.get("yes_bid_dollars") or 0
                        ),
                        float(
                            market.get("yes_ask_dollars") or 0
                        ),
                        float(
                            market.get("last_price_dollars") or 0
                        ),
                        float(
                            market.get("volume_fp") or 0
                        ),
                        float(
                            market.get("volume_24h_fp") or 0
                        ),
                        market.get("updated_time"),
                    ],
                )

            for trade in trades.get("trades", []):
                trade_id = trade.get("trade_id")

                if not trade_id:
                    continue

                await db.execute(
                    """
                    INSERT OR IGNORE INTO trades(
                        trade_id,
                        ticker,
                        count,
                        yes_price,
                        no_price,
                        side,
                        created_time,
                        is_block_trade
                    )
                    VALUES(?,?,?,?,?,?,?,?)
                    """,
                    [
                        trade_id,
                        trade.get("ticker"),
                        float(
                            trade.get("count_fp") or 0
                        ),
                        float(
                            trade.get("yes_price_dollars") or 0
                        ),
                        float(
                            trade.get("no_price_dollars") or 0
                        ),
                        trade.get("taker_side"),
                        trade.get("created_time"),
                        int(
                            bool(
                                trade.get("is_block_trade")
                            )
                        ),
                    ],
                )

            print("KalshiBot scheduled collection complete")

        except Exception as exc:
            print(
                f"KalshiBot scheduled collection failed: "
                f"{type(exc).__name__}: {exc}"
            )

        finally:
            await client.close()
