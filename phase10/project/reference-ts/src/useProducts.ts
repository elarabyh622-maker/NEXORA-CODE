import { useEffect, useState } from 'react';
import type { Catalogue, Filters, Product } from './model.ts';

export type ListState =
  | { status: 'loading' }
  | { status: 'success'; products: Product[] }
  | { status: 'error'; message: string };

export function useProducts(api: Catalogue, filters: Filters, revision: number) {
  const [state, setState] = useState<ListState>({ status: 'loading' });
  const { q, category } = filters;

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: 'loading' });
    api.list({ q, category }, controller.signal).then(products => {
      if (!controller.signal.aborted) setState({ status: 'success', products });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) {
        setState({ status: 'error', message: error instanceof Error ? error.message : 'تعذّر تحميل المنتجات.' });
      }
    });
    return () => controller.abort();
  }, [api, q, category, revision]);

  return state;
}
