"""
Database exploration script to inspect accessible schemas, tables, and permissions.
"""

from src.etl.db import get_db_connection
from psycopg2.extras import RealDictCursor

def inspect():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 1. Schemas
    cur.execute("""
        SELECT schema_name 
        FROM information_schema.schemata 
        ORDER BY schema_name;
    """)
    schemas = [r['schema_name'] for r in cur.fetchall()]
    print("Available schemas in intrinio db:", schemas)

    # 2. Tables across non-system schemas
    cur.execute("""
        SELECT table_schema, table_name 
        FROM information_schema.tables 
        WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
        ORDER BY table_schema, table_name;
    """)
    tables = cur.fetchall()
    print(f"\nTotal non-system tables found: {len(tables)}")
    for t in tables[:40]:
        print(f"  {t['table_schema']}.{t['table_name']}")

    # 3. Columbia specific privileges
    cur.execute("""
        SELECT DISTINCT table_schema, table_name, privilege_type 
        FROM information_schema.table_privileges 
        WHERE grantee = 'columbia'
        ORDER BY table_schema, table_name;
    """)
    privs = cur.fetchall()
    print(f"\nSpecific table privileges for user 'columbia': {len(privs)}")
    for p in privs:
        print(f"  {p['table_schema']}.{p['table_name']} -> {p['privilege_type']}")

    cur.close()
    conn.close()

if __name__ == "__main__":
    inspect()
