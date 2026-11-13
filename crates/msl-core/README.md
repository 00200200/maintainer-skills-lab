# Optional native Markdown minifier (M1)

`msl_core.minify_markdown(text: str) -> str` implements the existing `tools/kit.py`
algorithm in Rust with PyO3. It is a literal compatibility port, not a CommonMark
parser. There is no tokenizer, AST, directory scanner, incremental hasher or CI.
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
