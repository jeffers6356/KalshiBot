from datetime import datetime, timedelta, timezone

from .db import D1Database


def _get_db():
    """
    Signals that depend on stored trader activity require a D1
    database instance to be supplied by the caller.
    """
    raise RuntimeError(
        "A D1 database instance is required for trader signal queries."
    )


async def trader_scores(db: D1Database):
    rows = await db.all(
        """
        SELECT
            username,
            score,
            roi,
            profit,
            win_rate,
            volume,
            enabled,
            notes
        FROM traders
        WHERE enabled = 1
        ORDER BY score DESC, profit DESC
        """
    )

    return rows


async def consensus_signals(
    db: D1Database,
    window_minutes: int = 30,
    min_traders: int = 2,
):
    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(minutes=window_minutes)
    ).isoformat()

    rows = await db.all(
        """
        SELECT
            market_ticker,
            side,
            COUNT(DISTINCT username) AS trader_count,
            SUM(contracts) AS contracts,
            AVG(price) AS average_price
        FROM trader_activity
        WHERE occurred_at >= ?
        GROUP BY market_ticker, side
        HAVING COUNT(DISTINCT username) >= ?
        ORDER BY trader_count DESC, contracts DESC
        """,
        [
            cutoff,
            min_traders,
        ],
    )

    return rows
