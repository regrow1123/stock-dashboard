#!/bin/sh
# Auto-migrate SQLite to PostgreSQL on first run
set -e

DB_URL="${DB_URL:-postgresql://stock:stock@db:5432/stock_dashboard}"
SQLITE_PATH="${SQLITE_PATH:-/app/data/dashboard.db}"

# Check if PostgreSQL already has data
python3 -c "
from sqlalchemy import create_engine, text
engine = create_engine('$DB_URL')
with engine.connect() as conn:
    result = conn.execute(text('SELECT count(*) FROM accounts'))
    count = result.scalar()
    exit(0 if count > 0 else 1)
" 2>/dev/null

if [ $? -eq 0 ]; then
    echo "PostgreSQL already has data, skipping migration"
    exec "$@"
fi

# Check if SQLite file exists
if [ ! -f "$SQLITE_PATH" ]; then
    echo "No SQLite file found, skipping migration"
    exec "$@"
fi

echo "Migrating SQLite to PostgreSQL..."
python3 /app/migrate_to_pg.py
echo "Migration complete"

exec "$@"
