import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .db import connect
from .trader_intel import save_public_leaderboard


PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

DEFAULT_DATA_FILE = (
    PROJECT_ROOT
    / "data"
    / "public_leaderboard.json"
)

ARCHIVE_DIR = (
    PROJECT_ROOT
    / "data"
    / "leaderboard_history"
)


# ---------------------------------------------------------
# Load leaderboard data
# ---------------------------------------------------------

def load_entries(data_file):
    if not data_file.exists():
        raise FileNotFoundError(
            f"Leaderboard file not found: {data_file}"
        )

    with open(
        data_file,
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


# ---------------------------------------------------------
# Normalize entries
# ---------------------------------------------------------

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
            float(
                entry.get("value") or 0
            ),
            8,
        ),
    }


# ---------------------------------------------------------
# Snapshot signature
# ---------------------------------------------------------

def snapshot_signature(entries):

    """
    Create a stable signature for the actual
    leaderboard data.

    These fields are intentionally ignored:

        observed_at
        category
        source

    Therefore the exact same public leaderboard
    cannot create another historical snapshot merely
    because it was imported at a different time.
    """

    normalized = []

    for entry in entries:

        item = normalize_entry(
            entry
        )

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


# ---------------------------------------------------------
# Find duplicate snapshot
# ---------------------------------------------------------

def find_existing_snapshot(entries):

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
            [],
        )

        snapshots[key].append(
            {
                "username":
                    row["username"],

                "leaderboard":
                    row["leaderboard"],

                "timeframe":
                    row["timeframe"],

                "rank":
                    row["rank"],

                "value":
                    row["value"],
            }
        )

    incoming_signature = (
        snapshot_signature(entries)
    )

    for (
        observed_at,
        snapshot_entries,
    ) in snapshots.items():

        existing_signature = (
            snapshot_signature(
                snapshot_entries
            )
        )

        if (
            existing_signature
            == incoming_signature
        ):
            return observed_at

    return None


# ---------------------------------------------------------
# Archive snapshot
# ---------------------------------------------------------

def archive_snapshot(
    entries,
    snapshot_time,
    source_file,
):

    ARCHIVE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = (
        snapshot_time
        .replace(
            ":",
            "",
        )
        .replace(
            ".",
            "",
        )
        .replace(
            "+00:00",
            "Z",
        )
    )

    archive_file = (
        ARCHIVE_DIR
        / f"snapshot_{timestamp}.json"
    )

    archive_data = {
        "source": (
            "Kalshi Social public leaderboard"
        ),

        "source_file": str(
            source_file
        ),

        "captured_at":
            snapshot_time,

        "entry_count":
            len(entries),

        "entries":
            entries,
    }

    with open(
        archive_file,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            archive_data,
            file,
            indent=2,
        )

    return archive_file


# ---------------------------------------------------------
# Main import process
# ---------------------------------------------------------

def main():

    if len(sys.argv) > 1:

        data_file = Path(
            sys.argv[1]
        )

        if not data_file.is_absolute():
            data_file = (
                PROJECT_ROOT
                / data_file
            )

    else:

        data_file = DEFAULT_DATA_FILE

    print(
        "Loading leaderboard data from:"
    )

    print(data_file)

    print()

    entries = load_entries(
        data_file
    )

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

        if not isinstance(
            entry,
            dict,
        ):
            continue

        normalized = (
            normalize_entry(
                entry
            )
        )

        if not normalized[
            "username"
        ]:
            continue

        if normalized[
            "leaderboard"
        ] not in {
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

    # -----------------------------------------------------
    # Duplicate protection
    # -----------------------------------------------------

    existing_snapshot = (
        find_existing_snapshot(
            prepared
        )
    )

    if existing_snapshot:

        print()

        print(
            "This leaderboard data already "
            "exists as a recorded snapshot."
        )

        print(
            f"Existing snapshot: "
            f"{existing_snapshot}"
        )

        print()

        print(
            "No new snapshot created."
        )

        return

    # -----------------------------------------------------
    # New snapshot
    # -----------------------------------------------------

    snapshot_time = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    for entry in prepared:

        entry[
            "observed_at"
        ] = snapshot_time

    # -----------------------------------------------------
    # Save to database
    # -----------------------------------------------------

    saved = save_public_leaderboard(
        prepared
    )

    # -----------------------------------------------------
    # Archive the exact imported snapshot
    # -----------------------------------------------------

    archive_file = archive_snapshot(
        prepared,
        snapshot_time,
        data_file,
    )

    print()

    print(
        f"Entries saved: {saved}"
    )

    print()

    print(
        "Snapshot timestamp:"
    )

    print(
        snapshot_time
    )

    print()

    print(
        "Archived snapshot:"
    )

    print(
        archive_file
    )

    print()

    print(
        "Leaderboard snapshot "
        "imported successfully."
    )


if __name__ == "__main__":
    main()
