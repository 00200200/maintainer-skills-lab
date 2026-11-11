# Maintainer Studio

A local, read-only React 19 dashboard for the existing Studio profile API. No
external services, fonts, telemetry or chart libraries. For Python-only startup,
run `python3 tools/kit.py studio` from the repository root. The ready-to-run build
is shipped in `static/`; see [installation and delivery](../../docs/studio.md).

## Development

Use Python 3.11+ for the backend and Node.js 22.12+ with npm for the frontend.
From the repository root, start the API in one terminal:

```sh
python3 tools/studio_server.py
```

In another terminal:

```sh
cd apps/studio
npm ci --no-audit --no-fund
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` to `127.0.0.1:8765` with
`changeOrigin: true` so the backend receives an allowed local Host header. Both
servers bind to loopback. If port 5173 is occupied, Vite exits instead of silently
changing ports. The backend only accepts `localhost` or `127.0.0.1`, optionally
with its actual listening port; foreign, missing and duplicate Host headers fail.

`npm run typecheck` checks TypeScript; `npm run build` checks types and generates
`static/`. Include generated assets with source changes. The checked-in lockfile
and the Node 22.17.1 CI toolchain define the reference build. Production serves
these assets through Python, with no Node/npm runtime process.

## Reading the dashboard

- Skills, Agents and Providers have separate searchable, sortable inventories.
  Select a bar or table name to inspect exact profiler fields. Charts use CSS and
  SVG, support keyboard selection and respect reduced-motion preferences.
- Skill **all file tokens** are `tokens`; **SKILL.md incl. frontmatter** is
  `body_tokens`. Description and SKILL.md counts overlap the skill total. The
  profiler's warning strings are displayed verbatim, even where its warning says
  “body” for a threshold applied to all skill files.
- Agent totals are `total_tokens`: instruction tokens (including the subagent
  handoff protocol where applicable) plus referenced skill content or a lazy
  manifest. Provider estimates cover their complete generated exports. Shared
  source content means totals across agents or providers must not be added.
- Names-only floor and description overhead are separate context baselines from
  `summary`. Neither is added to source-file totals. No combined “session usage”
  figure is calculated.
- Reference budgets are 8,000 / 32,000 / 128,000 / 200,000 / 1,000,000 tokens.
  The percentage compares one selected static estimate with that reference;
  it does not measure runtime context occupancy, headroom or session consumption.
  Over-budget percentages remain visible above 100%; only the ring is capped.
- When `encoding` includes `heuristic`, an amber badge labels the results as
  heuristic estimates. The original encoding label remains visible in the footer.
  Tokenizer-based file counts are still not live-session measurements.
- Manual refresh and optional 15/30/60-second polling fetch fresh profiles without
  overlapping requests. Polling pauses while the page is hidden. Requests time out
  after 30 seconds. Failed refreshes retain the last successful snapshot and its
  timestamp with a visible stale-data message. Unmounting cancels pending requests.

The frontend uses React/React DOM 19, TypeScript, Vite with its React plugin, and
Tailwind CSS 4 with its Vite plugin. See the [Vite requirements](https://vite.dev/guide/)
and [Tailwind Vite setup](https://tailwindcss.com/docs/installation/using-vite).
