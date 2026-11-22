CREATE TABLE public.purchase_requests (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES public.users(id),
    goal_id text NOT NULL CHECK (char_length(goal_id) BETWEEN 1 AND 100),
    price numeric(10, 2) NOT NULL CHECK (price > 0),
    currency text NOT NULL CHECK (currency = 'EGP'),
    status text NOT NULL DEFAULT 'pending',
    checkout_url text CHECK (checkout_url ~ '^https://paymob[.]link/[A-Za-z0-9]{1,64}$'),
    payment_reference text CHECK (payment_reference ~ '^[1-9][0-9]{0,19}$'),
    requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (
        (status = 'pending' AND checkout_url IS NULL AND payment_reference IS NULL)
        OR (status = 'link-ready' AND checkout_url IS NOT NULL AND payment_reference IS NULL)
        OR (status = 'confirmed' AND checkout_url IS NOT NULL AND payment_reference IS NOT NULL)
        OR (status = 'closed' AND payment_reference IS NULL)
    )
);

CREATE UNIQUE INDEX purchase_requests_open_goal ON public.purchase_requests(user_id, goal_id)
    WHERE status IN ('pending', 'link-ready');
CREATE UNIQUE INDEX purchase_requests_checkout_url ON public.purchase_requests(checkout_url)
    WHERE checkout_url IS NOT NULL;
CREATE UNIQUE INDEX purchase_requests_payment_reference ON public.purchase_requests(payment_reference)
    WHERE payment_reference IS NOT NULL;
CREATE INDEX purchase_requests_owner ON public.purchase_requests(user_id, requested_at DESC, id DESC);
CREATE INDEX purchase_requests_queue ON public.purchase_requests(requested_at, id)
    WHERE status IN ('pending', 'link-ready');

REVOKE ALL ON public.purchase_requests FROM PUBLIC;
