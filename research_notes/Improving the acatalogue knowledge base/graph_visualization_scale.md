# Browser visualization of 10^5–10^6-node knowledge graphs as physical particle systems, applied to acatalogue (as of 2026-09-25)

Scope and conventions. Every claim carries a link. "(search summary)" marks a claim I saw only in a search-result summary, not on a page I opened, so treat it as weaker. "Measured (this session)" marks numbers I produced here by running acatalogue's compiled code (`viz/dist`, commit `0f9b65c`) under Node v22.22.2 on a 4-vCPU container (Intel Xeon @ 2.10 GHz). That CPU is slower per core than a current laptop, so these thresholds are conservative. The benchmark scripts are in the session scratchpad: `/tmp/claude-0/-home-user-acatalogue/0c6b5ec4-d312-5493-9173-1d9be46979db/scratchpad/{bh_bench,grid_bench,grid2_bench,spring_check}.mjs`. The scratchpad is ephemeral, so move the scripts if they are to be kept. There was no browser in this environment, so no rendering frame time for acatalogue itself was measured. Relative links such as `../../viz/src/physics.ts` point into this repository.

## Q1. Rendering: Canvas 2D limits vs WebGL2 instancing vs WebGPU; sprites/SDF; edges; OffscreenCanvas; measured library numbers

### Takeaway
In September 2026 the production baseline for 10^5–10^6 marks is WebGL2: instanced quads with the circle carved in the fragment shader, one draw call per layer. WebGPU now ships in Chrome/Edge, Safari 26 and Firefox on Windows and macOS. It is still missing on most Linux GPUs and in Firefox for Linux and Android, and deck.gl 9.4 (5 Sep 2026) still calls its WebGPU path experimental. Canvas 2D stops being interactive in the low tens of thousands of edges. In Cytoscape's measurement, a 3,200-node / 68,000-edge network ran at 3 fps on Canvas and 10 fps on WebGL on an M1.

### Cited Findings

