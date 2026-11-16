CREATE TABLE public.code_lab_drafts (
    user_id uuid NOT NULL REFERENCES public.users(id),
    release_id text NOT NULL REFERENCES public.content_releases(release_id),
    exercise_id text NOT NULL CHECK (char_length(exercise_id) BETWEEN 1 AND 100),
    code text NOT NULL CHECK (octet_length(code) <= 16384),
    version integer NOT NULL CHECK (version > 0),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, release_id, exercise_id)
);

CREATE TABLE public.code_lab_runs (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES public.users(id),
    release_id text NOT NULL REFERENCES public.content_releases(release_id),
    lesson_id text NOT NULL CHECK (char_length(lesson_id) BETWEEN 1 AND 100),
    exercise_id text NOT NULL CHECK (char_length(exercise_id) BETWEEN 1 AND 100),
    exercise_version text NOT NULL CHECK (exercise_version ~ '^[0-9a-f]{64}$'),
    skill_id text NOT NULL CHECK (char_length(skill_id) BETWEEN 1 AND 100),
    language text NOT NULL CHECK (language IN ('python', 'javascript')),
    code text NOT NULL CHECK (octet_length(code) BETWEEN 1 AND 16384),
    stdin text NOT NULL CHECK (octet_length(stdin) <= 4096),
    mode text NOT NULL CHECK (mode IN ('run', 'assess')),
    test_cases jsonb NOT NULL CHECK (jsonb_typeof(test_cases) = 'array' AND octet_length(test_cases::text) <= 32768),
    idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 128),
    payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    status text NOT NULL DEFAULT 'queued' CHECK (status IN
        ('queued', 'running', 'completed', 'timed_out', 'output_limit', 'code_error', 'infrastructure_error')),
    verdict text NOT NULL DEFAULT 'not_evaluated' CHECK (verdict IN ('not_evaluated', 'passed', 'needs_work')),
    stdout text NOT NULL DEFAULT '',
    stderr text NOT NULL DEFAULT '',
    passed_cases integer,
    total_cases integer,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL DEFAULT (now() + interval '2 minutes'),
    completed_at timestamptz,
    UNIQUE (user_id, idempotency_key),
    UNIQUE (id, user_id, release_id, lesson_id, exercise_id, exercise_version, skill_id, verdict),
    CHECK (octet_length(stdout) + octet_length(stderr) <= 16384),
    CHECK ((mode = 'run' AND test_cases = '[]'::jsonb)
        OR (mode = 'assess' AND jsonb_array_length(test_cases) BETWEEN 1 AND 4 AND stdin = '' AND stdout = '' AND stderr = '')),
    CHECK ((status IN ('queued', 'running')) = (completed_at IS NULL)),
    CHECK (
        (verdict = 'not_evaluated' AND passed_cases IS NULL AND total_cases IS NULL
            AND (mode = 'run' OR status <> 'completed'))
        OR (mode = 'assess' AND status = 'completed' AND passed_cases IS NOT NULL
            AND total_cases = jsonb_array_length(test_cases) AND total_cases IS NOT NULL
            AND passed_cases BETWEEN 0 AND total_cases AND ((verdict = 'passed' AND passed_cases = total_cases)
                OR (verdict = 'needs_work' AND passed_cases < total_cases)))
    )
);

CREATE INDEX code_lab_active_runs_idx ON public.code_lab_runs (status, created_at)
    WHERE status IN ('queued', 'running');
CREATE INDEX code_lab_owner_rate_idx ON public.code_lab_runs (user_id, created_at DESC);

CREATE FUNCTION public.guard_code_lab_run() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF ROW(NEW.id, NEW.user_id, NEW.release_id, NEW.lesson_id, NEW.exercise_id, NEW.exercise_version,
           NEW.skill_id, NEW.language, NEW.code, NEW.stdin, NEW.mode, NEW.test_cases,
           NEW.idempotency_key, NEW.payload_hash, NEW.created_at)
       IS DISTINCT FROM
       ROW(OLD.id, OLD.user_id, OLD.release_id, OLD.lesson_id, OLD.exercise_id, OLD.exercise_version,
           OLD.skill_id, OLD.language, OLD.code, OLD.stdin, OLD.mode, OLD.test_cases,
           OLD.idempotency_key, OLD.payload_hash, OLD.created_at) THEN
        RAISE EXCEPTION 'Code lab submission snapshots are immutable';
    END IF;
    IF NOT ((OLD.status = 'queued' AND NEW.status IN ('running', 'infrastructure_error'))
        OR (OLD.status = 'running' AND NEW.status NOT IN ('queued', 'running'))) THEN
        RAISE EXCEPTION 'Invalid code lab run transition';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER guard_code_lab_run BEFORE UPDATE ON public.code_lab_runs
    FOR EACH ROW EXECUTE FUNCTION public.guard_code_lab_run();

CREATE TABLE public.code_lab_evidence (
    user_id uuid NOT NULL,
    release_id text NOT NULL,
    lesson_id text NOT NULL,
    exercise_id text NOT NULL,
    exercise_version text NOT NULL,
    skill_id text NOT NULL,
    run_id uuid NOT NULL UNIQUE,
    verdict text NOT NULL DEFAULT 'passed' CHECK (verdict = 'passed'),
    awarded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, release_id, exercise_id),
    FOREIGN KEY (run_id, user_id, release_id, lesson_id, exercise_id, exercise_version, skill_id, verdict)
        REFERENCES public.code_lab_runs (id, user_id, release_id, lesson_id, exercise_id, exercise_version, skill_id, verdict)
);

REVOKE ALL ON public.code_lab_drafts, public.code_lab_runs, public.code_lab_evidence FROM PUBLIC;
REVOKE ALL ON FUNCTION public.guard_code_lab_run() FROM PUBLIC;
