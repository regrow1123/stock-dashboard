# stock-dashboard

Self-hosted KR+US stock portfolio dashboard.

## Quickstart

```bash
cp .env.example .env
# Edit .env with your values

docker compose up -d

# Seed initial holdings
docker compose exec app python -m app.cli seed

# Backfill historical prices
docker compose exec app python -m app.cli backfill-prices --from 2024-01-01
```
