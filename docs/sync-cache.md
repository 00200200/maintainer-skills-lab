# Synchronization cache and native hashing (M5)

`python3 tools/kit.py sync` maintains an optional local cache at
`.msl/sync-cache.json`. It is ignored by Git and contains only a source/options
fingerprint and the SHA-256 of the provider manifest, not generated file content.
No cache or native extension is required. Delete the cache to force regeneration.
The existing Python API, CLI flags and sync result fields are unchanged.

## Scope and safety

The optimization skips `provider_files()` only when all of these checks succeed:

1. A versioned, structurally valid cache matches the current input fingerprint.
2. The validated provider manifest matches the cached manifest digest.
3. Every manifest-owned output still matches its SHA-256, using the existing
   `checked_path()` and `current_digest()` protections and CRLF normalization.
4. `load_library()` passes again, including current tokenizer-dependent source
   validation. A cache hit never replaces source validation with an old result.

The fingerprint hashes the complete bytes and relative paths of `skills/`,
`agents/`, `grok-bot/` and `assets/` using existing `source_files()` traversal.
Additions, deletions, renames and edits invalidate it, even if file sizes and
mtimes are unchanged. It includes `minify`, `mode`, Python runtime version, cache
schema, and the running `kit.py` implementation bytes. With native minification,
loaded `msl_core` package/binary bytes are also included. Unknown custom minifiers
disable reuse. Restart the interpreter after changing generator implementation
files; hot replacement of Python functions/globals is not a supported cache input.

On a miss, the existing generator, SHA-256 comparisons, ownership checks, writes
and obsolete-file removals run normally. A changed/deleted output or changed
manifest forces this path. Cache entries never supply replacement content or
authorize overwriting user edits. `digest()` and manifest schema/version/hash
format are unchanged. Unknown/unmanaged neighboring files retain existing sync
semantics; this cache does not expand the set of managed paths.

`python3 tools/kit.py sync --check` always bypasses the cache and regenerates the
expected exports. It therefore detects missing, edited and stale managed exports
independently of cached metadata, and never creates or updates a cache file.

Cache reads reject malformed JSON, unknown schemas/fields, invalid hashes and
oversized metadata. Cache paths use existing symlink checks. Writes use the
existing atomic replacement helper, only after successful sync and a second
matching input fingerprint. An unchanged cache is not rewritten. Unsafe,
unreadable or non-writable cache paths are treated as unavailable. Cache errors
do not change ownership policy or suppress validation failures.

Keep source trees stable during synchronization; this is not a snapshot or a lock
against concurrent source/destination changes. The cache is local optimization
metadata, not authenticated state or a security boundary against someone who
can rewrite both cache and ownership manifests. `--check` remains independent.

## Native byte hashing

The optional M5 extension exposes:

```python
import msl_core

checksum = msl_core.blake3_hash(b"exact bytes\r\n")
```

It returns 64 lowercase hexadecimal characters, hashes binary content verbatim,
and releases the Python GIL. Non-byte arguments raise `TypeError`. It uses pinned
`blake3 = 1.5.5`; there is no Python BLAKE3 dependency. Build instructions are in
[the extension README](../crates/msl-core/README.md).

Input fingerprints use native BLAKE3 when available; otherwise they use standard
library SHA-256. An algorithm change invalidates the cache. Older M1–M4 wheels
without this function are supported; broken native imports/calls propagate.
Provider/install manifests always retain canonical SHA-256, regardless of the
fingerprint algorithm. Native BLAKE3 does not duplicate the existing output-write
deduplication mechanism.

## Verification and benchmark

```sh
python3 -m unittest discover -s tests -p 'test_sync_cache.py' -v
python3 tools/benchmark_sync.py --repeat 3
python3 tools/benchmark_sync.py --repeat 3 --minify --mode lazy
```

The benchmark copies repository sources into disposable directories. It compares
cold, warm and same-size content-change syncs against the same implementation
with its cache disabled. Every phase checks identical provider bytes, SHA-256
manifests and public sync results, then independently runs `--check`. It also
asserts that warm caching skips generation while cold/changed runs regenerate.
It alternates cached/reference timing order between repetitions. JSON reports
per-phase samples, medians, ratios, source/generator/output hashes, options,
Python/platform versions and the fingerprint algorithm. Copying, source edits,
snapshots and verification are outside the timed region; all sync work, including
cache fingerprinting, validation and cache writes, is included.

Measured with the two benchmark commands above (`--repeat 3`), Python 3.12.7,
Linux 6.14.0 x86_64/glibc 2.40, using SHA-256 fallback fingerprints:

| Options | Phase | Cached median (ms) | Uncached median (ms) | Uncached / cached |
| --- | --- | ---: | ---: | ---: |
| full, no minification | cold | 262.803 | 250.631 | 0.95× |
| full, no minification | warm | 77.630 | 217.061 | 2.80× |
| full, no minification | changed | 234.083 | 221.395 | 0.95× |
| lazy, minified | cold | 298.898 | 292.984 | 0.98× |
| lazy, minified | warm | 77.043 | 250.362 | 3.25× |
| lazy, minified | changed | 265.228 | 252.970 | 0.95× |

All phases passed the benchmark's byte/manifest/result equality checks and its
independent `--check`. Warm runs skipped generation; cold/changed runs generated
once. The generator SHA-256 was
`fb53a6979851711661ab82bc86d490c71c619c14bd528360df6cbc7a771dc954`;
the input-source SHA-256 was
`7fdb436573392139d558eda7bb87d48bbc23463713379a3a59b822c26586aad2`.

These SHA-256 fallback measurements show a warm-cache improvement on this
corpus, not a general speedup.

Additional measurements used the release-built native BLAKE3 extension with
Python 3.11.18 on Linux x86_64 and five repetitions per configuration
(`--repeat 5`):

| Options | Phase | Cached median (ms) | Uncached median (ms) | Uncached / cached |
| --- | --- | ---: | ---: | ---: |
| full, no minification | cold | 185.10 | 183.22 | 0.99× |
| full, no minification | warm | 61.89 | 140.40 | **2.27×** |
| full, no minification | changed | 150.32 | 141.91 | 0.94× |
| lazy, minified | cold | 205.75 | 183.81 | 0.89× |
| lazy, minified | warm | 68.32 | 148.09 | **2.17×** |
| lazy, minified | changed | 170.47 | 150.03 | 0.88× |

The native BLAKE3 runs also verified identical provider output bytes, manifests,
and public sync results, expected generation counts, and independent `--check`
behavior. On this corpus, warm sync was faster, while cold and changed runs
incurred additional fingerprinting overhead.

Verification completed successfully: 17 M5 cache/hash tests and 562 full-suite
Python tests passed. Checks also covered `cargo check`, `cargo test --locked`,
Clippy with `-D warnings`, Rust formatting, a maturin release build, native
`blake3_hash()` execution, Ruff, `kit.py check`, and `kit.py sync --check`.

This is deliberately a whole-library no-change fast path, not a per-provider
dependency graph or mtime memoization. Each run still reads/hashes source bytes,
validates the library and checks output SHA-256. Any relevant change regenerates
all providers. Cold/changed runs do extra fingerprint work and may be slower.
More granular reuse would require refactoring the generator's repeated library
loads and validation dependencies; that broader change is deferred.
