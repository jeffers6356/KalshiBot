import json
from datetime import datetime, timezone
from pathlib import Path

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


def main():
    print("Loading leaderboard data from:")
    print(DATA_FILE)
    print()

    entries = load_entries()

    print(
        f"Entries loaded: {len(entries)}"
    )

    if not entries:
        print("No leaderboard entries found.")
        return

    # One timestamp for the entire import.
    #
    # This timestamp represents one independent
    # leaderboard observation.
    snapshot_time = datetime.now(
        timezone.utc
    ).isoformat()

    prepared = []

    for entry in entries:

        if not isinstance(entry, dict):
            continue

        username = str(
            entry.get("username") or ""
        ).strip()

        leaderboard = str(
            entry.get("leaderboard") or ""
        ).strip().lower()

        if not username:
            continue

        if leaderboard not in {
            "profit",
            "volume",
            "predictions",
        }:
            continue

        prepared.append(
            {
                "username": username,
                "leaderboard": leaderboard,
                "timeframe": str(
                    entry.get("timeframe")
                    or "week"
                ).lower(),
                "category": str(
                    entry.get("category")
                    or ""
                ),
                "rank": entry.get("rank"),
                "value": float(
                    entry.get("value") or 0
                ),
                "observed_at": snapshot_time,
            }
        )

    print(
        f"Valid entries: {len(prepared)}"
    )

    if not prepared:
        print(
            "No valid leaderboard entries found."
        )
        return

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