#### Browser support status (Sept 2026)
- WebGPU, Chromium: Mac/Windows x86-64/ChromeOS since 113. Android 12+ (ARM/Qualcomm/Intel GPUs) since 121. Imagination GPUs (Android 16+) since 139. Linux only on Intel Gen12+ (144) and NVIDIA driver ≥ 535.183.01 on Wayland (147); other Linux GPUs are "behind experimental flag". Windows ARM64 is behind a flag. — [gpuweb Implementation Status wiki](https://github.com/gpuweb/gpuweb/wiki/Implementation-Status)
- WebGPU, Firefox: Windows 141. macOS Apple Silicon 145 (macOS 26+). macOS Intel 147. Linux and Android are Nightly only ("Mozilla expects Linux shipping in 2026"). WebGPU, Safari: 26 on macOS, iOS/iPadOS and visionOS, "supported and enabled by default". — [gpuweb Implementation Status wiki](https://github.com/gpuweb/gpuweb/wiki/Implementation-Status)
- **Superseded:** WebGL 2.0 Compute never shipped to production browsers. The Khronos spec page calls it obsolete and points to WebGPU for GPU compute, and Chromium removed the prototype (search summary). — [Khronos WebGL 2.0 Compute](https://www.khronos.org/registry/webgl/specs/latest/2.0-compute/); [9ballsyndrome/WebGL_Compute_shader #9](https://github.com/9ballsyndrome/WebGL_Compute_shader/issues/9)
- deck.gl WebGPU status by release:
  - v9.0 (21 Mar 2024): foundation only.
  - v9.2 (7 Oct 2025): "WebGPU Early Preview" for LineLayer, PointCloudLayer and ScatterplotLayer only.
  - v9.3 (13 Apr 2026): experimental.
  - v9.4 (5 Sep 2026): every catalogue layer runs on WebGPU, but "WebGPU support remains experimental and is not yet recommended for production".
  - [deck.gl What's New](https://deck.gl/docs/whats-new)
- OffscreenCanvas: Chrome 69+, Firefox 105+, Safari 16.4+ (search summary). `transferControlToOffscreen()` has been available across browsers since March 2023 and is one-way: after the handover the main thread can no longer draw on that canvas. Apps embedding WKWebView on iOS ≤ 16.3 do not see OffscreenCanvas (search summary). — [MDN transferControlToOffscreen](https://developer.mozilla.org/en-US/docs/Web/API/HTMLCanvasElement/transferControlToOffscreen); [web.dev OffscreenCanvas](https://web.dev/articles/offscreen-canvas)
- `getContext("webgl2")` on an OffscreenCanvas inside a worker works in Safari 17 / iOS 17 (search summary). — [mdn/browser-compat-data #21127](https://github.com/mdn/browser-compat-data/issues/21127)

#### Canvas 2D limits (measured elsewhere)
- Cytoscape.js on an M1 MacBook Pro in Chrome:
  - EnrichmentMap, ~1,200 nodes / 16,000 edges: Canvas "about 20 FPS", WebGL "over 100 FPS".
  - NDEx network, 3,200 nodes / 68,000 edges: Canvas "crawls at 3 FPS", WebGL "improves to 10 FPS".
  - The WebGL renderer rasterises nodes with the Canvas renderer into a sprite sheet and uses it as a texture. Bezier edges become straight-segment polylines. Dashed edges and gradients are unsupported.
  - Their advice: "most applications that use Cytoscape.js probably don't need the WebGL renderer".
  - [Cytoscape.js WebGL renderer preview, Jan 2025](https://blog.js.cytoscape.org/2025/01/13/webgl-preview/)
- Earlier Cytoscape canvas reports: 2,643 nodes / 4,903 edges at ~5 fps (Firefox 85, 4K screen, i7-9700); a 286-node / 288-edge graph at ~50 ms per render (~20 fps). These come from a search summary of the Cytoscape.js threads; I did not open them, so which thread holds which number is unverified. — [cytoscape.js #2798](https://github.com/cytoscape/cytoscape.js/issues/2798); [discussion #3088](https://github.com/cytoscape/cytoscape.js/discussions/3088)
- NetV.js (WebGL, Visual Informatics 2021) visualises "up to 50 thousand nodes and 1 million edges" at an interactive frame rate on a commodity computer. D3.js and Stardust.js reach ~100k total elements, while NetV.js reaches ~1M elements at ≥ 1 fps (search summary of the paper). — [NetV.js](https://www.sciencedirect.com/science/article/pii/S2468502X21000048)
- acatalogue's current Canvas renderer is already batched: one `beginPath`/`stroke` per edge group (broader, related or semantic), arcs batched per alpha bucket, and labels drawn with `fillText` after a greedy screen-space `RectGrid` collision test with 48-px cells. — [viz/src/render.ts](../../viz/src/render.ts); [viz/src/grid.ts](../../viz/src/grid.ts)

#### WebGL2 techniques: instancing, point sprites vs quads, SDF circles, readback
- MDN WebGL best practices:
  - Batch draw calls ("If you have 1000 sprites to paint, try to do it as a single drawArrays() or drawElements() call") and use instanced drawing.
  - Never call `getError()` in production, and avoid synchronous `readPixels()`; both force a flush and a round trip. Use `PIXEL_PACK_BUFFER` plus `fenceSync` for async readback.
  - Effectively all systems guarantee only `ALIASED_POINT_SIZE_RANGE` [1,100]. Use quads for larger sprites.
  - Float textures are not guaranteed renderable; WebGL2 needs `EXT_color_buffer_float`.
  - To trade quality for speed, render into a smaller back buffer.
  - Size the canvas with `ResizeObserver` using `device-pixel-content-box`.
  - [MDN WebGL best practices](https://developer.mozilla.org/en-US/docs/Web/API/WebGL_API/WebGL_best_practices)
- sigma.js renderer programs:
  - `NodePointProgram` uses `gl.POINTS`. It is "highly RAM and speed efficient" but limited to a 100 px radius.
  - `NodeCircleProgram` draws triangles with the circle "carved" in the fragment shader.
  - `EdgeLineProgram` draws 1-px lines and is the most efficient.
  - `EdgeRectangleProgram` (the default) draws thick edges from triangles.
  - [sigma.js Renderers](https://www.sigmajs.org/docs/advanced/renderers/)
- sigma.js 3.0 (March 2024) moved to instanced rendering: a per-item buffer plus a per-vertex buffer. It also moved to colour-ID picking, which "would eliminate the need for managing the quadtree". — [OuestWare: sigma.js 3.0](https://www.ouestware.com/2024/03/21/sigma-js-3-0-en/)
- A sigma v4 exists only as a beta ("This is the v4-beta website"). — [v4.sigmajs.org](https://v4.sigmajs.org/)
- deck.gl performance guide:
  - On 2015 MacBook Pros, up to ~1M items render "fluidly at 60 FPS" during pan and zoom.
  - 10M items drop to "low double digits (10-20FPS)".
  - Beyond ~10M items, the browser memory limit (Chrome caps allocations at 1 GB) causes crashes.
  - A 10M-point ScatterplotLayer at 5-px radius means "up to 1 billion fragment shader invocations per frame".
  - For maximum throughput, supply typed arrays directly via `data.attributes`.
  - [deck.gl performance](https://deck.gl/docs/developer-guide/performance)
- regl-scatterplot renders "up to 20 million points (depending on your hardware)". Its performance mode draws squares with alpha blending disabled; the README example uses `pointSize` 0.25 for 20M points. Lasso selection uses a KDBush spatial index. — [regl-scatterplot](https://github.com/flekschas/regl-scatterplot)
- Embedding Atlas (Apple, 2025):
  - Rendering is WebGPU. A vertex shader generates quads and a fragment shader makes circles and writes order-independent transparency.
  - The KDE density map runs in a WebGPU compute kernel (Deriche approximation).
  - On an M1 Pro, 1600×1600 view at 2× scale: above 60 fps up to 4M points, ~25 fps at 10M+.
  - Density mode with 5M points at 3840×2160: 46 → 33 fps.
  - [Embedding Atlas, arXiv 2505.06386](https://arxiv.org/html/2505.06386)
- GPU text for labels: multi-channel signed distance fields (MSDF) reproduce sharp glyph corners "almost perfectly". msdf-atlas-gen packs glyph atlases from TTF/OTF files. — [msdfgen](https://github.com/Chlumsky/msdfgen); [Chlumský et al., CGF 2018](https://onlinelibrary.wiley.com/doi/abs/10.1111/cgf.13265)

#### GPU graph engines and their numbers
- cosmos.gl:
  - "All the computations and drawing occur on the GPU in fragment and vertex shaders".
  - Real-time simulation of "hundreds of thousands of points and links on modern hardware".
  - MIT licence. `randomSeed` is an init-only config field.
  - Unsupported on Android devices that lack `OES_texture_float`. The iOS `EXT_float_blend` problem is resolved.
  - [cosmos.gl README](https://github.com/cosmosgl/graph)
  - The OpenJS Foundation announcement says "over one million nodes and links". — [OpenJS: Introducing cosmos.gl](https://openjsf.org/blog/introducing-cosmos-gl)
- cosmos.gl releases:
  - v2.4.0 (26 Aug 2025): 8 point shapes.
  - v2.6.1 (15 Nov 2025): pinned points (fixed positions that still take part in forces).
  - v3.0.0 (17 Jun 2026): ported from regl to luma.gl (WebGL 2); async init with a `ready` promise; "GPU transitions".
  - v3.1.0 (30 Jun 2026): GPU collision force on a spatial-hash grid.
  - v3.4.0 (27 Jul 2026): rebuilt repulsion for dense graphs, GPU pixel-level picking for hover, point occlusion culling, and on-demand rendering that stops when idle.
  - [cosmos.gl releases](https://github.com/cosmosgl/graph/releases)
- Cosmograph (Nightingale):
  - CPU layouts "usually choking at around 100,000 nodes".
  - Demo sizes: 133K nodes / 321K edges; 475,448 nodes / 1,014,134 edges.
  - The simulation "runs on a square grid". Space size is limited, and many nodes in one cell produce "computational artifacts".
  - A naive many-body port to the GPU is slow because of random memory access.
  - [Nightingale: How to Visualize a Graph with a Million Nodes](https://nightingaledvs.com/how-to-visualize-a-graph-with-a-million-nodes/)
- Graphistry 2.53.0's blog title claims "10 million edges in 537 MB of browser memory". The page body could not be retrieved. Graphistry pairs server GPUs with a WebGL client. — [Graphistry blog](https://www.graphistry.com/blog/graphistry-2-53-0-large-graph-visualization-at-10-million-edges)
- Carina (2017): WebGL; "does not store the full graph in RAM"; graphs "with up to 69M edges". — [Carina, arXiv 1702.07099](https://arxiv.org/abs/1702.07099)

#### Edges at scale (culling, aggregation, bundling)
- sigma.js ships performance switches `hideEdgesOnMove` and `hideLabelsOnMove` (both default false). Edge events are off by default (`enableEdgeEvents: false`). — [sigma settings.ts](https://github.com/jacomyal/sigma.js/blob/main/packages/sigma/src/settings.ts)
- KDEEB (kernel density estimation edge bundling):
  - Method: KDE density map → move edge sample points up the normalised gradient → optional Laplacian smoothing → repeat with shrinking kernels.
  - "Easily accelerated using texture splatting".
  - Demonstrated on graphs of up to ~900k edges (Amazon, 899,792 edges).
  - [KDEEB](https://www.cs.rug.nl/svcg/Shapes/KDEEB)
- CUBu (GPU bundling) bundles "up to a million edges at interactive framerates" and is ">50 times faster" than comparable methods (abstract, search summary). — [CUBu](https://www.researchgate.net/publication/289569911_CUBu_Universal_Real-Time_Bundling_for_Large_Graphs)
- Zinsmaier et al. (TVCG 2012) combine density-based node aggregation with edge cumulation on the GPU, with no precomputed hierarchy. Render times stay nearly constant, below 1 s, up to ~10^6 edges (search summary). — [Zinsmaier et al.](https://graphics.uni-konstanz.de/publikationen/Zinsmaier2012InteractiveLevelDetail/Zinsmaier2012InteractiveLevelDetail.pdf)

### Inferences
- WebGL2 is the only renderer that is both fast enough and available everywhere acatalogue will be opened in 2026. WebGPU is missing on most Linux GPUs and in Firefox for Linux and Android. It should be an optional accelerator, mainly for compute, never a requirement.
- **Superseded patterns:**
  - `gl.POINTS` for sprites larger than 100 px → instanced quads (MDN; sigma).
  - WebGL1 `ANGLE_instanced_arrays` → WebGL2 core instancing.
  - Synchronous `readPixels` picking → async PBO readback (MDN).
  - WebGL 2.0 Compute → WebGPU.
- A hand-written WebGL2 renderer is small and fits the no-bundler, no-dependency rule. It needs three instanced programs:
  - particles: a quad per particle with an SDF circle antialiased by `smoothstep` over `fwidth`;
  - edges: instanced quads, or 1-px `LINES` at low zoom;
  - glow: additive halos driven by the existing energy array.
  Labels stay on a Canvas 2D overlay because their count is bounded by the label grid (Q4).
- Libraries do not fit well:
  - sigma.js requires graphology.
  - cosmos.gl requires luma.gl. Its fixed GPU force model cannot express acatalogue's ring spring, cutoff kernel and glow energy.
  - deck.gl is map-oriented and heavy.
  All three bring their own camera and simulation models, which would have to be overridden to keep "motion is physics".
- Canvas 2D threshold for acatalogue (transferred, not measured): the Cytoscape data put the Canvas bottleneck between ~1.6×10^4 edges (20 fps) and ~7×10^4 edges (3 fps) on an M1. acatalogue's plain arcs and lines are cheaper than Cytoscape's styled elements, so its limit may be somewhat higher.
- At 10^6 particles and the current packing of 700 world-units² per particle (`ring.nodeArea`), the layout disc is ≈ 2·√(10^6·700/π) ≈ 29,900 world units across. Fitted into ~1,000 CSS px, that is ≈ 1.3 particles per CSS px². At low zoom, individual dots are meaningless; use density (KDE) or aggregate particles (Q4).
- Rendering in a worker via OffscreenCanvas is supported widely enough (Safari 16.4+, WebGL in workers on Safari 17+), but its benefit is secondary. WebGL work is mostly GPU-side, while physics is the main-thread hog. Do physics-in-worker first (Q2).

### Gaps
- No acatalogue-specific Canvas 2D vs WebGL2 frame times; no headless browser was available.
- A claim that sigma.js "renders 100k edges easily … struggles with 5k nodes with icons" appeared only in a search summary of unclear provenance. Not used.
- Graphistry's "up to 8MM nodes + edges; older client GPUs 100K–2MM elements" appeared only in a search summary and was not found on the pygraphistry README.
- sigma v4's rendering changes are not described on the beta landing page.
- regl's own maintenance status was not checked. cosmos.gl leaving regl in v3.0 is suggestive, not proof.

## Q2. Layout computation at scale: Barnes-Hut in workers, SharedArrayBuffer and isolation, GPU layouts, multilevel methods, convergence, determinism

### Takeaway
Measured on this container, acatalogue's own CPU repulsion costs ~10–12 ms per step at 10^4 particles, ~110 ms at 10^5 and ~1.4 s at 10^6. At the current constants the Barnes-Hut far field is never actually used: the 65-unit cutoff makes it an exact neighbour search. Whole-graph live physics in JavaScript therefore ends around 10^4 particles at the 120 Hz step rate. Beyond that there are two proven routes:
1. A multilevel or offline ("baked") layout, with live physics only where the user interacts.
2. The GPU. The best published WebGPU result is 94,893 nodes / 6.6M edges at 5.48 ms per iteration on a laptop RTX 4070.

Only CPU code with a fixed operation order and a seeded initialisation is deterministic. JavaScript `Math.*` and GPU floating point are not bit-exact across engines or devices.

### Cited Findings

#### Measured (this session): acatalogue's own repulsion kernel
- Setup: `repulsionBarnesHut` (leaf-group tree walk, bucket 12, θ = 0.8, softening 6, smooth cutoff 35→65, k = 600) on seeded uniform discs at the layout's packing density of 700 units²/particle ([bh_bench.mjs](/tmp/claude-0/-home-user-acatalogue/0c6b5ec4-d312-5493-9173-1d9be46979db/scratchpad/bh_bench.mjs) running [viz/src/physics.ts](../../viz/src/physics.ts) via `viz/dist`):

  | Particles | With cutoff (ms/step) | Without cutoff (ms/step) |
  |---|---|---|
  | 10^3 | 1.41 | 1.35 |
  | 10^4 | 10.49 | 13.28 |
  | 10^5 | 105.9 | 156.5 |
  | 10^6 | 1,429 | not run |

  Repeat runs varied: 10.5–12.3 ms at 10^4, 106–120 ms at 10^5, 1,429–1,471 ms at 10^6.
- Accuracy: at n = 5,000 the maximum force error of the current Barnes-Hut against the O(n²) `repulsionBrute` is 1.14×10⁻¹³ (max |F| = 218). The far-field approximation is effectively never taken because every distant cell lies beyond the cutoff. θ buys nothing at these constants. — [grid_bench.mjs](/tmp/claude-0/-home-user-acatalogue/0c6b5ec4-d312-5493-9173-1d9be46979db/scratchpad/grid_bench.mjs)
- A plain uniform grid visited in particle order was only 1.0–1.5× faster (7.3 / 86.6 / 1,389 ms at 10^4 / 10^5 / 10^6). Memory locality dominates. — [grid_bench.mjs](/tmp/claude-0/-home-user-acatalogue/0c6b5ec4-d312-5493-9173-1d9be46979db/scratchpad/grid_bench.mjs)
- A cache-friendly cell list computes the identical force (max error vs brute force 1.07×10⁻¹³) at 2.0–2.6× the speed of the current Barnes-Hut, still on one thread. It counting-sorts particles into 65-unit cells, keeps sorted copies of x/y/q, and sweeps cells in order, reading 3×3 neighbourhoods as contiguous row spans. — [grid2_bench.mjs](/tmp/claude-0/-home-user-acatalogue/0c6b5ec4-d312-5493-9173-1d9be46979db/scratchpad/grid2_bench.mjs)

  | Particles | Sorted cell list (ms/step) | Current Barnes-Hut (ms/step) |
  |---|---|---|
  | 10^4 | 6.09 | 12.3 |
  | 10^5 | 53.6 | 119.5 |
  | 10^6 | 558 | 1,471 |

- Frame budgeting in acatalogue (code read):
  - Fixed `dt = 1/120` s. Each frame runs at least one step, then stops at 4 steps or when the elapsed time plus the predicted next step would exceed `frameBudgetMs = 10`.
  - Leftover accumulator time is dropped (`clamped`).
  - Sleep triggers when mean kinetic energy stays below 1.0 for 90 steps.
  - [viz/src/physics.ts](../../viz/src/physics.ts)

#### Barnes-Hut, d3-force, ForceAtlas2
- Barnes & Hut (1986): hierarchical O(n log n) force calculation. — [Nature 324:446–449](https://doi.org/10.1038/324446a0)
- d3-force `forceManyBody`: θ defaults to 0.9. A quadtree is built "for each application". Each application costs O(n log n). `distanceMin` defaults to 1 and `distanceMax` to ∞; a finite `distanceMax` "can be set to improve performance with localized layouts". — [d3-force many-body](https://d3js.org/d3-force/many-body)
- ForceAtlas2 (Jacomy et al. 2014):
  - Repulsion is proportional to (deg+1)·(deg+1). LinLog mode "converges slowly in some cases". Gravity and strong gravity are available.
  - Barnes-Hut "may be counter-productive on small networks".
  - Adaptive local speed comes from per-node "swinging". Global speed balances swinging against "effective traction".
  - The benchmark covered 68 networks of 5–23,133 nodes.
  - "ForceAtlas2 is not adapted to networks bigger than 100,000 nodes, unless allowed to work over several hours."
  - [ForceAtlas2, PLOS ONE](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0098679)
- graphology ForceAtlas2:
  - `barnesHutTheta` defaults to 0.5.
  - `inferSettings()` turns `barnesHutOptimize` on when `order > 2000` and sets gravity 0.05, scalingRatio 10, slowDown `1 + Math.log(order)`.
  - `FA2Layout` runs the layout in a web worker.
  - [graphology FA2 docs](https://graphology.github.io/standard-library/layout-forceatlas2.html); [source](https://github.com/graphology/graphology/blob/master/src/layout-forceatlas2/index.js)

#### Workers, SharedArrayBuffer, cross-origin isolation
- SharedArrayBuffer requires a secure context and cross-origin isolation; check `crossOriginIsolated` in both window and worker. Without isolation, `postMessage` of a SharedArrayBuffer throws. `Atomics` is always available. Shared memory was disabled at the start of 2018 because of Spectre and re-enabled in 2020 behind isolation. — [MDN SharedArrayBuffer](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/SharedArrayBuffer)
- Cross-origin isolation needs two headers:
  - `Cross-Origin-Opener-Policy: same-origin`;
  - `Cross-Origin-Embedder-Policy: require-corp` or `credentialless`. `credentialless` loads no-CORS cross-origin resources without cookies or credentials.
  - (search summary of MDN) [MDN COEP](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cross-Origin-Embedder-Policy); [MDN COOP](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cross-Origin-Opener-Policy)
- acatalogue's server writes all response headers in one place (Content-Type, Content-Length, Cache-Control, X-Content-Type-Options), so adding COOP/COEP is local. — [acatalogue/server.py](../../acatalogue/server.py)
- KDBush and Flatbush keep a whole spatial index in a single ArrayBuffer that can be transferred between threads and rebuilt with `.from(data)`. — [KDBush](https://github.com/mourner/kdbush); [Flatbush](https://github.com/mourner/flatbush)

#### GPU force layouts
- GraphWaGu (EGPGV 2022) is the first WebGPU graph system. It runs a modified Fruchterman-Reingold with Barnes-Hut in WebGPU compute shaders, θ default 0.8. — [GraphWaGu (EG digital library)](https://diglib.eg.org/items/b9dc1e24-9dea-4483-9229-f40315220a29); [npm graphwagu](https://www.npmjs.com/package/graphwagu)
- Dyken, Usher, Petruzza, Sintos, Kumar, "Accelerating Web-Based Graph Drawing with Bottom-Up GPU Quadtree Construction" (NSF PAR record; c. 2025, benchmarks run with Node v22.12). All from the [paper](https://par.nsf.gov/servlets/purl/10610241):
  - Problem: GraphWaGu builds its quadtree single-threaded and top-down.
  - Method: sort vertices by Hilbert code and build the quadtree bottom-up in parallel in WebGPU, with a lower-memory depth-first traversal.
  - Speed-ups over GraphWaGu: 15.7–69.5× on an RTX 4070 Laptop GPU and 15.0–35.2× on Intel Iris Xe (i9-13900H, D3D12 backend).
  - pkustk13 (94,893 nodes / 6,616,827 edges): 5.48 ms per iteration ("182fps"); 1,000 iterations in 5.48 s.
  - comYoutube (1,134,890 nodes / 5,975,248 edges) is computable in the browser.
  - GraphWaGu hit memory errors on finance512 (74,752 nodes / 261,120 edges), pkustk13 and comYoutube.
  - All runs used approximation factor 2 and a cooling factor of 0.95–0.99.
- cosmos.gl's GPU many-body (v1.x configuration wiki, search summary):
  - `simulationRepulsionTheta` default 1.15;
  - `useClassicQuadtree` default false;
  - `simulationRepulsionQuadtreeLevels` default 12.
  - v3.4 "rebuilt repulsion" may have changed these.
  - [cosmos.gl legacy v1.x configuration](https://github.com/cosmosgl/graph/wiki/Legacy-v1.x-Cosmos-configuration); [releases](https://github.com/cosmosgl/graph/releases)
- GPU FM³ (Godiyal, Hoberock, Garland, Hart, GD 2008), all from [Godiyal et al.](https://mgarland.org/files/papers/layoutgpu.pdf):
  - Method: a k-d tree built and traversed on the GPU.
  - Speed-ups: 20–60× faster than CPU FM³ and 1.3–4× faster than a previous GPU layout.
  - Examples on a GeForce 8800 GTX: fe_ocean (143,437 v / 409,593 e) in 12.07 s; bcsstk32 (44,609 v / 985,046 e) in 1.99 s.
  - CPU FM³ spends 85.5% of its cycles computing forces.
  - The GPU version spends 18–25% of its time on CPU↔GPU data movement.

#### Multilevel layouts
- sfdp (Hu 2005, *Mathematica Journal* 10(1):37–71) is a multilevel scheme to escape local minima plus Barnes-Hut long-range approximation, in O(V log V). It ships in Graphviz. — [Graphviz sfdp](https://graphviz.org/docs/layouts/sfdp/); [Hu's SFDP page](https://yifanhu.net/SOFTWARE/SFDP/index.html) (search summary)
- FM³ (Hachul & Jünger, GD 2004) runs in O(|V| log |V| + |E|) worst case (search summary). — [Hachul & Jünger](https://link.springer.com/chapter/10.1007/978-3-540-31843-9_29)
- OpenOrd (Martin et al., SPIE 2011) extends VxOrd with edge cutting, a multilevel scheme, average-link clustering and parallel threads. It anneals through five phases: liquid, expansion, cool-down, crunch, simmer. It is "one of the few force-directed layout algorithms that can scale to over 1 million nodes" (search summary). — [Gephi OpenOrd wiki](https://github.com/gephi/gephi/wiki/OpenOrd); [SPIE paper](https://www.spiedigitallibrary.org/conference-proceedings-of-spie/7868/786806/OpenOrd-an-open-source-toolbox-for-large-graph-layout/10.1117/12.871402.short)

#### Determinism, stability, timestep
- "Many `Math` functions have a precision that's *implementation-dependent* … different browsers can give a different result. Even the same JavaScript engine on a different OS or architecture can give different results!" — [MDN Math](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Math)
- The WGSL specification has normative subsections "Differences from IEEE-754", "Floating Point Accuracy" and "Reassociation and Fusion" (§15.7). GPU floating point is specified to tolerances, not bit-exact results. — [W3C WGSL](https://www.w3.org/TR/WGSL/)
- Preserving the mental map in a changing graph gave significantly faster performance and fewer errors on orientation tasks (search summary of the abstract). — [Archambault & Purchase, GD 2012](https://link.springer.com/chapter/10.1007/978-3-642-36763-2_42)
- Fix Your Timestep:
  - Variable `dt` changes behaviour, "as extreme as your spring simulation exploding to infinity".
  - Use a fixed `dt` with an accumulator, and clamp the frame time to avoid the "spiral of death".
  - Render by interpolating the previous and current states with `alpha = accumulator/dt`.
  - [Fiedler, Fix Your Timestep](https://gafferongames.com/post/fix_your_timestep/)

### Inferences
- Threshold, derived from the measurements:
  - The 120 Hz step rate allows 8.3 ms per step. One core meets that only up to roughly 0.8–1.4×10^4 particles (current Barnes-Hut vs sorted cell list), counting repulsion alone.
  - With the "≥ 1 step per frame" rule, 10^4 particles means ~12 ms of physics in every frame: the simulation falls to about half real time and the frame rate drops.
  - At 10^5, each frame carries ~110 ms of physics (~9 fps, ~7% of real time).
  - At 10^6, each frame carries ~1.4 s.
- A module worker with transferable buffers needs no COOP/COEP. It protects input and render latency but does not raise the particle ceiling. A 4-worker SharedArrayBuffer partition would, by arithmetic rather than measurement, raise the ceiling roughly 3–4× to ~3–5×10^4. That requires COOP/COEP headers, which fit in `server.py`.
- At the current constants θ is irrelevant. The cutoff kernel is a local interaction, which is why a cell list (uniform grid or spatial hash, as in cosmos.gl's v3.1 collision force) is the natural CPU and GPU data structure. If long-range repulsion is ever used (for example, for domain-level spacing), θ ≈ 0.8–1.0 is standard: d3 uses 0.9, GraphWaGu 0.8, graphology 0.5.
- Two routes for 10^5–10^6:
  1. **Bake:** compute canonical rest positions offline. This can use the same compiled `viz/dist/physics.js` in Node, which this session imported directly, so there is one force law and no new dependency. The browser then simulates only perturbations near the interaction.
  2. **GPU:** WebGPU compute with a fallback, because of the Linux and Firefox-Android gaps.
- acatalogue's SKOS hierarchy (13 domains → concepts → entities) is a ready-made coarsening. A multilevel "place level by level, refine locally" schedule gets the sfdp/FM³/OpenOrd benefit (escaping local minima, near n log n cost) without matching-based coarsening.
- Deterministic contract:
  - Canonical positions come only from CPU code with a seeded init, a fixed iteration order and a fixed step count, ideally baked once. Golden tests compare with a tolerance, because `Math.exp`/`sin`/`cos` differ across engines (MDN).
  - GPU or live results are "presentation", never canonical, because WGSL permits reassociation and fusion.

### Gaps
- FM³ CPU timings ("<2, 24, 263 s" for graphs under 10^3 / 10^4 / 10^5 nodes on a 2.8 GHz PC) appeared only in a search summary. Not verified.
- No verified numbers for GPU ForceAtlas2 variants (Brinkmann, Rietveld, Takes, ICPP 2017; RAPIDS cuGraph). Not retrieved.
- Dyken et al.'s absolute Iris Xe iteration times were not extracted; only the speed-ups were.
- Multi-worker SharedArrayBuffer scaling for acatalogue's kernel was not measured.
- The algorithm and determinism of cosmos.gl v3.4's "rebuilt repulsion" are undocumented in what I read.

## Q3. Semantic layouts: UMAP/PaCMAP/t-SNE projections, combining projection with force refinement, stability across updates

### Takeaway
The initialisation matters more than the choice between UMAP and t-SNE (Kobak & Linderman). acatalogue already computes an informative seed at no cost: `xy`, the first two principal components of its LSA-48 concept vectors. The browser physics parses it but never uses it. Use it, or an offline UMAP/PaCMAP projection initialised from it, as weak anchor springs under the hierarchy and ring forces. Keep updates stable by anchoring existing nodes to their previous positions and placing new ones with a transform or at their parent's position.

### Cited Findings
- acatalogue `semantic.py` computes a "2-D seed layout": the principal components of the L2-normalised LSA vectors, scaled to [-1, 1], stored in a `layout` table per model and emitted as `xy` per node. — [acatalogue/semantic.py](../../acatalogue/semantic.py); [acatalogue/views.py](../../acatalogue/views.py)
- In the browser, `data.ts` parses `xy`, but a search of `viz/src` shows no other use. — [viz/src/data.ts](../../viz/src/data.ts)
- The shipped model is `lsa-tfidf-svd-48`, with k = 6 semantic neighbours per concept (`--k` default). — [viz/data/graph.json](../../viz/data/graph.json); [acatalogue/cli.py](../../acatalogue/cli.py)
- umap-js:
  - API: `fit`, `fitAsync` (per-epoch callback), `initializeFit` + `step()` + `getEmbedding()`, `transform` (new points after fitting), `setSupervisedProjection(labels)`.
  - Defaults: nNeighbors 15, minDist 0.1, spread 1.0; `random` is `Math.random` and can be replaced with a seeded generator.
  - "The optimization step is seeded with a random embedding rather than a spectral embedding", because eigen-solvers "are not easily done in JS".
  - [umap-js](https://github.com/PAIR-code/umap-js)
- Kobak & Linderman (Nature Biotechnology 2021): UMAP's apparent global-structure advantage over t-SNE came entirely from informative initialisation. Informative (PCA/spectral) initialisation is necessary to preserve global structure (search summary). — [Kobak & Linderman](https://www.nature.com/articles/s41587-020-00809-z)
- PaCMAP (Wang, Huang, Rudin, Shaposhnik, JMLR 22(201), 2021) derives principles for attractive and repulsive forces on neighbours versus further points, and uses highly weighted "mid-near" pairs to keep global structure (search summary). — [JMLR](https://jmlr.org/papers/v22/20-1061.html)
- AlignedUMAP optimises several embeddings jointly. `alignment_regularisation` weights alignment against layout quality, and `alignment_window_size` sets how many neighbouring datasets are considered. `update()` "will append a new embedding … aligned with what has been seen so far". — [umap-learn AlignedUMAP](https://umap-learn.readthedocs.io/en/latest/aligned_umap_basic_usage.html)
- openTSNE can add new data points to an existing embedding. It is FFT-accelerated and "can scale to millions of data points". — [openTSNE](https://github.com/pavlin-policar/openTSNE)
- WizMap (ACL 2023 demo):
  - Builds a quadtree over embedding points and extracts keywords per tree node with efficient branch aggregation.
  - Summarising 1.8M text embeddings at three granularity levels takes ~55 s on a MacBook Pro.
  - Uses WebGL and Web Workers with no backend (abstract, search summary).
  - [WizMap, arXiv 2306.09328](https://arxiv.org/abs/2306.09328)
- deepscatter:
  - Claims over a billion points, with examples of 5.5M tweets and 1M+ arXiv documents.
  - Data ships as Apache Arrow feather tiles "in a custom quadtree format that makes it possible to only load data as needed on zoom".
  - Renders with WebGL via REGL.
  - `x0`/`y0` columns drive animated transitions.
  - [deepscatter](https://github.com/nomic-ai/deepscatter)
- Embedding Atlas accepts precomputed 2D coordinates or computes UMAP in the browser (WASM). Density-based clustering yields automatic labels. — [Embedding Atlas](https://arxiv.org/html/2505.06386)

### Inferences
- A semantic map is compatible with "the circle of learning emerges from physics" if semantics enter as a weak anchor spring, F_i = −k_a (x_i − a_i):
  - a_i is the projected point mapped into the particle's domain sector, for example by projecting per domain and scaling into that sector.
  - k_a ≪ the hierarchy spring (`broader.k = 12`), so ring and hierarchy decide global structure and semantics decides local order.
  - Anchors also stabilise the layout under updates (mental map; Archambault & Purchase).
- Zero-dependency first step: use the existing PCA `xy` both as initial positions (informative init, per Kobak & Linderman) and as anchor targets.
- Next step: for 10^5–10^6 entities, compute UMAP or PaCMAP offline (seeded, PCA-initialised) as an optional Python extra. The existing extra `semantic = ["numpy"]` is the precedent. Ship the result as float32 tiles.
- In-browser umap-js is not advisable at 10^5+. It uses random initialisation, which is a global-structure risk, and its speed at that scale is undocumented.
- Update policy:
  1. Existing nodes keep their baked positions as anchors.
  2. New nodes enter via `transform` (umap-js or openTSNE), or at their parent's position plus a seeded offset.
  3. Large corpus changes trigger an AlignedUMAP-style re-bake with alignment regularisation.

### Gaps
- No measured umap-js runtimes at 10^4–10^6 points.
- No JavaScript PaCMAP port verified (not searched exhaustively).
- Parametric UMAP not researched.
- No published evaluation found of "projection-anchored force refinement" for knowledge graphs specifically. The anchor-spring design above is inference.

## Q4. Level of detail and labels: hierarchical aggregation, label placement and collision at scale, semantic zoom, clustering

### Takeaway
Build LOD from acatalogue's own hierarchy: domains at low zoom, concepts at mid zoom, entities at high zoom. Aggregates are real particles whose mass is the sum of their members'. Make label visibility a pure function of zoom, precomputed as "active ranges" that satisfy Been, Daiches and Yap's consistency rules (no popping, no dependence on navigation history). Resolve residual collisions with a greedy, priority-ordered screen grid (as in sigma.js and Mapbox). Fade labels with the same first-order decay as the glow. Use Leiden, not Louvain, only where no hierarchy exists.

### Cited Findings
- Been, Daiches, Yap, "Dynamic Map Labeling" (InfoVis 2006):
  - Static labeling is "NP-hard" in most formulations, and even an O(n log n) solution "is too slow during interaction". Their map of the USA has "over 12 million labels".
  - Desiderata:
    - (D1) labels should not vanish when zooming in or appear when zooming out, except when sliding in or out of the view;
    - (D2) a visible label's position and size change continuously under pan and zoom;
    - (D3) labels should not vanish or appear during panning;
    - (D4) "placement and selection of any label is a function of the current map state (scale and view area) … not … the history".
  - Solution: move all selection and placement decisions into preprocessing. Each label gets an *active range* [s_min, s_max] of scales.
  - [Been et al.](https://cs.nyu.edu/~visual/home/pub/infovis06.pdf)
  - The 2006 paper's TVCG DOI is [10.1109/tvcg.2006.136](https://doi.org/10.1109/tvcg.2006.136).
  - Follow-up: Been, Nöllenburg, Poon, Wolff, "Optimizing active ranges for consistent dynamic map labeling", CGTA 43(3):312–328, 2010. It was named in a search summary; no link retrieved.
- sigma.js label grid ([labels.ts](https://github.com/jacomyal/sigma.js/blob/main/packages/sigma/src/core/labels.ts); [settings.ts](https://github.com/jacomyal/sigma.js/blob/main/packages/sigma/src/settings.ts)):
  - The viewport is split into constant-size cells (`labelGridCellSize` default 100).
  - Candidates in each cell are ranked by node size (descending), then by key as a deterministic tie-break.
  - Labels shown per cell = `ceil(scaledCellArea × density / cellArea)`, with `scaledCellArea = cellArea / ratio²`.
  - Defaults: `labelDensity` 1, `labelRenderedSizeThreshold` 6.
  - Edge labels show when an endpoint is highlighted or hovered, or when both endpoint labels are shown.
- Mapbox GL JS (search summary of the PR):
  - Collision detection moved to a global viewport-space grid index, computed synchronously in the foreground.
  - Fades are time-based rather than zoom-based.
  - A `CrossTileSymbolIndex` stops the same symbol fading out and in when crossing zoom-level tiles.
  - [mapbox-gl-js PR #5150](https://github.com/mapbox/mapbox-gl-js/pull/5150)
- Flatbush (static packed Hilbert R-tree), measured on an M1 Pro with Node 24:
  - indexing 1,000,000 rectangles: 109 ms;
  - 100 searches at 10% area: 64 ms;
  - 10,000 searches at 0.001% area: 31 ms.
  - Supports kNN via `neighbors()`.
  - [Flatbush](https://github.com/mourner/flatbush)
- KDBush is a static flat kd-tree for points that uses about half of Flatbush's memory, with `range` and `within` queries. — [KDBush](https://github.com/mourner/kdbush)
- Embedding Atlas uses fast 2D-density clustering to produce labels, placed with a "map-like de-overlapping algorithm that maintains consistency while zooming". — [Embedding Atlas](https://arxiv.org/html/2505.06386)
- GraphMaps builds "a sequence of layers, where each layer refines the previous one". The number of entities rendered in any view stays below a threshold, and geometry is stable. — [GraphMaps, arXiv 1506.06745](https://arxiv.org/abs/1506.06745)
- Leiden (Traag, Waltman, van Eck 2019): Louvain produces "up to 25% of the communities … badly connected and up to 16% … disconnected". Leiden "yields communities that are guaranteed to be connected", converges iteratively to partitions whose subsets are locally optimally assigned, and "runs faster than the Louvain algorithm". — [arXiv 1810.08473](https://arxiv.org/abs/1810.08473)
- Leiden in JavaScript:
  - ngraph.leiden: MIT; modularity and CPM with a resolution parameter; `randomSeed` for "deterministic, reproducible partitions"; young (11 commits, 3 stars when read). — [ngraph.leiden](https://github.com/anvaka/ngraph.leiden)
  - graphology ships Louvain. — [graphology-communities-louvain](https://www.npmjs.com/package/graphology-communities-louvain)
  - `leiden-ts` 0.1.0 and a repackaged `graphology-communities-leiden` exist (search). — [leiden-ts](https://libraries.io/npm/leiden-ts); [aflsolutions fork](https://github.com/aflsolutions/graphology-communities-leiden)
- acatalogue today places labels with a screen-space `RectGrid` (48-px cells) and greedy collision each frame. — [viz/src/grid.ts](../../viz/src/grid.ts)

### Inferences
- LOD bands for acatalogue (inference). Aggregate particles are physical (mass = sum of members, position = centre of mass), so zooming changes which bodies are drawn, not how motion works.

  | Zoom | Draw | Labels | Edges |
  |---|---|---|---|
  | z0 (fit) | 13 domain aggregates on the ring; density or halo for their members | domain labels | aggregated domain↔domain edges, width = link count |
  | z1 | concepts (10^3–10^4) | by active range | hierarchy edges of the focused domain |
  | z2 | entities (10^5–10^6), streamed per tile | only above a priority cut | only the focus neighbourhood |

- Deterministic label priority: depth (domain > concept > entity), then coverage (language editions), then degree, then id. This mirrors sigma.js's size-then-key rule.
- Active-range precomputation (offline or in a worker at load): walk zoom levels from coarse to fine and place labels greedily by priority into a collision grid. A label becomes active at the first level where it fits and, per D1, stays active when zooming in. At runtime, selection is O(visible): show a label if it is in view and zoom ≥ s_min. The existing `RectGrid` stays as a final safety pass.
- Label opacity should follow first-order decay toward a target, dE/dt = (target − E)/τ, as the glow does. That is physical, matches Mapbox's time-based fades, and removes popping.
- Leiden is needed only for hierarchy-less entity sets (for example, raw Wikidata items). Run it offline (Python `leidenalg`, or `ngraph.leiden` in Node, seeded) and ship the result as a hierarchy level. Louvain is superseded for this use.

### Gaps
- The cost of precomputing active ranges for 10^6 labels was not measured.
- Been et al.'s own timing numbers were not extracted.
- Christensen–Marks–Shieber point-label heuristics were not retrieved.

## Q5. Interaction and accessibility (keyboard, screen readers, reduced motion, colour vision) and hit-testing at scale

### Takeaway
Two accessibility items are correctness requirements, not polish:
- **Pause control.** A pause/stop mechanism is WCAG Level A whenever automatic motion lasts more than 5 s alongside other content. At 10^5 nodes, settling will exceed 5 s unless the layout is baked.
- **Non-visual route.** The data needs a keyboard and screen-reader path: an APG tree of the hierarchy, lazily loaded, with graph neighbours as navigable lists.

For hit-testing, a CPU uniform grid or kd-tree in the worker is enough up to 10^6 points. GPU colour picking only pays off for non-circular marks or GPU-resident positions, and then needs async readback.

### Cited Findings
- WCAG 2.2 SC 2.2.2 Pause, Stop, Hide (Level A):
  - "For any moving, blinking or scrolling information that (1) starts automatically, (2) lasts more than five seconds, and (3) is presented in parallel with other content, there is a mechanism for the user to pause, stop, or hide it unless … essential".
  - "Starts automatically" includes starting from indirect interaction such as focusing, hovering or scrolling into view.
  - Related: SC 2.3.3 Animation from Interactions.
  - [WCAG 2.2 Understanding 2.2.2](https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide.html)
- WCAG 2.2 SC 2.3.3 Animation from Interactions (AAA): motion animation triggered by interaction can be disabled unless essential. — [Understanding 2.3.3](https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions.html)
- WCAG 1.4.1 Use of Color (A): colour must not be the only visual means of conveying information. — [Understanding 1.4.1](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html)
- WCAG 1.4.11 Non-text Contrast (AA): graphical objects required for understanding need ≥ 3:1 contrast against adjacent colours. — [Understanding 1.4.11](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html)
- `prefers-reduced-motion: reduce` signals that the user asked to minimise non-essential motion. — [MDN prefers-reduced-motion](https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion)
- APG Tree View pattern ([APG Tree View](https://www.w3.org/WAI/ARIA/apg/patterns/treeview/)):
  - Keys: Right opens a node or moves to its first child; Left closes a node or moves to its parent; Up and Down move without opening or closing; Home and End; type-ahead; `*` expands siblings; Enter activates.
  - Roles: `tree` / `treeitem` / `group`, with `aria-expanded` on parents.
  - Lazy loading: "If the complete set of available nodes is not present in the DOM due to dynamic loading … each node has aria-level, aria-setsize, and aria-posinset specified".
  - `aria-activedescendant` is an alternative to moving DOM focus.
- Data Navigator (Elavsky, Nadolskis, Moritz; IEEE TVCG 2023) is built on a dynamic graph structure. It lets developers construct "navigable lists, trees, graphs, and flows as well as spatial, diagrammatic, and geographic relations" and supports screen reader, keyboard, speech, gesture and fabricated devices. It can add accessible navigation on top of raster images. — [arXiv 2308.08475](https://arxiv.org/abs/2308.08475); [cmudig/data-navigator](https://github.com/cmudig/data-navigator)
- Chartability (Elavsky, Bennett, Moritz; EuroVis 2022, CGF 41:57–70) is a set of heuristics for "visual, motor, vestibular, neurological, and cognitive accessibility" of data visualisations and interfaces. Novice practitioners were more confident auditing with it. — [Chartability](https://chartability.fizz.studio/); [paper PDF](https://www.domoritz.de/papers/2022-Chartability.pdf)
- Zong et al., "Rich Screen Reader Experiences for Accessible Data Visualization" (EuroVis 2022). Only the title and link were seen this session. — [arXiv 2205.04917](https://arxiv.org/pdf/2205.04917)
- Hit-testing and picking:
  - sigma.js draws a second image in which every item has a unique colour. — [sigma.js Renderers](https://www.sigmajs.org/docs/advanced/renderers/)
  - deck.gl picking renders every pickable layer offscreen and "can only distinguish between 16M items per layer" across up to 256 layers. — [deck.gl performance](https://deck.gl/docs/developer-guide/performance)
  - Synchronous `readPixels` costs a "finish + round-trip", so async PBO readback is recommended. — [MDN WebGL best practices](https://developer.mozilla.org/en-US/docs/Web/API/WebGL_API/WebGL_best_practices)
  - cosmos.gl 3.4 added GPU pixel-level picking for hover. — [releases](https://github.com/cosmosgl/graph/releases)
  - regl-scatterplot uses KDBush for lasso selection. — [regl-scatterplot](https://github.com/flekschas/regl-scatterplot)
- acatalogue today (code read):
  - Keyboard pan (arrows), zoom (+/-), fit (0), `/` focuses search, Escape clears.
  - The canvas has `role="img"` with an `aria-label`; status regions use `aria-live="polite"`; search results are an `<ol>`; the coverage legend has an `aria-label`.
  - Reduced motion: the camera cuts instantly and the simulation pre-settles and freezes.
  - Hit-testing uses a uniform `PointGrid`.
  - No tree view and no explicit pause control were found.
  - [viz/index.html](../../viz/index.html); [viz/src/main.ts](../../viz/src/main.ts); [viz/src/camera.ts](../../viz/src/camera.ts); [viz/src/grid.ts](../../viz/src/grid.ts)

### Inferences
- **2.2.2 (Level A).** Today the simulation sleeps after ~0.75 s of calm (mean KE < 1 for 90 steps at 1/120 s), so post-load motion for 966 nodes is probably under 5 s. At 10^4–10^5 nodes, settling will exceed 5 s unless the layout is baked (R1). Add a visible Pause/Freeze control now, with a keyboard shortcut. It is cheap and future-proof. Measure time-to-sleep at each scale as a test.
- **Tree alternative.** The left work panel should hold an APG tree of the hierarchy (lazy, with `aria-level`/`setsize`/`posinset` so it scales to 10^6) and a "neighbours" list per focused node for related, crosswalk and semantic links, following Data Navigator's graph navigation. The field mirrors keyboard focus: the camera spring retargets and the glow pulses. One structure serves screen readers, keyboard users, and the "table/tree view" alternative.
- **Colour.** With density rendering at low zoom, the coverage ramp must not be the only carrier; show the numeric language count in the tree, inspector and tooltip (1.4.1). Verify the accent against both Papyrus `#f4eedf` and Sea backgrounds at ≥ 3:1 (1.4.11) using the owner's palette validator.
- **Hit-testing.** Rebuild the uniform `PointGrid` in the physics worker: O(n) per rebuild, O(1) per query, zero dependencies. For static baked tiles, a per-tile KDBush index (a transferable ArrayBuffer) avoids rebuilds. Use GPU colour picking only if positions ever live only on the GPU (WebGPU simulation, R11), and then with async readback of a few pixels.

### Gaps
- No empirical study found specifically on screen-reader navigation of graphs with 10^5+ nodes.
- No colour-vision-deficiency simulation or contrast measurement of acatalogue's actual Papyrus/Sea palette was run here.
- Zong et al.'s content was not opened.

## Q6. Physics-based UI motion: critically damped springs, stable at variable frame rates

### Takeaway
acatalogue's camera is already a critically damped spring on (x, y, log-zoom), stepped at a fixed 1/120 s with an accumulator. It is stable. The exact closed-form critically damped step (Holden) makes it exact at any timestep, removes the catch-up loop, and restores the stated stiffness: measured, the ω = 42 drag spring settles 16% slower under semi-implicit Euler at 120 Hz than it should. Particle physics must stay fixed-step. When it moves to a worker, render by interpolating the last two physics states. That samples the physical trajectory and is not a tween.

### Cited Findings
- Holden, "Spring-It-On" ([theorangeduck.com](https://theorangeduck.com/page/spring-roll-call)):
  - Exact critically damped update, with `y = d/2` and goal `c`:
    ```
    j0 = x − c
    j1 = v + j0·y
    e  = exp(−y·dt)
    x  = e·(j0 + j1·dt) + c
    v  = e·(v − j1·y·dt)
    ```
  - `fast_negexp(x) = 1/(1 + x + 0.48x² + 0.235x³)` can replace `exp`.
  - A half-life parameterisation is recommended. The damping ratio is r = d/(2√s), where r = 1 means critically damped.
  - Velocity stays continuous when the goal is retargeted.
  - The fetch summary adds that the exact form is unconditionally stable, whereas semi-implicit Euler becomes unstable at large damping·dt.
- Apple WWDC23 "Animate with springs" (search summary): springs are specified by duration and bounce. A retargeted spring uses its current velocity as the initial velocity toward the new destination, which keeps interruptions smooth. Presets: smooth (no bounce), snappy, bouncy. — [WWDC23 session 10158](https://developer.apple.com/videos/play/wwdc2023/10158/)
- van Wijk & Nuij (InfoVis 2003) give a metric for simultaneous zooming and panning based on perceived velocity. From it they derive optimal, smooth and efficient transitions between two views (search summary). — [van Wijk & Nuij](https://vanwijk.win.tue.nl/zoompan.pdf)
- Fiedler: fixed timestep, accumulator, and interpolation `alpha = accumulator/dt`. — [Fix Your Timestep](https://gafferongames.com/post/fix_your_timestep/)
- acatalogue camera:
  - Acceleration a = ω²(target − x) − 2ωv, integrated with semi-implicit Euler at `PHYSICS.dt` = 1/120 s.
  - ω = 9 rad/s for zoom, fly-to and fit; ω = 42 rad/s while dragging.
  - `maxStepsPerFrame` 24; the zoom target is in log space.
  - Reduced motion makes every change an instant cut.
  - [viz/src/camera.ts](../../viz/src/camera.ts)
- acatalogue glow: `E *= exp(−dt/τ)` with τ = 0.9 s, which is exact for dE/dt = −E/τ. — [viz/src/physics.ts](../../viz/src/physics.ts)
- Measured (this session), 1% settle time from rest ([spring_check.mjs](/tmp/claude-0/-home-user-acatalogue/0c6b5ec4-d312-5493-9173-1d9be46979db/scratchpad/spring_check.mjs)):

  | ω (rad/s) | Continuous solution | Exact step | Semi-implicit Euler @ 120 Hz |
  |---|---|---|---|
  | 9 | 738 ms | 742 ms | 767 ms (+4%) |
  | 42 | 158 ms | 158 ms | 183 ms (+16%) |

- Measured (this session): the ω = 42 spring was also stepped at the frame rate instead of the fixed 1/120, reading x(0.1 s) from x₀ = 1. Semi-implicit Euler at 30 Hz diverges to −14.0. The exact step gives 0.0780 at 30, 60 and 240 Hz alike. The 144 Hz run is not comparable because 0.1 s is not a whole number of its steps. — [spring_check.mjs](/tmp/claude-0/-home-user-acatalogue/0c6b5ec4-d312-5493-9173-1d9be46979db/scratchpad/spring_check.mjs)

### Inferences
- **Camera.** Replace `Camera.step` with Holden's exact form (same ω, y = ω) and advance it by the real frame dt, clamped as now. The accumulator and the 24-step cap become unnecessary. Behaviour becomes frame-rate independent and exactly critically damped, which is still "motion is physics".
- **Particles.** Keep the fixed step: forces are nonlinear, so no closed form exists. Add render interpolation once physics runs in a worker at 120 Hz against displays at 60, 120 or 144 Hz.
- **Long fly-tos at 10^6 scale.** Following van Wijk & Nuij's perceived-velocity argument without writing a tween: schedule the spring targets.
  1. Set the zoom target to the view that fits both the start and the goal.
  2. Once the pan error drops below a threshold, set the zoom target to the final zoom.
  Every frame remains a spring integration; only the targets change.
- **Retargeting.** Keep it velocity-preserving, as the current state-carrying spring already is, in line with the WWDC23 advice.

### Gaps
- No user study found comparing spring-driven and tweened camera motion for graph navigation specifically.

## Q7. Prioritized recommendations for acatalogue: architecture, library or hand-written, and the threshold at which each becomes necessary

### Takeaway
Priority order:
- **P0, now:** make the layout a baked, deterministic function of (data, seed), and close the Level-A accessibility gaps.
- **P1, before ~10^4 nodes:** move physics to a worker, write a WebGL2 instanced renderer, and make labels consistent across zoom.
- **P2, 10^5–10^6:** hierarchy LOD, semantic anchors, binary tiles, and offline clustering.
- **P3, optional:** WebGPU compute, exact camera springs, edge bundling.

Everything except the optional WebGPU path is hand-written with zero runtime dependencies. The decisive evidence: measured JavaScript physics cost (10^4 ≈ 10–12 ms per step, 10^5 ≈ 110 ms), Cytoscape's Canvas-vs-WebGL numbers, the WebGPU platform gaps, and deck.gl still calling WebGPU experimental in September 2026.

### Cited Findings
- Measured physics costs and the exact equivalence of the current Barnes-Hut to a cutoff neighbour search: Q2, [bh_bench.mjs](/tmp/claude-0/-home-user-acatalogue/0c6b5ec4-d312-5493-9173-1d9be46979db/scratchpad/bh_bench.mjs), [grid2_bench.mjs](/tmp/claude-0/-home-user-acatalogue/0c6b5ec4-d312-5493-9173-1d9be46979db/scratchpad/grid2_bench.mjs).
- Payload today: `viz/data/graph.json` is 308,631 bytes for 966 nodes and 3,798 edges, ≈ 64.8 bytes per element. At that rate, 10^6 nodes plus 4×10^6 edges would be ≈ 324 MB of JSON. Measured (this session) — [viz/data/graph.json](../../viz/data/graph.json)
- Canvas vs WebGL: [Cytoscape.js WebGL preview](https://blog.js.cytoscape.org/2025/01/13/webgl-preview/). WebGL2 capacity: [deck.gl performance](https://deck.gl/docs/developer-guide/performance); [regl-scatterplot](https://github.com/flekschas/regl-scatterplot).
- WebGPU availability: [gpuweb Implementation Status](https://github.com/gpuweb/gpuweb/wiki/Implementation-Status); [deck.gl What's New](https://deck.gl/docs/whats-new). WebGPU layout speed: [Dyken et al.](https://par.nsf.gov/servlets/purl/10610241).
- Determinism: [MDN Math](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Math); [WGSL](https://www.w3.org/TR/WGSL/). Mental map: [Archambault & Purchase](https://link.springer.com/chapter/10.1007/978-3-642-36763-2_42).
- Labels: [Been et al.](https://cs.nyu.edu/~visual/home/pub/infovis06.pdf); [sigma labels.ts](https://github.com/jacomyal/sigma.js/blob/main/packages/sigma/src/core/labels.ts). Accessibility: [WCAG 2.2.2](https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide.html); [APG Tree View](https://www.w3.org/WAI/ARIA/apg/patterns/treeview/). Motion: [Holden](https://theorangeduck.com/page/spring-roll-call).

### Inferences
Each recommendation states what it relates to, the threshold at which it becomes necessary, whether to hand-write it or use a library, and its evidence (receipt).

#### P0: now (at 966 nodes)
- **R1. Bake the layout** (determinism and truth; all scales; hand-written, zero dependencies).
  - Compute canonical rest positions at build time by running the same compiled `viz/dist/physics.js` in Node. This session imported it from Node without changes.
  - Use a seeded init from the PCA `xy` and a fixed step count. Store the result as a new model in the existing `layout` table.
  - The browser starts at rest and simulates only perturbations: drag, focus pulses, data updates.
  - Threshold: cheap now; mandatory by ~10^4 nodes, where live settling costs ≥ 10 ms per step (measured).
  - Receipts:
    - JavaScript physics cost (Q2);
    - FA2 "not adapted to >100,000 nodes unless … several hours" ([Jacomy et al.](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0098679));
    - cross-engine `Math` drift ([MDN](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Math));
    - mental-map benefit ([Archambault & Purchase](https://link.springer.com/chapter/10.1007/978-3-642-36763-2_42));
    - Been's D4 principle applied to positions ([Been et al.](https://cs.nyu.edu/~visual/home/pub/infovis06.pdf)).
- **R2. Accessibility baseline** (access and truth for all users; hand-written DOM).
  - A visible Pause/Freeze control with a key binding, required under 2.2.2 once motion lasts more than 5 s.
  - An APG tree of the hierarchy in the work panel, with lazy `aria-level`/`setsize`/`posinset`, plus neighbour lists per focused node. Keyboard focus drives the camera spring.
  - Numeric coverage values next to the ramp, and a ≥ 3:1 accent check against both themes.
  - Threshold: now. 2.2.2 becomes binding the moment settling exceeds 5 s, which is certain at 10^5 without R1.
  - Data Navigator is a design reference, not a required dependency.
  - Receipts: [WCAG 2.2.2](https://www.w3.org/WAI/WCAG22/Understanding/pause-stop-hide.html), [APG Tree View](https://www.w3.org/WAI/ARIA/apg/patterns/treeview/), [Data Navigator](https://arxiv.org/abs/2308.08475), [WCAG 1.4.1](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html), [WCAG 1.4.11](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html), [Chartability](https://chartability.fizz.studio/).

#### P1: before ~10^4 nodes / ~2×10^4 edges
- **R3. Physics in a module worker** (main-thread latency; hand-written).
  - The worker owns the `Sim` and posts Float32 position snapshots as transferables, ping-ponging two buffers.
  - The main thread renders by interpolating the last two snapshots with `alpha = accumulator/dt`.
  - Replace the repulsion tree walk with the sorted cell list: identical forces, 2.0–2.6× faster (measured).
  - No COOP/COEP needed. Add `Cross-Origin-Opener-Policy: same-origin` and `Cross-Origin-Embedder-Policy: require-corp` in `server.py` only if a later multi-worker SharedArrayBuffer split is wanted (~3–5×10^4 live particles, unmeasured).
  - Threshold: when a physics step exceeds ~4 ms, which on this CPU is ≈ 3–4×10^3 particles by linear scaling of the measurements.
  - Receipts: Q2 measurements; [MDN SharedArrayBuffer](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/SharedArrayBuffer); [MDN COEP](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cross-Origin-Embedder-Policy); [Fix Your Timestep](https://gafferongames.com/post/fix_your_timestep/).
- **R4. Hand-written WebGL2 renderer** (throughput; ~3 instanced programs; zero dependencies).
  - Particles: instanced quads with an SDF circle (antialiased) and an additive glow halo.
  - Edges: instanced thick quads, or 1-px `LINES` at low zoom, with per-kind alpha. One draw call per layer.
  - Labels: kept on a Canvas 2D overlay.
  - Keep the current Canvas 2D path as a fallback (no WebGL2, or context lost).
  - Avoid `gl.POINTS` for anything that can exceed 100 px.
  - Threshold: before ~2×10^4 edges or ~5×10^3 nodes. Cytoscape measured 20 fps at 16k edges and 3 fps at 68k edges on Canvas.
  - Receipts: [Cytoscape](https://blog.js.cytoscape.org/2025/01/13/webgl-preview/); [MDN best practices](https://developer.mozilla.org/en-US/docs/Web/API/WebGL_API/WebGL_best_practices); [sigma renderers](https://www.sigmajs.org/docs/advanced/renderers/); [deck.gl](https://deck.gl/docs/developer-guide/performance) (1M items at 60 fps); [Embedding Atlas](https://arxiv.org/html/2505.06386).
  - Why not a library: sigma.js requires graphology; cosmos.gl requires luma.gl and has a fixed force model; deck.gl is heavy. All would replace acatalogue's camera and physics.
- **R5. Consistent labels** (truth of reading: no popping; hand-written).
  - Precompute each label's active zoom range by greedy priority placement over coarse-to-fine zoom levels. Priority: depth > language editions > degree > id.
  - At runtime: visible ∧ zoom ≥ s_min, then the existing `RectGrid` as a final pass.
  - Opacity follows first-order decay toward its target, like the glow.
  - Threshold: now for correctness; essential at ≥ 10^4 labels.
  - Receipts: [Been et al. D1–D4](https://cs.nyu.edu/~visual/home/pub/infovis06.pdf); [sigma label grid](https://github.com/jacomyal/sigma.js/blob/main/packages/sigma/src/core/labels.ts); [Mapbox time-based fades](https://github.com/mapbox/mapbox-gl-js/pull/5150).
- **R6. Hit-testing moves with the positions** (correctness under scale).
  - Keep the uniform `PointGrid`, rebuilt in the worker.
  - For static tiles, use per-tile KDBush, either vendored (small) or as a hand-written flat kd-tree.
  - Use GPU colour picking only with R11, and then with async readback.
  - Receipts: [KDBush](https://github.com/mourner/kdbush), [Flatbush](https://github.com/mourner/flatbush) (1M rectangles in 109 ms), [MDN readPixels warning](https://developer.mozilla.org/en-US/docs/Web/API/WebGL_API/WebGL_best_practices), [deck.gl picking limits](https://deck.gl/docs/developer-guide/performance).

#### P2: 10^5–10^6 concepts and entities
- **R7. Hierarchy LOD with physical aggregates** (legibility and fragment cost).
  - Show domains, then concepts, then entities by zoom band.
  - Aggregate particle = summed mass at the centre of mass.
  - Draw edges only for the focus neighbourhood plus aggregated domain↔domain edges at low zoom.
  - Hide non-focus edges while the camera is moving.
  - At fit zoom with 10^6 particles (≈ 1.3 per px², computed), draw density or aggregates instead of dots.
  - Live physics runs only in the "awake region" (viewport ∪ k-hop of the interaction). Other particles stay pinned at baked positions, as with cosmos.gl's pinned points, which still exert force.
  - Threshold: above ~5×10^4 nodes or ~2×10^5 edges.
  - Receipts: [Zinsmaier et al.](https://graphics.uni-konstanz.de/publikationen/Zinsmaier2012InteractiveLevelDetail/Zinsmaier2012InteractiveLevelDetail.pdf); [GraphMaps](https://arxiv.org/abs/1506.06745); [sigma hideEdgesOnMove](https://github.com/jacomyal/sigma.js/blob/main/packages/sigma/src/settings.ts); [deck.gl fragment cost](https://deck.gl/docs/developer-guide/performance); [Embedding Atlas density mode](https://arxiv.org/html/2505.06386); [cosmos.gl v2.6.1 pinned points](https://github.com/cosmosgl/graph/releases).
- **R8. Semantic anchors** (meaning in position; zero dependencies first, optional Python extra second).
  - First, use the existing PCA `xy`, mapped into each domain's sector, as initialisation and as weak anchor springs (k_a ≪ 12).
  - Second, for entities, bake UMAP or PaCMAP offline with a seed and PCA initialisation.
  - On updates, anchor old nodes to their baked positions and place new ones via `transform` or at the parent's position plus a seeded offset.
  - Receipts: [Kobak & Linderman](https://www.nature.com/articles/s41587-020-00809-z), [umap-js](https://github.com/PAIR-code/umap-js), [AlignedUMAP](https://umap-learn.readthedocs.io/en/latest/aligned_umap_basic_usage.html), [openTSNE](https://github.com/pavlin-policar/openTSNE), [Archambault & Purchase](https://link.springer.com/chapter/10.1007/978-3-642-36763-2_42).
- **R9. Binary, tiled data transport** (memory and load time).
  - Nodes as float32 x/y plus small integer attributes; edges as uint32 pairs plus a kind byte.
  - Organise the data as a quadtree of tiles loaded by zoom, as in deepscatter; label strings load per tile.
  - Rough arithmetic: ~56 MB for 10^6 nodes + 4×10^6 edges, versus ~324 MB as JSON.
  - Threshold: when the JSON exceeds ~5–10 MB, which at 64.8 B per element is ≈ 10^5 elements.
  - Receipts: measured payload ([graph.json](../../viz/data/graph.json)); [deepscatter](https://github.com/nomic-ai/deepscatter); [deck.gl binary attributes](https://deck.gl/docs/developer-guide/performance); [Graphistry "10M edges in 537 MB"](https://www.graphistry.com/blog/graphistry-2-53-0-large-graph-visualization-at-10-million-edges).
- **R10. Offline Leiden** for entity sets without a hierarchy (aggregation truth).
  - Seeded, and shipped as a hierarchy level.
  - Receipts: [Leiden](https://arxiv.org/abs/1810.08473) (Louvain produces up to 25% badly connected and 16% disconnected communities); [ngraph.leiden](https://github.com/anvaka/ngraph.leiden).

#### P3: optional, ≥ 10^5 live or 10^6 live
- **R11. WebGPU compute accelerator** (live global motion at scale).
  - Port the cutoff kernel as a GPU cell list or spatial hash (the cosmos.gl v3.1 approach), or a Hilbert bottom-up quadtree (Dyken et al.) if long-range forces return.
  - Feature-detect `navigator.gpu`. Fall back to R1 + R7 on Linux (most GPUs), Firefox Linux/Android, and older devices.
  - Results are presentation-only, never canonical.
  - Using cosmos.gl instead is possible (MIT, WebGL2, GPU simulation, "hundreds of thousands" of points), but it trades away acatalogue's force law, and its luma.gl dependency must work without a bundler (unverified).
  - Receipts: [Dyken et al.](https://par.nsf.gov/servlets/purl/10610241) (94,893 nodes / 6.6M edges at 5.48 ms per iteration); [gpuweb status](https://github.com/gpuweb/gpuweb/wiki/Implementation-Status); [deck.gl 9.4: WebGPU "not yet recommended for production"](https://deck.gl/docs/whats-new); [WGSL reassociation/fusion](https://www.w3.org/TR/WGSL/); [cosmos.gl](https://github.com/cosmosgl/graph).
- **R12. Motion polish.** Adopt the exact critically damped camera step (16% truer drag response, exact at any dt, per the Q6 measurements), render interpolation (R3), and target-scheduled zoom-out/pan/zoom-in for long fly-tos. — [Holden](https://theorangeduck.com/page/spring-roll-call); [van Wijk & Nuij](https://vanwijk.win.tue.nl/zoompan.pdf); [WWDC23](https://developer.apple.com/videos/play/wwdc2023/10158/)
- **R13. Cosmetic extras**, last:
  - KDEEB-style density-gradient bundling, which is itself a physical relaxation, only for aggregated domain↔domain edges.
  - Order-independent transparency for dense overlaps.
  - MSDF glyph atlases, if labels ever move to the GPU.
  - Receipts: [KDEEB](https://www.cs.rug.nl/svcg/Shapes/KDEEB); [CUBu](https://www.researchgate.net/publication/289569911_CUBu_Universal_Real-Time_Bundling_for_Large_Graphs); [Embedding Atlas](https://arxiv.org/html/2505.06386); [msdfgen](https://github.com/Chlumsky/msdfgen).

#### Threshold summary (inference from the receipts above)
Physics columns are measured on this container. Rendering columns are transferred from Cytoscape, deck.gl and Embedding Atlas.

| Scale (nodes / edges) | Physics | Rendering | Labels / LOD | Data |
|---|---|---|---|---|
| ≤ 5×10^3 / ≤ 2×10^4 (today 966 / 3,798) | Main-thread CPU is fine (1.4 ms/step at 10^3) | Canvas 2D is fine | `RectGrid` greedy + active ranges (R5) | JSON (309 KB) is fine |
| 5×10^3 – 5×10^4 / ≤ 2×10^5 | Worker + sorted cell list (R3); optional SharedArrayBuffer workers | WebGL2 instanced (R4) | Active ranges; hide non-focus edges while moving | Float32 binary |
| 5×10^4 – 10^6 / ≤ 4×10^6 | Baked layout (R1) + awake-region physics (R7) | WebGL2; density/aggregates at low zoom | Hierarchy LOD bands; per-tile labels | Quadtree tiles (R9) |
| ≥ 10^5 live global motion | WebGPU compute (R11), with R1 + R7 fallback | WebGL2 (or WebGPU) | Same | Same |

#### Superseded or not-yet-ready techniques to avoid
- WebGL 2.0 Compute (obsolete).
- `gl.POINTS` sprites above 100 px.
- Synchronous `readPixels` picking.
- Louvain as the aggregation basis (use Leiden).
- Random-init UMAP/t-SNE for global structure.
- CPU ForceAtlas2 or d3-force for whole graphs above ~10^5 nodes.
- GraphWaGu's single-threaded top-down quadtree (superseded by bottom-up Hilbert construction).
- regl-based cosmos (≤ v2), superseded by the luma.gl v3.
- WebGPU-only libraries in production (deck.gl still experimental as of 9.4).

### Gaps
- None of the rendering thresholds were measured on acatalogue's own renderer; a browser benchmark harness is needed (for example, Playwright in CI).
- Module-worker support across all target browsers was not re-verified this session. It matters for R3 with plain ES modules and no bundler.
- The awake-region rule (which particles to integrate after a local perturbation) is a design inference with no measured energy or stability behaviour yet.
- Whether cosmos.gl and luma.gl can load as plain ES modules through an import map without a bundler was not verified.
- Settle time to sleep at 10^4–10^5 particles was not measured; it determines when WCAG 2.2.2 binds.
