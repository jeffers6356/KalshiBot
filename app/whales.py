from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from .db import connect


DEFAULT_MIN_DOLLARS = 1000.0
DEFAULT_WINDOW_MINUTES = 60
DEFAULT_LIMIT = 50


def _parse_timestamp(value: str) -> datetime:
    """
    Convert a Kalshi timestamp into an aware UTC datetime.
    """
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)

    value = value.strip()

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def _side_price(trade: Dict[str, Any]) -> float:
    """
    Return the price paid for the side represented by the trade.

    YES trade -> yes_price
    NO trade  -> no_price
    """
    side = str(trade.get("side", "")).lower()

    if side == "yes":
        return float(trade.get("yes_price") or 0)

    if side == "no":
        return float(trade.get("no_price") or 0)

    return 0.0


def trade_notional(trade: Dict[str, Any]) -> float:
    """
    Estimate the dollar value of a trade.

    Kalshi contracts pay $1 if correct, so:
        contracts × contract price = capital committed
    """
    contracts = float(trade.get("count") or 0)
    price = _side_price(trade)

    return contracts * price


def _normalize_trade(row) -> Dict[str, Any]:
    """
    Convert a SQLite row into a normal dictionary and add
    calculated whale-detection fields.
    """
    trade = dict(row)

    trade["notional"] = round(
        trade_notional(trade),
        2,
    )

    trade["contracts"] = float(
        trade.get("count") or 0
    )

    trade["price"] = round(
        _side_price(trade),
        4,
    )

    trade["side"] = str(
        trade.get("side") or ""
    ).lower()

    trade["is_block_trade"] = bool(
        trade.get("is_block_trade")
    )

    return trade


def recent_whales(
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
    min_dollars: float = DEFAULT_MIN_DOLLARS,
    limit: int = DEFAULT_LIMIT,
) -> List[Dict[str, Any]]:
    """
    Find unusually large trades within a recent time window.

    This does NOT identify the trader.

    It identifies:
        - market
        - direction
        - contracts
        - estimated dollars committed
        - price
        - timestamp
        - block-trade status
    """

    window_minutes = max(1, int(window_minutes))
    min_dollars = max(0.0, float(min_dollars))
    limit = max(1, min(500, int(limit)))

    cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=window_minutes
    )

    conn = connect()

    try:
        rows = conn.execute(
            """
            SELECT
                t.trade_id,
                t.ticker,
                t.count,
                t.yes_price,
                t.no_price,
                t.side,
                t.created_time,
                t.is_block_trade,
                m.title,
                m.status
            FROM trades t
            LEFT JOIN markets m
                ON t.ticker = m.ticker
            ORDER BY t.created_time DESC
            """
        ).fetchall()
    finally:
        conn.close()

    whales: List[Dict[str, Any]] = []

    for row in rows:
        trade = _normalize_trade(row)

        timestamp = _parse_timestamp(
            trade.get("created_time", "")
        )

        if timestamp < cutoff:
            continue

        if trade["notional"] < min_dollars:
            continue

        whales.append(trade)

        if len(whales) >= limit:
            break

    return whales


def whale_consensus(
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
    min_dollars: float = DEFAULT_MIN_DOLLARS,
    min_trades: int = 3,
    limit: int = 25,
) -> List[Dict[str, Any]]:
    """
    Find markets where large trades are concentrated in one direction.

    Important:
    This measures aggregate large-trade pressure.

    It does NOT mean that multiple trades came from multiple
    identifiable traders.
    """

    window_minutes = max(1, int(window_minutes))
    min_dollars = max(0.0, float(min_dollars))
    min_trades = max(1, int(min_trades))
    limit = max(1, min(100, int(limit)))

    whales = recent_whales(
        window_minutes=window_minutes,
        min_dollars=min_dollars,
        limit=500,
    )

    grouped: Dict[str, Dict[str, Any]] = {}

    for trade in whales:
        ticker = trade["ticker"]

        if ticker not in grouped:
            grouped[ticker] = {
                "ticker": ticker,
                "title": trade.get("title") or ticker,
                "yes_dollars": 0.0,
                "no_dollars": 0.0,
                "yes_trades": 0,
                "no_trades": 0,
                "yes_contracts": 0.0,
                "no_contracts": 0.0,
                "total_dollars": 0.0,
                "total_trades": 0,
                "block_trades": 0,
                "latest_trade": trade.get("created_time"),
            }

        market = grouped[ticker]

        notional = trade["notional"]
        contracts = trade["contracts"]
        side = trade["side"]

        if side == "yes":
            market["yes_dollars"] += notional
            market["yes_contracts"] += contracts
            market["yes_trades"] += 1

        elif side == "no":
            market["no_dollars"] += notional
            market["no_contracts"] += contracts
            market["no_trades"] += 1

        market["total_dollars"] += notional
        market["total_trades"] += 1

        if trade["is_block_trade"]:
            market["block_trades"] += 1

    results: List[Dict[str, Any]] = []

    for market in grouped.values():
        if market["total_trades"] < min_trades:
            continue

        yes_dollars = market["yes_dollars"]
        no_dollars = market["no_dollars"]
        total_dollars = market["total_dollars"]

        if yes_dollars > no_dollars:
            direction = "YES"
            dominant_dollars = yes_dollars
        elif no_dollars > yes_dollars:
            direction = "NO"
            dominant_dollars = no_dollars
        else:
            direction = "NEUTRAL"
            dominant_dollars = total_dollars

        if total_dollars > 0:
            pressure = (
                (yes_dollars - no_dollars)
                / total_dollars
            )
        else:
            pressure = 0.0

        results.append(
            {
                **market,
                "yes_dollars": round(
                    yes_dollars,
                    2,
                ),
                "no_dollars": round(
                    no_dollars,
                    2,
                ),
                "total_dollars": round(
                    total_dollars,
                    2,
                ),
                "pressure": round(
                    pressure,
                    4,
                ),
                "direction": direction,
                "dominant_dollars": round(
                    dominant_dollars,
                    2,
                ),
            }
        )

    results.sort(
        key=lambda item: (
            abs(item["pressure"]),
            item["total_dollars"],
        ),
        reverse=True,
    )

    return results[:limit]
