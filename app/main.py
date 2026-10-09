from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .db import D1Database
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


def get_db(request: Request) -> D1Database:
    env = request.scope["env"]
    return D1Database(env.DB)

def get_kalshi_client(request: Request) -> KalshiClient:
    env = request.scope["env"]

    return KalshiClient(
        api_key_id=getattr(env, "KALSHI_API_KEY_ID", None),
        private_key_pem=getattr(env, "KALSHI_PRIVATE_KEY", None),
    )

@app.get("/", response_class=HTMLResponse)
async def home():
    return open("static/index.html", encoding="utf-8").read()


@app.get("/api/health")
async def health(request: Request):
    kalshi_ok = False
    db_ok = False
    db_error = None
    kalshi_error = None

    try:
        db = get_db(request)
        await db.first("SELECT 1 AS ok")
        db_ok = True
    except Exception as exc:
        db_error = f"{type(exc).__name__}: {exc}"

    try:
       async with get_kalshi_client(request) as client:
           kalshi_ok = await client.health_check()
    except Exception as exc:
        kalshi_error = f"{type(exc).__name__}: {exc}"

    return {
        "ok": True,
        "service": "kalshi-smart-money",
        "version": "0.1.1",
        "database": "connected" if db_ok else "unavailable",
        "database_error": db_error,
        "kalshi_api": "connected" if kalshi_ok else "unavailable",
        "kalshi_error": kalshi_error,
    }


