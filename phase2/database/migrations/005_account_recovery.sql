-- A recovery code is a 256-bit random bearer secret. Only its SHA-256 digest is stored.
-- Each account has at most one active code; issuing a replacement invalidates the old code.
CREATE TABLE public.account_recovery_codes (
    user_id uuid PRIMARY KEY REFERENCES public.users(id),
    code_hash text NOT NULL CHECK (code_hash ~ '^[0-9a-f]{64}$'),
    issued_by uuid NOT NULL REFERENCES public.users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    CHECK (expires_at IS NULL OR expires_at > created_at)
);
REVOKE ALL ON public.account_recovery_codes FROM PUBLIC;
-- Reapply the environment's explicit runtime DML grant after migrating an existing installation.
