-- =====================================================================
--  CTPB Bank — schema for PostgreSQL database `CTPBD`
--  All statements are idempotent (IF NOT EXISTS) so the app can ensure
--  the schema at startup without a separate migration tool.
-- =====================================================================

CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    username      VARCHAR(40)  NOT NULL UNIQUE,
    full_name     VARCHAR(120) NOT NULL,
    email         VARCHAR(160) NOT NULL UNIQUE,
    password_hash TEXT         NOT NULL,
    role          VARCHAR(10)  NOT NULL DEFAULT 'user'
                  CHECK (role IN ('user', 'admin')),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS accounts (
    id             BIGSERIAL PRIMARY KEY,
    account_number VARCHAR(12) NOT NULL UNIQUE,
    user_id        BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_type   VARCHAR(10) NOT NULL
                   CHECK (account_type IN ('savings', 'current')),
    balance        NUMERIC(14, 2) NOT NULL DEFAULT 0
                   CHECK (balance >= -50000),   -- hard floor = current-account overdraft
    status         VARCHAR(10) NOT NULL DEFAULT 'active'
                   CHECK (status IN ('active', 'frozen')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- A customer may hold at most one savings and one current account.
    UNIQUE (user_id, account_type)
);

CREATE TABLE IF NOT EXISTS transactions (
    id                    BIGSERIAL PRIMARY KEY,
    txn_ref               VARCHAR(24) NOT NULL UNIQUE,
    idempotency_key       VARCHAR(64) UNIQUE,           -- dedupes double-submits / retries
    from_account_id       BIGINT REFERENCES accounts(id),
    to_account_id         BIGINT REFERENCES accounts(id),
    amount                NUMERIC(14, 2) NOT NULL CHECK (amount > 0),
    txn_type              VARCHAR(10)  NOT NULL
                          CHECK (txn_type IN ('transfer', 'deposit', 'withdrawal', 'interest')),
    status                VARCHAR(10)  NOT NULL DEFAULT 'success'
                          CHECK (status IN ('success', 'flagged', 'failed')),
    note                  TEXT,
    sender_balance_after   NUMERIC(14, 2),
    receiver_balance_after NUMERIC(14, 2),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes: the queries we actually run (see README complexity table).
CREATE INDEX IF NOT EXISTS idx_accounts_user      ON accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_accounts_number    ON accounts(account_number);
CREATE INDEX IF NOT EXISTS idx_txn_from           ON transactions(from_account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_txn_to             ON transactions(to_account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_txn_created        ON transactions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_txn_flagged        ON transactions(status) WHERE status = 'flagged';
