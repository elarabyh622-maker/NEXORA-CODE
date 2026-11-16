import { useEffect, useRef, useState } from 'react';
import { ApiError, errorText, request, type SessionScope } from './api';

export function useResource<T>(path: string | null, revision = 0, optional404 = false, scope?: SessionScope) {
  const [state, setState] = useState<{ data: T | null; error: string; loading: boolean }>({ data: null, error: '', loading: !!path });
  const [retry, setRetry] = useState(0);
  const key = `${path}|${revision}|${retry}`;
  const previousKey = useRef(key);
  const changed = previousKey.current !== key;
  useEffect(() => {
    previousKey.current = key;
    const controller = new AbortController();
    setState({ data: null, error: '', loading: !!path });
    if (path) request<T>(path, { scope, signal: controller.signal }).then(data => {
      if (!controller.signal.aborted && !scope?.signal.aborted) setState({ data, error: '', loading: false });
    }).catch(error => {
      if (!controller.signal.aborted && !scope?.signal.aborted) setState({ data: null, error: optional404 && error instanceof ApiError && error.status === 404 ? '' : errorText(error), loading: false });
    });
    return () => controller.abort();
  }, [path, revision, retry, optional404, key, scope]);
  return { ...(changed ? { data: null, error: '', loading: !!path } : state), reload: () => setRetry(value => value + 1) };
}
