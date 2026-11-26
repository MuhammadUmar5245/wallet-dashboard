"""Create the schema and load SAMPLE data (custodial + non-custodial wallets).

All addresses/hashes are randomly generated demo values - not real wallets.
Replace the sample section with your own list/import when you have real data.
"""
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg

DSN = os.environ.get("DATABASE_URL", "postgresql://wallet:wallet@localhost:5433/walletdb")
random.seed(42)

CHAINS = {1: "Ethereum", 56: "BNB Chain", 137: "Polygon", 42161: "Arbitrum"}
NATIVE = {1: ("ETH", 3000.0), 56: ("BNB", 600.0), 137: ("POL", 0.4), 42161: ("ETH", 3000.0)}
STABLES = [("USDT", 1.0), ("USDC", 1.0)]
EXCHANGES = {1: "Binance", 2: "OKX", 3: "Coinbase", 4: "Kraken", 5: "Bybit", 6: "KuCoin"}

N_CUSTODIAL = 40
N_NON_CUSTODIAL = 28
DAYS = 90


def hex_addr():
    return "0x" + "".join(random.choices("0123456789abcdef", k=40))


def hex_hash():
    return "0x" + "".join(random.choices("0123456789abcdef", k=64))


def pick_token(chain_id):
    if random.random() < 0.55:
        return random.choice(STABLES)
    return NATIVE[chain_id]


def make_tx(wallet_id, chain_id, to_addr, exchange_id, usd_scale, now):
    token, price = pick_token(chain_id)
    usd = round(min(random.lognormvariate(0, 1.0) * usd_scale, 250_000), 2)
    usd = max(usd, 5.0)
    # recent days a bit more likely
    age = DAYS * (random.random() ** 1.4)
    when = now - timedelta(days=age, minutes=random.randint(0, 1439))
    return (hex_hash(), chain_id, wallet_id, to_addr, exchange_id, token,
            round(usd / price, 8), usd, random.randint(18_000_000, 24_000_000), when)


def main():
    now = datetime.now(timezone.utc)
    schema = (Path(__file__).parent / "schema.sql").read_text()

    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute(schema)
        cur.executemany("INSERT INTO chains VALUES (%s, %s)", CHAINS.items())
        cur.executemany("INSERT INTO exchanges VALUES (%s, %s)", EXCHANGES.items())

        # exchange hot wallets per (chain, exchange) - demo values
        hot = {(c, e): [hex_addr(), hex_addr()] for c in CHAINS for e in EXCHANGES}
        chain_ids = list(CHAINS)
        ex_ids = list(EXCHANGES)
        # Binance + OKX are bigger
        ex_weights = [5, 4, 3, 2, 3, 1]

        wallets = []  # (chain_id, address, type)
        for _ in range(N_CUSTODIAL):
            wallets.append((random.choices(chain_ids, [4, 3, 2, 2])[0], hex_addr(), "custodial"))
        for _ in range(N_NON_CUSTODIAL):
            wallets.append((random.choices(chain_ids, [5, 2, 2, 3])[0], hex_addr(), "non_custodial"))

        wallet_rows = []
        for chain_id, addr, wtype in wallets:
            cur.execute(
                "INSERT INTO deposit_addresses (chain_id, address, wallet_type, created_at) "
                "VALUES (%s, %s, %s, %s) RETURNING wallet_id",
                (chain_id, addr, wtype, now - timedelta(days=random.randint(DAYS, DAYS + 200))),
            )
            wallet_rows.append((cur.fetchone()[0], chain_id, wtype))

        txs = []
        custodial_ids = [w for w in wallet_rows if w[2] == "custodial"]
        odd_ones = {custodial_ids[3][0], custodial_ids[17][0]}   # 2 deliberately "suspicious" custodial wallets

        for wallet_id, chain_id, wtype in wallet_rows:
            if wtype == "custodial":
                # deposit address sweeps into ONE exchange's hot wallets
                main_ex = random.choices(ex_ids, ex_weights)[0]
                for _ in range(random.randint(6, 38)):
                    to = random.choice(hot[(chain_id, main_ex)])
                    txs.append(make_tx(wallet_id, chain_id, to, main_ex, 900, now))
                if wallet_id in odd_ones:       # data-quality example: custodial but 2 exchanges
                    other = random.choice([e for e in ex_ids if e != main_ex])
                    for _ in range(random.randint(2, 4)):
                        to = random.choice(hot[(chain_id, other)])
                        txs.append(make_tx(wallet_id, chain_id, to, other, 900, now))
            else:
                # personal wallet: several exchanges + some non-exchange destinations
                chosen = random.sample(ex_ids, random.choice([1, 2, 2, 3, 3, 4]))
                for _ in range(random.randint(4, 26)):
                    if random.random() < 0.25:
                        txs.append(make_tx(wallet_id, chain_id, hex_addr(), None, 2500, now))
                    else:
                        ex = random.choice(chosen)
                        to = random.choice(hot[(chain_id, ex)])
                        txs.append(make_tx(wallet_id, chain_id, to, ex, 2500, now))

        cur.executemany(
            "INSERT INTO outgoing_txs (tx_hash, chain_id, wallet_id, to_address, exchange_id, token,"
            " amount, amount_usd, block_number, block_time) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            txs,
        )
        cur.execute("SELECT refresh_exchange_ids()")
        conn.commit()

        cur.execute("SELECT wallet_type, count(*) FROM deposit_addresses GROUP BY 1 ORDER BY 1")
        print("wallets:", cur.fetchall())
        cur.execute("SELECT count(*) FROM outgoing_txs")
        print("outgoing_txs:", cur.fetchone()[0])
        cur.execute("SELECT count(*) FROM v_wallet_summary WHERE needs_review")
        print("needs_review:", cur.fetchone()[0])


if __name__ == "__main__":
    main()
