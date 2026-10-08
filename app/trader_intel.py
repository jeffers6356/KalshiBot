from typing import Any, Dict, List

from .db import connect


LEADERBOARD_WEIGHTS = {
    "profit": 0.50,
    "volume": 0.20,
    "predictions": 0.10,
}


def _rank_score(rank: int | None) -> float:
    """
    Convert leaderboard rank into a 0-100 score.

    Rank 1 = 100.
    Rank 2 = 97.
    Rank 10 = 73.
    """

    if rank is None or rank <= 0:
        return 0.0

    return max(
        0.0,
        100.0 - ((rank - 1) * 3.0),
    )


def _average(values: List[float]) -> float:
    if not values:
        return 0.0

    return sum(values) / len(values)


def _calculate_snapshot_score(
    profit_score: float,
    volume_score: float,
    prediction_score: float,
    leaderboard_count: int,
) -> float:

    score = (
        profit_score
        * LEADERBOARD_WEIGHTS["profit"]
        + volume_score
        * LEADERBOARD_WEIGHTS["volume"]
        + prediction_score
        * LEADERBOARD_WEIGHTS["predictions"]
    )

    breadth_bonus = min(
        10.0,
        leaderboard_count * 3.33,
    )

    return min(
        100.0,
        score + breadth_bonus,
    )


def _trend_label(
    current_score: float,
    historical_average: float,
) -> str:

    if historical_average <= 0:
        return "NEW"

    difference = (
        current_score -
        historical_average
    )

    if difference >= 8:
        return "RISING"

    if difference <= -8:
        return "FALLING"

    return "STABLE"


def _consistency_label(
    snapshot_count: int,
    score_values: List[float],
) -> str:

    if snapshot_count < 2:
        return "NEW"

    if not score_values:
        return "NEW"

    average = _average(score_values)

    if average <= 0:
        return "NEW"

    variance = _average(
        [
            abs(score - average)
            for score in score_values
        ]
    )

    if snapshot_count >= 5 and variance <= 8:
        return "HIGH"

    if snapshot_count >= 3 and variance <= 15:
        return "MEDIUM"

    return "LOW"


