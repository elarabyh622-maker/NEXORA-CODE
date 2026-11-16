-- Manual entitlement only. Payment verification and payment details remain external.
CREATE TABLE public.commercial_access (
    user_id uuid PRIMARY KEY REFERENCES public.users(id),
    active boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now()
);
REVOKE ALL ON public.commercial_access FROM PUBLIC;

CREATE INDEX code_lab_runs_created_at ON public.code_lab_runs(created_at);
