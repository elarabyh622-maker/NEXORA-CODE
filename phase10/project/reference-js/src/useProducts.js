import { useEffect, useState } from 'react';

export function useProducts(api, filters, revision) {
  const [state, setState] = useState({ status: 'loading' });
  const { q, category } = filters;

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: 'loading' });
    api.list({ q, category }, controller.signal).then(products => {
      if (!controller.signal.aborted) setState({ status: 'success', products });
    }).catch((error) => {
      if (!controller.signal.aborted) {
        setState({ status: 'error', message: error instanceof Error ? error.message : 'تعذّر تحميل المنتجات.' });
      }
    });
    return () => controller.abort();
  }, [api, q, category, revision]);

  return state;
}
