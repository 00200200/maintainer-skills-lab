# Maintainer Studio v1

Studio is a local, read-only view of the library's skills, agents and provider
exports. It uses `kit.profile_tokens()` directly, preserving its fields and
heuristic encoding label. It provides search, sorting, independent token charts,
reference budgets and manual or periodic refresh. Search resets when switching
categories.

## Install and run

Obtain the complete repository, including `apps/studio/static/`, and use Python
3.11 or newer. No Python packages, Node.js or npm are needed at runtime:

```sh
python3 tools/kit.py studio
```

The command binds only to `127.0.0.1:8765`, serves the production React frontend
at `/` and starts opening that address in the system browser after the socket is
listening. Browser startup runs separately from HTTP handling. If a browser
cannot open, the server keeps running and prints the URL for manual use.

```sh
python3 tools/kit.py studio --no-browser
python3 tools/kit.py studio --port 9000
```

Ctrl+C closes the listening socket. An occupied port produces an error and never
opens the browser. If the shipped `index.html` is missing or unsafe, the Studio
CLI exits with a rebuild hint before binding or opening a browser. Missing
individual assets return 404. Neither startup nor requests build, install, sync
or write repository files.

## Frontend delivery and rebuilding

The source is in `apps/studio/src/`. The generated `apps/studio/static/` directory
is checked in alongside it, so a complete clone or repository source archive
contains the ready-to-run UI. Include the lockfile and regenerated assets in the
same change as frontend source updates; do not edit minified assets manually.
Third-party notices in `public/THIRD_PARTY_NOTICES.txt` are copied into the build;
retain them when distributing ready-to-run assets.

The reference build uses Node.js **22.17.1** and the checked-in npm lockfile:

```sh
cd apps/studio
npm ci --no-audit --no-fund
npm run build
```

`build` runs `tsc --noEmit` followed by `vite build`; Vite replaces only its
`static/` output. Dependencies are locked by `package-lock.json`; `npm ci`
recreates that dependency graph. Tailwind scans only `src/`, excluding generated
assets from its inputs. Source maps are disabled. The same source, lockfile and
reference toolchain should generate the same filenames and bytes; CI enforces
this comparison on Linux rather than claiming cross-platform reproducibility.
Review the generated files before including them with the sources.

The separate Studio job in `.github/workflows/ci.yml` installs the lockfile,
checks TypeScript, builds into runner temporary storage, and compares every
file with `apps/studio/static/`. It uploads that build as `maintainer-studio-assets`.
This artifact is also a way to restore the frontend into `apps/studio/static/`
without Node on the destination machine. Existing library and client jobs keep
their checks and artifacts.

If runtime assets are missing, restore the directory from the matching repository
revision or its matching CI artifact, or rebuild on a machine with Node/npm and
copy the whole generated directory. Do not mix hashed assets from different
builds. The server never downloads frontend assets automatically.

## Development

Run the API with Python in one terminal, and Vite in another:

```sh
python3 tools/studio_server.py
```

```sh
cd apps/studio
npm ci --no-audit --no-fund
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` to `127.0.0.1:8765` and rewrites
Host to the backend's local address. The standalone Python command does not open
a browser and can run the API even when the production frontend is absent; `/`
then returns 503 with a rebuild hint. Frontend and backend remain separate during
Vite development; production uses one Python HTTP server and no Vite process.

## API and security boundaries

- `GET /api/profile` returns the unmodified profiler JSON; `GET /api/health`
  returns `{"status": "ok"}`. Unknown API routes return JSON 404, and methods
  other than GET return 405. Errors never fall through to the React page.
- Host must be exactly `127.0.0.1` or `localhost`, optionally with the actual
  listening port. Foreign, missing and duplicate Host headers are rejected before
  dispatch, including when a forwarded Host header claims to be local. The bind
  address cannot be changed through the CLI.
- The frontend serves only `index.html`, `favicon.svg`, `THIRD_PARTY_NOTICES.txt`
  and recognized asset file types directly under `static/assets/`. Paths are decoded once and matched to
  that allowlist. Symlinks in file paths or the static root are rejected. No
  directory listings, source maps, repository files or arbitrary SPA fallbacks
  are served.
- API responses are not cached; frontend responses require cache revalidation.
  Content types are explicit, `nosniff` is set, and a content security policy
  restricts frontend scripts and connections to the same origin. CORS is not
  enabled. Inline styles are allowed for React's chart dimensions.

This is a local development tool, not a hardened public web server. It has no
authentication or TLS and is not intended for remote access, reverse proxying
or shared hosting. Local users can access the loopback endpoint. Do not expose
it through a tunnel or change the bind address for public use.

## Interpreting results and verification

Skill file totals overlap with their SKILL.md and description counts. Agent
profiles can reference the same skills; provider exports reuse source content.
Studio never adds those overlapping categories into a session total. Reference
budgets compare a selected file estimate with a chosen number, not real context
occupancy or remaining session capacity. Heuristic values are labelled explicitly.
See [the frontend field guide](../apps/studio/README.md#reading-the-dashboard).

Run focused Python tests with `python3 -m unittest discover -s tests -p test_studio.py -v`.
They cover live HTTP, CLI startup without Node on PATH, packaged assets, missing
files, browser launch dispatch, Host checks and traversal/symlink rejection.
The frontend CI build establishes type and generated-asset consistency; it does
not establish browser rendering or live-agent behavior. Composer, replay and
cache simulations are outside v1.
