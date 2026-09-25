# acatalogue particle field (`viz/`)

The living view of the catalogue: every concept is a particle, every relation a
spring, and the whole field is a physical simulation you can pull on. Work on the
left (grepper, results, inspector, lenses, audit tables); the field on the right.

It consumes the JSON contract in [`../docs/API.md`](../docs/API.md) and nothing else.

## Run it

**With the API** (normal use): `acat serve` serves this directory at `/`, and the
page reads `/api/graph`, `/api/grep`, `/api/node` and `/api/audit`.

**Standalone** (no Node, no API): `dist/` is committed, so any static server works.
ES modules do not load from `file://`, so use a server:

```sh
cd viz
python3 -m http.server 8000
# with an exported graph (acat export-graph viz/data/graph.json):
#   http://localhost:8000/
# with the synthetic test fixture (placeholder data, never real):
#   http://localhost:8000/?graph=test/fixtures/graph.sample.json
```

Load order: `?graph=<url>` if given (testing), else `/api/graph`, else
`data/graph.json` next to `index.html`. When the API does not answer, the grepper
falls back to a case-insensitive substring match over node labels and says so
("offline: label search only (API not reachable)"); the inspector shows what the
graph alone knows, and the audit is computed in the browser, each labelled offline.

## Build and test

Node is needed only to change the source (`src/*.ts`, TypeScript 7.0.2, strict).

```sh
cd viz
npm install        # typescript 7.0.2, the only (dev) dependency
npm run build      # tsc -> dist/*.js (+ source maps)
npm run check      # type-check only
npm test           # build, then node --test over test/*.test.mjs
```

`npm test` runs three suites against `dist/`:

- `physics.test.mjs`: 3000 steps on the 600-node fixture stay finite; kinetic energy
  ends far below its early peak; spring-connected pairs sit closer than random pairs;
  Barnes-Hut matches brute force within 5% (300 random particles, theta 0.3; the
  error at the working theta 0.8 is reported too); two runs are bit-identical; the
  ring spring holds every root within ±15% of its ring radius; sleep, wake and the
  drag spring; the frame accumulator clamp; glow decay `dE/dt = -E/tau`.
- `data.test.mjs`: payload validation (bad records dropped and counted, edge
  indices remapped), the offline label search, response coercion, offline audit.
- `rules.test.mjs`: the standing rules, checked mechanically: typescript pinned at
  7.0.2 and strict, no runtime dependencies, no `innerHTML`/`Math.random`/`eval`,
  no CSS transitions or animations, no external scripts, colours only in `style.css`.

## Using the field

| Input | Does |
|---|---|
| drag empty space | pan (the camera follows the pointer on a stiff spring) |
| drag a particle | pull it: it hangs on a stiff, critically damped spring to the pointer |
| wheel / pinch | zoom around the pointer |
| click a particle | select it: inspector, neighbours in full ink, the rest muted |
| hover | tooltip: label, coverage (language editions), scheme and id |
| `/` | focus the search box |
| `Esc` | clear the selection and the search |
| arrows, `+` `-`, `0` | pan, zoom, fit the whole field |

**Encoding.** Domains are not colour-coded: a domain is its spatial cluster plus a
label at the cluster's mass-weighted centroid (always drawn: when two would overlap,
one moves just above or below its cluster, and the size steps down from 13 to 10 px). Particles are neutral ink, radius ∝
sqrt(mass), alpha falling gently with depth; edges are solid hairlines (`broader`
0.16, `related`/`mapping` 0.08, `semantic` only when toggled on). Colour is
reserved: accent for search hits and hover, accent-2 for the one selected node
(which always carries a label). Other labels appear only when their particle is big
enough on screen, placed greedily so they never overlap.

**Lenses.** *Structure* (default) and *Coverage*: a single-hue sequential ramp on
log(1 + langs), the number of Wikipedia language editions with an article; `langs ==
null` is a hollow ring (no data). The ramp's anchor flips in dark mode. The key in
the corner always explains the marks of the current lens.

