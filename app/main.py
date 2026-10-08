from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .db import init_db, connect
from .kalshi import KalshiClient
from .signals import trader_scores, consensus_signals


app = FastAPI(
    title="Kalshi Smart Money Research Dashboard",
    version="0.1.1",
)


class TraderIn(BaseModel):
    username: str
    score: float = 0
    roi: float = 0
    profit: float = 0
    win_rate: float = 0
    volume: float = 0
    notes: str = ""


class ActivityIn(BaseModel):
    username: str
    market_ticker: str
    side: str = Field(pattern="^(yes|no|YES|NO)$")
    action: str = "buy"
    price: float = Field(ge=0, le=1)
    contracts: float = Field(gt=0)
    source: str = "public_social"
    occurred_at: str


@app.on_event("startup")
async def startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
async def home():
    return open("static/index.html", encoding="utf-8").read()


@app.get("/api/health")
async def health():
    """
    Check both the application and the Kalshi public API.
    """
    kalshi_ok = False

    async with KalshiClient() as client:
        kalshi_ok = await client.health_check()

    return {
        "ok": True,
        "service": "kalshi-smart-money",
        "version": "0.1.1",
        "kalshi_api": "connected" if kalshi_ok else "unavailable",
    }


@app.post("/api/collect")
async def collect():
    """
    Collect the current public Kalshi market and trade data
    and store it in SQLite.
    """

    async with KalshiClient() as client:
        markets = await client.markets(
            status="open",
            page_size=200,
            max_pages=20,
        )

        trades = await client.trades(
            limit=200,
            max_pages=20,
        )

    conn = connect()

    try:
        market_count = 0
        trade_count = 0

        for market in markets.get("markets", []):
            ticker = market.get("ticker")

            if not ticker:
                continue

            conn.execute(
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
                (
                    ticker,
                    market.get("title"),
                    market.get("status"),
                    float(market.get("yes_bid_dollars") or 0),
                    float(market.get("yes_ask_dollars") or 0),
                    float(market.get("last_price_dollars") or 0),
                    float(market.get("volume_fp") or 0),
                    float(market.get("volume_24h_fp") or 0),
                    market.get("updated_time"),
                ),
            )

            market_count += 1

        for trade in trades.get("trades", []):
            trade_id = trade.get("trade_id")

            if not trade_id:
                continue

            conn.execute(
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
                (
                    trade_id,
                    trade.get("ticker"),
                    float(trade.get("count_fp") or 0),
                    float(trade.get("yes_price_dollars") or 0),
                    float(trade.get("no_price_dollars") or 0),
                    trade.get("taker_side"),
                    trade.get("created_time"),
                    int(bool(trade.get("is_block_trade"))),
                ),
            )

            trade_count += 1

        conn.commit()

    finally:
        conn.close()

    return {
        "ok": True,
        "markets_collected": market_count,
        "trades_collected": trade_count,
    }


@app.get("/api/markets")
async def get_markets(limit: int = 100):
    limit = max(1, min(limit, 500))

    conn = connect()

    try:
        rows = conn.execute(
            """
            SELECT *
            FROM markets
            ORDER BY volume_24h DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        return [dict(row) for row in rows]

    finally:
        conn.close()


@app.get("/api/trades")
async def get_trades(limit: int = 100):
    limit = max(1, min(limit, 500))

    conn = connect()

    try:
        rows = conn.execute(
            """
            SELECT *
            FROM trades
            ORDER BY created_time DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        return [dict(row) for row in rows]

    finally:
        conn.close()


@app.get("/api/traders")
async def get_traders():
    return trader_scores()


@app.post("/api/traders")
async def add_trader(trader: TraderIn):
    conn = connect()

    try:
        conn.execute(
            """
            INSERT INTO traders(
                username,
                score,
                roi,
                profit,
                win_rate,
                volume,
                enabled,
                notes
            )
            VALUES(?,?,?,?,?,?,1,?)

            ON CONFLICT(username) DO UPDATE SET
                score=excluded.score,
                roi=excluded.roi,
                profit=excluded.profit,
                win_rate=excluded.win_rate,
                volume=excluded.volume,
                notes=excluded.notes
            """,
            (
                trader.username,
                trader.score,
                trader.roi,
                trader.profit,
                trader.win_rate,
                trader.volume,
                trader.notes,
            ),
        )

        conn.commit()

    finally:
        conn.close()

    return {
        "ok": True,
        "username": trader.username,
    }


@app.post("/api/trader-activity")
async def add_activity(activity: ActivityIn):
    conn = connect()

    try:
        exists = conn.execute(
            """
            SELECT 1
            FROM traders
            WHERE username=?
            """,
            (activity.username,),
        ).fetchone()

        if not exists:
            raise HTTPException(
                status_code=400,
                detail="Add the trader to the watchlist first",
            )

        conn.execute(
            """
            INSERT OR IGNORE INTO trader_activity(
                username,
                market_ticker,
                side,
                action,
                price,
                contracts,
                source,
                occurred_at
            )
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                activity.username,
                activity.market_ticker,
                activity.side.lower(),
                activity.action,
                activity.price,
                activity.contracts,
                activity.source,
                activity.occurred_at,
            ),
        )

        conn.commit()

    finally:
        conn.close()

    return {
        "ok": True,
    }

@app.get("/api/smart-money")
async def smart_money(
    window_minutes: int = 60,
    min_dollars: float = 500,
    min_trades: int = 2,
    limit: int = 25,
):
    from .smart_money import smart_money_signals

    try:
        signals = smart_money_signals(
            window_minutes=window_minutes,
            min_dollars=min_dollars,
            min_trades=min_trades,
            limit=limit,
        )

        return {
            "ok": True,
            "window_minutes": window_minutes,
            "min_dollars": min_dollars,
            "min_trades": min_trades,
            "signals": signals,
        }

    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "signals": [],
        }

@app.get("/api/signals")
async def signals(
    window_minutes: int = 30,
    min_traders: int = 2,
):
    return consensus_signals(
        window_minutes,
        min_traders,
    )