def trader_intelligence(
    min_observations: int = 1,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Build trader intelligence from public leaderboard
    observations.

    Historical consistency is only calculated when
    multiple distinct snapshots exist.

    This function does not infer private trading activity.
    """

    min_observations = max(
        1,
        int(min_observations),
    )

    limit = max(
        1,
        min(200, int(limit)),
    )

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

    traders: Dict[str, Dict[str, Any]] = {}

    for row in rows:

        username = row["username"]

        if username not in traders:
            traders[username] = {
                "username": username,
                "observations": 0,
                "leaderboards": set(),
                "first_seen": row["observed_at"],
                "last_seen": row["observed_at"],
                "profit_scores": [],
                "volume_scores": [],
                "prediction_scores": [],
                "snapshot_scores": [],
                "profit_value": 0.0,
                "volume_value": 0.0,
                "prediction_value": 0.0,
                "best_profit_rank": None,
                "best_volume_rank": None,
                "best_prediction_rank": None,
            }

        trader = traders[username]

        leaderboard = str(
            row["leaderboard"] or ""
        ).lower()

        rank = row["rank"]

        value = float(
            row["value"] or 0
        )

        trader["observations"] += 1

        trader["leaderboards"].add(
            leaderboard
        )

        trader["last_seen"] = (
            row["observed_at"]
        )

        if leaderboard == "profit":

            trader["profit_scores"].append(
                _rank_score(rank)
            )

            trader["profit_value"] = max(
                trader["profit_value"],
                value,
            )

            if (
                trader["best_profit_rank"] is None
                or (
                    rank is not None
                    and rank <
                    trader["best_profit_rank"]
                )
            ):
                trader["best_profit_rank"] = rank

        elif leaderboard == "volume":

            trader["volume_scores"].append(
                _rank_score(rank)
            )

            trader["volume_value"] = max(
                trader["volume_value"],
                value,
            )

            if (
                trader["best_volume_rank"] is None
                or (
                    rank is not None
                    and rank <
                    trader["best_volume_rank"]
                )
            ):
                trader["best_volume_rank"] = rank

        elif leaderboard == "predictions":

            trader["prediction_scores"].append(
                _rank_score(rank)
            )

            trader["prediction_value"] = max(
                trader["prediction_value"],
                value,
            )

            if (
                trader["best_prediction_rank"] is None
                or (
                    rank is not None
                    and rank <
                    trader["best_prediction_rank"]
                )
            ):
                trader["best_prediction_rank"] = rank

    results: List[Dict[str, Any]] = []

    for trader in traders.values():

        if trader["observations"] < min_observations:
            continue

        profit_score = _average(
            trader["profit_scores"]
        )

        volume_score = _average(
            trader["volume_scores"]
        )

        prediction_score = _average(
            trader["prediction_scores"]
        )

        current_score = _calculate_snapshot_score(
            profit_score,
            volume_score,
            prediction_score,
            len(trader["leaderboards"]),
        )

        #We currently have leaderboard observations rather
        #than explicitly grouped snapshots.

        #Until multiple collection timestamps exist,
        #historical statistics remain NEW.
       

        snapshot_scores = trader[
            "snapshot_scores"
        ]

        historical_average = (
            _average(snapshot_scores)
            if snapshot_scores
            else 0.0
        )

        consistency = _consistency_label(
            len(snapshot_scores),
            snapshot_scores,
        )

        trend = _trend_label(
            current_score,
            historical_average,
        )

        results.append(
            {
                "username":
                    trader["username"],

                "score":
                    round(current_score),

                "profit_score":
                    round(profit_score),

                "volume_score":
                    round(volume_score),

                "prediction_score":
                    round(prediction_score),

                "observations":
                    trader["observations"],

                "leaderboards":
                    sorted(
                        trader["leaderboards"]
                    ),

                "best_profit_rank":
                    trader["best_profit_rank"],

                "best_volume_rank":
                    trader["best_volume_rank"],

                "best_prediction_rank":
                    trader[
                        "best_prediction_rank"
                    ],

                "profit_value":
                    round(
                        trader["profit_value"],
                        2,
                    ),

                "volume_value":
                    round(
                        trader["volume_value"],
                        2,
                    ),

                "prediction_value":
                    round(
                        trader[
                            "prediction_value"
                        ],
                        2,
                    ),

                "historical_average":
                    round(
                        historical_average
                    ),

                "consistency":
                    consistency,

                "trend":
                    trend,

                "snapshot_count":
                    len(snapshot_scores),

                "first_seen":
                    trader["first_seen"],

                "last_seen":
                    trader["last_seen"],
            }
        )

    results.sort(
        key=lambda item: (
            item["score"],
            item["profit_score"],
            item["observations"],
        ),
        reverse=True,
    )

    return results[:limit]


def top_traders(
    min_observations: int = 1,
    limit: int = 25,
) -> List[Dict[str, Any]]:
    """
    Convenience wrapper for dashboard/API use.
    """

    return trader_intelligence(
        min_observations=min_observations,
        limit=limit,
    )


def trader_detail(
    username: str,
) -> Dict[str, Any] | None:
    """
    Return detailed public leaderboard history
    for one trader.
    """

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
            WHERE username = ?
            ORDER BY observed_at DESC
            """,
            (username,),
        ).fetchall()

    finally:
        conn.close()

    if not rows:
        return None

    history = []

    for row in rows:

        history.append(
            {
                "leaderboard":
                    row["leaderboard"],

                "timeframe":
                    row["timeframe"],

                "category":
                    row["category"],

                "rank":
                    row["rank"],

                "value":
                    row["value"],

                "observed_at":
                    row["observed_at"],
            }
        )

    rankings = trader_intelligence(
        min_observations=1,
        limit=200,
    )

    summary = next(
        (
            item
            for item in rankings
            if item["username"] ==
            username
        ),
        None,
    )

    return {
        "username":
            username,

        "summary":
            summary,

        "history":
            history,
    }


def save_public_leaderboard(
    entries: List[Dict[str, Any]],
) -> int:
    """
    Save legitimately obtained public
    leaderboard data.

    This function deliberately accepts
    supplied public data rather than
    attempting to bypass Kalshi Social
    access controls.
    """

    if not entries:
        return 0

    conn = connect()

    saved = 0

    try:

        for entry in entries:

            username = str(
                entry.get("username") or ""
            ).strip()

            leaderboard = str(
                entry.get("leaderboard") or ""
            ).strip().lower()

            timeframe = str(
                entry.get("timeframe") or ""
            ).strip().lower()

            if not username:
                continue

            if leaderboard not in {
                "profit",
                "volume",
                "predictions",
            }:
                continue

            if not timeframe:
                timeframe = "unknown"

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
                (username,),
            )

            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO
                leaderboard_snapshots(
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
                    leaderboard,
                    timeframe,
                    str(
                        entry.get("category")
                        or ""
                    ),
                    entry.get("rank"),
                    float(
                        entry.get("value") or 0
                    ),
                    entry.get(
                        "observed_at"
                    ),
                ),
            )

            if cursor.rowcount > 0:
                saved += 1

        conn.commit()

    finally:
        conn.close()

    return saved
