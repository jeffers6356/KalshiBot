import os
import sqlite3
from pathlib import Path


# Local development database.
# Cloudflare Workers does not provide a writable local filesystem,
# so database operations are disabled there until D1 is connected.

IS_CLOUDFLARE = os.getenv("WORKERS_RS_VERSION") is not None


if IS_CLOUDFLARE:
    DB_PATH = None
else:
    DB_PATH = Path(
        os.getenv(
            "KALSHI_DB_PATH",
            str(Path(__file__).resolve().parent.parent / "data" / "kalshi.db"),
        )
    )
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def connect():
    if IS_CLOUDFLARE:
        raise RuntimeError(
            "SQLite is not available in Cloudflare Workers. "
            "Use Cloudflare D1 for persistent database access."
        )

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    if IS_CLOUDFLARE:
        return

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
