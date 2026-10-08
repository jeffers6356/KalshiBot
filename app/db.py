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
        UNIQUE(
            username,
            market_ticker,
            side,
            action,
            price,
            contracts,
            occurred_at
        )
    );

    /*
    Public Kalshi Social trader profiles.
    This contains only information that is publicly available.
    */
    CREATE TABLE IF NOT EXISTS social_traders (
        username TEXT PRIMARY KEY,
        display_name TEXT,
        profile_url TEXT,
        description TEXT,
        followers INTEGER DEFAULT 0,
        following INTEGER DEFAULT 0,
        posts_count INTEGER DEFAULT 0,
        trades_count INTEGER DEFAULT 0,
        volume REAL DEFAULT 0,
        pnl REAL DEFAULT 0,
        open_interest REAL DEFAULT 0,
        top_categories TEXT DEFAULT '',
        joined_at TEXT,
        last_seen_at TEXT,
        enabled INTEGER DEFAULT 1
    );

    /*
    Historical leaderboard observations.
    Keeping snapshots lets us measure consistency instead of
    relying only on someone's current leaderboard position.
    */
    CREATE TABLE IF NOT EXISTS leaderboard_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        leaderboard TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        category TEXT DEFAULT '',
        rank INTEGER,
        value REAL,
        observed_at TEXT NOT NULL,
        UNIQUE(
            username,
            leaderboard,
            timeframe,
            category,
            observed_at
        )
    );

    CREATE INDEX IF NOT EXISTS idx_leaderboard_username
        ON leaderboard_snapshots(username);

    CREATE INDEX IF NOT EXISTS idx_leaderboard_observed
        ON leaderboard_snapshots(observed_at);

    CREATE INDEX IF NOT EXISTS idx_social_traders_pnl
        ON social_traders(pnl);

    CREATE INDEX IF NOT EXISTS idx_social_traders_volume
        ON social_traders(volume);
    """)

    conn.commit()
    conn.close()
