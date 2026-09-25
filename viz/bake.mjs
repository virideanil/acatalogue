// Bake the particle layout offline: run the same compiled physics the browser runs (dist/physics.js),
// from its deterministic placement, until the field rests or a step limit is reached. Prints JSON.
//
//   node viz/bake.mjs <graph.json> [maxSteps]
//
// The browser then starts from these positions at rest and simulates only disturbances (drags),
// so every viewer sees the same layout regardless of how their engine rounds Math functions.
import { readFileSync } from "node:fs";
import { parseGraph } from "./dist/data.js";
import { Sim } from "./dist/physics.js";

const [path, maxArg] = process.argv.slice(2);
if (!path) {
  console.error("usage: node viz/bake.mjs <graph.json> [maxSteps]");
  process.exit(2);
}
const maxSteps = Number(maxArg ?? 20000);
const parsed = parseGraph(JSON.parse(readFileSync(path, "utf8")));
const sim = new Sim(parsed.payload);
const t0 = performance.now();
const steps = sim.settle(maxSteps);
const ms = performance.now() - t0;
const positions = {};
for (let i = 0; i < sim.n; i++) positions[sim.ids[i]] = [sim.x[i], sim.y[i]];
process.stdout.write(
  JSON.stringify({
    steps,
    asleep: !sim.awake,
    ms: Math.round(ms),
    node: process.version,
    nodes: sim.n,
    edges: sim.m,
    dropped_nodes: parsed.droppedNodes,
    dropped_edges: parsed.droppedEdges + sim.droppedEdges,
    positions,
  }),
);
