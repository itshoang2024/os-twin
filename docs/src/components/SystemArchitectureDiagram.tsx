import './SystemArchitectureDiagram.css';

type NodeVariant = 'entry' | 'runtime' | 'coordination' | 'edge';

type DiagramNode = {
  readonly id: string;
  readonly title: string;
  readonly subtitle: string;
  readonly lines: readonly string[];
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
  readonly variant: NodeVariant;
};

type Connector = {
  readonly id: string;
  readonly path: string;
};

export interface SystemArchitectureDiagramProps {
  readonly className?: string;
}

const nodes: readonly DiagramNode[] = [
  {
    id: 'user',
    title: 'User / CLI',
    subtitle: 'operator surface',
    lines: [],
    x: 260,
    y: 24,
    width: 680,
    height: 92,
    variant: 'entry',
  },
  {
    id: 'engine',
    title: 'Engine',
    subtitle: 'PowerShell orchestration',
    lines: ['Invoke-Agent.ps1', 'Build-PlanningDAG.ps1', 'New-WarRoom.ps1', 'Resolve-*.ps1'],
    x: 88,
    y: 178,
    width: 420,
    height: 232,
    variant: 'runtime',
  },
  {
    id: 'dashboard',
    title: 'Dashboard',
    subtitle: 'FastAPI + Next.js',
    lines: ['FastAPI backend', 'REST + SSE streaming', 'Next.js frontend', 'Plan and room views'],
    x: 692,
    y: 178,
    width: 420,
    height: 232,
    variant: 'runtime',
  },
  {
    id: 'filesystem',
    title: 'Filesystem',
    subtitle: '.agents coordination layer',
    lines: ['plans / war-rooms / roles / skills / ledger.jsonl'],
    x: 180,
    y: 500,
    width: 840,
    height: 126,
    variant: 'coordination',
  },
  {
    id: 'mcp',
    title: 'MCP Servers',
    subtitle: 'Python process isolation',
    lines: ['memory', 'warroom', 'channel', 'knowledge'],
    x: 88,
    y: 712,
    width: 420,
    height: 118,
    variant: 'edge',
  },
  {
    id: 'bot',
    title: 'Bot',
    subtitle: 'TypeScript adapters',
    lines: ['Discord', 'Telegram', 'Slack'],
    x: 692,
    y: 712,
    width: 420,
    height: 118,
    variant: 'edge',
  },
];

const connectors: readonly Connector[] = [
  { id: 'user-engine', path: 'M600 116 V140 H298 V178' },
  { id: 'user-dashboard', path: 'M600 140 H902 V178' },
  { id: 'engine-filesystem', path: 'M298 410 V454 H360 V500' },
  { id: 'dashboard-filesystem', path: 'M902 410 V454 H840 V500' },
  { id: 'filesystem-mcp', path: 'M360 626 V670 H298 V712' },
  { id: 'filesystem-bot', path: 'M840 626 V670 H902 V712' },
];

function getRenderedLines(node: DiagramNode) {
  if (node.id === 'mcp') {
    return ['memory / warroom', 'channel / knowledge'];
  }

  if (node.variant === 'edge') {
    return [node.lines.join(' / ')];
  }

  return node.lines;
}

