import { useCallback, useMemo, useState } from 'react';
import type { OntologyProfile, ValidationIssue } from './types';
import { cloneProfile, validateOntologyProfile } from './ontology-draft-commands';

interface HistoryEntry { profile: OntologyProfile; label: string }

export function useOntologyDraftController(sourceProfile: OntologyProfile) {
  const [draft, setDraftState] = useState(() => cloneProfile(sourceProfile));
  const [undoStack, setUndoStack] = useState<HistoryEntry[]>([]);
  const [redoStack, setRedoStack] = useState<HistoryEntry[]>([]);
  const [validationIssues, setValidationIssues] = useState<ValidationIssue[]>([]);
  const [lastDiff, setLastDiff] = useState<string>('No diff preview yet.');


  const isDirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(sourceProfile), [draft, sourceProfile]);

  const setDraft = useCallback((profile: OntologyProfile) => setDraftState(cloneProfile(profile)), []);

  const commitDraft = useCallback((next: OntologyProfile, label: string) => {
    setDraftState((current) => {
      if (JSON.stringify(current) === JSON.stringify(next)) return current;
      setUndoStack((stack) => [...stack.slice(-24), { profile: cloneProfile(current), label }]);
      setRedoStack([]);
      return cloneProfile(next);
    });
  }, []);

  const resetDraft = useCallback(() => {
    setDraftState(cloneProfile(sourceProfile));
    setUndoStack([]);
    setRedoStack([]);
    setValidationIssues([]);
  }, [sourceProfile]);

  const handleUndoDraft = useCallback(() => {
    setUndoStack((stack) => {
      const previous = stack.at(-1);
      if (!previous) return stack;
      setRedoStack((redo) => [...redo, { profile: cloneProfile(draft), label: 'redo' }]);
      setDraftState(cloneProfile(previous.profile));
      return stack.slice(0, -1);
    });
  }, [draft]);

  const handleRedoDraft = useCallback(() => {
    setRedoStack((stack) => {
      const next = stack.at(-1);
      if (!next) return stack;
      setUndoStack((undo) => [...undo, { profile: cloneProfile(draft), label: 'undo' }]);
      setDraftState(cloneProfile(next.profile));
      return stack.slice(0, -1);
    });
  }, [draft]);

  const runValidation = useCallback(() => {
    const issues = validateOntologyProfile(draft);
    setValidationIssues(issues);
    return issues;
  }, [draft]);

  const previewDiff = useCallback(() => {
    const objectDelta = Object.keys(draft.conceptTypes).length - Object.keys(sourceProfile.conceptTypes).length;
    const relationshipDelta = Object.keys(draft.relationshipTypes).length - Object.keys(sourceProfile.relationshipTypes).length;
    const message = `Objects ${objectDelta >= 0 ? '+' : ''}${objectDelta}; Relationships ${relationshipDelta >= 0 ? '+' : ''}${relationshipDelta}; GraphInstruction defaults preserved.`;
    setLastDiff(message);
    return message;
  }, [draft, sourceProfile]);

  return { draft, setDraft, commitDraft, resetDraft, handleUndoDraft, handleRedoDraft, undoStack, redoStack, isDirty, validationIssues, runValidation, lastDiff, previewDiff };
}
