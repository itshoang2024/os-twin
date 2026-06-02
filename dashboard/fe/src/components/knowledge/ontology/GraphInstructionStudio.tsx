import React from 'react';
import type { GraphInstruction, OntologyProfile } from '@/hooks/use-ontology';
import { SectionCard } from './ontology-ui';

function formatInstruction(instruction: GraphInstruction | undefined): string {
  return JSON.stringify(instruction ?? {}, null, 2);
}

function countKeys(record: Record<string, unknown> | undefined): number {
  return Object.keys(record ?? {}).length;
}

export default function GraphInstructionStudio({ profile, onChange, onValidate }: { profile: OntologyProfile; onChange: (profile: OntologyProfile) => void; onValidate: (profile: OntologyProfile) => Promise<void>; }) {
  const instruction = (profile.graph_instruction ?? {}) as GraphInstruction;
  const [text, setText] = React.useState(formatInstruction(instruction));
  const [parseError, setParseError] = React.useState<string | null>(null);
  const [isValidating, setIsValidating] = React.useState(false);

  React.useEffect(() => {
    setText(formatInstruction((profile.graph_instruction ?? {}) as GraphInstruction));
    setParseError(null);
  }, [profile.graph_instruction]);

  const applyText = async (validate = false) => {
    try {
      const parsed = JSON.parse(text) as GraphInstruction;
      const next = { ...profile, graph_instruction: parsed } as OntologyProfile;
      setParseError(null);
      onChange(next);
      if (validate) {
        setIsValidating(true);
        await onValidate(next);
      }
    } catch (err) {
      setParseError(err instanceof Error ? err.message : 'Graph Instruction JSON could not be parsed.');
    } finally {
      setIsValidating(false);
    }
  };

  const defaultViews = instruction.default_views ?? [];
  const examples = instruction.examples ?? [];
  const layout = instruction.layout_hints ?? {};

  return (
    <SectionCard title="Graph Instruction Authoring" subtitle="Edit the profile-owned rendering contract, then preview lanes, defaults, examples, and validation surfaces before saving." action={<div className="flex flex-wrap gap-2"><button className="rounded-lg border px-3 py-1.5 text-xs font-semibold" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }} onClick={() => setText(formatInstruction(instruction))}>Revert JSON</button><button className="rounded-lg border px-3 py-1.5 text-xs font-semibold" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }} onClick={() => applyText(false)}>Apply preview</button><button className="rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50" disabled={isValidating} onClick={() => applyText(true)}>{isValidating ? 'Validating…' : 'Validate instruction'}</button></div>}>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div>
          <textarea aria-label="Graph Instruction JSON editor" value={text} onChange={(event) => setText(event.target.value)} spellCheck={false} className="min-h-[360px] w-full rounded-xl border p-3 font-mono text-xs outline-none focus:ring-2 focus:ring-primary/20" style={{ background: 'var(--color-background)', borderColor: parseError ? 'var(--color-danger)' : 'var(--color-border)', color: 'var(--color-text-main)' }} />
          {parseError && <p className="mt-2 text-xs text-danger">JSON parse error: {parseError}</p>}
        </div>
        <aside className="space-y-3">
          <div className="rounded-xl border p-3" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }}>
            <div className="text-[11px] font-semibold uppercase tracking-[0.12em]" style={{ color: 'var(--color-text-muted)' }}>Preview</div>
            <dl className="mt-2 grid grid-cols-2 gap-2 text-xs" style={{ color: 'var(--color-text-main)' }}>
              <dt>Lane dimension</dt><dd className="font-semibold">{instruction.default_lane_dimension ?? 'default_layer'}</dd>
              <dt>Layout density</dt><dd className="font-semibold">{String(layout.density ?? 'comfortable')}</dd>
              <dt>Concept defaults</dt><dd className="font-semibold">{countKeys(instruction.concept_type_defaults as Record<string, unknown>)}</dd>
              <dt>Relationship defaults</dt><dd className="font-semibold">{countKeys(instruction.relationship_type_defaults as Record<string, unknown>)}</dd>
              <dt>Validation rules</dt><dd className="font-semibold">{instruction.validation_rules?.length ?? 0}</dd>
            </dl>
          </div>
          <div className="rounded-xl border p-3" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }}>
            <div className="text-[11px] font-semibold uppercase tracking-[0.12em]" style={{ color: 'var(--color-text-muted)' }}>Default views</div>
            <div className="mt-2 space-y-2">{defaultViews.length === 0 ? <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>No named views declared.</p> : defaultViews.map((view) => <div key={view.id} className="rounded-lg border px-2 py-1.5 text-xs" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}><strong>{view.label}</strong><br /><span style={{ color: 'var(--color-text-muted)' }}>{view.id} · {view.lane_dimension ?? instruction.default_lane_dimension ?? 'default_layer'}</span></div>)}</div>
          </div>
          <div className="rounded-xl border p-3" style={{ borderColor: 'var(--color-border)', background: 'var(--color-background)' }}>
            <div className="text-[11px] font-semibold uppercase tracking-[0.12em]" style={{ color: 'var(--color-text-muted)' }}>Examples</div>
            <div className="mt-2 space-y-2">{examples.length === 0 ? <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>No graph examples declared.</p> : examples.map((example) => <div key={String(example.id)} className="rounded-lg border px-2 py-1.5 text-xs" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-main)' }}><strong>{String(example.id)}</strong><br /><span style={{ color: 'var(--color-text-muted)' }}>{String(example.description ?? 'Graph instruction example')}</span></div>)}</div>
          </div>
        </aside>
      </div>
    </SectionCard>
  );
}
