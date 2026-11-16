import type { Draft, DraftState } from './types';

export function receiveServerDraft(current: DraftState, remote: Draft): DraftState {
  if (current.dirty) return { ...current, loaded: true, ...(current.version !== remote.version ? { remote } : {}) };
  return { ...current, ...remote, loaded: true, dirty: false };
}

export function acknowledgeDraftSave(current: DraftState, submitted: string, saved: Draft): DraftState {
  return { ...current, version: saved.version, remote: undefined, dirty: current.answer !== submitted };
}

export function attemptKey(current: DraftState, signature: string, createKey: () => string = () => crypto.randomUUID()): string {
  return current.attempt?.signature === signature ? current.attempt.key : createKey();
}
