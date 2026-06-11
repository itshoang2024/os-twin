import './LegacyDeliveryFlow.css';
import type { CSSProperties } from 'react';

type EffortTone = 'mixed' | 'human' | 'agent';

type NodeEffort = {
  human: string;
  agent: string;
  note: string;
  tone: EffortTone;
};

type LegacyTask = {
  label: string;
  detail: string;
  drift: string;
  effort: NodeEffort;
};

type OstwinStep = {
  label: string;
  detail: string;
  effort: NodeEffort;
};

const legacyTasks: LegacyTask[] = [
  {
    label: 'Task A',
    detail: 'local context',
    drift: 'hidden assumptions',
    effort: { human: '49%', agent: '51%', note: 'human prompts, agent produces', tone: 'mixed' },
  },
  {
    label: 'Task B',
    detail: 'local context',
    drift: 'duplicated decisions',
    effort: { human: '46%', agent: '54%', note: 'human interprets, agent expands', tone: 'mixed' },
  },
  {
    label: 'Task C',
    detail: 'local context',
    drift: 'late conflicts',
    effort: { human: '51%', agent: '49%', note: 'human checks, agent patches', tone: 'mixed' },
  },
];

const ostwinSteps: OstwinStep[] = [
  {
    label: 'Plan',
    detail: 'product + system contract',
    effort: { human: '72%', agent: '28%', note: 'human-led product and design judgment', tone: 'human' },
  },
  {
    label: 'DAG',
    detail: 'dependency-aware slices',
    effort: { human: '18%', agent: '82%', note: 'agent-heavy graph decomposition', tone: 'agent' },
  },
  {
    label: 'Rooms',
    detail: 'isolated epic teams',
    effort: { human: '16%', agent: '84%', note: 'agents run scoped execution loops', tone: 'agent' },
  },
  {
    label: 'Review',
    detail: 'QA evidence per handoff',
    effort: { human: '32%', agent: '68%', note: 'agents test, humans judge exceptions', tone: 'agent' },
  },
  {
    label: 'Artifacts',
    detail: 'merge-ready outcomes',
    effort: { human: '22%', agent: '78%', note: 'agents package evidence-backed output', tone: 'agent' },
  },
];

function NodeEffortBadge({ effort }: { effort: NodeEffort }) {
  return (
    <div className={`legacy-flow__node-effort legacy-flow__node-effort--${effort.tone}`} aria-label={`Human ${effort.human}, agent ${effort.agent}`}>
      <div className="legacy-flow__node-effort-bars" style={{ '--human-share': effort.human } as CSSProperties} aria-hidden="true" />
      <div className="legacy-flow__node-effort-split">
        <span>Human {effort.human}</span>
        <span>Agent {effort.agent}</span>
      </div>
      <small>{effort.note}</small>
    </div>
  );
}

export default function LegacyDeliveryFlow() {
  return (
    <section className="legacy-flow" aria-labelledby="legacy-flow-title">
      <div className="legacy-flow__header">
        <p className="legacy-flow__eyebrow">Delivery flow contrast</p>
        <h3 id="legacy-flow-title">From late merge pressure to controlled agent rooms</h3>
        <p>
          The old pattern waits until many local task contexts reconnect before the real system appears.
          In agentic delivery, that delay turns small ambiguity into fast-moving integration risk.
        </p>
      </div>

      <div className="legacy-flow__grid">
        <article className="legacy-flow__panel legacy-flow__panel--legacy" aria-label="Old agile-shaped delivery loop">
          <div className="legacy-flow__panel-heading">
            <span>Old loop</span>
            <strong>Plan, split, merge, repair</strong>
          </div>

          <div className="legacy-flow__stage legacy-flow__stage--planner">
            <span className="legacy-flow__index">01</span>
            <strong>Single planner effort</strong>
            <small>one large plan absorbs product and system intent</small>
            <NodeEffortBadge effort={{ human: '56%', agent: '44%', note: 'mixed drafting and steering', tone: 'mixed' }} />
          </div>

          <div className="legacy-flow__connector legacy-flow__connector--down" aria-hidden="true">
            <i />
          </div>

          <div className="legacy-flow__stage legacy-flow__stage--split">
            <span className="legacy-flow__index">02</span>
            <strong>Team decomposition</strong>
            <small>work becomes separate implementation tasks</small>
            <NodeEffortBadge effort={{ human: '52%', agent: '48%', note: 'mixed task splitting and expansion', tone: 'mixed' }} />
          </div>

          <div className="legacy-flow__task-row">
            {legacyTasks.map((task, index) => (
              <div className="legacy-flow__task" key={task.label} style={{ '--flow-index': index } as CSSProperties}>
                <span>{task.label}</span>
                <strong>{task.detail}</strong>
                <small>{task.drift}</small>
                <NodeEffortBadge effort={task.effort} />
              </div>
            ))}
          </div>

          <div className="legacy-flow__merge-zone" aria-label="Merge and repair effort">
            <div className="legacy-flow__merge-lines" aria-hidden="true">
              <i />
              <i />
              <i />
            </div>
            <div className="legacy-flow__merge">
              <span className="legacy-flow__index">03</span>
              <strong>Merge-and-repair effort</strong>
              <small>bugs surface after separate contexts reconnect</small>
              <NodeEffortBadge effort={{ human: '58%', agent: '42%', note: 'mixed debugging, heavier human repair', tone: 'mixed' }} />
              <div className="legacy-flow__risk-list">
                <span>context loss</span>
                <span>unclear ownership</span>
                <span>integration bugs</span>
              </div>
            </div>
          </div>

          <div className="legacy-flow__packet legacy-flow__packet--one" aria-hidden="true" />
          <div className="legacy-flow__packet legacy-flow__packet--two" aria-hidden="true" />
          <div className="legacy-flow__packet legacy-flow__packet--three" aria-hidden="true" />
        </article>

        <article className="legacy-flow__panel legacy-flow__panel--ostwin" aria-label="OSTwin controlled agent delivery flow">
          <div className="legacy-flow__panel-heading">
            <span>OSTwin loop</span>
            <strong>Slice, isolate, verify, integrate</strong>
          </div>

          <div className="legacy-flow__rail">
            {ostwinSteps.map((step, index) => (
              <div className="legacy-flow__rail-step" key={step.label} style={{ '--flow-index': index } as CSSProperties}>
                <span className="legacy-flow__index">{String(index + 1).padStart(2, '0')}</span>
                <strong>{step.label}</strong>
                <small>{step.detail}</small>
                <NodeEffortBadge effort={step.effort} />
              </div>
            ))}
            <div className="legacy-flow__rail-pulse" aria-hidden="true" />
          </div>

          <div className="legacy-flow__room-stack" aria-label="Isolated rooms produce reviewed outputs">
            <div>
              <span>EPIC-001</span>
              <strong>Room context</strong>
              <small>role + skill + scoped tools</small>
            </div>
            <div>
              <span>QA gate</span>
              <strong>Evidence before merge</strong>
              <small>acceptance criteria and regression checks</small>
            </div>
            <div>
              <span>Artifact</span>
              <strong>Merge-ready output</strong>
              <small>traceable result, not a late surprise</small>
            </div>
          </div>

          <p className="legacy-flow__summary">
            Each epic becomes a controlled room with its own boundary, memory, lifecycle, and review loop.
            Integration happens after evidence, not after guesswork.
          </p>
        </article>
      </div>
    </section>
  );
}
