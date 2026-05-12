-- global-gold-saas — Supabase schema
-- Run ONCE in your Supabase dashboard SQL editor.
-- Free-tier safe; no extensions or paid features required.

CREATE TABLE IF NOT EXISTS watchlist (
    id            BIGSERIAL PRIMARY KEY,
    user_email    TEXT NOT NULL,
    metal         TEXT NOT NULL CHECK (metal IN ('XAU','XAG','XPT','XPD')),
    currency      TEXT NOT NULL CHECK (char_length(currency) = 3),
    target_price  NUMERIC(14,4) NOT NULL CHECK (target_price > 0),
    direction     TEXT NOT NULL CHECK (direction IN ('above','below')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_email);

ALTER TABLE watchlist ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS watchlist_owner_select ON watchlist;
CREATE POLICY watchlist_owner_select ON watchlist
    FOR SELECT TO authenticated
    USING (auth.jwt() ->> 'email' = user_email);

DROP POLICY IF EXISTS watchlist_owner_insert ON watchlist;
CREATE POLICY watchlist_owner_insert ON watchlist
    FOR INSERT TO authenticated
    WITH CHECK (auth.jwt() ->> 'email' = user_email);

DROP POLICY IF EXISTS watchlist_owner_delete ON watchlist;
CREATE POLICY watchlist_owner_delete ON watchlist
    FOR DELETE TO authenticated
    USING (auth.jwt() ->> 'email' = user_email);

-- Recommended (audit your existing portfolio table — do not run blindly):
-- ALTER TABLE portfolio ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY portfolio_owner_select ON portfolio
--     FOR SELECT TO authenticated USING (auth.jwt() ->> 'email' = user_email);
-- CREATE POLICY portfolio_owner_insert ON portfolio
--     FOR INSERT TO authenticated WITH CHECK (auth.jwt() ->> 'email' = user_email);
-- CREATE POLICY portfolio_owner_delete ON portfolio
--     FOR DELETE TO authenticated USING (auth.jwt() ->> 'email' = user_email);
