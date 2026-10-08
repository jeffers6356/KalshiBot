from collections import defaultdict
from datetime import datetime, timezone, timedelta
from .db import connect


def trader_scores():
    conn = connect()
    rows = conn.execute("SELECT * FROM traders WHERE enabled=1 ORDER BY score DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def consensus_signals(window_minutes=30, min_traders=2):
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    cutoff_s = cutoff.isoformat().replace('+00:00', 'Z')
    conn = connect()
    rows = conn.execute("""
        SELECT a.*, t.score, t.roi, t.profit
        FROM trader_activity a
        JOIN traders t ON t.username = a.username
        WHERE t.enabled=1 AND a.occurred_at >= ?
    """, (cutoff_s,)).fetchall()
    conn.close()

    groups = defaultdict(lambda: {"yes": [], "no": []})
    for r in rows:
        side = r["side"].lower()
        if side in groups[(r["market_ticker"])]:
            groups[r["market_ticker"]][side].append(dict(r))

    signals = []
    for ticker, sides in groups.items():
        yes_users = {x["username"] for x in sides["yes"]}
        no_users = {x["username"] for x in sides["no"]}
        if len(yes_users) >= min_traders or len(no_users) >= min_traders:
            weighted_yes = sum(max(0, x["score"] or 0) for x in sides["yes"])
            weighted_no = sum(max(0, x["score"] or 0) for x in sides["no"])
            total = weighted_yes + weighted_no
            if total:
                consensus = "YES" if weighted_yes >= weighted_no else "NO"
                confidence = max(weighted_yes, weighted_no) / total
            else:
                consensus, confidence = "NEUTRAL", 0
            signals.append({
                "market_ticker": ticker,
                "consensus": consensus,
                "confidence": round(confidence, 3),
                "yes_traders": sorted(yes_users),
                "no_traders": sorted(no_users),
                "window_minutes": window_minutes,
            })
    signals.sort(key=lambda x: x["confidence"], reverse=True)
    return signals
