'use client';

import { useState, useEffect } from 'react';
import { StructuredPlanView } from './StructuredPlanView';
import DAGViewer from './DAGViewer';

interface PlanEditorTabProps {
  content: string;
  onChange: (content: string) => void;
}

type ViewMode = 'split' | 'structured' | 'dag';

export default function PlanEditorTab({ content, onChange }: PlanEditorTabProps) {
  const [viewMode, setViewMode] = useState<ViewMode>('structured');

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === 's') {
        e.preventDefault();
        setViewMode('structured');
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-surface">
        <div className="flex items-center gap-1 bg-background/50 p-1 rounded-lg border border-border">
          <button
            onClick={() => setViewMode('split')}
            className={`px-3 py-1.5 text-xs font-bold rounded-md transition-all flex items-center gap-2 ${
              viewMode === 'split'
                ? 'bg-primary text-white shadow-sm'
                : 'text-text-muted hover:text-text-main hover:bg-surface-hover'
            }`}
          >
            <span className="material-symbols-outlined text-[16px]">vertical_split</span>
            Split
          </button>
          <button
            onClick={() => setViewMode('structured')}
            className={`px-3 py-1.5 text-xs font-bold rounded-md transition-all flex items-center gap-2 ${
              viewMode === 'structured'
                ? 'bg-primary text-white shadow-sm'
                : 'text-text-muted hover:text-text-main hover:bg-surface-hover'
            }`}
            title="Epic Design View (Ctrl+Shift+S)"
          >
            <span className="material-symbols-outlined text-[16px]">account_tree</span>
            Epic Design
          </button>
          <button
            onClick={() => setViewMode('dag')}
            className={`px-3 py-1.5 text-xs font-bold rounded-md transition-all flex items-center gap-2 ${
              viewMode === 'dag'
                ? 'bg-primary text-white shadow-sm'
                : 'text-text-muted hover:text-text-main hover:bg-surface-hover'
            }`}
          >
            <span className="material-symbols-outlined text-[16px]">account_tree</span>
            DAG View
          </button>
        </div>
        
        <div className="text-[10px] font-bold text-text-faint uppercase tracking-widest">
          {viewMode} Mode
        </div>
      </div>

      {/* Planner view area */}
      <div className="flex-1 flex overflow-hidden">
        {viewMode === 'split' && (
          <textarea
            className="h-full w-1/2 font-mono text-sm bg-background border-none border-r border-border resize-none p-4 focus:outline-none custom-scrollbar text-text-main placeholder:text-text-faint"
            value={content}
            onChange={(e) => onChange(e.target.value)}
            placeholder={"# Plan: My Feature\n\n## Config\nworking_dir: .\n\n## EPIC-001 — Feature Title\n..."}
            spellCheck={false}
          />
        )}
        
        {viewMode === 'split' && (
          <div className="w-1/2 h-full bg-background/30">
            <StructuredPlanView />
          </div>
        )}

        {viewMode === 'structured' && (
          <div className="w-full h-full bg-background/30">
            <StructuredPlanView />
          </div>
        )}

        {viewMode === 'dag' && (
          <div className="w-full h-full bg-background/30">
            <DAGViewer />
          </div>
        )}
      </div>
    </div>
  );
}