@app.post("/api/collect")
async def collect(request: Request):
    """
    Collect current public Kalshi market and trade data
    and store it in Cloudflare D1.
    """

    async with get_kalshi_client(request) as client:
        markets = await client.markets(
            status="open",
            page_size=200,
            max_pages=1,
        )

        trades = await client.trades(
            limit=200,
            max_pages=1,
        )

    db = get_db(request)

    markets_fetched = 0
    markets_updated = 0
    trades_fetched = 0
    new_trades = 0
    duplicate_trades = 0

    # ---------------------------------------------------------
    # Markets
    # ---------------------------------------------------------

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

        markets_fetched += 1
        markets_updated += 1

    # ---------------------------------------------------------
    # Trades
    # ---------------------------------------------------------

    for trade in trades.get("trades", []):

        trade_id = trade.get("trade_id")

        if not trade_id:
            continue

        trades_fetched += 1

        # Check whether we already have this trade.
        existing = await db.first(
            """
            SELECT trade_id
            FROM trades
            WHERE trade_id=?
            """,
            [trade_id],
        )

        if existing:
            duplicate_trades += 1
            continue

        await db.execute(
            """
            INSERT INTO trades(
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

        new_trades += 1

    return {
        "ok": True,
        "markets_fetched": markets_fetched,
        "markets_updated": markets_updated,
        "trades_fetched": trades_fetched,
        "new_trades": new_trades,
        "duplicate_trades": duplicate_trades,
    }

@app.get("/api/markets")
async def get_markets(
    request: Request,
    limit: int = 100,
):
    limit = max(1, min(limit, 500))

    db = get_db(request)

    rows = await db.all(
        """
        SELECT *
        FROM markets
        ORDER BY volume_24h DESC
        LIMIT ?
        """,
        [limit],
    )

    return rows


@app.get("/api/trades")
async def get_trades(
    request: Request,
    limit: int = 100,
):
    limit = max(1, min(limit, 500))

    db = get_db(request)

    rows = await db.all(
        """
        SELECT *
        FROM trades
        ORDER BY created_time DESC
        LIMIT ?
        """,
        [limit],
    )

    return rows

@app.get("/api/smart-money-candidates")
async def smart_money_candidates(
    request: Request,
    window_minutes: int = 60,
    min_dollars: float = 500,
    min_trades: int = 2,
    limit: int = 25,
):
    """
    Identify markets showing characteristics associated with
    potentially significant/smart money flow.

    IMPORTANT:
    These are candidates, not confirmed smart-money trades.
    Public trade data does not identify the underlying trader.
    """

    # Keep parameters within sensible limits.
    window_minutes = max(5, min(window_minutes, 1440))
    min_dollars = max(1.0, min(min_dollars, 1000000))
    min_trades = max(1, min(min_trades, 100))
    limit = max(1, min(limit, 100))

    db = get_db(request)

    rows = await db.all(
        """
        SELECT
            t.ticker,

            COALESCE(m.title, t.ticker) AS title,

            COUNT(*) AS trade_count,

            SUM(
                CASE
                    WHEN LOWER(t.side) = 'yes'
                        THEN t.count * t.yes_price
                    WHEN LOWER(t.side) = 'no'
                        THEN t.count * t.no_price
                    ELSE 0
                END
            ) AS total_dollars,

            SUM(
                CASE
                    WHEN LOWER(t.side) = 'yes'
                        THEN t.count * t.yes_price
                    ELSE 0
                END
            ) AS yes_dollars,

            SUM(
                CASE
                    WHEN LOWER(t.side) = 'no'
                        THEN t.count * t.no_price
                    ELSE 0
                END
            ) AS no_dollars,

            MAX(
                CASE
                    WHEN LOWER(t.side) = 'yes'
                        THEN t.count * t.yes_price
                    WHEN LOWER(t.side) = 'no'
                        THEN t.count * t.no_price
                    ELSE 0
                END
            ) AS largest_trade

        FROM trades t

        LEFT JOIN markets m
            ON m.ticker = t.ticker

        WHERE t.created_time >= datetime(
            'now',
            '-' || ? || ' minutes'
        )

        GROUP BY t.ticker

        HAVING
            total_dollars >= ?
            AND trade_count >= ?

        ORDER BY total_dollars DESC
        """,
        [
            window_minutes,
            min_dollars,
            min_trades,
        ],
    )

    candidates = []

    for row in rows:
        total_dollars = float(row.get("total_dollars") or 0)
        yes_dollars = float(row.get("yes_dollars") or 0)
        no_dollars = float(row.get("no_dollars") or 0)
        trade_count = int(row.get("trade_count") or 0)
        largest_trade = float(row.get("largest_trade") or 0)

        if total_dollars <= 0:
            continue

        # -1.0 = entirely NO
        # +1.0 = entirely YES
        pressure = (
            (yes_dollars - no_dollars)
            / total_dollars
        )

        direction = "YES" if pressure > 0 else "NO"

        # -------------------------
        # SCORE COMPONENTS
        # -------------------------

        # 30 points:
        # Strong directional imbalance gets rewarded.
        pressure_score = min(abs(pressure), 1.0) * 30

        # 25 points:
        # More money = stronger signal.
        volume_score = min(
            total_dollars / 5000.0,
            1.0
        ) * 25

        # 25 points:
        # Multiple trades are more meaningful than one isolated trade.
        activity_score = min(
            trade_count / 10.0,
            1.0
        ) * 25

        # 20 points:
        # Meaningful individual trades add confidence.
        largest_trade_score = min(
            largest_trade / 2000.0,
            1.0
        ) * 20

        score = round(
            pressure_score
            + volume_score
            + activity_score
            + largest_trade_score
        )

        # Confidence deliberately considers BOTH score
        # and the number of observations.
        if score >= 80 and trade_count >= 5:
            confidence = "HIGH"
        elif score >= 60 and trade_count >= 2:
            confidence = "MODERATE"
        else:
            confidence = "WATCH"

        candidates.append(
            {
                "ticker": row.get("ticker"),
                "title": row.get("title"),
                "direction": direction,
                "score": score,
                "confidence": confidence,
                "pressure": round(pressure, 4),
                "trade_count": trade_count,
                "total_dollars": round(total_dollars, 2),
                "yes_dollars": round(yes_dollars, 2),
                "no_dollars": round(no_dollars, 2),
                "largest_trade": round(largest_trade, 2),
                "components": {
                    "pressure": round(pressure_score, 1),
                    "volume": round(volume_score, 1),
                    "activity": round(activity_score, 1),
                    "largest_trade": round(largest_trade_score, 1),
                },
            }
        )

    # Highest score first.
    candidates.sort(
        key=lambda item: (
            item["score"],
            item["total_dollars"],
            item["trade_count"],
        ),
        reverse=True,
    )

    candidates = candidates[:limit]

    return {
        "ok": True,
        "window_minutes": window_minutes,
        "min_dollars": min_dollars,
        "min_trades": min_trades,
        "count": len(candidates),
        "candidates": candidates,
    }

@app.get("/api/trade-analytics")
async def trade_analytics(
    request: Request,
    window_minutes: int = 60,
    min_dollars: float = 0,
    limit: int = 25,
):
    """
    Analyze recently collected Kalshi trades.

    Returns:
    - largest trades
    - most active markets
    - YES/NO dollar pressure
    - aggregate totals
    """

    window_minutes = max(1, min(window_minutes, 1440))
    min_dollars = max(0, min_dollars)
    limit = max(1, min(limit, 100))

    db = get_db(request)

    # ---------------------------------------------------------
    # Largest trades
    # ---------------------------------------------------------

    largest_trades = await db.all(
        """
        SELECT
            trade_id,
            ticker,
            count,
            yes_price,
            no_price,
            side,
            created_time,
            is_block_trade,
            CASE
                WHEN side = 'yes'
                    THEN count * yes_price
                WHEN side = 'no'
                    THEN count * no_price
                ELSE 0
            END AS dollar_value
        FROM trades
        WHERE created_time >= datetime(
            'now',
            '-' || ? || ' minutes'
        )
        AND (
            CASE
                WHEN side = 'yes'
                    THEN count * yes_price
                WHEN side = 'no'
                    THEN count * no_price
                ELSE 0
            END
        ) >= ?
        ORDER BY dollar_value DESC
        LIMIT ?
        """,
        [
            window_minutes,
            min_dollars,
            limit,
        ],
    )

    # ---------------------------------------------------------
    # Market activity
    # ---------------------------------------------------------

    market_activity = await db.all(
        """
        SELECT
            ticker,
            COUNT(*) AS trade_count,

            SUM(
                CASE
                    WHEN side = 'yes'
                        THEN count * yes_price
                    WHEN side = 'no'
                        THEN count * no_price
                    ELSE 0
                END
            ) AS total_dollars,

            SUM(
                CASE
                    WHEN side = 'yes'
                        THEN count * yes_price
                    ELSE 0
                END
            ) AS yes_dollars,

            SUM(
                CASE
                    WHEN side = 'no'
                        THEN count * no_price
                    ELSE 0
                END
            ) AS no_dollars

        FROM trades

        WHERE created_time >= datetime(
            'now',
            '-' || ? || ' minutes'
        )

        GROUP BY ticker

        HAVING total_dollars >= ?

        ORDER BY total_dollars DESC

        LIMIT ?
        """,
        [
            window_minutes,
            min_dollars,
            limit,
        ],
    )

    # ---------------------------------------------------------
    # Overall pressure
    # ---------------------------------------------------------

    pressure = await db.first(
        """
        SELECT

            COUNT(*) AS trade_count,

            SUM(
                CASE
                    WHEN side = 'yes'
                        THEN count * yes_price
                    ELSE 0
                END
            ) AS yes_dollars,

            SUM(
                CASE
                    WHEN side = 'no'
                        THEN count * no_price
                    ELSE 0
                END
            ) AS no_dollars,

            SUM(
                CASE
                    WHEN side = 'yes'
                        THEN count * yes_price
                    WHEN side = 'no'
                        THEN count * no_price
                    ELSE 0
                END
            ) AS total_dollars

        FROM trades

        WHERE created_time >= datetime(
            'now',
            '-' || ? || ' minutes'
        )
        """,
        [window_minutes],
    )

    yes_dollars = float(
        (pressure or {}).get("yes_dollars") or 0
    )

    no_dollars = float(
        (pressure or {}).get("no_dollars") or 0
    )

    total_dollars = yes_dollars + no_dollars

    if total_dollars > 0:
        yes_percentage = (
            yes_dollars / total_dollars
        ) * 100

        no_percentage = (
            no_dollars / total_dollars
        ) * 100
    else:
        yes_percentage = 0
        no_percentage = 0

    if yes_dollars > no_dollars:
        pressure_direction = "YES"
    elif no_dollars > yes_dollars:
        pressure_direction = "NO"
    else:
        pressure_direction = "NEUTRAL"

    return {
        "ok": True,
        "window_minutes": window_minutes,
        "min_dollars": min_dollars,

        "summary": {
            "trade_count": int(
                (pressure or {}).get("trade_count") or 0
            ),
            "yes_dollars": yes_dollars,
            "no_dollars": no_dollars,
            "total_dollars": total_dollars,
            "yes_percentage": yes_percentage,
            "no_percentage": no_percentage,
            "pressure_direction": pressure_direction,
        },

        "largest_trades": largest_trades,
        "market_activity": market_activity,
    }

@app.get("/api/trader-records")
async def get_traders(request: Request):
    db = get_db(request)

    return await trader_scores(db)


@app.post("/api/traders")
async def add_trader(
    request: Request,
    trader: TraderIn,
):
    db = get_db(request)

    await db.execute(
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
        [
            trader.username,
            trader.score,
            trader.roi,
            trader.profit,
            trader.win_rate,
            trader.volume,
            trader.notes,
        ],
    )

    return {
        "ok": True,
        "username": trader.username,
    }


@app.post("/api/trader-activity")
async def add_activity(
    request: Request,
    activity: ActivityIn,
):
    db = get_db(request)

    exists = await db.first(
        """
        SELECT 1
        FROM traders
        WHERE username=?
        """,
        [activity.username],
    )

    if not exists:
        raise HTTPException(
            status_code=400,
            detail="Add the trader to the watchlist first",
        )

    await db.execute(
        """
        INSERT INTO trader_activity(
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
        [
            activity.username,
            activity.market_ticker,
            activity.side.lower(),
            activity.action,
            activity.price,
            activity.contracts,
            activity.source,
            activity.occurred_at,
        ],
    )

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

@app.get("/api/traders")
async def traders(
    request: Request,
    min_observations: int = 1,
    limit: int = 25,
):
    from .trader_intel import top_traders

    try:
        db = get_db(request)

        data = await top_traders(
            db,
            min_observations=min_observations,
            limit=limit,
        )

        return {
            "ok": True,
            "traders": data,
            "count": len(data),
        }

    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "traders": [],
            "count": 0,
        }

@app.get("/api/traders/{username}")
async def trader(
    request: Request,
    username: str,
):
    from .trader_intel import trader_detail

    try:
        db = get_db(request)

        data = await trader_detail(
            db,
            username,
        )

        if data is None:
            return {
                "ok": False,
                "error": "Trader not found",
            }

        return {
            "ok": True,
            **data,
        }

    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
        }
        
@app.get("/api/signals")
async def signals(
    request: Request,
    window_minutes: int = 30,
    min_traders: int = 2,
):
    db = get_db(request)

    return await consensus_signals(
        db,
        window_minutes,
        min_traders,
    )
