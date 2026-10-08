from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any, Dict, List, Optional

from .db import connect


# ---------------------------------------------------------
# Smart Trader scoring
# ---------------------------------------------------------

PROFIT_WEIGHT = 0.65
VOLUME_WEIGHT = 0.25
PREDICTION_WEIGHT = 0.10

MAX_BREADTH_BONUS = 5.0


def _rank_score(rank: Optional[int]) -> float:
    """
    Convert a leaderboard rank into a 0-100 score.

    The public leaderboard currently exposes roughly the
    top 12 positions to us.

    #1  = 100
    #2  = 95.45
    #7  = 72.73
    #12 = 50.00

    Missing rank = 0
    """

    if rank is None:
        return 0.0

    try:
        rank = int(rank)
    except (TypeError, ValueError):
        return 0.0

    if rank <= 0:
        return 0.0

    # Linear 1-12 scale.
    score = 100.0 - (
        (rank - 1) * (50.0 / 11.0)
    )

    return round(
        max(0.0, min(100.0, score)),
        2,
    )


def _average(values: List[float]) -> float:
    if not values:
        return 0.0

    return round(
        mean(values),
        2,
    )


def _snapshot_score(
    entries: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Calculate the trader's score for one snapshot.

    Missing leaderboard categories are ignored rather
    than treated as poor performance.
    """

    profit_rank = None
    volume_rank = None
    prediction_rank = None

    for entry in entries:

        leaderboard = entry.get(
            "leaderboard"
        )

        rank = entry.get("rank")

        if leaderboard == "profit":
            profit_rank = rank

        elif leaderboard == "volume":
            volume_rank = rank

        elif leaderboard == "predictions":
            prediction_rank = rank

    profit_score = _rank_score(
        profit_rank
    )

    volume_score = _rank_score(
        volume_rank
    )

    prediction_score = _rank_score(
        prediction_rank
    )

    #
    # Only use weights for categories in which the
    # trader actually appears.
    #
    weighted_total = 0.0
    active_weight = 0.0

    if profit_rank is not None:
        weighted_total += (
            profit_score * PROFIT_WEIGHT
        )
        active_weight += PROFIT_WEIGHT

    if volume_rank is not None:
        weighted_total += (
            volume_score * VOLUME_WEIGHT
        )
        active_weight += VOLUME_WEIGHT

    if prediction_rank is not None:
        weighted_total += (
            prediction_score
            * PREDICTION_WEIGHT
        )
        active_weight += PREDICTION_WEIGHT

    if active_weight > 0:
        base_score = (
            weighted_total
            / active_weight
        )
    else:
        base_score = 0.0

    #
    # Breadth bonus.
    #
    # Appearing on multiple leaderboards is useful
    # evidence, but it should never overpower profit.
    #
    leaderboards_present = sum(
        rank is not None
        for rank in (
            profit_rank,
            volume_rank,
            prediction_rank,
        )
    )

    if leaderboards_present <= 1:
        breadth_bonus = 0.0

    elif leaderboards_present == 2:
        breadth_bonus = 3.0

    else:
        breadth_bonus = MAX_BREADTH_BONUS

    final_score = min(
        100.0,
        base_score + breadth_bonus,
    )

    return {
        "score": round(
            final_score,
            2,
        ),

        "profit_score": round(
            profit_score,
            2,
        ),

        "volume_score": round(
            volume_score,
            2,
        ),

        "prediction_score": round(
            prediction_score,
            2,
        ),

        "breadth_score": round(
            breadth_bonus,
            2,
        ),

        "observations": len(entries),

        "leaderboards": sorted(
            {
                entry.get("leaderboard")
                for entry in entries
                if entry.get("leaderboard")
            }
        ),

        "best_profit_rank": profit_rank,

        "best_volume_rank": volume_rank,

        "best_prediction_rank": prediction_rank,
    }


def _consistency_label(
    scores: List[float],
) -> str:

    if len(scores) < 2:
        return "NEW"

    if len(scores) < 3:
        return "DEVELOPING"

    average_score = mean(scores)

    deviation = mean(
        abs(score - average_score)
        for score in scores
    )

    if len(scores) >= 5 and deviation <= 8:
        return "HIGH"

    if deviation <= 15:
        return "MEDIUM"

    return "LOW"


def _trend_label(
    current_score: float,
    historical_scores: List[float],
) -> str:

    if not historical_scores:
        return "NEW"

    historical_average = mean(
        historical_scores
    )

    change = (
        current_score
        - historical_average
    )

    if change >= 8:
        return "RISING"

    if change <= -8:
        return "FALLING"

    return "STABLE"

def _score_band(score: float) -> str:
    """
    Translate the numerical Smart Trader score
    into a human-readable strength category.
    """

    if score >= 90:
        return "ELITE"

    if score >= 75:
        return "STRONG"

    if score >= 60:
        return "INTERESTING"

    if score >= 40:
        return "WATCH"

    return "WEAK"

def _confidence_label(
    snapshot_count: int,
    consistency: str,
) -> str:

    if snapshot_count < 2:
        return "LOW"

    if snapshot_count < 3:
        return "MEDIUM"

    if consistency == "HIGH":
        return "HIGH"

    if consistency == "MEDIUM":
        return "MEDIUM"

    return "LOW"


def trader_intelligence(
    min_observations: int = 1,
    limit: int = 50,
) -> List[Dict[str, Any]]:

    conn = connect()

    try:
        rows = conn.execute(
            """
            SELECT
                username,
                leaderboard,
                timeframe,
                category,
                rank,
                value,
                observed_at
            FROM leaderboard_snapshots
            ORDER BY observed_at ASC
            """
        ).fetchall()
    finally:
        conn.close()

    #
    # username -> snapshot timestamp -> entries
    #
    trader_snapshots = defaultdict(
        lambda: defaultdict(list)
    )

    for row in rows:

        trader_snapshots[
            row["username"]
        ][
            row["observed_at"]
        ].append(
            {
                "username": row["username"],
                "leaderboard": row["leaderboard"],
                "timeframe": row["timeframe"],
                "category": row["category"],
                "rank": row["rank"],
                "value": row["value"],
                "observed_at": row["observed_at"],
            }
        )

    results = []

    for username, snapshots in trader_snapshots.items():

        ordered_snapshots = sorted(
            snapshots.items(),
            key=lambda item: item[0],
        )

        if len(ordered_snapshots) < min_observations:
            continue

        snapshot_scores = []

        for observed_at, entries in ordered_snapshots:

            score_data = _snapshot_score(
                entries
            )

            snapshot_scores.append(
                {
                    "observed_at": observed_at,
                    **score_data,
                }
            )

        current = snapshot_scores[-1]

        historical = snapshot_scores[:-1]

        historical_scores = [
            snapshot["score"]
            for snapshot in historical
        ]

        all_scores = [
            snapshot["score"]
            for snapshot in snapshot_scores
        ]

        consistency = _consistency_label(
            all_scores
        )

        trend = _trend_label(
            current["score"],
            historical_scores,
        )

        confidence = _confidence_label(
            len(snapshot_scores),
            consistency,
        )

        historical_average = (
            _average(historical_scores)
            if historical_scores
            else 0.0
        )

        results.append(
            {
                "username": username,

                "score": current["score"],

                "score_band": _score_band(
                    current["score"]
                ),

                "profit_score": current[
                    "profit_score"
                ],

                "volume_score": current[
                    "volume_score"
                ],

                "prediction_score": current[
                    "prediction_score"
                ],

                "breadth_score": current[
                    "breadth_score"
                ],

                "observations": current[
                    "observations"
                ],

                "leaderboards": current[
                    "leaderboards"
                ],

                "best_profit_rank": current[
                    "best_profit_rank"
                ],

                "best_volume_rank": current[
                    "best_volume_rank"
                ],

                "best_prediction_rank": current[
                    "best_prediction_rank"
                ],

                "historical_average":
                    historical_average,

                "consistency":
                    consistency,

                "trend":
                    trend,

                "confidence":
                    confidence,

                "snapshot_count":
                    len(snapshot_scores),

                "first_seen":
                    ordered_snapshots[0][0],

                "last_seen":
                    ordered_snapshots[-1][0],
            }
        )

    results.sort(
        key=lambda trader: (
            trader["score"],
            trader["profit_score"],
            trader["volume_score"],
        ),
        reverse=True,
    )

    return results[:limit]


def top_traders(
    min_observations: int = 1,
    limit: int = 20,
) -> List[Dict[str, Any]]:

    return trader_intelligence(
        min_observations=min_observations,
        limit=limit,
    )


def trader_detail(
    username: str,
) -> Optional[Dict[str, Any]]:

    traders = trader_intelligence(
        min_observations=1,
        limit=1000,
    )

    for trader in traders:

        if (
            trader["username"].lower()
            == username.lower()
        ):
            return trader

    return None


def save_public_leaderboard(
    entries: List[Dict[str, Any]],
) -> int:

    if not entries:
        return 0

    conn = connect()

    saved = 0

    try:

        for entry in entries:

            username = entry[
                "username"
            ]

            conn.execute(
                """
                INSERT INTO traders(
                    username,
                    enabled
                )
                VALUES(?, 1)

                ON CONFLICT(username)
                DO NOTHING
                """,
                (
                    username,
                ),
            )

            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO
                leaderboard_snapshots
                (
                    username,
                    leaderboard,
                    timeframe,
                    category,
                    rank,
                    value,
                    observed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    username,
                    entry.get(
                        "leaderboard",
                        "",
                    ),
                    entry.get(
                        "timeframe",
                        "week",
                    ),
                    entry.get(
                        "category",
                        "",
                    ),
                    entry.get(
                        "rank",
                    ),
                    entry.get(
                        "value",
                        0,
                    ),
                    entry[
                        "observed_at"
                    ],
                ),
            )

            if cursor.rowcount > 0:
                saved += 1

        conn.commit()

    finally:
        conn.close()

    return saved
