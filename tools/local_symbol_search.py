#!/usr/bin/env python3
"""
Zero-Dependency Local BM25 Symbol Search (tools/local_symbol_search.py)

A lightweight CLI tool and Python library utilizing Python's built-in sqlite3 FTS5
module and standard library ast parser to index and rank repository symbols with BM25.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sqlite3
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_DB_PATH = Path(".msl/symbols.db")
DEFAULT_WEIGHTS = (1.0, 10.0, 1.0, 5.0, 2.0, 1.0)


@dataclass
class SymbolItem:
    filepath: str
    symbol_name: str
    symbol_kind: str  # function, method, class, constant
    lineno: int
    end_lineno: int
    signature: str
    docstring: str
    body_snippet: str
    rank: float = 0.0


def extract_python_symbols(filepath: Path, base_dir: Path) -> list[SymbolItem]:
    """Extracts classes, functions, methods, and constants from a Python source file."""
    rel_path = filepath.relative_to(base_dir).as_posix()
    try:
        content = filepath.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(filepath))
    except Exception:
        return []

    lines = content.splitlines()
    symbols: list[SymbolItem] = []

    def _get_snippet(start: int, end: int, max_lines: int = 5) -> str:
        s = max(0, start - 1)
        e = min(len(lines), end)
        chunk = lines[s:e]
        if len(chunk) > max_lines:
            chunk = chunk[:max_lines] + ["..."]
        return "\n".join(chunk)

    def _extract_doc(node: ast.AST) -> str:
        doc = ast.get_docstring(node)
        if not doc:
            return ""
        # Keep only the first paragraph/summary line
        return doc.strip().split("\n\n")[0].replace("\n", " ").strip()

    def _format_func_sig(node: ast.FunctionDef | ast.AsyncFunctionDef, is_method: bool) -> str:
        prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
        # Extract signature line from source if available
        start_line = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
        match = re.search(
            r"((?:async\s+)?def\s+[\w_]+(?:\([^)]*\))?(?:\s*->\s*[^:]+)?)", start_line
        )
        if match:
            return match.group(1).strip()
        args = [a.arg for a in node.args.args]
        return f"{prefix}{node.name}({', '.join(args)})"

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.current_class: str | None = None

        def visit_ClassDef(self, node: ast.ClassDef):
            bases = [ast.unparse(b) for b in node.bases] if hasattr(ast, "unparse") else []
            base_str = f"({', '.join(bases)})" if bases else ""
            sig = f"class {node.name}{base_str}:"
            doc = _extract_doc(node)
            snippet = _get_snippet(node.lineno, getattr(node, "end_lineno", node.lineno + 5))

            symbols.append(
                SymbolItem(
                    filepath=rel_path,
                    symbol_name=node.name,
                    symbol_kind="class",
                    lineno=node.lineno,
                    end_lineno=getattr(node, "end_lineno", node.lineno),
                    signature=sig,
                    docstring=doc,
                    body_snippet=snippet,
                )
            )

            old_class = self.current_class
            self.current_class = node.name
            self.generic_visit(node)
            self.current_class = old_class

        def visit_FunctionDef(self, node: ast.FunctionDef):
            is_method = self.current_class is not None
            kind = "method" if is_method else "function"
            name = f"{self.current_class}.{node.name}" if is_method else node.name
            sig = _format_func_sig(node, is_method)
            doc = _extract_doc(node)
            snippet = _get_snippet(node.lineno, getattr(node, "end_lineno", node.lineno + 4))

            symbols.append(
                SymbolItem(
                    filepath=rel_path,
                    symbol_name=name,
                    symbol_kind=kind,
                    lineno=node.lineno,
                    end_lineno=getattr(node, "end_lineno", node.lineno),
                    signature=sig,
                    docstring=doc,
                    body_snippet=snippet,
                )
            )
            # Do not visit nested functions inside this function to keep index clean

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
            is_method = self.current_class is not None
            kind = "method" if is_method else "function"
            name = f"{self.current_class}.{node.name}" if is_method else node.name
            sig = _format_func_sig(node, is_method)
            doc = _extract_doc(node)
            snippet = _get_snippet(node.lineno, getattr(node, "end_lineno", node.lineno + 4))

            symbols.append(
                SymbolItem(
                    filepath=rel_path,
                    symbol_name=name,
                    symbol_kind=kind,
                    lineno=node.lineno,
                    end_lineno=getattr(node, "end_lineno", node.lineno),
                    signature=sig,
                    docstring=doc,
                    body_snippet=snippet,
                )
            )

    Visitor().visit(tree)
    return symbols


def extract_regex_symbols(filepath: Path, base_dir: Path) -> list[SymbolItem]:
    """Regex fallback symbol extractor for non-Python source files (TS, JS, Go, Rust)."""
    rel_path = filepath.relative_to(base_dir).as_posix()
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception:
        return []

    lines = content.splitlines()
    symbols: list[SymbolItem] = []
    suffix = filepath.suffix.lower()

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        # TypeScript / JavaScript
        if suffix in (".ts", ".tsx", ".js", ".jsx"):
            m = re.match(
                r"^(?:export\s+)?(?:async\s+)?(?:function|class|interface|type)\s+([a-zA-Z0-9_$]+)",
                stripped,
            )
            if m:
                kind = (
                    "class"
                    if "class " in stripped
                    else ("interface" if "interface " in stripped else "function")
                )
                symbols.append(SymbolItem(rel_path, m.group(1), kind, idx, idx, stripped, "", line))
        # Go
        elif suffix == ".go":
            m = re.match(r"^func\s+(?:\([^)]+\)\s+)?([a-zA-Z0-9_]+)\s*\(", stripped)
            if m:
                kind = "method" if "(" in stripped[: stripped.find(m.group(1))] else "function"
                symbols.append(SymbolItem(rel_path, m.group(1), kind, idx, idx, stripped, "", line))
            m_type = re.match(r"^type\s+([a-zA-Z0-9_]+)\s+(?:struct|interface)", stripped)
            if m_type:
                symbols.append(
                    SymbolItem(rel_path, m_type.group(1), "type", idx, idx, stripped, "", line)
                )
        # Rust
        elif suffix == ".rs":
            m = re.match(
                r"^(?:pub(?:\([^)]+\))?\s+)?(?:async\s+)?(?:fn|struct|enum|trait)\s+([a-zA-Z0-9_]+)",
                stripped,
            )
            if m:
                kind = (
                    "struct"
                    if "struct " in stripped
                    else ("enum" if "enum " in stripped else "function")
                )
                symbols.append(SymbolItem(rel_path, m.group(1), kind, idx, idx, stripped, "", line))

    return symbols


class SymbolIndex:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path) if db_path else ":memory:")
        self._init_db()

    def _init_db(self):
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS file_meta (
                    filepath TEXT PRIMARY KEY,
                    mtime REAL,
                    sha256 TEXT
                )
                """
            )
            self.conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS symbol_fts USING fts5(
                    filepath,
                    symbol_name,
                    symbol_kind,
                    lineno UNINDEXED,
                    end_lineno UNINDEXED,
                    signature,
                    docstring,
                    body_snippet,
                    tokenize='unicode61'
                )
                """
            )

    def index_project(self, project_dir: Path, force: bool = False) -> int:
        """Indexes all symbols in the project directory, skipping unchanged files."""
        total_symbols = 0
        extensions = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"}
        ignore_dirs = {
            ".git",
            ".venv",
            "venv",
            "node_modules",
            "dist",
            "build",
            "__pycache__",
            ".scratch",
            ".msl",
        }

        for root, dirs, files in os.walk(project_dir):
            dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]
            for f in files:
                p = Path(root) / f
                if p.suffix.lower() not in extensions:
                    continue

                rel = p.relative_to(project_dir).as_posix()
                mtime = p.stat().st_mtime

                if not force:
                    cur = self.conn.execute(
                        "SELECT mtime FROM file_meta WHERE filepath = ?", (rel,)
                    )
                    row = cur.fetchone()
                    if row and row[0] == mtime:
                        continue

                # File changed or new: extract symbols
                if p.suffix.lower() == ".py":
                    items = extract_python_symbols(p, project_dir)
                else:
                    items = extract_regex_symbols(p, project_dir)

                with self.conn:
                    self.conn.execute("DELETE FROM file_meta WHERE filepath = ?", (rel,))
                    self.conn.execute("DELETE FROM symbol_fts WHERE filepath = ?", (rel,))
                    self.conn.execute(
                        "INSERT INTO file_meta (filepath, mtime) VALUES (?, ?)", (rel, mtime)
                    )
                    for it in items:
                        self.conn.execute(
                            """
                            INSERT INTO symbol_fts (
                                filepath, symbol_name, symbol_kind, lineno, end_lineno, signature, docstring, body_snippet
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                it.filepath,
                                it.symbol_name,
                                it.symbol_kind,
                                it.lineno,
                                it.end_lineno,
                                it.signature,
                                it.docstring,
                                it.body_snippet,
                            ),
                        )
                total_symbols += len(items)

        return total_symbols

    def query(
        self,
        query_str: str,
        limit: int = 10,
        kind: str | None = None,
        max_tokens: int = 800,
    ) -> list[SymbolItem]:
        """Queries symbols matching query_str ranked by BM25 with token budgeting."""
        # Sanitize query for FTS5
        clean_terms = re.findall(r"\w+", query_str)
        if not clean_terms:
            return []

        # Construct FTS5 match query
        fts_match = " OR ".join(f'"{t}"*' for t in clean_terms)
        sql = """
            SELECT filepath, symbol_name, symbol_kind, lineno, end_lineno, signature, docstring, body_snippet,
                   bm25(symbol_fts, 1.0, 10.0, 1.0, 5.0, 2.0, 1.0) AS score
            FROM symbol_fts
            WHERE symbol_fts MATCH ?
        """
        params: list[str] = [fts_match]
        if kind:
            sql += " AND symbol_kind = ?"
            params.append(kind)

        sql += " ORDER BY score ASC LIMIT ?"
        params.append(limit * 2)  # fetch buffer for token budgeting

        cur = self.conn.execute(sql, params)
        results: list[SymbolItem] = []
        token_count = 0

        for row in cur.fetchall():
            item = SymbolItem(
                filepath=row[0],
                symbol_name=row[1],
                symbol_kind=row[2],
                lineno=int(row[3]),
                end_lineno=int(row[4]),
                signature=row[5],
                docstring=row[6],
                body_snippet=row[7],
                rank=row[8],
            )
            # Estimate tokens: ~4 characters per token
            item_tokens = max(
                1, (len(item.signature) + len(item.docstring) + len(item.filepath) + 20) // 4
            )
            if token_count + item_tokens > max_tokens and results:
                break
            results.append(item)
            token_count += item_tokens
            if len(results) >= limit:
                break

        return results

    def close(self):
        self.conn.close()


