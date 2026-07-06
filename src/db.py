from __future__ import annotations

from sqlalchemy import create_engine, text
import pandas as pd


def get_engine(database_url: str):
    return create_engine(database_url, pool_pre_ping=True)


def replace_by_dates(engine, table: str, df: pd.DataFrame) -> None:
    if df.empty:
        print(f"{table}: no rows")
        return

    df = df.where(pd.notna(df), None)

    with engine.begin() as conn:
        conn.execute(text(f'TRUNCATE TABLE "{table}"'))

        df.to_sql(
            table,
            conn,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=500,
        )

    print(f"{table}: loaded {len(df)} rows")


def log_load(
    engine,
    table_name: str,
    source_file: str,
    rows_loaded: int,
    status: str,
    message: str = "",
):
    with engine.begin() as conn:
        conn.execute(
            text("""
                insert into load_log(table_name, source_file, rows_loaded, status, message)
                values (:table_name, :source_file, :rows_loaded, :status, :message)
            """),
            {
                "table_name": table_name,
                "source_file": source_file,
                "rows_loaded": rows_loaded,
                "status": status,
                "message": message[:1000],
            },
        )