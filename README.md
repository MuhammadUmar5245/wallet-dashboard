# Wallet & Exchange Dashboard (local)

PostgreSQL + Flask. Sample data: 40 custodial + 28 non-custodial wallets, ~1,300 outgoing txs.
All addresses are randomly generated demo values, not real wallets.

## Run (Docker only)

Needs only **Docker Desktop** (or Docker Engine + Compose). No Python or Postgres install required.

```bash
docker compose up --build
```

Open **http://localhost:5000**. That is all. On first start the app container waits for Postgres,
creates the tables and loads the sample data. On later starts it keeps your data.

| Command | What it does |
|---|---|
| `docker compose up --build -d` | start in background |
| `docker compose logs -f app` | see app logs |
| `docker compose down` | stop (data is kept in the `walletdata` volume) |
| `docker compose down -v` | stop and **delete all data** (next start re-seeds sample data) |

Open the database from your PC (DBeaver / psql): host `localhost`, port `5433`, db `walletdb`, user `wallet`, password `wallet`.

Run SQL inside the container:

```bash
docker compose exec db psql -U wallet -d walletdb -c "SELECT * FROM v_wallet_summary WHERE needs_review;"
```

## Files

| File | Purpose |
|---|---|
| `schema.sql` | Tables, indexes, `refresh_exchange_ids()` function, `v_wallet_summary` view |
| `seed.py` | Runs schema.sql and inserts sample data (**running it by hand wipes and recreates the tables**) |
| `init_db.py` | Container start-up: waits for DB, seeds only if the DB is empty |
| `Dockerfile`, `docker-compose.yml` | App + Postgres containers |
| `app.py` | Flask API + page |
| `templates/index.html` | Dashboard UI (no external libraries, works offline) |

## How the data model works

- `deposit_addresses` – one row per wallet, `wallet_type` = `custodial` | `non_custodial`,
  `exchange_ids SMALLINT[]` (array, GIN indexed).
- `outgoing_txs` – outgoing transfers with `chain_id` and `exchange_id` (NULL = not a known exchange).
- The array is **never edited by hand**. It is rebuilt from `outgoing_txs.exchange_id`
  (which has a real foreign key), so invalid exchange IDs cannot enter:

```sql
SELECT refresh_exchange_ids();     -- run after every batch of new transactions
```

Useful queries:

```sql
-- all wallets linked to Binance (id 1)
SELECT * FROM deposit_addresses WHERE exchange_ids @> ARRAY[1::smallint];

-- wallets linked to BOTH Binance and OKX
SELECT * FROM deposit_addresses WHERE exchange_ids @> ARRAY[1,2]::smallint[];

-- custodial wallets that look wrong (more than one exchange)
SELECT * FROM v_wallet_summary WHERE needs_review;
```

## Using your own data

Replace the sample section of `seed.py` with your import (or load CSVs with `COPY` inside the db container):
1. insert wallets into `deposit_addresses` (lowercase address, `wallet_type`)
2. insert transactions into `outgoing_txs`
3. run `SELECT refresh_exchange_ids();`

Notes
- Dashboard filters pick **wallets** first (type / chain / exchange / address), then every chart
  shows those wallets' activity. So filtering "Binance" still shows a wallet's other exchanges too.
- For production, store `amount` as raw `NUMERIC(78,0)` and partition `outgoing_txs` by month
  once it reaches tens of millions of rows.
