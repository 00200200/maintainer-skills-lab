# Optional native helpers (M1/M2/M3/M4/M5)

`msl_core.minify_markdown(text: str) -> str` implements the existing `tools/kit.py`
algorithm in Rust with PyO3. It is a literal compatibility port, not a CommonMark
parser. M2 adds the separate `walk_project()` API and M3 adds exact BPE token
counting. M4 adds standalone Tree-sitter symbol extraction; M5 adds BLAKE3 byte
hashing and a conservative no-change synchronization cache. There is no
dependency graph or new CI.
Python-only users need no Rust tools or additional Python packages.

## Build and install (opt-in)

Use Python 3.11+, a Rust toolchain supporting the declared MSRV (1.74 or newer),
Cargo and a platform linker. The crate pins PyO3 0.27.2 and uses `abi3-py311`.
The build backend is maturin 1.x; it is needed only to build the optional wheel.
From the repository root, create an isolated environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install 'maturin>=1.9,<2'
maturin develop --release --manifest-path crates/msl-core/Cargo.toml
```

On Windows, activate `.venv\Scripts\activate` instead. To build a wheel for an
interpreter/platform supported by the toolchain:

```sh
maturin build --release --manifest-path crates/msl-core/Cargo.toml --out dist/native
```

Install the resulting wheel into the Python environment that runs `kit.py`.
Compiled wheels do not require a Rust toolchain at runtime. Built wheels are
not committed to the repository. The `crates/msl-core/Cargo.lock` file is
included to pin Rust dependencies for reproducible builds and benchmarks.
Update the lockfile deliberately when changing dependencies. MSRV describes the
crate/PyO3 baseline; newly resolved transitive dependencies may need newer Rust.

M2 uses `ignore = 0.4.23`; M3 uses `tiktoken-rs = 0.6.0` with optional features
disabled. The checked-in lockfile already includes the M1–M3 dependencies.

M4 adds Tree-sitter 0.24.7 and pinned ABI-compatible language grammars.
The committed `Cargo.lock` includes these dependencies.

M5 adds `blake3 = 1.5.5`. The committed `Cargo.lock` includes this dependency.

Building M4 also requires the C toolchain used by Tree-sitter's grammar build
scripts. No separate Tree-sitter CLI, grammar download or compiler is needed at
runtime; the generated parsers are linked into the optional extension.

Packaging follows the [maturin pure Rust layout](https://www.maturin.rs/project_layout.html).
See the [PyO3 versioned sources](https://github.com/PyO3/pyo3/tree/v0.27.2) and
[maturin bindings documentation](https://www.maturin.rs/bindings) for platform
and interpreter support. Building requires access to the Rust crates unless
they have already been cached. This is not part of ordinary Python setup.

## Dispatch and compatibility

`tools.kit.minify_markdown()` retains its public signature. When `msl_core` is
absent, it uses the original `_minify_markdown_python()` implementation. When
installed, it calls the native function. Import failures for an installed/broken
extension, missing native dependencies, and errors during native execution are
propagated; they never silently switch to Python. Backend selection happens when
`kit` is imported; restart Python after installing/uninstalling the extension.

The native code retains existing behavior, including:

- Splitting only at LF; no general newline normalization. In particular, CRLF
  closing fences retain the Python recognizer's behavior, and table compaction
  can strip a trailing CR that ordinary prose retains.
- Backtick/tilde fence lengths, zero to three leading ASCII spaces, unclosed
  fences, and unchanged fenced content. Four-space/tab indents are not fences.
- Non-greedy, multiline HTML-comment removal outside protected spans; unclosed
  comments remain literal.
- Unicode table-cell trimming, ASCII-only trailing space/tab removal on ordinary
  lines, and collapsing three or more LF characters to two.
- The original naive pipe splitting and first-occurrence `@@FENCE<n>@@`
  placeholder replacement, including literal-placeholder collision behavior.

Python's UTF-8 `surrogatepass` codec is used at the binding boundary so lone
surrogates round-trip too. The core uses bytes and explicit Python whitespace
rules; it does not call the Python minifier. Codec conversion and allocation
costs are part of the native call and may outweigh benefits on small inputs.

## Verify and measure

```sh
python -m unittest discover -s tests -p 'test_native_minify.py' -v
python -m unittest discover -s tests -p 'test_kit.py' -v
python tools/benchmark_minify.py --size 64 --repeat 5 --iterations 10
```

Dispatch/fallback tests run without the extension; native differential tests
are explicitly skipped when it is absent. An installed but broken extension
fails rather than being skipped. Tests compare tables, comments, mixed line
endings, Unicode, surrogate code points, fence edge cases and repository Markdown
against the unchanged Python reference.

The benchmark uses a fixed synthetic corpus and records its SHA-256, UTF-8 size,
Python/platform and native package version, parameters, samples and medians.
It checks equality first, warms both engines and alternates timing order. Import
and installation time are excluded; Python-to-Rust conversion is included. Use
the same corpus parameters, interpreter, machine, release build and dependency
lockfile to compare runs. A ratio above 1 means a shorter native time for that
corpus; it does not establish a general speedup. Missing native support exits 2
without reporting a comparison; a parity mismatch exits 1 before timing.

No performance measurements or acceleration claims are supplied with M1.

## Project file walker (M2)

```python
import msl_core

