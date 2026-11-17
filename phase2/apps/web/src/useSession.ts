import { useCallback, useEffect, useRef, useState } from 'react';
import { applicationPath, errorText, SESSION_INVALIDATED, verifySession, type SessionScope } from './api';
import type { DraftState, User } from './types';

type Session = {
  user: User | null;
  scope: SessionScope;
  generation: number;
  drafts: Map<string, DraftState>;
};

export function useSession() {
  const [session, setSession] = useState<Session | null>(null);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState('');
  const previous = useRef<{ session: Session; controller: AbortController } | null>(null);
  const pending = useRef<{ controller: AbortController; promise: Promise<Session | null> } | null>(null);
  const channel = useRef<BroadcastChannel | null>(null);

  const refresh = useCallback((restart = false) => {
    if (pending.current && !restart) return pending.current.promise;
    pending.current?.controller.abort();
    const controller = new AbortController();
    const last = previous.current;
    const background = !restart && last && !last.controller.signal.aborted;
    if (!background) {
      last?.controller.abort();
      setChecking(true);
      setSession(null);
    }
    setError('');

    const promise = verifySession(controller.signal).then(user => {
      controller.signal.throwIfAborted();
      const userId = user?.id ?? null;
      if (background && last.session.scope.userId === userId) {
        const verified = { ...last.session, user };
        previous.current = { ...last, session: verified };
        setSession(verified);
        return verified;
      }
      last?.controller.abort();
      const verified: Session = {
        user,
        scope: { userId, signal: controller.signal },
        generation: (last?.session.generation ?? 0) + 1,
        drafts: last?.session.scope.userId === userId ? last.session.drafts : new Map(),
      };
      previous.current = { session: verified, controller };
      setSession(verified);
      return verified;
    }).catch(cause => {
      if (!controller.signal.aborted) {
        last?.controller.abort();
        setSession(null);
        setError(errorText(cause));
      }
      return null;
    }).finally(() => {
      if (pending.current?.controller === controller) {
        pending.current = null;
        setChecking(false);
      }
    });
    pending.current = { controller, promise };
    return promise;
  }, []);

  useEffect(() => {
    if ('BroadcastChannel' in window) {
      const commercialMount = applicationPath('/') === '/nexora-commercial/';
      channel.current = new BroadcastChannel(commercialMount ? 'masar-session-commercial' : 'masar-session');
      channel.current.onmessage = event => { if (event.data === 'changed') void refresh(true); };
    }
    const focus = () => { void refresh(); };
    const visible = () => { if (document.visibilityState === 'visible') focus(); };
    const invalidated = () => { void refresh(true); };
    window.addEventListener('focus', focus);
    window.addEventListener('pageshow', focus);
    document.addEventListener('visibilitychange', visible);
    window.addEventListener(SESSION_INVALIDATED, invalidated);
    void refresh();
    return () => {
      window.removeEventListener('focus', focus);
      window.removeEventListener('pageshow', focus);
      document.removeEventListener('visibilitychange', visible);
      window.removeEventListener(SESSION_INVALIDATED, invalidated);
      channel.current?.close();
      channel.current = null;
      const current = pending.current;
      pending.current = null;
      current?.controller.abort();
      previous.current?.controller.abort();
    };
  }, [refresh]);

  function authenticationChanged() {
    channel.current?.postMessage('changed');
    return refresh(true);
  }

  const hasUnsavedDrafts = useCallback(() => {
    return [...(previous.current?.session.drafts.values() ?? [])].some(draft => draft.dirty);
  }, []);

  return { session, checking, error, refresh, authenticationChanged, hasUnsavedDrafts };
}
