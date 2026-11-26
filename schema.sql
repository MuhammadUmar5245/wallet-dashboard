-- Wallet / Exchange attribution schema (PostgreSQL 14+)
-- Option 2: exchange_ids SMALLINT[] array column (an address can map to many exchanges)

DROP VIEW  IF EXISTS v_wallet_summary;
DROP TABLE IF EXISTS outgoing_txs, deposit_addresses, exchanges, chains CASCADE;

-- ---------- Lookup tables ----------
CREATE TABLE chains (
    chain_id INT  PRIMARY KEY,               -- 1 = Ethereum, 56 = BSC ...
    name     TEXT NOT NULL UNIQUE
);

CREATE TABLE exchanges (
    exchange_id SMALLINT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE
);

-- ---------- Table 1: wallets (custodial + non-custodial) ----------
CREATE TABLE deposit_addresses (
    wallet_id    BIGSERIAL PRIMARY KEY,
    chain_id     INT  NOT NULL REFERENCES chains,
    address      TEXT NOT NULL CHECK (address = lower(address)),   -- always lowercase
    wallet_type  TEXT NOT NULL CHECK (wallet_type IN ('custodial', 'non_custodial')),
    exchange_ids SMALLINT[] NOT NULL DEFAULT '{}',                 -- derived from outgoing_txs
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (chain_id, address)
);
CREATE INDEX idx_wallet_exchange_ids ON deposit_addresses USING GIN (exchange_ids);
CREATE INDEX idx_wallet_type         ON deposit_addresses (wallet_type);

-- ---------- Table 2: outgoing transactions ----------
CREATE TABLE outgoing_txs (
    tx_id        BIGSERIAL PRIMARY KEY,
    tx_hash      TEXT        NOT NULL,
    chain_id     INT         NOT NULL REFERENCES chains,
    wallet_id    BIGINT      NOT NULL REFERENCES deposit_addresses,
    to_address   TEXT        NOT NULL,
    exchange_id  SMALLINT    REFERENCES exchanges,   -- NULL = destination is not a known exchange
    token        TEXT        NOT NULL,
    amount       NUMERIC(38, 8) NOT NULL,            -- production: store raw NUMERIC(78,0)
    amount_usd   NUMERIC(18, 2) NOT NULL,
    block_number BIGINT,
    block_time   TIMESTAMPTZ NOT NULL,
    UNIQUE (chain_id, tx_hash)
);
CREATE INDEX idx_tx_wallet_time ON outgoing_txs (wallet_id, block_time DESC);
CREATE INDEX idx_tx_exchange    ON outgoing_txs (exchange_id, block_time DESC) WHERE exchange_id IS NOT NULL;
CREATE INDEX idx_tx_time        ON outgoing_txs (block_time);

-- ---------- Refresh the array from the transactions ----------
-- Array elements can't carry a FOREIGN KEY, so we never write them by hand:
-- they are always rebuilt from outgoing_txs.exchange_id, which IS foreign-keyed.
CREATE OR REPLACE FUNCTION refresh_exchange_ids() RETURNS void
LANGUAGE sql AS $$
    UPDATE deposit_addresses w
    SET exchange_ids = COALESCE((
        SELECT array_agg(DISTINCT t.exchange_id ORDER BY t.exchange_id)
        FROM outgoing_txs t
        WHERE t.wallet_id = w.wallet_id AND t.exchange_id IS NOT NULL
    ), '{}');
$$;

-- ---------- Handy summary view ----------
CREATE VIEW v_wallet_summary AS
SELECT w.wallet_id,
       w.chain_id,
       c.name                                   AS chain,
       w.address,
       w.wallet_type,
       w.exchange_ids,
       COALESCE((SELECT array_agg(e.name ORDER BY e.name)
                 FROM exchanges e WHERE e.exchange_id = ANY (w.exchange_ids)), '{}') AS exchange_names,
       cardinality(w.exchange_ids)              AS exchange_count,
       -- custodial wallet that sends to >1 exchange = suspicious, needs a manual look
       (w.wallet_type = 'custodial' AND cardinality(w.exchange_ids) > 1) AS needs_review,
       COALESCE(s.tx_count, 0)                  AS tx_count,
       COALESCE(s.volume_usd, 0)                AS volume_usd,
       s.first_tx,
       s.last_tx
FROM deposit_addresses w
JOIN chains c ON c.chain_id = w.chain_id
LEFT JOIN (
    SELECT wallet_id, count(*) AS tx_count, sum(amount_usd) AS volume_usd,
           min(block_time) AS first_tx, max(block_time) AS last_tx
    FROM outgoing_txs GROUP BY wallet_id
) s ON s.wallet_id = w.wallet_id;
