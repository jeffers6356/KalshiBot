import re
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx
from bs4 import BeautifulSoup


KALSHI_SOCIAL_BASE = "https://kalshi.com/social/leaderboard"


TIMEFRAMES = {
    "day": "day",
    "week": "week",
    "month": "month",
    "year": "year",
    "all": "all",
}


class SocialCollectorError(Exception):
    """Raised when Kalshi Social data cannot be collected."""


class KalshiSocialClient:
    def __init__(self, timeout: float = 20.0):
        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": "KalshiBot/0.1",
            },
            follow_redirects=True,
        )

    async def close(self):
        await self.client.aclose()

    async def leaderboard_html(self, timeframe: str = "week") -> str:
        timeframe = TIMEFRAMES.get(timeframe, timeframe)

        url = KALSHI_SOCIAL_BASE
        params = {"timeframe": timeframe}

        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SocialCollectorError(
                f"Unable to retrieve Kalshi Social leaderboard: {exc}"
            ) from exc

        return response.text


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _parse_money(value: str) -> float:
    value = value.replace("$", "").replace(",", "").strip()

    if value.startswith("(") and value.endswith(")"):
        value = "-" + value[1:-1]

    try:
        return float(value)
    except ValueError:
        return 0.0


def _parse_number(value: str) -> float:
    value = value.replace(",", "").strip()

    try:
        return float(value)
    except ValueError:
        return 0.0


def _extract_leaderboard_entries(
    section_text: str,
    metric: str,
) -> List[Dict[str, Any]]:
    """
    Parse leaderboard entries from visible Kalshi Social text.

    Expected examples:

        7 BaronVonBid $96,979
        11 quiet.badger5137 $76,058
        12 soupwins $73,875

    or:

        11 witty.falcon1093 13,134,321
        12 BaronVonBid 11,725,083
    """

    entries: List[Dict[str, Any]] = []

    pattern = re.compile(
        r"(?P<rank>\d{1,4})\s+"
        r"(?P<username>[A-Za-z0-9._-]{2,64})\s+"
        r"(?P<value>\$?[\d,]+(?:\.\d+)?)"
    )

    for match in pattern.finditer(section_text):
        rank = int(match.group("rank"))
        username = match.group("username")
        raw_value = match.group("value")

        if metric == "profit":
            value = _parse_money(raw_value)
        else:
            value = _parse_number(raw_value)

        entries.append(
            {
                "username": username,
                "rank": rank,
                "value": value,
                "leaderboard": metric,
            }
        )

    return entries


def parse_leaderboard(html: str, timeframe: str) -> List[Dict[str, Any]]:
    """
    Parse the public Kalshi Social leaderboard.

    The page currently exposes three leaderboard sections:
        Profit
        Volume
        Predictions
    """

    soup = BeautifulSoup(html, "html.parser")

    # Remove non-visible elements.
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    text = soup.get_text("\n", strip=True)
    text = _clean_text(text)

    results: List[Dict[str, Any]] = []

    section_patterns = {
        "profit": r"\bProfit\b",
        "volume": r"\bVolume\b",
        "predictions": r"\bPredictions\b",
    }

    positions = []

    for metric, pattern in section_patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            positions.append((match.start(), metric))

    positions.sort()

    for index, (start, metric) in enumerate(positions):
        end = positions[index + 1][0] if index + 1 < len(positions) else len(text)

        section = text[start:end]

        entries = _extract_leaderboard_entries(
            section,
            metric,
        )

        for entry in entries:
            entry["timeframe"] = timeframe
            results.append(entry)

    return results


async def collect_leaderboard(
    timeframe: str = "week",
) -> Dict[str, Any]:
    """
    Retrieve and parse one Kalshi Social leaderboard.
    """

    if timeframe not in TIMEFRAMES:
        raise ValueError(
            f"Invalid timeframe '{timeframe}'. "
            f"Use one of: {', '.join(TIMEFRAMES)}"
        )

    client = KalshiSocialClient()

    try:
        html = await client.leaderboard_html(timeframe)
    finally:
        await client.close()

    entries = parse_leaderboard(
        html,
        timeframe,
    )

    observed_at = datetime.now(timezone.utc).isoformat()

    for entry in entries:
        entry["observed_at"] = observed_at

    return {
        "timeframe": timeframe,
        "entries": entries,
        "count": len(entries),
    }


def save_leaderboard(
    entries: List[Dict[str, Any]],
) -> int:
    """
    Save leaderboard observations into SQLite.
    """

    from .db import connect

    if not entries:
        return 0

    conn = connect()

    saved = 0

    try:
        for entry in entries:
            username = entry["username"]

            # Keep the existing traders table synchronized.
            conn.execute(
                """
                INSERT INTO traders(username, enabled)
                VALUES(?, 1)
                ON CONFLICT(username) DO NOTHING
                """,
                (username,),
            )

            conn.execute(
                """
                INSERT OR IGNORE INTO leaderboard_snapshots
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
                    entry["leaderboard"],
                    entry["timeframe"],
                    "",
                    entry["rank"],
                    entry["value"],
                    entry["observed_at"],
                ),
            )

            saved += 1

        conn.commit()

    finally:
        conn.close()

    return saved