**Themes.** Papyrus (light) and Sea (dark; the Sea surface `#0f1c21` is an
assumption pending the owner). Colours live only in `style.css` custom properties;
the canvas reads them back. The page follows `prefers-color-scheme`; the theme
button stamps `data-theme` on `<html>`, which wins both ways (remembered per browser
when storage is available).

**Reduced motion** (`prefers-reduced-motion: reduce`): the simulation settles
off-screen before the first paint (at most 4000 steps or 5 s, then it is frozen),
camera moves are instant cuts, and highlights are static (no glow).

## How it moves

Everything that moves is an ODE integrated with semi-implicit Euler on a fixed
timestep (1/120 s) behind a frame accumulator. The accumulator input is clamped and
the backlog is dropped when a frame runs out of steps or time budget, so a slow frame
cannot snowball (the simulation then runs slower than the clock instead).

- **Repulsion**: softened 2D Coulomb (`k qi qj r / (r² + ε²)`, charge = sqrt(mass))
  fading smoothly to zero between 35 and 65 world units, via a Barnes-Hut quadtree
  (theta 0.8) walked once per leaf group.
- **Springs** per edge kind: `broader` short and stiff; `related` weaker; `mapping`
  weaker and longer; `semantic` weakest and off unless toggled. Tension stops growing
  past a reach (Huber springs), and edges between different domains are weaker, so a
  few cross-links cannot fold two domains together.
- **Circle of learning**: the depth-0 roots of the primary scheme (`acat`) feel a
  radial spring toward a ring; other schemes' roots toward a larger ring; roots on a
  ring repel each other (charge ∝ cluster size). Roots are never pinned: they start at
  equal angles in id order and their angles come from the forces.
- Weak centering gravity, viscous damping, a velocity clamp, kinetic-energy tracking,
  **sleep** when the mean kinetic energy stays low for 90 steps, **wake** on a press,
  drag, wheel or key in the field, on a selection, and on data or link changes.
- The **camera** is a critically damped spring toward a target centre and log-zoom.
- **Glow** energy per particle decays as `dE/dt = -E/tau`.

Every physics constant is in `PHYSICS` (`src/physics.ts`); camera and drawing
constants are in `CAMERA` (`src/camera.ts`) and `RENDER` (`src/render.ts`). The
initial layout is seeded from a hash of each node id (mulberry32): the same data
gives the same layout, every time.

## Files

| Path | Role |
|---|---|
| `index.html`, `style.css` | page shell and every colour token |
| `src/physics.ts` | DOM-free particle system (structure of arrays, forces, integrator, sleep) |
| `src/quadtree.ts` | Barnes-Hut quadtree in flat typed arrays |
| `src/rng.ts` | FNV-1a hash and mulberry32 (seeded layout) |
| `src/camera.ts` | pan/zoom camera on a critically damped spring |
| `src/render.ts` | Canvas 2D renderer: batched marks, hairlines, glow, label placement |
| `src/grid.ts` | screen-space grids for hit testing and label collisions |
| `src/data.ts` | API types (mirroring docs/API.md), loaders, validation, offline search |
| `src/ui.ts` | the work panel, key, tooltip (text nodes only, never innerHTML) |
| `src/theme.ts` | reads colours from CSS, follows the OS, the toggle |
| `src/main.ts` | wiring, the frame loop, input |
| `dist/` | compiled ES modules (committed) |
| `test/make-sample.mjs` | generator of the synthetic fixture |
| `test/fixtures/graph.sample.json` | synthetic graph: 13 placeholder domains (600 nodes) + `space` (60) |

The fixture is synthetic: labels are placeholders ("Domain 01", "Topic 03.2.1"),
numbers come from a seeded PRNG, and the scheme titles say so. Regenerate it, or
make a bigger graph for performance runs, with:

```sh
node test/make-sample.mjs                                   # the fixture
node test/make-sample.mjs --nodes 5800 --space 200 --out /tmp/graph.6000.json
```

## Diagnostics

`window.__acat.stats` (in the browser console) reports node and edge counts, whether
the simulation is awake, steps taken, mean kinetic energy, the last physics step and
draw times in ms, the frame rate over the last second, and how often the accumulator
clamp fired. `window.__acat.screenOf(id)` gives a node's position on the canvas.