function ArchitectureNode({ node }: Readonly<{ node: DiagramNode }>) {
  const renderedLines = getRenderedLines(node);
  const titleY = node.y + 42;
  const subtitleY = node.y + 70;
  const lineStartY =
    node.y + (node.id === 'filesystem' ? 103 : node.variant === 'edge' ? (renderedLines.length > 1 ? 94 : 100) : 112);
  const lineSpacing = node.variant === 'edge' ? 20 : 28;

  return (
    <g className={`system-architecture-diagram__node system-architecture-diagram__node--${node.variant}`}>
      <rect
        className="system-architecture-diagram__node-frame"
        x={node.x}
        y={node.y}
        width={node.width}
        height={node.height}
        rx="18"
      />
      <text
        className="system-architecture-diagram__node-title"
        x={node.x + node.width / 2}
        y={titleY}
        textAnchor="middle"
      >
        {node.title}
      </text>
      <text
        className="system-architecture-diagram__node-subtitle"
        x={node.x + node.width / 2}
        y={subtitleY}
        textAnchor="middle"
      >
        {node.subtitle}
      </text>
      {renderedLines.map((line, index) => (
        <text
          className="system-architecture-diagram__node-line"
          x={node.x + node.width / 2}
          y={lineStartY + index * lineSpacing}
          textAnchor="middle"
          key={line}
        >
          {line}
        </text>
      ))}
    </g>
  );
}

export default function SystemArchitectureDiagram({ className }: SystemArchitectureDiagramProps) {
  const classNames = ['system-architecture-diagram', className].filter(Boolean).join(' ');
  const userNode = nodes.find((node) => node.id === 'user');
  const engineNode = nodes.find((node) => node.id === 'engine');
  const dashboardNode = nodes.find((node) => node.id === 'dashboard');
  const filesystemNode = nodes.find((node) => node.id === 'filesystem');
  const mcpNode = nodes.find((node) => node.id === 'mcp');
  const botNode = nodes.find((node) => node.id === 'bot');

  const renderMobileNode = (node: DiagramNode | undefined) =>
    node ? (
      <div className={`system-architecture-diagram__mobile-node system-architecture-diagram__mobile-node--${node.variant}`}>
        <strong>{node.title}</strong>
        <span>{node.subtitle}</span>
        {node.lines.length > 0 && <small>{node.lines.join(' / ')}</small>}
      </div>
    ) : null;

  return (
    <figure
      className={classNames}
      aria-label="OSTwin system architecture: User and CLI connect to the engine and dashboard, which coordinate through the .agents filesystem before MCP servers and bot adapters."
    >
      <svg
        className="system-architecture-diagram__canvas"
        viewBox="0 0 1200 860"
        role="img"
        aria-describedby="system-architecture-diagram-desc"
      >
        <title id="system-architecture-diagram-title">OSTwin system architecture</title>
        <desc id="system-architecture-diagram-desc">
          User commands reach the engine and dashboard. Both coordinate through the .agents filesystem,
          which also connects MCP servers and bot adapters.
        </desc>
        <defs>
          <marker
            id="system-architecture-diagram-arrow"
            viewBox="0 0 10 10"
            refX="8"
            refY="5"
            markerWidth="8"
            markerHeight="8"
            orient="auto-start-reverse"
          >
            <path className="system-architecture-diagram__arrow" d="M 0 0 L 10 5 L 0 10 z" />
          </marker>
        </defs>
        <rect className="system-architecture-diagram__field" x="16" y="16" width="1168" height="828" rx="28" />
        <g className="system-architecture-diagram__connectors">
          {connectors.map((connector) => (
            <path
              className="system-architecture-diagram__connector"
              d={connector.path}
              markerEnd="url(#system-architecture-diagram-arrow)"
              key={connector.id}
            />
          ))}
        </g>
        {nodes.map((node) => (
          <ArchitectureNode node={node} key={node.id} />
        ))}
      </svg>
      <div className="system-architecture-diagram__mobile-flow" aria-hidden="true">
        {renderMobileNode(userNode)}
        <div className="system-architecture-diagram__mobile-split">
          {renderMobileNode(engineNode)}
          {renderMobileNode(dashboardNode)}
        </div>
        {renderMobileNode(filesystemNode)}
        <div className="system-architecture-diagram__mobile-split">
          {renderMobileNode(mcpNode)}
          {renderMobileNode(botNode)}
        </div>
      </div>
      <figcaption>
        The four runtime surfaces stay independent. Durable state and handoffs live in the .agents
        filesystem instead of a shared database or broker.
      </figcaption>
    </figure>
  );
}
