from typing import Any, Dict, List

from .whales import whale_consensus


DEFAULT_MIN_DOLLARS = 500.0
DEFAULT_MIN_TRADES = 2
DEFAULT_LIMIT = 25


def _score_pressure(pressure: float) -> float:
    """
    Directional concentration is the strongest component
    of the initial signal.

    +1.0 / -1.0 = completely one-sided
    0.0 = perfectly balanced
    """
    return min(abs(float(pressure)), 1.0) * 35.0


def _score_volume(total_dollars: float) -> float:
    """
    Reward larger amounts of concentrated capital.

    $10,000+ receives the maximum volume score.
    """
    return min(
        max(float(total_dollars), 0.0) / 10000.0,
        1.0,
    ) * 30.0


def _score_trade_count(total_trades: int) -> float:
    """
    Reward repeated activity.

    10+ qualifying trades receives the maximum score.
    """
    return min(
        max(int(total_trades), 0) / 10.0,
        1.0,
    ) * 20.0


def _score_block_trades(block_trades: int) -> float:
    """
    Give additional weight to block trades.

    Three or more block trades receives the maximum score.
    """
    return min(
        max(int(block_trades), 0) / 3.0,
        1.0,
    ) * 15.0


def calculate_score(signal: Dict[str, Any]) -> int:
    """
    Calculate an initial 0-100 large-money signal score.

    Current components:

        Directional pressure    35 points
        Total dollars           30 points
        Number of trades        20 points
        Block trades             15 points

    This score does NOT claim that the underlying traders
    are profitable. Public trader performance will be added
    later as a separate signal component.
    """

    score = (
        _score_pressure(
            signal.get("pressure", 0)
        )
        + _score_volume(
            signal.get("total_dollars", 0)
        )
        + _score_trade_count(
            signal.get("total_trades", 0)
        )
        + _score_block_trades(
            signal.get("block_trades", 0)
        )
    )

    return max(
        0,
        min(
            100,
            round(score),
        ),
    )


def _signal_strength(score: int) -> str:
    """
    Convert the numeric score into an easy-to-read category.
    """

    if score >= 75:
        return "STRONG"

    if score >= 55:
        return "MODERATE"

    if score >= 40:
        return "WATCH"

    return "WEAK"


def _confidence(score: int) -> str:
    """
    Human-readable interpretation of the signal score.
    """

    if score >= 75:
        return "high"

    if score >= 55:
        return "medium"

    return "low"


def build_signal(signal: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert a whale-consensus record into a smart-money signal.
    """

    score = calculate_score(signal)

    direction = signal.get(
        "direction",
        "NEUTRAL",
    )

    return {
        **signal,
        "score": score,
        "strength": _signal_strength(score),
        "confidence": _confidence(score),
        "signal": (
            f"{_signal_strength(score)} "
            f"{direction}"
        ),
    }


def smart_money_signals(
    window_minutes: int = 60,
    min_dollars: float = DEFAULT_MIN_DOLLARS,
    min_trades: int = DEFAULT_MIN_TRADES,
    limit: int = DEFAULT_LIMIT,
) -> List[Dict[str, Any]]:
    """
    Return the highest-ranked large-money signals.

    Results are sorted by signal score first, followed by
    total dollars committed.
    """

    raw_signals = whale_consensus(
        window_minutes=window_minutes,
        min_dollars=min_dollars,
        min_trades=min_trades,
        limit=100,
    )

    signals = [
        build_signal(signal)
        for signal in raw_signals
    ]

    signals.sort(
        key=lambda item: (
            item["score"],
            item["total_dollars"],
        ),
        reverse=True,
    )

    return signals[:limit]


def top_signals(
    window_minutes: int = 60,
    min_dollars: float = DEFAULT_MIN_DOLLARS,
    min_trades: int = DEFAULT_MIN_TRADES,
    limit: int = DEFAULT_LIMIT,
) -> List[Dict[str, Any]]:
    """
    Convenience wrapper for the dashboard/API.
    """

    return smart_money_signals(
        window_minutes=window_minutes,
        min_dollars=min_dollars,
        min_trades=min_trades,
        limit=limit,
    )
