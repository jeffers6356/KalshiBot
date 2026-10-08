import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .trader_intel import save_public_leaderboard


DEFAULT_FILE = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "public_leaderboard.json"
)


def load_entries(path: Path):
    if not path.exists():
        raise FileNotFoundError(
            f"Leaderboard file not found: {path}"
        )

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        data = json.load(file)

    if isinstance(data, dict):
        entries = data.get("entries", [])
    elif isinstance(data, list):
        entries = data
    else:
        raise ValueError(
            "Leaderboard JSON must contain either "
            "an array or an object with an 'entries' array."
        )

    if not isinstance(entries, list):
        raise ValueError(
            "'entries' must be a JSON array."
        )

    return entries


def normalize_entries(entries):
    observed_at = datetime.now(
        timezone.utc
    ).isoformat()

    normalized = []

    for entry in entries:
        username = str(
            entry.get("username") or ""
        ).strip()

        leaderboard = str(
            entry.get("leaderboard") or ""
        ).strip().lower()

        timeframe = str(
            entry.get("timeframe") or "week"
        ).strip().lower()

        if not username:
            continue

        if leaderboard not in {
            "profit",
            "volume",
            "predictions",
        }:
            continue

        rank = entry.get("rank")

        if rank is not None:
            rank = int(rank)

        value = float(
            entry.get("value") or 0
        )

        normalized.append(
            {
                "username": username,
                "leaderboard": leaderboard,
                "timeframe": timeframe,
                "category": str(
                    entry.get("category") or ""
                ),
                "rank": rank,
                "value": value,
                "observed_at": observed_at,
            }
        )

    return normalized


def main():
    path = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else DEFAULT_FILE
    )

    print(
        f"Loading leaderboard data from:\n{path}\n"
    )

    entries = load_entries(path)
    entries = normalize_entries(entries)

    if not entries:
        print(
            "No valid leaderboard entries found."
        )
        return 1

    saved = save_public_leaderboard(
        entries
    )

    print(
        f"Valid entries: {len(entries)}"
    )

    print(
        f"Entries processed: {saved}"
    )

    print(
        "\nLeaderboard data imported successfully."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
