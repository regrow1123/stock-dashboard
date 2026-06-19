#!/bin/sh
# Auto-migrate SQLite to PostgreSQL on first run

DB_URL="${DB_URL:-postgresql://stock:stock@db:5432/stock_dashboard}"
SQLITE_PATH="${SQLITE_PATH:-/app/data/dashboard.db}"

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL..."
for i in $(seq 1 30); do
  python3 -c "import sqlalchemy; sqlalchemy.create_engine('${DB_URL}').connect()" 2>/dev/null && break
  sleep 1
done

# Check if PostgreSQL already has data
HAS_DATA=$(python3 -c "
from sqlalchemy import create_engine, text
engine = create_engine('${DB_URL}')
with engine.connect() as conn:
    result = conn.execute(text('SELECT count(*) FROM accounts'))
    print(result.scalar())
" 2>/dev/null || echo "0")

if [ "$HAS_DATA" -gt 0 ]; then
    echo "PostgreSQL already has data ($HAS_DATA accounts), skipping migration"
    exec "$@"
fi

# Check if SQLite file exists
if [ ! -f "$SQLITE_PATH" ]; then
    echo "No SQLite file found at $SQLITE_PATH, skipping migration"
    exec "$@"
fi

echo "Migrating SQLite to PostgreSQL..."
python3 /app/migrate_to_pg.py || echo "Migration failed, continuing anyway"
echo "Migration complete"

exec "$@"
