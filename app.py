"""Small Flask dashboard over the wallet / exchange database.

Run:  python app.py   ->  http://localhost:5000
"""
import os
from decimal import Decimal

import psycopg
from flask import Flask, jsonify, render_template, request
from psycopg.rows import dict_row

DSN = os.environ.get("DATABASE_URL", "postgresql://wallet:wallet@localhost:5433/walletdb")
app = Flask(__name__)


def db():
    return psycopg.connect(DSN, row_factory=dict_row)


def clean(obj):
    """Make Decimal / datetime JSON friendly."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return obj


def filters():
    a = request.args
    return {
        "wtype": a.get("type") or None,
        "chain": int(a["chain"]) if a.get("chain") else None,
        "ex": int(a["exchange"]) if a.get("exchange") else None,
        "q": (a.get("q") or "").strip().lower() or None,
    }


# Wallet set after filters. exchange filter uses the array column (GIN indexed).
WALLET_CTE = """
WITH w AS (
    SELECT wallet_id FROM deposit_addresses d
    WHERE (%(wtype)s::text     IS NULL OR d.wallet_type = %(wtype)s::text)
      AND (%(chain)s::int      IS NULL OR d.chain_id    = %(chain)s::int)
      AND (%(ex)s::smallint    IS NULL OR d.exchange_ids @> ARRAY[%(ex)s::smallint])
      AND (%(q)s::text         IS NULL OR d.address LIKE '%%' || %(q)s::text || '%%')
)
"""


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/meta")
def meta():
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT chain_id AS id, name FROM chains ORDER BY name")
        chains = cur.fetchall()
        cur.execute("SELECT exchange_id AS id, name FROM exchanges ORDER BY name")
        exchanges = cur.fetchall()
    return jsonify(chains=chains, exchanges=exchanges)


@app.get("/api/data")
def data():
    p = filters()
    with db() as conn, conn.cursor() as cur:
        cur.execute(WALLET_CTE + """
            SELECT count(*)                                            AS wallets,
                   count(*) FILTER (WHERE s.wallet_type='custodial')     AS custodial,
                   count(*) FILTER (WHERE s.wallet_type='non_custodial') AS non_custodial,
                   count(*) FILTER (WHERE s.needs_review)                AS needs_review,
                   COALESCE(sum(s.tx_count), 0)                          AS txs,
                   COALESCE(sum(s.volume_usd), 0)                        AS volume_usd
            FROM v_wallet_summary s JOIN w USING (wallet_id)""", p)
        kpi = cur.fetchone()

        cur.execute(WALLET_CTE + """
            SELECT e.name, count(*) AS txs, sum(t.amount_usd) AS volume_usd
            FROM outgoing_txs t JOIN w USING (wallet_id)
            JOIN exchanges e ON e.exchange_id = t.exchange_id
            GROUP BY e.name ORDER BY volume_usd DESC""", p)
        by_exchange = cur.fetchall()

        cur.execute(WALLET_CTE + """
            SELECT c.name, count(DISTINCT t.wallet_id) AS wallets, sum(t.amount_usd) AS volume_usd
            FROM outgoing_txs t JOIN w USING (wallet_id)
            JOIN chains c ON c.chain_id = t.chain_id
            GROUP BY c.name ORDER BY volume_usd DESC""", p)
        by_chain = cur.fetchall()

        cur.execute(WALLET_CTE + """
            SELECT date_trunc('week', t.block_time)::date AS week,
                   COALESCE(sum(t.amount_usd) FILTER (WHERE d.wallet_type='custodial'), 0)     AS custodial,
                   COALESCE(sum(t.amount_usd) FILTER (WHERE d.wallet_type='non_custodial'), 0) AS non_custodial
            FROM outgoing_txs t JOIN w USING (wallet_id)
            JOIN deposit_addresses d USING (wallet_id)
            GROUP BY 1 ORDER BY 1""", p)
        weekly = cur.fetchall()

        cur.execute(WALLET_CTE + """
            SELECT s.wallet_id, s.chain, s.address, s.wallet_type, s.exchange_names,
                   s.exchange_count, s.needs_review, s.tx_count, s.volume_usd, s.last_tx
            FROM v_wallet_summary s JOIN w USING (wallet_id)
            ORDER BY s.volume_usd DESC LIMIT 500""", p)
        wallets = cur.fetchall()

    return jsonify(clean(dict(kpi=kpi, by_exchange=by_exchange, by_chain=by_chain,
                              weekly=weekly, wallets=wallets)))


@app.get("/api/wallet/<int:wallet_id>")
def wallet_txs(wallet_id):
    with db() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT t.tx_hash, t.to_address, e.name AS exchange, t.token, t.amount,
                   t.amount_usd, t.block_time
            FROM outgoing_txs t LEFT JOIN exchanges e USING (exchange_id)
            WHERE t.wallet_id = %s ORDER BY t.block_time DESC LIMIT 25""", (wallet_id,))
        return jsonify(clean(cur.fetchall()))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