paths = msl_core.walk_project("/absolute/project/path", ["*.log", "/scratch/"])
```

`walk_project(root: str, ignore_patterns: list[str]) -> list[str]` discovers text
file candidates using the Rust [`ignore` crate](https://docs.rs/ignore/0.4.23/ignore/).
Scanning uses its parallel walker with two to eight workers, depending on CPU
availability, and releases the Python GIL. Results are unique, sorted relative
paths with `/` separators on every platform. Unicode filenames retain their
spelling. Empty trees return `[]`; directory entries themselves are not returned.
The root must be a directory with no symlink components.

Ignore semantics are deliberately independent of `tools.kit.source_files()`:

- `.gitignore` works without a Git repository. Nested `.gitignore` and
  `.mklignore` files use the crate's Gitignore syntax and directory scoping;
  `.mklignore` has higher priority than `.gitignore`.
- Additional patterns are rooted at the project and use Gitignore syntax:
  `*.log` excludes matching files, `/scratch/` excludes that root directory, and
  `!keep.log` can undo a preceding additional rule. They are a subtractive layer:
  they cannot restore entries excluded by local ignore files or descend into
  already excluded directories.
- Ancestor/global Git rules, `.git/info/exclude`, and `.ignore` are disabled.
  Hidden files are eligible; `.git` entries are always excluded. Rule files
  themselves are eligible unless ignored by a rule.
- File/directory symlinks, broken links, and non-regular files such as FIFOs are
  skipped. A symlink or non-regular `.gitignore`/`.mklignore` in a visited
  directory is rejected before loading its rules.

Binary filtering reads at most the first 8 KiB of each eligible regular file.
A NUL byte or invalid UTF-8 excludes the file; an incomplete UTF-8 character at
the sample boundary is allowed if more bytes exist. Empty files are included.
This is a bounded heuristic, not a complete binary classifier: legacy text
encodings may be excluded, and binary data outside the sample may go unnoticed.
Filename extensions do not determine whether content is text.

Invalid roots, traversal/read failures, and rule-file errors raise `OSError`;
malformed additional patterns (including embedded line breaks or NULs), empty
roots, and non-UTF-8 result paths raise `ValueError`. Python binding type errors
remain `TypeError`. Errors never return a partial list. When simultaneous
failures occur, the first reported diagnostic can vary with scheduling.

Keep the project tree stable during a call. Entry metadata is checked before
opening files, but this API does not provide race-proof filesystem isolation
against concurrent renames or symlink replacement. It does not read full file
contents, normalize Unicode, or make snapshots. Python strings containing lone
surrogates are unsupported for walker arguments.

The walker is not wired into `kit.py`: its existing `source_files()` includes
binary files, excludes Python caches, and rejects symlinks instead of skipping
them. M1 minifier behavior and optional Python fallback are unchanged.

After rebuilding the optional extension, run the contract tests and benchmark:

```sh
python -m unittest discover -s tests -p 'test_native_walk.py' -v
python tools/benchmark_walk.py --files 2000 --repeat 5
```

Tests skip only when `msl_core` is absent; an installed M1-only extension needs
rebuilding and does not silently skip M2 checks. Symlink/permission-specific
cases skip when the platform or executing user cannot exercise them.

The benchmark creates a fixed temporary tree containing nested text, ignored
files and binary samples. It verifies expected paths before timing and checks
every repetition. JSON records corpus/path SHA-256 hashes, file counts, Python
and platform versions, native package version, samples and median seconds.
Tree creation/imports are excluded; traversal, ignore parsing, sample reads,
sorting and binding conversion are included. Caches are warmed first. Compare
runs only with the same parameters, machine, toolchain, dependency lockfile and
release build. It does not compare against `source_files()` because the contracts
differ. No measurements or speedup claims are supplied with M2.

## BPE token counting (M3)

```python
import msl_core

