import { useEffect, useRef, useCallback } from 'react';
import type { SimulationInput, SimNode, SimLink, SimulationOptions } from './types';

const hasWorker = typeof Worker !== 'undefined';

function seedInitialPositions(nodes: SimNode[], previous: SimNode[] = []): SimNode[] {
  const previousById = new Map(previous.map((node) => [node.id, node]));
  const radius = Math.max(120, nodes.length * 24);
  return nodes.map((node, index) => {
    const prior = previousById.get(node.id);
    if (typeof prior?.x === 'number' && typeof prior?.y === 'number') {
      return { ...node, x: prior.x, y: prior.y, z: typeof prior.z === 'number' ? prior.z : 0 };
    }
    if (typeof node.x === 'number' && typeof node.y === 'number') {
      return { ...node, z: typeof node.z === 'number' ? node.z : 0 };
    }
    const angle = nodes.length ? (index / nodes.length) * Math.PI * 2 : 0;
    return {
      ...node,
      x: Math.round(Math.cos(angle) * radius),
      y: Math.round(Math.sin(angle) * radius),
      z: typeof node.z === 'number' ? node.z : 0,
    };
  });
}

function seedNodePositions(nodes: SimNode[], previous: SimNode[] = [], dimension: SimulationOptions['dimension'] = '2d'): SimNode[] {
  const previousById = new Map(previous.map((node) => [node.id, node]));
  const count = Math.max(nodes.length, 1);
  const radius = Math.max(120, count * 24);
  const is2D = (dimension ?? '2d') === '2d';
  return nodes.map((node, index) => {
    const prior = previousById.get(node.id);
    if (typeof node.x === 'number' && typeof node.y === 'number') {
      return { ...node, z: is2D ? 0 : (node.z ?? 0) };
    }
    if (prior && typeof prior.x === 'number' && typeof prior.y === 'number') {
      return { ...node, x: prior.x, y: prior.y, z: is2D ? 0 : (prior.z ?? 0) };
    }
    const angle = (index / count) * Math.PI * 2;
    return {
      ...node,
      x: Math.round(Math.cos(angle) * radius),
      y: Math.round(Math.sin(angle) * radius),
      z: is2D ? 0 : Math.round(((index % 7) - 3) * 32),
    };
  });
}

function endpointId(endpoint: string | SimNode): string {
  return typeof endpoint === 'string' ? endpoint : endpoint.id;
}

function simulationInputKey(input: SimulationInput, options: SimulationOptions): string {
  const nodeKey = input.nodes
    .map((node) => [node.id, node.x ?? '', node.y ?? '', node.z ?? ''].join('@'))
    .join('|');
  const linkKey = input.links
    .map((link) => [endpointId(link.source), endpointId(link.target), link.weight ?? ''].join('>'))
    .join('|');
  return [
    options.dimension ?? '3d',
    options.width ?? '',
    options.height ?? '',
    nodeKey,
    linkKey,
  ].join('::');
}

