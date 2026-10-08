import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "kalshi.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = connect()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS markets (
        ticker TEXT PRIMARY KEY,
        title TEXT,
        status TEXT,
        yes_bid REAL,
        yes_ask REAL,
        last_price REAL,
        volume REAL,
        volume_24h REAL,
        updated_at TEXT
    );

    CREATE TABLE IF NOT EXISTS trades (
        trade_id TEXT PRIMARY KEY,
        ticker TEXT,
        count REAL,
        yes_price REAL,
        no_price REAL,
        side TEXT,
        created_time TEXT,
        is_block_trade INTEGER
    );

    CREATE TABLE IF NOT EXISTS traders (
        username TEXT PRIMARY KEY,
        score REAL DEFAULT 0,
        roi REAL DEFAULT 0,
        profit REAL DEFAULT 0,
        win_rate REAL DEFAULT 0,
        volume REAL DEFAULT 0,
        enabled INTEGER DEFAULT 1,
        notes TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS trader_activity (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        market_ticker TEXT,
        side TEXT,
        action TEXT,
        price REAL,
        contracts REAL,
        source TEXT,
        occurred_at TEXT,
        UNIQUE(username, market_ticker, side, action, price, contracts, occurred_at)
    );
    """)
    conn.commit()
    conn.close()
