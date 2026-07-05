-- Migration 001: Initial schema
-- Run via: make migrate
--
-- Schema is the source of truth for the FastAPI routers:
--   app/routers/user.py  -> user_profiles(session_id, profile_json)
--   app/routers/trip.py  -> trips(id, session_id, slug, public, query,
--                                 is_international, itinerary_json,
--                                 reality_score, token_usage_json)

BEGIN;

-- user_profiles: one row per session, full UserProfile stored as JSON.
-- Keyed by session_id to match PUT/GET /api/user/profile (X-Session-ID header).
CREATE TABLE IF NOT EXISTS user_profiles (
    session_id   TEXT PRIMARY KEY,               -- client session UUID
    profile_json JSONB NOT NULL,                 -- serialised UserProfile model
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- trips: one row per generated itinerary.
-- Multiple trips may share a session_id (latest wins on GET by session).
CREATE TABLE IF NOT EXISTS trips (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id       TEXT NOT NULL,              -- client session UUID
    slug             VARCHAR(80) UNIQUE,         -- public share slug (nullable)
    public           BOOLEAN NOT NULL DEFAULT FALSE,
    query            TEXT,                       -- original free-text query
    is_international  BOOLEAN NOT NULL DEFAULT FALSE,
    itinerary_json   JSONB,                      -- serialised Itinerary model
    reality_score    INT,                        -- derived from crowd_level (0-100)
    token_usage_json JSONB NOT NULL DEFAULT '{}',-- per-agent AgentTokenUsage
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_trips_session_id ON trips (session_id);
CREATE INDEX IF NOT EXISTS idx_trips_created_at ON trips (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trips_public     ON trips (public) WHERE public = TRUE;
CREATE INDEX IF NOT EXISTS idx_trips_slug       ON trips (slug)   WHERE slug IS NOT NULL;

-- Auto-update updated_at on row change
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_user_profiles_updated_at'
    ) THEN
        CREATE TRIGGER trg_user_profiles_updated_at
            BEFORE UPDATE ON user_profiles
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_trips_updated_at'
    ) THEN
        CREATE TRIGGER trg_trips_updated_at
            BEFORE UPDATE ON trips
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END;
$$;

COMMIT;
