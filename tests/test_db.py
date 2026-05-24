from sqlalchemy import create_engine

from app.db import init_db


def test_init_db_adds_sector_column_to_existing_instruments(tmp_path):
    # Simulate a pre-existing DB whose instruments table lacks `sector`.
    url = f"sqlite:///{tmp_path / 'old.db'}"
    engine = create_engine(url, future=True)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE instruments (ticker VARCHAR PRIMARY KEY, name VARCHAR)"
        )
        conn.exec_driver_sql(
            "INSERT INTO instruments (ticker, name) VALUES ('AAPL', 'Apple')"
        )
    # init_db must add the missing column without dropping data.
    init_db(engine)
    with engine.begin() as conn:
        cols = {r[1] for r in conn.exec_driver_sql(
            "PRAGMA table_info(instruments)").fetchall()}
        assert "sector" in cols
        row = conn.exec_driver_sql(
            "SELECT name FROM instruments WHERE ticker='AAPL'").fetchone()
        assert row[0] == "Apple"
