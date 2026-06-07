import React from 'react';
import type { OntologyProfile } from '@/hooks/use-ontology';
import { cloneProfile } from './ontology-ui';

export type DraftHistoryEntry = { profile: OntologyProfile; label: string; timestamp: number };

export function useOntologyDraftController(sourceProfile: OntologyProfile | null) {
  const [draft, setDraftState] = React.useState<OntologyProfile | null>(() => sourceProfile ? cloneProfile(sourceProfile) : null);
  const [undoStack, setUndoStack] = React.useState<DraftHistoryEntry[]>([]);
  const [redoStack, setRedoStack] = React.useState<DraftHistoryEntry[]>([]);

  const clearHistory = React.useCallback(() => {
    setUndoStack([]);
    setRedoStack([]);
  }, []);

  const resetDraft = React.useCallback((next: OntologyProfile | null) => {
    setDraftState(next ? cloneProfile(next) : null);
    clearHistory();
  }, [clearHistory]);

  React.useEffect(() => {
    resetDraft(sourceProfile);
  }, [sourceProfile, resetDraft]);

  const setDraft = React.useCallback((next: OntologyProfile | null) => {
    setDraftState(next ? cloneProfile(next) : null);
  }, []);

  const commitDraft = React.useCallback((next: OntologyProfile | null, label = 'Draft edit') => {
    setDraftState((current) => {
      if (!current || !next) return next ? cloneProfile(next) : next;
      if (JSON.stringify(current) === JSON.stringify(next)) return current;
      setUndoStack((stack) => [...stack.slice(-19), { profile: cloneProfile(current), label, timestamp: Date.now() }]);
      setRedoStack([]);
      return cloneProfile(next);
    });
  }, []);

  const handleUndoDraft = React.useCallback(() => {
    setDraftState((current) => {
      if (!current || undoStack.length === 0) return current;
      const previous = undoStack[undoStack.length - 1];
      setUndoStack((stack) => stack.slice(0, -1));
      setRedoStack((stack) => [...stack.slice(-19), { profile: cloneProfile(current), label: 'Redo draft edit', timestamp: Date.now() }]);
      return cloneProfile(previous.profile);
    });
  }, [undoStack]);

  const handleRedoDraft = React.useCallback(() => {
    setDraftState((current) => {
      if (!current || redoStack.length === 0) return current;
      const next = redoStack[redoStack.length - 1];
      setRedoStack((stack) => stack.slice(0, -1));
      setUndoStack((stack) => [...stack.slice(-19), { profile: cloneProfile(current), label: 'Undo draft edit', timestamp: Date.now() }]);
      return cloneProfile(next.profile);
    });
  }, [redoStack]);

  return { draft, setDraft, resetDraft, commitDraft, undoStack, redoStack, handleUndoDraft, handleRedoDraft, clearHistory };
}
