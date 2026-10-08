import os
import sqlite3
from pathlib import Path


def _db_path():
    return Path(
        os.getenv(
            "KALSHI_DB_PATH",
            str(
                Path(__file__).resolve().parent.parent
                / "data"
                / "kalshi.db"
            ),
        )
    )


def connect():
    db_path = _db_path()

    # SQLite is only used when this function is explicitly called.
    # Do not create directories during module import because Cloudflare
    # Workers has a read-only application filesystem.
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = connect()

    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS markets (
                ticker TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT UNIQUE,
                ticker TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS traders (
                username TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS trader_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                data TEXT NOT NULL,
                observed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS social_traders (
                username TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                observed_at TEXT NOT NULL
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

            CREATE INDEX IF NOT EXISTS idx_leaderboard_username
                ON leaderboard_snapshots(username);

            CREATE INDEX IF NOT EXISTS idx_leaderboard_observed
                ON leaderboard_snapshots(observed_at);

            CREATE INDEX IF NOT EXISTS idx_social_traders_pnl
                ON social_traders(username);

            CREATE INDEX IF NOT EXISTS idx_social_traders_volume
                ON social_traders(username);
            """
        )

        conn.commit()

    finally:
        conn.close()
