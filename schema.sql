CREATE TABLE IF NOT EXISTS markets (
    ticker TEXT PRIMARY KEY,
    title TEXT,
    status TEXT,
    yes_bid REAL,
    yes_ask REAL,
    last_price REAL,
    volume INTEGER DEFAULT 0,
    volume_24h INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT UNIQUE,
    ticker TEXT NOT NULL,
    count INTEGER DEFAULT 0,
    yes_price REAL,
    no_price REAL,
    side TEXT,
    created_time TEXT,
    is_block_trade INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS traders (
    username TEXT PRIMARY KEY,
    score REAL DEFAULT 0,
    roi REAL DEFAULT 0,
    profit REAL DEFAULT 0,
    win_rate REAL DEFAULT 0,
    volume REAL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS trader_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    market_ticker TEXT,
    side TEXT,
    action TEXT,
    price REAL,
    contracts INTEGER DEFAULT 0,
    source TEXT,
    occurred_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS leaderboard_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    leaderboard TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    category TEXT NOT NULL,
    rank INTEGER,
    value REAL,
    observed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trades_ticker
    ON trades(ticker);

CREATE INDEX IF NOT EXISTS idx_trades_created_time
    ON trades(created_time);

CREATE INDEX IF NOT EXISTS idx_trader_activity_username
    ON trader_activity(username);

CREATE INDEX IF NOT EXISTS idx_trader_activity_market
    ON trader_activity(market_ticker);

CREATE INDEX IF NOT EXISTS idx_leaderboard_username
    ON leaderboard_snapshots(username);

CREATE INDEX IF NOT EXISTS idx_leaderboard_observed
    ON leaderboard_snapshots(observed_at);

CREATE INDEX IF NOT EXISTS idx_leaderboard_timeframe
    ON leaderboard_snapshots(timeframe);
