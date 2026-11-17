CREATE TABLE public.commercial_scope_access (
    user_id uuid NOT NULL REFERENCES public.users(id),
    scope_type text NOT NULL CHECK (scope_type IN ('goal', 'lesson')),
    scope_id text NOT NULL CHECK (char_length(scope_id) BETWEEN 1 AND 100),
    PRIMARY KEY (user_id, scope_type, scope_id)
);
REVOKE ALL ON public.commercial_scope_access FROM PUBLIC;

CREATE TABLE public.commercial_offers (
    goal_id text PRIMARY KEY CHECK (char_length(goal_id) BETWEEN 1 AND 100),
    price numeric(10, 2) NOT NULL CHECK (price >= 0 AND price <= 99999999.99),
    currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$')
);
REVOKE ALL ON public.commercial_offers FROM PUBLIC;
