# The knowledge map panel: an agent's knowledge as a graph on its dashboard

A service whose agent keeps a knowledge layer (the agents database's decision D-84; [agent knowledge](agent-knowledge.md),
Part 4) can show it on its dashboard: the nodes of its knowledge, the links between them and their clusters, read from
the layer's eighth part, the map `knowledge-map/1`. This page is the recipe: the data the panel reads, the five
renderers the base baked and checked, which one to start from, and the traps already found. It extends the
[dashboard principles](dashboard.md) and the [dashboard kit](dashboard-kit.md); it replaces none of their rules.

The base's board request `599b59d6` (2026-11-19, relayed with the operator's words of 2026-11-19, provenance `trusted`)
asked for it. The five variants and their sources live in the agents database (its report on memory graphs,
2026-11-19); the kit does not ship them yet (backlog FAA-367: a dashboard-kit component with a variant switch).

## Contents

- [The data: `knowledge-map/1`](#the-data-knowledge-map1)
- [The five variants](#the-five-variants)
- [Which one to start from](#which-one-to-start-from)
- [Building the panel](#building-the-panel)
- [Traps already found](#traps-already-found)
- [Proving it](#proving-it)

## The data: `knowledge-map/1`

The service serves the map as JSON from its own API, built by the layer and read by the panel; the panel never builds
it. The shape the base serves today (the agent contract will define the schema; until a pinned contract does, name it
as the base does):

| Field | What |
|---|---|
| `schema` | `"knowledge-map/1"` |
| `built_at`, `revision` | when the map was built and the commit or revision of the knowledge it was built from |
| `embedder` | the local model the semantic links and coordinates came from, e.g. `ollama:embeddinggemma` |
| `degraded` | what is missing from this build (`["vectors"]` when no embedder answered); empty when whole |
| `nodes[]` | `id`, `kind`, `label`, `x` and `y` in `[0, 1]`, `cluster`, `degree` |
| `edges[]` | `source`, `target` and `kind`: `explicit` (a file states it), `semantic` (nearest neighbours no file states) and the layer's other kinds |
| `clusters[]` | `id`, `label` (the cluster's words) and `size` |

A map whose `degraded` is not empty is shown with that sentence beside it ("No semantic links: the local embedder did
not answer at the last build"), never as a whole map. A map older than the knowledge it describes says when it was
built. The panel loads on its own (`Promise.allSettled`): a failed map is one sentence and a retry, and the rest of the
page renders.

## The five variants

Each was baked by the base as a self-contained page and checked in WebKit (Safari's engine) through Playwright with no
script error: data embedded as a JSON block, libraries vendored by version with their licence files, no CDN, no inline
script, light and dark, reduced motion honoured.

| Variant | Shows | Library and licence | Draws with |
|---|---|---|---|
| Circulation | the agent as an organism: flows as particles along layered curves | d3 7.9.2 (ISC) | SVG |
| Living organism | the organism as a left-to-right force graph with directional particles | force-graph 1.52.0 (MIT) | Canvas |
| Atlas | the knowledge graph: clusters by colour, semantic links lighter, hover lights a neighbourhood | sigma 4.0.6 + graphology 0.26.0 (MIT) | WebGL |
| Galaxy | the knowledge graph as a live GPU force simulation that settles into clusters | cosmos.gl 3.6.0 (MIT) | WebGL 2 |
| Semantic map | the embedding space: knowledge placed by meaning, clusters named, zoom and nearest-point hover | d3 7.9.2 (ISC) | Canvas |

Circulation and Living organism read the base's `organism/1` (the agent's parts as layers with health and counts),
not the knowledge map; the other three read `knowledge-map/1`.

Left out by the base, with the reason: Cosmograph and deepscatter (non-commercial licences), Ogma and KeyLines
(commercial), the TensorFlow Embedding Projector (archived), vis-network (slow past a few thousand nodes), Embedding
Atlas (WebGPU only and about 6.6 MB; a sixth variant once the dashboard host runs a WebGPU engine).

## Which one to start from

Start from **Semantic map** for a knowledge base read by a person: it draws on a Canvas with d3 alone, injects no
style, so it runs under the strict CSP the kit's sample service sends (`style-src 'self'`), and its hover answers
"what is near this". Use **Atlas** when the links matter more than the placement (which records point to which), and
**Galaxy** past some ten thousand nodes, where WebGL 2 keeps the frame rate. Atlas and Living organism need the CSP
widened (below); record that decision in the service's own docs with its reason.

## Building the panel

1. Vendor the library files by version into the service's static folder, each with its licence file beside it, and
   list them in the static whitelist; never a CDN (the page works offline).
2. Load the panel's own script as a file (`app.js` or a module beside it); data comes from the service's API, never as
   an inline JSON block in a dynamic page (the base's baked pages embed it only because they are static).
3. Read the theme from the kit's tokens (`data-theme`, `data-scheme`; the host's appearance wins) and redraw on a
   theme change; the canvases read colours from CSS custom properties, never hard-coded.
4. Honour `prefers-reduced-motion`: no particles, no live simulation, the layout settled before the first frame.
5. Keep the facts in words: a side card and a legend name the selected node, its kind, cluster and links; the canvas
   carries an `aria-label`. A screen-reader pass was not part of the base's check: do it before calling the panel done.
6. The panel holds from 360 CSS px (ED-1) inside its own scroll box (ED-4); the graph never makes the document scroll
   sideways.

## Traps already found

- **sigma 4 replaces its default styles.** The `styles` option replaces the standard node and edge styles whole;
  pass your own together with them (`nodes: [Sigma.DEFAULT_STYLES.nodes, {...}]`, `edges: Sigma.DEFAULT_STYLES.edges`),
  or the default drawing is lost.
- **cosmos.gl does not fit the view by itself.** Call `fitView` after the first frame is drawn (and once more after
  the simulation settles), not only at construction, or the graph opens off screen.
- **sigma and force-graph inject styles.** Their pages need `style-src 'self' 'unsafe-inline'`; the d3 variants do
  not. Widen the CSP only on the page that hosts such a variant, never `script-src`.
- **Galaxy logs one `ResizeObserver loop` warning in WebKit.** It is benign; do not count it as a script error, and
  count every other one.
- **Empty texts make false links.** A record whose text lives in a field the embedder does not read embeds as an empty
  string and links to every other such record at similarity 1.0, which also collapses the clusters. The layer refuses
  empty texts before embedding ([agent knowledge](agent-knowledge.md), Part 4); the panel shows a map with a cluster of
  identical coordinates as a finding, not as knowledge.

## Proving it

- Open the dashboard through Fabric Dashboards (the `fabric-dashboards` MCP `link` tool, never a browser) and through
  Safari's engine (Playwright `webkit`) at 360 px and at a wide pane, light and dark, with reduced motion on and off:
  no script error other than the benign one above, no sideways document scroll.
- `check_dashboard_layout.mjs` passes on the page that hosts the panel.
- With the embedder stopped, the next build's map says `degraded` and the panel shows the sentence.
