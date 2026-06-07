import { useEffect, useRef, useCallback } from 'react';
import type { SimulationInput, SimNode, SimLink, SimulationOptions } from './types';

const hasWorker = typeof Worker !== 'undefined';

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
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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

    const key = `${input.nodes.length}:${input.links.length}`;
    if (key === inputKeyRef.current) return;
    inputKeyRef.current = key;

    nodesDataRef.current = input.nodes.map((n, index) => ({
      ...n,
      x: n.x ?? Math.cos(index * 2.399963229728653) * (40 + index * 4),
      y: n.y ?? Math.sin(index * 2.399963229728653) * (40 + index * 4),
      z: n.z ?? 0,
    }));
    linksDataRef.current = [...input.links];

    if (workerRef.current) {
      initWorker(workerRef.current, input, options, nodesDataRef);
      isRunningRef.current = true;
    } else {
      isRunningRef.current = true;
    }
  }, [input, options]);

  const step = useCallback(() => {
    if (workerRef.current) {
      if (pendingStepRef.current) return;
      pendingStepRef.current = true;
      workerRef.current.postMessage({ type: 'step' });
    } else {
      nodesDataRef.current = nodesDataRef.current.map((node, index) => ({
        ...node,
        x: (node.x ?? 0) + Math.cos(index + 1) * 0.1,
        y: (node.y ?? 0) + Math.sin(index + 1) * 0.1,
        z: node.z ?? 0,
      }));
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
  options: SimulationOptions,
  nodesDataRef: React.MutableRefObject<SimNode[]>
) {
  const is2D = (options.dimension ?? '2d') === '2d';

  // Create serializable versions of nodes and links
  const nodes = input.nodes.map(n => ({
    id: n.id,
    x: n.x,
    y: n.y,
    z: n.z,
    degree: n.degree ?? 0,
    roleScale: n.roleScale ?? 1.0,
    community_id: ('community_id' in n) ? (n as any).community_id : undefined
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