def format_markdown(results: list[SymbolItem]) -> str:
    if not results:
        return "No symbols found matching query."
    out = [f"Found {len(results)} matching symbols:\n"]
    for r in results:
        out.append(f"### `{r.symbol_name}` ({r.symbol_kind}) — {r.filepath}:{r.lineno}")
        if r.signature:
            out.append(f"```python\n{r.signature}\n```")
        if r.docstring:
            out.append(f"> {r.docstring}\n")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Zero-dependency local BM25 symbol search.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: index
    p_index = subparsers.add_parser("index", help="Index project symbols into SQLite database.")
    p_index.add_argument("--project", default=".", help="Project root directory.")
    p_index.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to SQLite database.")
    p_index.add_argument("--force", action="store_true", help="Force re-indexing all files.")

    # Subcommand: query
    p_query = subparsers.add_parser("query", help="Query existing indexed symbol database.")
    p_query.add_argument("query", help="Symbol query text.")
    p_query.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to SQLite database.")
    p_query.add_argument("--limit", type=int, default=5, help="Maximum results to return.")
    p_query.add_argument("--kind", help="Filter by symbol kind (class, function, method).")
    p_query.add_argument("--max-tokens", type=int, default=800, help="Strict token budget limit.")
    p_query.add_argument("--json", action="store_true", help="Output JSON format.")

    # Subcommand: search
    p_search = subparsers.add_parser("search", help="One-shot search: index in-memory and query.")
    p_search.add_argument("query", help="Symbol query text.")
    p_search.add_argument("--project", default=".", help="Project root directory.")
    p_search.add_argument("--limit", type=int, default=5, help="Maximum results to return.")
    p_search.add_argument("--kind", help="Filter by symbol kind (class, function, method).")
    p_search.add_argument("--max-tokens", type=int, default=800, help="Strict token budget limit.")
    p_search.add_argument("--json", action="store_true", help="Output JSON format.")

    args = parser.parse_args(argv)

    if args.command == "index":
        db_path = Path(args.db)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        idx = SymbolIndex(db_path)
        count = idx.index_project(Path(args.project), force=args.force)
        idx.close()
        print(f"Indexed {count} symbols into {db_path}.")
        return 0

    elif args.command == "query":
        db_path = Path(args.db)
        if not db_path.exists():
            print(
                f"Index database not found at {db_path}. Run 'index' or 'search' first.",
                file=sys.stderr,
            )
            return 1
        idx = SymbolIndex(db_path)
        results = idx.query(
            args.query, limit=args.limit, kind=args.kind, max_tokens=args.max_tokens
        )
        idx.close()
        if args.json:
            print(json.dumps([asdict(r) for r in results], indent=2))
        else:
            print(format_markdown(results))
        return 0

    elif args.command == "search":
        idx = SymbolIndex(None)  # in-memory SQLite
        idx.index_project(Path(args.project))
        results = idx.query(
            args.query, limit=args.limit, kind=args.kind, max_tokens=args.max_tokens
        )
        idx.close()
        if args.json:
            print(json.dumps([asdict(r) for r in results], indent=2))
        else:
            print(format_markdown(results))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