export function useForceSimulation(
  input: SimulationInput | null,
  options: SimulationOptions = {}
) {
  const workerRef = useRef<Worker | null>(null);
  const inputKeyRef = useRef('');
  const nodesDataRef = useRef<SimNode[]>([]);
  const linksDataRef = useRef<SimLink[]>([]);
  const isRunningRef = useRef(false);
  const subscribersRef = useRef(new Set<() => void>());
  const pendingStepRef = useRef(false);

  useEffect(() => {
    if (hasWorker) {
      try {
        const workerUrl = new URL('./simulation.worker.ts', import.meta.url);
        const worker = new Worker(workerUrl);
        workerRef.current = worker;

        worker.onerror = (e) => {
          console.error('[SIM WORKER ERROR]', e.message);
        };

        worker.onmessage = (e: MessageEvent) => {
          const { type: msgType, isRunning, positions } = e.data;
          if (msgType === 'step' || msgType === 'tick') {
            if (positions) {
              const pos = new Float64Array(positions);
              if (pos.length >= nodesDataRef.current.length * 3) {
                for (let i = 0; i < nodesDataRef.current.length; i++) {
                  const idx = i * 3;
                  nodesDataRef.current[i].x = pos[idx];
                  nodesDataRef.current[i].y = pos[idx + 1];
                  nodesDataRef.current[i].z = pos[idx + 2];
                }
              }
            }
            isRunningRef.current = isRunning;
            pendingStepRef.current = false;
            for (const fn of subscribersRef.current) fn();
          }
        };

        return () => {
          worker.terminate();
          workerRef.current = null;
        };
      } catch (err) {
        console.error('Failed to init worker', err);
        workerRef.current = null;
      }
    }
  }, []);

  useEffect(() => {
    if (!input || input.nodes.length === 0) {
      nodesDataRef.current = [];
      linksDataRef.current = [];
      if (workerRef.current) {
        workerRef.current.postMessage({ type: 'stop' });
      }
      inputKeyRef.current = '';
      return;
    }

    const key = simulationInputKey(input, options);
    if (key === inputKeyRef.current) return;
    inputKeyRef.current = key;

    const previousNodes = nodesDataRef.current;
    nodesDataRef.current = seedNodePositions(input.nodes, previousNodes, options.dimension);
    linksDataRef.current = [...input.links];

    if (workerRef.current) {
      initWorker(workerRef.current, { ...input, nodes: nodesDataRef.current }, options);
      isRunningRef.current = true;
    }
  }, [input, options]);

  const step = useCallback(() => {
    if (workerRef.current) {
      if (pendingStepRef.current) return;
      pendingStepRef.current = true;
      workerRef.current.postMessage({ type: 'step' });
    } else {
      // In jsdom or browsers without Worker support, keep coordinates defined so
      // callers can render immediately while the real worker path remains async.
      nodesDataRef.current = seedInitialPositions(nodesDataRef.current);
      isRunningRef.current = false;
      for (const fn of subscribersRef.current) fn();
    }
  }, []);

  const subscribe = useCallback((fn: () => void) => {
    subscribersRef.current.add(fn);
    return () => { subscribersRef.current.delete(fn); };
  }, []);

  const reheat = useCallback((alpha = 0.3) => {
    if (workerRef.current) {
      workerRef.current.postMessage({ type: 'reheat', data: { alpha } });
    }
    isRunningRef.current = true;
  }, []);

  const pause = useCallback(() => {
    if (workerRef.current) {
      workerRef.current.postMessage({ type: 'pause' });
    }
    isRunningRef.current = false;
  }, []);

  const resume = useCallback(() => {
    if (workerRef.current) {
      workerRef.current.postMessage({ type: 'resume' });
    }
  }, []);

  const getPositions = useCallback((): { nodes: SimNode[]; links: SimLink[] } => ({
    nodes: nodesDataRef.current,
    links: linksDataRef.current,
  }), []);

  const getIsRunning = useCallback((): boolean => {
    return isRunningRef.current;
  }, []);

  return { step, subscribe, getPositions, reheat, pause, resume, getIsRunning };
}

function initWorker(
  worker: Worker,
  input: SimulationInput,
  options: SimulationOptions
) {
  type SimNodeWithCommunity = SimNode & { community_id?: string | number };
  // Create serializable versions of nodes and links
  const nodes = input.nodes.map(n => ({
    id: n.id,
    x: n.x,
    y: n.y,
    z: n.z,
    degree: n.degree ?? 0,
    roleScale: n.roleScale ?? 1.0,
    community_id: (n as SimNodeWithCommunity).community_id
  }));

  const links = input.links.map(l => ({
    source: typeof l.source === 'string' ? l.source : (l.source as SimNode).id,
    target: typeof l.target === 'string' ? l.target : (l.target as SimNode).id,
    weight: l.weight ?? 1
  }));

  worker.postMessage({
    type: 'init',
    data: {
      nodes,
      links,
      dimension: options.dimension ?? '3d',
    },
  });
}

export type { SimNode, SimLink, SimulationInput, SimulationOptions } from './types';
