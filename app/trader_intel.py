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

    Rank 1 = 100
    Rank 2 = 97
    Rank 10 = 73
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


def _snapshot_score(
    entries: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Calculate a trader's score for one leaderboard snapshot.
    """

    profit_score = 0.0
    volume_score = 0.0
    prediction_score = 0.0

    profit_value = 0.0
    volume_value = 0.0
    prediction_value = 0.0

    best_profit_rank = None
    best_volume_rank = None
    best_prediction_rank = None

    leaderboards = set()

    for entry in entries:

        leaderboard = str(
            entry.get("leaderboard") or ""
        ).lower()

        rank = entry.get("rank")
        value = float(
            entry.get("value") or 0
        )

        if leaderboard == "profit":

            leaderboards.add("profit")

            profit_score = _rank_score(rank)

            profit_value = value

            best_profit_rank = rank

        elif leaderboard == "volume":

            leaderboards.add("volume")

            volume_score = _rank_score(rank)

            volume_value = value

            best_volume_rank = rank

        elif leaderboard == "predictions":

            leaderboards.add("predictions")

            prediction_score = _rank_score(rank)

            prediction_value = value

            best_prediction_rank = rank

    weighted_score = (
        profit_score
        * LEADERBOARD_WEIGHTS["profit"]
        + volume_score
        * LEADERBOARD_WEIGHTS["volume"]
        + prediction_score
        * LEADERBOARD_WEIGHTS["predictions"]
    )

    breadth_bonus = min(
        10.0,
        len(leaderboards) * 3.33,
    )

    score = min(
        100.0,
        weighted_score + breadth_bonus,
    )

    return {
        "score": score,
        "profit_score": profit_score,
        "volume_score": volume_score,
        "prediction_score": prediction_score,
        "profit_value": profit_value,
        "volume_value": volume_value,
        "prediction_value": prediction_value,
        "best_profit_rank": best_profit_rank,
        "best_volume_rank": best_volume_rank,
        "best_prediction_rank": best_prediction_rank,
        "leaderboards": leaderboards,
    }


def _consistency_label(
    snapshot_scores: List[float],
) -> str:
    """
    Determine consistency from independent snapshots.
    """

    count = len(snapshot_scores)

    if count < 2:
        return "NEW"

    average = _average(snapshot_scores)

    if average <= 0:
        return "NEW"

    variance = _average(
        [
            abs(score - average)
            for score in snapshot_scores
        ]
    )

    if count >= 5 and variance <= 8:
        return "HIGH"

    if count >= 3 and variance <= 15:
        return "MEDIUM"

    return "LOW"


def _trend_label(
    current_score: float,
    previous_scores: List[float],
) -> str:
    """
    Compare the current score with previous snapshots.
    """

    if not previous_scores:
        return "NEW"

    previous_average = _average(
        previous_scores
    )

    difference = (
        current_score -
        previous_average
    )

    if difference >= 8:
        return "RISING"

    if difference <= -8:
        return "FALLING"

    return "STABLE"


def trader_intelligence(
    min_observations: int = 1,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Build trader intelligence from public leaderboard data.

    Each unique observed_at timestamp represents one
    leaderboard snapshot.

    Profit, volume, and prediction entries occurring at
    the same timestamp are treated as part of the same
    snapshot.

    Historical statistics are only calculated when
    multiple independent snapshots exist.
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

    # --------------------------------------------------
    # Group database rows into:
    #
    # trader -> timestamp -> leaderboard entries
    # --------------------------------------------------

    trader_snapshots: Dict[
        str,
        Dict[str, List[Dict[str, Any]]]
    ] = {}

    for row in rows:

        username = row["username"]

        observed_at = (
            row["observed_at"]
            or ""
        )

        if username not in trader_snapshots:
            trader_snapshots[username] = {}

        if observed_at not in trader_snapshots[username]:
            trader_snapshots[
                username
            ][observed_at] = []

        trader_snapshots[
            username
        ][observed_at].append(
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
                    observed_at,
            }
        )

    results: List[Dict[str, Any]] = []

    for username, snapshots in trader_snapshots.items():

        total_observations = sum(
            len(entries)
            for entries in snapshots.values()
        )

        if total_observations < min_observations:
            continue

        # Sort snapshots chronologically.
        ordered_snapshots = sorted(
            snapshots.items(),
            key=lambda item: item[0],
        )

        calculated_snapshots = []

        for observed_at, entries in ordered_snapshots:

            snapshot = _snapshot_score(
                entries
            )

            calculated_snapshots.append(
                {
                    "observed_at":
                        observed_at,

                    **snapshot,
                }
            )

        if not calculated_snapshots:
            continue

        # Latest snapshot is the current state.
        current = calculated_snapshots[-1]

        # Everything before the latest snapshot
        # represents actual historical data.
        previous = calculated_snapshots[:-1]

        current_score = current["score"]

        historical_scores = [
            snapshot["score"]
            for snapshot in calculated_snapshots
        ]

        previous_scores = [
            snapshot["score"]
            for snapshot in previous
        ]

        historical_average = (
            _average(previous_scores)
            if previous_scores
            else 0.0
        )

        consistency = _consistency_label(
            historical_scores
        )

        trend = _trend_label(
            current_score,
            previous_scores,
        )

        # Determine all leaderboard types the trader
        # has appeared on.
        all_leaderboards = set()

        for snapshot in calculated_snapshots:
            all_leaderboards.update(
                snapshot["leaderboards"]
            )

        # Best ranks ever observed.
        best_profit_rank = None
        best_volume_rank = None
        best_prediction_rank = None

        for snapshot in calculated_snapshots:

            rank = snapshot[
                "best_profit_rank"
            ]

            if rank is not None:
                if (
                    best_profit_rank is None
                    or rank < best_profit_rank
                ):
                    best_profit_rank = rank

            rank = snapshot[
                "best_volume_rank"
            ]

            if rank is not None:
                if (
                    best_volume_rank is None
                    or rank < best_volume_rank
                ):
                    best_volume_rank = rank

            rank = snapshot[
                "best_prediction_rank"
            ]

            if rank is not None:
                if (
                    best_prediction_rank is None
                    or rank < best_prediction_rank
                ):
                    best_prediction_rank = rank

        results.append(
            {
                "username":
                    username,

                "score":
                    round(current_score),

                "profit_score":
                    round(
                        current[
                            "profit_score"
                        ]
                    ),

                "volume_score":
                    round(
                        current[
                            "volume_score"
                        ]
                    ),

                "prediction_score":
                    round(
                        current[
                            "prediction_score"
                        ]
                    ),

                "observations":
                    total_observations,

                "leaderboards":
                    sorted(
                        all_leaderboards
                    ),

                "best_profit_rank":
                    best_profit_rank,

                "best_volume_rank":
                    best_volume_rank,

                "best_prediction_rank":
                    best_prediction_rank,

                "profit_value":
                    round(
                        current[
                            "profit_value"
                        ],
                        2,
                    ),

                "volume_value":
                    round(
                        current[
                            "volume_value"
                        ],
                        2,
                    ),

                "prediction_value":
                    round(
                        current[
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
                    len(
                        calculated_snapshots
                    ),

                "first_seen":
                    calculated_snapshots[
                        0
                    ]["observed_at"],

                "last_seen":
                    current[
                        "observed_at"
                    ],
            }
        )

    results.sort(
        key=lambda item: (
            item["score"],
            item["historical_average"],
            item["snapshot_count"],
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
