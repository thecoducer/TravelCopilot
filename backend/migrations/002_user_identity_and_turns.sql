-- Migration 002: Username identity, session history, and chat turns
-- Run via: make migrate
--
-- Adds a lightweight (auth-free) username identity so the frontend can show a
-- ChatGPT-style sidebar of a user's past sessions and persist preferences
-- across sessions.
--
--   users          -> one row per username (no auth, no password)
--   trips          -> gains username, title, deleted_at (soft delete)
--   chat_turns     -> ordered prompt/response history per session
--   user_profiles  -> gains username so preferences survive new sessions

BEGIN;

-- users: bare username identity, no credentials.
CREATE TABLE IF NOT EXISTS users (
    username   TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Self-heal a pre-existing/partial users table (e.g. an older schema that lacks
-- the username column) so INSERT ... ON CONFLICT (username) always resolves.
ALTER TABLE users ADD COLUMN IF NOT EXISTS username   TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Guarantee a unique key on username so ON CONFLICT (username) can infer it even
-- when username was added to an existing table without a primary key.
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users (username);

-- trips: associate with a username, give each session a display title, and
-- support reversible deletion from the sidebar.
ALTER TABLE trips ADD COLUMN IF NOT EXISTS username   TEXT;
ALTER TABLE trips ADD COLUMN IF NOT EXISTS title      TEXT;
ALTER TABLE trips ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_trips_username_created
    ON trips (username, created_at DESC)
    WHERE deleted_at IS NULL;

-- chat_turns: ordered conversation history for a session.
CREATE TABLE IF NOT EXISTS chat_turns (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL,
    username   TEXT,
    turn_index INT  NOT NULL,
    role       TEXT NOT NULL,              -- 'user' | 'assistant'
    content    TEXT NOT NULL,
    trip_id    UUID,                       -- itinerary produced by this turn, if any
    intent     TEXT,                       -- classified follow-up intent, if any
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chat_turns_session
    ON chat_turns (session_id, turn_index);

-- user_profiles: add a username so a profile can be looked up independently of
-- the session it was first created in.  session_id stays as the primary key for
-- backward compatibility.
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS username TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_profiles_username
    ON user_profiles (username)
    WHERE username IS NOT NULL;

-- Keep updated_at fresh on the new users table too.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_users_updated_at'
    ) THEN
        CREATE TRIGGER trg_users_updated_at
            BEFORE UPDATE ON users
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END;
$$;

COMMIT;
