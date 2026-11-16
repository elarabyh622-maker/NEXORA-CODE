CREATE SCHEMA IF NOT EXISTS public;

CREATE TABLE public.users (
    id uuid PRIMARY KEY,
    user_name text NOT NULL,
    normalized_user_name text NOT NULL UNIQUE,
    display_name text NOT NULL,
    password_hash text NOT NULL,
    role text NOT NULL DEFAULT 'Learner' CHECK (role IN ('Learner','Author','Reviewer','Admin')),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (char_length(user_name) BETWEEN 3 AND 40),
    CHECK (char_length(display_name) BETWEEN 2 AND 80)
);
CREATE TABLE public.sessions (
    token_hash text PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES public.users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    CHECK (expires_at > created_at)
);
CREATE INDEX sessions_user_idx ON public.sessions(user_id);
CREATE INDEX sessions_expiry_idx ON public.sessions(expires_at);
CREATE TABLE public.login_failures (
    key_hash text PRIMARY KEY,
    failures integer NOT NULL DEFAULT 0 CHECK (failures >= 0),
    window_started_at timestamptz NOT NULL DEFAULT now(),
    blocked_until timestamptz
);
CREATE TABLE public.content_releases (
    id uuid PRIMARY KEY,
    release_id text NOT NULL UNIQUE CHECK (char_length(release_id) BETWEEN 1 AND 100),
    title text NOT NULL,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','technical_review','learning_review','published','retired')),
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    bundle jsonb NOT NULL CHECK (jsonb_typeof(bundle) = 'object'),
    created_by uuid REFERENCES public.users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz
);
CREATE TABLE public.settings (
    key text PRIMARY KEY,
    value text NOT NULL
);
CREATE TABLE public.learning_plans (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES public.users(id),
    revision integer NOT NULL CHECK (revision > 0),
    release_id text NOT NULL REFERENCES public.content_releases(release_id),
    goal_id text NOT NULL,
    status text NOT NULL,
    plan jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(user_id,revision)
);
CREATE INDEX plans_user_latest_idx ON public.learning_plans(user_id,revision DESC);
CREATE TABLE public.attempts (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES public.users(id),
    release_id text NOT NULL REFERENCES public.content_releases(release_id),
    lesson_id text NOT NULL,
    exercise_id text NOT NULL,
    answer text NOT NULL CHECK (char_length(answer) <= 4096),
    hints_used integer NOT NULL CHECK (hints_used >= 0),
    correct boolean NOT NULL,
    assisted boolean NOT NULL,
    explanation text NOT NULL,
    idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 128),
    payload_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(user_id,idempotency_key)
);
CREATE INDEX attempts_progress_idx ON public.attempts(user_id,release_id,exercise_id);
CREATE TABLE public.drafts (
    user_id uuid NOT NULL REFERENCES public.users(id),
    release_id text NOT NULL REFERENCES public.content_releases(release_id),
    exercise_id text NOT NULL,
    answer text NOT NULL CHECK (char_length(answer) <= 4096),
    version integer NOT NULL CHECK (version > 0),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(user_id,release_id,exercise_id)
);
CREATE TABLE public.audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_id uuid REFERENCES public.users(id),
    action text NOT NULL,
    resource_id text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Content is immutable even while in draft: revisions use a new release identifier.
CREATE FUNCTION public.reject_bundle_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.bundle IS DISTINCT FROM OLD.bundle OR NEW.release_id IS DISTINCT FROM OLD.release_id
       OR NEW.title IS DISTINCT FROM OLD.title THEN
        RAISE EXCEPTION 'Content releases are immutable';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER immutable_release BEFORE UPDATE ON public.content_releases
    FOR EACH ROW EXECUTE FUNCTION public.reject_bundle_mutation();

-- The migration owner grants the separate runtime login DML privileges after migration.
-- No role names, passwords, superuser grants or database creation belong in migrations.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;
