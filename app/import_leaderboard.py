import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .db import connect
from .trader_intel import save_public_leaderboard


DATA_FILE = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "public_leaderboard.json"
)


def load_entries():
    if not DATA_FILE.exists():
        raise FileNotFoundError(
            f"Leaderboard file not found: {DATA_FILE}"
        )

    with open(
        DATA_FILE,
        "r",
        encoding="utf-8",
    ) as file:
        data = json.load(file)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        if "entries" in data:
            return data["entries"]

        if "traders" in data:
            return data["traders"]

    raise ValueError(
        "Leaderboard JSON must be a list or contain "
        "'entries' or 'traders'."
    )


def normalize_entry(entry):
    return {
        "username": str(
            entry.get("username") or ""
        ).strip(),

        "leaderboard": str(
            entry.get("leaderboard") or ""
        ).strip().lower(),

        "timeframe": str(
            entry.get("timeframe") or "week"
        ).strip().lower(),

        "rank": int(
            entry.get("rank") or 0
        ),

        "value": round(
            float(entry.get("value") or 0),
            8,
        ),
    }


def snapshot_signature(entries):
    """
    Create a stable signature for the actual leaderboard data.

    We intentionally ignore:
      - observed_at
      - category

    Those fields should not make identical leaderboard
    data look like a new snapshot.
    """

    normalized = []

    for entry in entries:
        item = normalize_entry(entry)

        normalized.append(
            (
                item["username"],
                item["leaderboard"],
                item["timeframe"],
                item["rank"],
                item["value"],
            )
        )

    normalized.sort()

    payload = json.dumps(
        normalized,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()


def find_existing_snapshot(entries):
    conn = connect()

    try:
        rows = conn.execute(
            """
            SELECT
                username,
                leaderboard,
                timeframe,
                rank,
                value,
                observed_at
            FROM leaderboard_snapshots
            ORDER BY observed_at
            """
        ).fetchall()
    finally:
        conn.close()

    snapshots = {}

    for row in rows:

        key = row["observed_at"]

        snapshots.setdefault(
            key,
            []
        )

        snapshots[key].append(
            {
                "username": row["username"],
                "leaderboard": row["leaderboard"],
                "timeframe": row["timeframe"],
                "rank": row["rank"],
                "value": row["value"],
            }
        )

    incoming_signature = snapshot_signature(
        entries
    )

    for (
        observed_at,
        snapshot_entries,
    ) in snapshots.items():

        existing_signature = snapshot_signature(
            snapshot_entries
        )

        if existing_signature == incoming_signature:
            return observed_at

    return None


def main():

    print(
        "Loading leaderboard data from:"
    )
    print(DATA_FILE)
    print()

    entries = load_entries()

    print(
        f"Entries loaded: {len(entries)}"
    )

    if not entries:
        print(
            "No leaderboard entries found."
        )
        return

    prepared = []

    for entry in entries:

        if not isinstance(entry, dict):
            continue

        normalized = normalize_entry(
            entry
        )

        if not normalized["username"]:
            continue

        if normalized["leaderboard"] not in {
            "profit",
            "volume",
            "predictions",
        }:
            continue

        prepared.append(
            normalized
        )

    print(
        f"Valid entries: {len(prepared)}"
    )

    if not prepared:
        print(
            "No valid leaderboard entries found."
        )
        return

    existing_snapshot = find_existing_snapshot(
        prepared
    )

    if existing_snapshot:

        print()
        print(
            "This leaderboard data already exists "
            "as a recorded snapshot."
        )

        print(
            f"Existing snapshot: {existing_snapshot}"
        )

        print()
        print(
            "No new snapshot created."
        )

        return

    #
    # This is a genuinely new snapshot.
    #
    snapshot_time = datetime.now(
        timezone.utc
    ).isoformat()

    for entry in prepared:
        entry["observed_at"] = snapshot_time

    saved = save_public_leaderboard(
        prepared
    )

    print(
        f"Entries saved: {saved}"
    )

    print()
    print(
        "Snapshot timestamp:"
    )
    print(snapshot_time)

    print()
    print(
        "Leaderboard snapshot imported successfully."
    )


if __name__ == "__main__":
    main()
