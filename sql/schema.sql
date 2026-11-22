-- Run once in Supabase: Dashboard -> SQL Editor -> New query.

CREATE TABLE IF NOT EXISTS public.users (
    id         TEXT PRIMARY KEY,
    email      TEXT UNIQUE NOT NULL,
    name       TEXT NOT NULL,
    picture    TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.chat_sessions (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    title      TEXT NOT NULL DEFAULT 'New Chat',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.chat_messages (
    id             TEXT PRIMARY KEY,
    session_id     TEXT NOT NULL REFERENCES public.chat_sessions(id) ON DELETE CASCADE,
    role           TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content        TEXT NOT NULL,
    source_context TEXT DEFAULT '',
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.user_documents (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    file_name   TEXT NOT NULL,
    file_size   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'processing' CHECK (status IN ('processing', 'indexed', 'failed')),
    chunk_count INTEGER DEFAULT 0,
    upload_date TIMESTAMPTZ DEFAULT NOW(),
    session_id  TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id     ON public.chat_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id  ON public.chat_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_user_documents_user_id    ON public.user_documents(user_id);

-- Existing database from the old version? Uploads are no longer stored on disk, so drop the column:
-- ALTER TABLE public.user_documents DROP COLUMN IF EXISTS file_path;
