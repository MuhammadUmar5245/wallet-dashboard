"""Container start-up: wait for Postgres, seed sample data only if the DB is still empty."""
import os
import sys
import time

import psycopg

import seed

DSN = os.environ.get("DATABASE_URL", seed.DSN)

for attempt in range(40):
    try:
        with psycopg.connect(DSN, connect_timeout=3) as conn:
            exists = conn.execute("SELECT to_regclass('public.deposit_addresses')").fetchone()[0]
        break
    except psycopg.OperationalError as e:
        print(f"waiting for database ({attempt + 1}/40): {e}".splitlines()[0], flush=True)
        time.sleep(2)
else:
    sys.exit("database not reachable")

if exists:
    print("tables already exist - keeping your data", flush=True)
else:
    print("empty database - creating tables and loading sample data", flush=True)
    seed.main()
