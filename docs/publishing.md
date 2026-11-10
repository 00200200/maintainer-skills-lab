# Marketplace bundles (v1)

Python 3.11+ and its standard library are sufficient. From the repository root:

```sh
python3 tools/publish_marketplace.py validate
python3 tools/publish_marketplace.py build --version 1.2.3
python3 tools/publish_marketplace.py build --version 1.2.3 --output-dir /tmp/mkl-release
```

`validate` reads the Claude marketplace metadata and its local plugin sources,
calls `kit.check_library()` for skill descriptions, agent dependencies and token
budgets, and compares checked-in Claude and Cursor files with `kit.export_files()`.
Missing, changed or extra provider files fail validation. Regenerate stale exports
with `python3 tools/kit.py sync`; validation and building never sync them implicitly.
Validation writes no release artifacts.

The existing library's hard budgets apply, including the 60-token description
limit. Advisory token warnings remain warnings, including bodies over 800 tokens;
the tool does not impose the original issue's proposed 800-token hard limit.
Token counting follows `kit.py`, which works without third-party packages and
uses its optional tokenizer when available. Reports include advisory warnings.

There is no dependency on `pyproject.toml`. Versions use SemVer without a leading
`v`, for example `1.2.3` or `1.2.3-rc.1`. Existing version fields in marketplace
metadata, plugin entries and plugin manifests must agree with each other and with
`--version`. Absent version fields remain absent; the release version determines
artifact names. Source metadata is never rewritten. Local `./directory` plugin
sources are supported; remote sources, traversal and symlinks are rejected.
Strict plugins require a `.claude-plugin/plugin.json` with a matching name.

After validation, `build` writes these files into `dist/` by default:

- `maintainer-skills-lab-claude-v1.2.3.zip`: `.claude-plugin/`, all source `skills/`
  and `agents/`, the Claude exports under `providers/claude/.claude/`, and every
  local plugin source at its original path. Both current marketplace entries
  therefore resolve after extraction.
- `maintainer-skills-lab-cursor-v1.2.3.zip`: the complete
  `providers/cursor/.cursor/` tree, including skills, agents and generated rules,
  plus root `.cursorrules` if present. Copy the extracted `.cursor` tree from
  `providers/cursor/` into the destination project.
- `checksums.txt`: SHA-256 of the exact bytes of both ZIPs, with sorted filenames
  and two spaces between the digest and filename.

Both archives also include root `README.md` and `LICENSE`. ZIP entry paths have
no enclosing release directory. Entries are sorted and stored without compression,
with a fixed timestamp and Unix file mode `0644`, independent of source timestamps,
permissions and zlib versions. Identical inputs and version produce identical
ZIP bytes and checksums. Run packaged Python helpers with `python3`.

All inputs and ZIPs are prepared before writing output. Files are staged, then
replaced; a failed replacement rolls back previously replaced artifacts and keeps
unrelated output files. This handles ordinary build/I/O errors, not power loss,
process termination during replacement, concurrent builds into the same directory,
or a second filesystem failure during rollback. Use a separate output directory
for concurrent builds.

This command builds local bundles only. It does not publish, generate release
notes or add release automation. Validation covers source and export consistency;
it does not establish live marketplace acceptance or client execution.
