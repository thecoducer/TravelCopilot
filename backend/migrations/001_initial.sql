-- Migration 001: Initial schema
-- Run via: make migrate

BEGIN;

-- user_profiles: stores traveller preferences persisted across trips
CREATE TABLE IF NOT EXISTS user_profiles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         TEXT NOT NULL UNIQUE,           -- external auth identifier
    display_name    TEXT,
    home_city       TEXT,
    nationality     TEXT,
    passport_country TEXT,
    preferred_currency TEXT DEFAULT 'INR',
    dietary_restrictions TEXT[],
    accessibility_needs TEXT[],
    preferred_airlines TEXT[],
    preferred_hotel_chains TEXT[],
    loyalty_programs JSONB DEFAULT '{}',            -- {"airline": "program_id"}
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_profiles_user_id ON user_profiles (user_id);

-- trips: one row per planning session / trip
CREATE TABLE IF NOT EXISTS trips (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         TEXT NOT NULL REFERENCES user_profiles (user_id) ON DELETE CASCADE,
    session_id      TEXT NOT NULL UNIQUE,           -- LangGraph session / Redis key
    status          TEXT NOT NULL DEFAULT 'planning'
                        CHECK (status IN ('planning','confirmed','completed','cancelled')),
    origin          TEXT,
    destination     TEXT,
    departure_date  DATE,
    return_date     DATE,
    num_travelers   INT DEFAULT 1,
    trip_type       TEXT DEFAULT 'international'
                        CHECK (trip_type IN ('domestic','international')),
    budget_inr      NUMERIC(14,2),
    itinerary       JSONB,                          -- serialised Itinerary model
    state_snapshot  JSONB,                          -- latest TripState for resumption
    token_usage     JSONB DEFAULT '{}',             -- AgentTokenUsage per agent
    llm_spend_usd   NUMERIC(8,6) DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_trips_user_id    ON trips (user_id);
CREATE INDEX IF NOT EXISTS idx_trips_session_id ON trips (session_id);
CREATE INDEX IF NOT EXISTS idx_trips_status     ON trips (status);
CREATE INDEX IF NOT EXISTS idx_trips_created_at ON trips (created_at DESC);

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
