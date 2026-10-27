"""
PostgreSQL database connector for the Intrinio Columbia database.
Handles secure connection, schema discovery, and Polars streaming integration.
"""

import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor
import polars as pl
from sqlalchemy import create_engine

# Load environment variables from .env
load_dotenv()

PG_HOST = os.getenv("PG_HOST", "intrinio-userdata-cluster.cluster-c0uqyiscfxcq.us-east-1.rds.amazonaws.com")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_DATABASE = os.getenv("PG_DATABASE", "intrinio")
PG_USER = os.getenv("PG_USER", "columbia")
PG_SCHEMA = os.getenv("PG_SCHEMA", "columbia")
PG_PASSWORD = os.getenv("PG_PASSWORD", "")


def get_connection_string() -> str:
    """Constructs SQLAlchemy/psycopg2 connection URI."""
    if not PG_PASSWORD:
        raise ValueError(
            "PG_PASSWORD is not set. Please add PG_PASSWORD to your .env file."
        )
    return f"postgresql+psycopg2://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}?options=-csearch_path%3D{PG_SCHEMA}"


def get_db_connection():
    """Returns a direct psycopg2 database connection with search_path set."""
    if not PG_PASSWORD:
        raise ValueError(
            "PG_PASSWORD is not set. Please add PG_PASSWORD to your .env file."
        )
    conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_DATABASE,
        user=PG_USER,
        password=PG_PASSWORD,
        options=f"-c search_path={PG_SCHEMA}",
        connect_timeout=10,
    )
    return conn


def test_connection() -> Dict[str, Any]:
    """Tests the database connection and lists available tables in the schema."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Check current user and schema
        cursor.execute("SELECT current_user, current_database(), current_schema();")
        identity = cursor.fetchone()
        
        # Discover tables in the target schema
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = %s
            ORDER BY table_name;
        """, (PG_SCHEMA,))
        tables = [row["table_name"] for row in cursor.fetchall()]
        
        # Get row counts for discovered tables
        table_stats = []
        for table in tables:
            try:
                cursor.execute(f"SELECT COUNT(*) AS row_count FROM {PG_SCHEMA}.{table};")
                cnt = cursor.fetchone()["row_count"]
                table_stats.append({"table": table, "row_count": cnt})
            except Exception as e:
                table_stats.append({"table": table, "row_count": f"Error: {e}"})
                conn.rollback()
                
        cursor.close()
        conn.close()
        return {
            "status": "connected",
            "identity": identity,
            "tables": table_stats
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


def read_sql_to_polars(query: str) -> pl.DataFrame:
    """Executes a SQL query and returns results as a Polars DataFrame."""
    conn = get_db_connection()
    try:
        # Fetch using pandas/sqlalchemy and convert or use psycopg2
        df = pl.read_database(query, connection=conn)
        return df
    finally:
        conn.close()


if __name__ == "__main__":
    print(f"Connecting to Postgres at {PG_HOST} (User: {PG_USER}, DB: {PG_DATABASE}, Schema: {PG_SCHEMA})...")
    res = test_connection()
    if res["status"] == "connected":
        print("\n[OK] Connection Successful!")
        print("Identity:", res["identity"])
        print("\nDiscovered Tables:")
        for t in res["tables"]:
            print(f"  - {t['table']}: {t['row_count']:,} rows" if isinstance(t['row_count'], int) else f"  - {t['table']}: {t['row_count']}")
    else:
        print("\n[FAIL] Connection Failed:")
        print(res.get("message"))
