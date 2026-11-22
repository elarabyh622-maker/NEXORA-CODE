CREATE TABLE public.access_cancellations (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES public.users(id),
    status text NOT NULL CHECK (status IN ('pending','approved','declined')),
    requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    resolved_at timestamptz,
    resolved_by uuid REFERENCES public.users(id),
    CHECK ((status = 'pending' AND resolved_at IS NULL AND resolved_by IS NULL) OR
           (status <> 'pending' AND resolved_at IS NOT NULL AND resolved_by IS NOT NULL))
);
CREATE UNIQUE INDEX access_cancellations_user_pending ON public.access_cancellations(user_id) WHERE status = 'pending';
CREATE INDEX access_cancellations_history ON public.access_cancellations(user_id,requested_at DESC,id DESC);
CREATE INDEX access_cancellations_queue ON public.access_cancellations(requested_at,id) WHERE status = 'pending';
REVOKE ALL ON public.access_cancellations FROM PUBLIC;
