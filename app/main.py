from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from .db import init_db, connect
from .kalshi import KalshiClient
from .signals import trader_scores, consensus_signals

app = FastAPI(title="Kalshi Smart Money Research Dashboard", version="0.1.0")


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
    return {"ok": True, "service": "kalshi-smart-money", "version": "0.1.0"}


@app.post("/api/collect")
async def collect():
    client = KalshiClient()
    try:
        markets = await client.markets()
        trades = await client.trades(limit=1000)
    finally:
        await client.close()

    conn = connect()
    for m in markets.get("markets", []):
        conn.execute("""
        INSERT INTO markets(ticker,title,status,yes_bid,yes_ask,last_price,volume,volume_24h,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(ticker) DO UPDATE SET
          title=excluded.title,status=excluded.status,yes_bid=excluded.yes_bid,
          yes_ask=excluded.yes_ask,last_price=excluded.last_price,volume=excluded.volume,
          volume_24h=excluded.volume_24h,updated_at=excluded.updated_at
        """, (
            m.get("ticker"), m.get("title"), m.get("status"),
            float(m.get("yes_bid_dollars") or 0), float(m.get("yes_ask_dollars") or 0),
            float(m.get("last_price_dollars") or 0), float(m.get("volume_fp") or 0),
            float(m.get("volume_24h_fp") or 0), m.get("updated_time")
        ))

    for t in trades.get("trades", []):
        conn.execute("""
        INSERT OR IGNORE INTO trades(trade_id,ticker,count,yes_price,no_price,side,created_time,is_block_trade)
        VALUES(?,?,?,?,?,?,?,?)
        """, (
            t.get("trade_id"), t.get("ticker"), float(t.get("count_fp") or 0),
            float(t.get("yes_price_dollars") or 0), float(t.get("no_price_dollars") or 0),
            t.get("taker_side"), t.get("created_time"), int(bool(t.get("is_block_trade")))
        ))
    conn.commit()
    conn.close()
    return {"markets": len(markets.get("markets", [])), "trades": len(trades.get("trades", []))}


@app.get("/api/markets")
async def get_markets(limit: int = 100):
    conn = connect()
    rows = conn.execute("SELECT * FROM markets ORDER BY volume_24h DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/trades")
async def get_trades(limit: int = 100):
    conn = connect()
    rows = conn.execute("SELECT * FROM trades ORDER BY created_time DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/traders")
async def get_traders():
    return trader_scores()


@app.post("/api/traders")
async def add_trader(trader: TraderIn):
    conn = connect()
    conn.execute("""
      INSERT INTO traders(username,score,roi,profit,win_rate,volume,enabled,notes)
      VALUES(?,?,?,?,?,?,1,?)
      ON CONFLICT(username) DO UPDATE SET
        score=excluded.score,roi=excluded.roi,profit=excluded.profit,
        win_rate=excluded.win_rate,volume=excluded.volume,notes=excluded.notes
    """, (trader.username, trader.score, trader.roi, trader.profit, trader.win_rate, trader.volume, trader.notes))
    conn.commit(); conn.close()
    return {"ok": True, "username": trader.username}


@app.post("/api/trader-activity")
async def add_activity(activity: ActivityIn):
    conn = connect()
    exists = conn.execute("SELECT 1 FROM traders WHERE username=?", (activity.username,)).fetchone()
    if not exists:
        conn.close()
        raise HTTPException(400, "Add the trader to the watchlist first")
    conn.execute("""
      INSERT OR IGNORE INTO trader_activity
      (username,market_ticker,side,action,price,contracts,source,occurred_at)
      VALUES(?,?,?,?,?,?,?,?)
    """, (activity.username, activity.market_ticker, activity.side.lower(), activity.action,
          activity.price, activity.contracts, activity.source, activity.occurred_at))
    conn.commit(); conn.close()
    return {"ok": True}


@app.get("/api/signals")
async def signals(window_minutes: int = 30, min_traders: int = 2):
    return consensus_signals(window_minutes, min_traders)
