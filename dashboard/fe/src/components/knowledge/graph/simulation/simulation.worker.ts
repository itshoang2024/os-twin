import { forceSimulation, forceLink, forceManyBody, forceCenter } from 'd3-force-3d';

let simulation: any = null;
let nodes: any[] = [];
let links: any[] = [];
let is2D = false;

self.onmessage = (e: MessageEvent) => {
  const { type, data } = e.data;

  switch (type) {
    case 'init': {
      is2D = data.dimension === '2d';
      nodes = data.nodes;
      links = data.links;

      // ALWAYS generate a perfect 3D spherical scatter on init to guarantee volume
      nodes.forEach((n: any) => {
        const radius = 600 * Math.cbrt(Math.random());
        const theta = Math.random() * 2 * Math.PI;
        const phi = Math.acos(2 * Math.random() - 1);

        n.x = radius * Math.sin(phi) * Math.cos(theta);
        n.y = radius * Math.sin(phi) * Math.sin(theta);
        n.z = is2D ? 0 : radius * Math.cos(phi);
        n.vx = 0;
        n.vy = 0;
        n.vz = 0;
      });

      if (simulation) {
        simulation.stop();
      }

      simulation = forceSimulation(nodes)
        .numDimensions(is2D ? 2 : 3)
        .alpha(1.0)
        .alphaDecay(0.01)
        .velocityDecay(0.3)
        .force('link', forceLink(links).id((d: any) => d.id).strength(0.1).distance((d: any) => {
          const srcDeg = d.source.degree || 0;
          const tgtDeg = d.target.degree || 0;

          const srcRadius = (srcDeg > 0 ? srcDeg * 10 : 5) * 25 * 0.5;
          const tgtRadius = (tgtDeg > 0 ? tgtDeg * 10 : 5) * 25 * 0.5;

          return srcRadius + tgtRadius + 300;
        }))
        .force('charge', forceManyBody().strength((d: any) => {
          const degree = d.degree || 0;
          const radius = (degree > 0 ? degree * 10 : 5) * 25 * 0.5;
          return -3000 - (radius * 10);
        }).distanceMax(2000))
        .force('center', forceCenter(0, 0, 0))
        .stop(); // We will tick manually

      // Pre-tick the simulation so initial positions are spread out before first render
      for (let i = 0; i < 100; i++) {
        simulation.tick();
      }

      // Send initial positions after pre-tick
      {
        const positions = new Float64Array(nodes.length * 3);
        for (let i = 0; i < nodes.length; i++) {
          const n = nodes[i];
          positions[i * 3] = n.x || 0;
          positions[i * 3 + 1] = n.y || 0;
          positions[i * 3 + 2] = is2D ? 0 : (n.z || 0);
        }
        const alpha = simulation.alpha();
        self.postMessage(
          { type: 'tick', isRunning: alpha > simulation.alphaMin(), positions: positions.buffer },
          { transfer: [positions.buffer] }
        );
      }

      break;
    }

    case 'step': {
      if (!simulation) {
        self.postMessage({ type: 'step', isRunning: false, positions: null });
        return;
      }

      simulation.tick();

      const alpha = simulation.alpha();
      const isRunning = alpha > simulation.alphaMin();

      const positions = new Float64Array(nodes.length * 3);
      for (let i = 0; i < nodes.length; i++) {
        const n = nodes[i];
        positions[i * 3] = n.x || 0;
        positions[i * 3 + 1] = n.y || 0;
        positions[i * 3 + 2] = is2D ? 0 : (n.z || 0);
      }

      self.postMessage(
        { type: 'step', isRunning, positions: positions.buffer },
        { transfer: [positions.buffer] }
      );

      break;
    }

    case 'reheat': {
      if (simulation) {
        simulation.alpha(data?.alpha ?? 0.3).restart();
        simulation.stop(); // Keep manual ticking
      }
      break;
    }

    case 'pause': {
      // Nothing needed for manual ticking
      break;
    }

    case 'resume': {
      // Nothing needed for manual ticking
      break;
    }

    case 'stop': {
      if (simulation) {
        simulation.stop();
        simulation = null;
      }
      break;
    }
  }
};
