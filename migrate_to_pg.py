#!/usr/bin/env python3
"""Migrate data from SQLite to PostgreSQL."""
import os
import sqlite3
from sqlalchemy import create_engine, text
from app.db import Base, init_db

sqlite_path = os.environ.get("SQLITE_PATH", "/app/data/dashboard.db")
pg_url = os.environ.get("DB_URL", "postgresql://stock:stock@db:5432/stock_dashboard")

if not os.path.exists(sqlite_path):
    print(f"No SQLite file at {sqlite_path}, skipping migration")
    exit(0)

sqlite_conn = sqlite3.connect(sqlite_path)
pg_engine = create_engine(pg_url)

init_db(pg_engine)

tables = [row[0] for row in sqlite_conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
).fetchall()]

print(f"Found {len(tables)} tables in SQLite")

with pg_engine.begin() as pg_conn:
    for table in tables:
        rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
        if not rows:
            print(f"  {table}: 0 rows (skipped)")
            continue
        cols = [desc[0] for desc in sqlite_conn.execute(f"SELECT * FROM {table} LIMIT 0").description]
        table_obj = Base.metadata.tables.get(table)
        if table_obj is None:
            print(f"  {table}: no model (skipped)")
            continue
        inserted = 0
        for row in rows:
            data = {}
            for i, col in enumerate(cols):
                if col in table_obj.columns:
                    data[col] = row[i]
            try:
                pg_conn.execute(table_obj.insert().values(**data))
                inserted += 1
            except Exception as e:
                print(f"  {table}: Error: {e}")
        print(f"  {table}: {inserted}/{len(rows)} rows")

sqlite_conn.close()
print("\nMigration complete!")
