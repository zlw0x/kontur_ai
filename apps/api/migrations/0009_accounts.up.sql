-- Accounts, sessions, and the column that says whose an order is.
--
-- Until this migration the only authentication in the service was one static
-- token, `MANUAL_API_TOKEN`, shared by everybody who had it, and the `orders`
-- table added in 0008 had no column saying who an order belonged to. Anybody
-- holding the token could read and cancel anybody else's order. That is the single
-- thing that blocked letting strangers in, and no amount of care in the handlers
-- could fix it, because the fact was simply not recorded.
--
-- Nothing here is clever. What is worth reading is why two columns are shaped the
-- way they are.

CREATE TABLE users (
    id varchar(36) PRIMARY KEY,
    -- As typed, so a greeting can use it.
    email varchar(320) NOT NULL,
    -- Case-folded, and the column uniqueness is on. `Ivan@example.com` and
    -- `ivan@example.com` are one account everywhere it matters, and letting them be
    -- two would make "this address is taken" something a user gets around by
    -- holding shift.
    email_folded varchar(320) NOT NULL UNIQUE,
    -- bcrypt, with the cost factor inside the string. Never a bare SHA-256: that is
    -- a lookup rather than a defence, and a commodity GPU runs billions of
    -- candidates a second against one.
    password_hash varchar(255) NOT NULL,
    role varchar(16) NOT NULL DEFAULT 'customer',
    -- Only `operator` and `admin` have one. A customer locked out of their own
    -- drawing by a flat phone is a bad trade; an account that can read *everybody's*
    -- drawings is a different size of accident.
    totp_secret varchar(64),
    created_at timestamptz NOT NULL,
    -- Set rather than deleted. An order points at its owner, so a deleted user would
    -- either take the order with it or leave a dangling reference.
    disabled_at timestamptz
);

CREATE INDEX IF NOT EXISTS ix_users_role ON users (role);

CREATE TABLE sessions (
    id varchar(36) PRIMARY KEY,
    user_id varchar(36) NOT NULL REFERENCES users (id),
    -- SHA-256 of what the browser holds, so a copy of this database is not a set of
    -- working credentials. A plain hash rather than bcrypt on purpose: the value is
    -- 32 random bytes, so there is no dictionary to run against it and no work
    -- factor worth paying on every single request.
    token_sha256 varchar(64) NOT NULL UNIQUE,
    -- The CSRF token, bound to the session rather than compared cookie-to-header.
    -- The naive double-submit form loses to anything that can write a cookie on a
    -- sibling subdomain: an attacker who sets both halves passes a check that only
    -- compares them to each other.
    csrf_sha256 varchar(64) NOT NULL,
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    -- Checked on every read, so signing out takes effect on the next request rather
    -- than at expiry. That requirement is the reason a session is a row at all and
    -- not a self-contained signed token, which nothing can recall.
    revoked_at timestamptz
);

CREATE INDEX IF NOT EXISTS ix_sessions_user_id ON sessions (user_id);

-- Nullable, and it will stay nullable.
--
-- Every order created before this migration has no owner and there is nothing to
-- fill it with: the service did not record who uploaded them because it had no
-- idea. A backfill would have to invent an answer, and handing those orders to
-- whoever asks first is not an invention but a giveaway. So they are readable by an
-- operator, who can already see everything, and by nobody else — which is a rule in
-- `app.accounts.principal.may_see_order`, in one place, rather than a condition
-- repeated in every handler.
ALTER TABLE orders ADD COLUMN owner_id varchar(36) REFERENCES users (id);

CREATE INDEX IF NOT EXISTS ix_orders_owner_id ON orders (owner_id);