msl_core.count_tokens("hello world")  # cl100k_base, 2 tokens
msl_core.count_tokens("hello world", encoding="o200k_base")
```

`count_tokens(text: str, encoding: str = "cl100k_base") -> int` supports exactly
`cl100k_base` and `o200k_base`. It uses the embedded vocabularies and BPE engine
from [tiktoken-rs 0.6.0](https://docs.rs/tiktoken-rs/0.6.0/tiktoken_rs/).
No vocabulary download or network access is needed at runtime. Each encoding is
initialized lazily once per process and reused across threads. Tokenization runs
with the Python GIL released. Counts concern the supplied text only; they do not
include chat envelopes, tool schemas, or actual agent session usage.

The reference is Python `tiktoken.get_encoding(encoding).encode(text)` with its
default arguments. Empty text returns zero. Known special-token spellings are
rejected with `msl_core.DisallowedSpecialTokenError`, a `ValueError` subclass;
there is no implicit `allowed_special="all"` behavior. The special set depends on
the encoding: for example, `<|fim_prefix|>` is rejected for `cl100k_base` and
encoded as ordinary text for `o200k_base`. Unknown encodings raise `ValueError`,
even for empty text. Non-string arguments raise `TypeError`. Unicode is not
normalized. Surrogate pairs/lone surrogates receive the same UTF-16 repair and
replacement as Python tiktoken before BPE encoding.

`tools.kit.count_tokens()` retains its signature and legacy fallback policy:

- Python tiktoken is preferred when installed and supports the requested encoding.
  Missing packages and recognized unknown-encoding errors allow fallback; real
  import, initialization and execution failures in the selected backend propagate.
- If Python BPE is unavailable for that encoding, native BPE is tried for
  `cl100k_base` and `o200k_base`. M1/M2 extensions missing both tokenizer exports
  count as no BPE backend. An extension exposing only one export is broken and
  raises an error when native BPE is needed. An unused native backend is not probed.
- If neither backend supports the requested encoding, the existing size-budget
  heuristic is used. Recognized special-token rejection also uses that heuristic;
  unexpected `ValueError` and other execution failures are not suppressed.
- The existing empty-input shortcut still returns zero before resolving a backend,
  including when the encoding name is unknown. Direct native calls validate the
  encoding first, like `tiktoken.get_encoding()`.

The profiler keeps its JSON schema and checks Python BPE before native BPE using
the same selection order. Its encoding label describes backend availability,
as before; individual inputs containing rejected special tokens still use the
legacy heuristic. Minifier dispatch and walker behavior are unchanged.

Rebuild the optional wheel using the instructions above, then run:

```sh
python -m unittest discover -s tests -p 'test_native_tokens.py' -v
python tools/benchmark_tokens.py --encoding cl100k_base --size 64 --repeat 5 --iterations 10
python tools/benchmark_tokens.py --encoding o200k_base --size 64 --repeat 5 --iterations 10
```

Python tiktoken is optional for normal use but required for differential tests
and this benchmark. Its first `get_encoding()` may fetch vocabulary files if its
cache is cold; prepare that cache beforehand for offline comparison. Native
contract tests skip if the extension is absent or is an M1/M2 version without
BPE exports; a partial native API fails instead of skipping. Parity tests require
both BPE backends. Mocked dispatch/fallback tests run without either dependency.

The benchmark reuses the fixed minifier corpus, validates every block's counts
before timing, warms both engines and alternates execution order. JSON records
the encoding, corpus SHA-256/byte count, token counts, parameters, versions,
samples and median times. Imports and first-time vocabulary initialization are
excluded; conversion across the binding boundary is included. The Python side
measures `len(encoding.encode(text))`; native counts do not transfer token IDs to
Python. Keep toolchain, lockfile, release build, Python tiktoken version, machine
and corpus parameters fixed when comparing runs.

Reported measurements on the benchmark corpus found native Rust BPE slower than
Python tiktoken:

| Encoding | Rust elapsed time / Python elapsed time |
| --- | --- |
| `cl100k_base` | 1.55× (Rust slower) |
| `o200k_base` | 2.13× (Rust slower) |

These corpus-specific results motivate preferring Python tiktoken. They do not
establish a general performance ratio across machines or inputs. Native BPE
remains an optional exact-count fallback when Python BPE is unavailable.

## AST symbol extraction (M4)

`msl_core.extract_ast_symbols(file_path, code)` returns read-only `Symbol` objects
for Python, JavaScript/TypeScript, Rust, Go, C++ and Java. It consumes supplied
source text, uses the path only to select a grammar, and never reads files.
See [the API contract and limitations](../../docs/native-symbols.md) for fields,
line numbering, supported declarations, public markers and parsing errors.

```sh
python -m unittest discover -s tests -p 'test_native_symbols.py' -v
python tools/benchmark_symbols.py --size 100 --repeat 5
```

The benchmark creates a fixed multilingual corpus, validates symbol counts and
checks repeatability. It records hashes, versions, corpus sizes, samples and
median times. It does not establish a speedup over the existing Python tools,
which have different extraction semantics. M1–M3 behavior is unchanged.

## BLAKE3 and synchronization cache (M5)

`msl_core.blake3_hash(data: bytes) -> str` returns the lowercase 64-character
BLAKE3 digest of the exact bytes, with the GIL released. It does not normalize
line endings. `tools.kit.digest()` and provider/install manifests still use their
existing canonical SHA-256 semantics.

Regular `kit.py sync` can skip export generation on a validated no-change cache
hit. Python-only installations and older wheels work with SHA-256 fingerprints.
`sync --check` always regenerates and never writes the cache. See
[cache safety, limitations and benchmark instructions](../../docs/sync-cache.md).

```sh
python -m unittest discover -s tests -p 'test_sync_cache.py' -v
python tools/benchmark_sync.py --repeat 3
python tools/benchmark_sync.py --repeat 3 --minify --mode lazy
```
