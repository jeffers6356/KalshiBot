# Kalshi Smart Money Research Dashboard

A research-first MVP for tracking Kalshi markets, public exchange activity, watched traders, and alert conditions.

## Important limitation

Kalshi's official public Trade API exposes market data and aggregate public trades, but the public `GET /markets/trades` response does **not** identify the individual trader behind each trade. Kalshi Social exposes public trader activity in the product, but Kalshi's current public API documentation does not document a Social/leaderboard activity endpoint. This MVP therefore separates the system into:

1. **Official market-data collector** — fully supported by the public Kalshi Trade API.
2. **Trader activity adapter** — accepts public activity records from an approved/public source without attempting to bypass Kalshi privacy or authentication controls.
3. **Research/alert engine** — scores traders, detects consensus, and generates alerts once trader activity is available.

The architecture is intentionally ready for a supported Kalshi Social data source if/when one is available.

## What works now

- FastAPI dashboard
- SQLite storage
- Pull open markets from Kalshi
- Pull recent public trades
- Store market snapshots
- Maintain a watched-trader list
- Ingest public trader activity through a simple JSON endpoint
- Calculate weighted smart-money consensus
- Generate alerts when watched traders converge on a market
- JSON API endpoints for dashboard/client use

## Run

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000

## Environment

Optional:

```text
KALSHI_BASE_URL=https://external-api.kalshi.com/trade-api/v2
```

No Kalshi API key is required for the public market-data endpoints used by this MVP.

## Public endpoints

- `GET /api/health`
- `GET /api/markets`
- `GET /api/trades`
- `GET /api/traders`
- `POST /api/traders`
- `POST /api/trader-activity`
- `GET /api/signals`
- `POST /api/collect`

### Example trader activity

```json
{
  "username": "example.trader",
  "market_ticker": "KXEXAMPLE-26-YES",
  "side": "yes",
  "action": "buy",
  "price": 0.63,
  "contracts": 2500,
  "source": "public_social",
  "occurred_at": "2026-10-08T15:00:00Z"
}
```

This endpoint is deliberately generic: the adapter can be connected later to a legitimate public activity feed without changing the signal engine.

## Next build step

The next thing to solve is **the trader-identity data source**. We should not assume that the aggregate public trade feed can tell us which profitable account made a trade. Once we have a supported public source for Social/leaderboard activity, plug it into `TraderActivityAdapter` and the rest of the dashboard is already wired for it.
