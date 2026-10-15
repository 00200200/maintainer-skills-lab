#!/usr/bin/env python3
"""
tools/repomap.py - PageRank AST-Based Symbol Map Generator

Builds a compact, token-bounded repository symbol map using Python standard library
ast and PageRank graph centrality. Prioritizes central domain abstractions, core
classes, and frequently referenced functions within a strict token budget.
"""

from __future__ import annotations

import argparse
import ast
import builtins
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# Try importing smart_ignore from tools; fallback gracefully if not in path
try:
    from tools.smart_ignore import is_ignorable_for_context
except ImportError:
    try:
        from smart_ignore import is_ignorable_for_context  # type: ignore
    except ImportError:

        def is_ignorable_for_context(path: Path | str) -> bool:
            p = str(path).replace("\\", "/")
            ignored_prefixes = (
                ".git/",
                ".venv/",
                "venv/",
                "build/",
                "dist/",
                "__pycache__/",
                ".scratch/",
                ".msl/",
            )
            return any(part in p for part in ignored_prefixes)


DEFAULT_MAX_TOKENS = 800
DEFAULT_DAMPING = 0.85
MAX_ITER = 100
TOLERANCE = 1e-6

PYTHON_BUILTINS = set(dir(builtins)) | {
    "args",
    "kwargs",
    "self",
    "cls",
    "None",
    "True",
    "False",
}

IGNORED_DUNDERS = {
    "__init__",
    "__new__",
    "__str__",
    "__repr__",
    "__eq__",
    "__hash__",
    "__len__",
    "__enter__",
    "__exit__",
    "__iter__",
    "__next__",
    "__getitem__",
    "__setitem__",
    "__delitem__",
}


@dataclass
class SymbolDef:
    name: str
    kind: str  # "class", "function", "method"
    lineno: int
    signature: str
    docstring: str = ""
    parent: str | None = None
    references: set[str] = field(default_factory=set)
    methods: list[SymbolDef] = field(default_factory=list)
    rank: float = 0.0

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "kind": self.kind,
            "lineno": self.lineno,
            "signature": self.signature,
            "docstring": self.docstring,
            "parent": self.parent,
            "rank": round(self.rank, 6),
        }
        if self.methods:
            d["methods"] = [m.to_dict() for m in self.methods]
        return d


@dataclass
class FileSymbols:
    path: str
    rel_path: str
    classes: list[SymbolDef] = field(default_factory=list)
    functions: list[SymbolDef] = field(default_factory=list)
    file_references: set[str] = field(default_factory=set)
    rank: float = 0.0

    @property
    def all_symbols(self) -> list[SymbolDef]:
        res = list(self.functions)
        for c in self.classes:
            res.append(c)
            res.extend(c.methods)
        return res

    def to_dict(self) -> dict:
        return {
            "path": self.rel_path,
            "rank": round(self.rank, 6),
            "classes": [c.to_dict() for c in self.classes],
            "functions": [f.to_dict() for f in self.functions],
        }


def count_tokens(text: str) -> int:
    """Fast approximation of cl100k_base tokens (roughly 4 chars per token)."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def _format_function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Format an ast function node into a concise signature."""
    prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
    args = []

    all_args = list(node.args.posonlyargs) + list(node.args.args)
    defaults = [None] * (len(all_args) - len(node.args.defaults)) + list(node.args.defaults)

    for arg, default in zip(all_args, defaults, strict=False):
        name = arg.arg
        if default is not None:
            name += "=..."
        args.append(name)

    if node.args.vararg:
        args.append(f"*{node.args.vararg.arg}")
    elif node.args.kwonlyargs:
        args.append("*")

    kw_defaults = dict(zip(node.args.kwonlyargs, node.args.kw_defaults, strict=False))
    for kwarg in node.args.kwonlyargs:
        name = kwarg.arg
        if kw_defaults.get(kwarg) is not None:
            name += "=..."
        args.append(name)

    if node.args.kwarg:
        args.append(f"**{node.args.kwarg.arg}")

    return f"{prefix}{node.name}({', '.join(args)})"


def _extract_references(node: ast.AST) -> set[str]:
    """
    Extract meaningful symbol references:
      - Explicit function/method calls
      - Base classes in class definitions
      - Type annotations
    Filters out language builtins and generic parameter names.
    """
    refs = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                name = child.func.id
                if name not in PYTHON_BUILTINS and not name.startswith("_"):
                    refs.add(name)
            elif isinstance(child.func, ast.Attribute):
                attr = child.func.attr
                if attr not in PYTHON_BUILTINS and not attr.startswith("_"):
                    refs.add(attr)
        elif isinstance(child, ast.ClassDef):
            for base in child.bases:
                if isinstance(base, ast.Name):
                    if base.id not in PYTHON_BUILTINS:
                        refs.add(base.id)
                elif isinstance(base, ast.Attribute):
                    refs.add(base.attr)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Extract annotations
            for arg in child.args.args:
                if arg.annotation and isinstance(arg.annotation, ast.Name):
                    if arg.annotation.id not in PYTHON_BUILTINS:
                        refs.add(arg.annotation.id)
            if child.returns and isinstance(child.returns, ast.Name):
                if child.returns.id not in PYTHON_BUILTINS:
                    refs.add(child.returns.id)
    return refs


def extract_file_symbols(filepath: Path, base_dir: Path) -> FileSymbols | None:
    """Parse a single Python file and extract classes, functions, and references."""
    try:
        rel_path = filepath.relative_to(base_dir).as_posix()
    except ValueError:
        rel_path = filepath.as_posix()

    try:
        content = filepath.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return None

    file_symbols = FileSymbols(path=str(filepath), rel_path=rel_path)
    file_refs = set()

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                imported_name = alias.asname or alias.name
                if imported_name not in PYTHON_BUILTINS:
                    file_refs.add(imported_name)
            if isinstance(node, ast.ImportFrom) and node.module:
                mod_tail = node.module.split(".")[-1]
                if mod_tail not in PYTHON_BUILTINS:
                    file_refs.add(mod_tail)

        elif isinstance(node, ast.ClassDef):
            doc = ast.get_docstring(node) or ""
            doc_line = doc.strip().split("\n")[0] if doc else ""
            class_refs = _extract_references(node)

            bases_str = ""
            base_names = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    base_names.append(base.id)
                    class_refs.add(base.id)
                elif isinstance(base, ast.Attribute):
                    base_names.append(base.attr)
                    class_refs.add(base.attr)
            if base_names:
                bases_str = f"({', '.join(base_names)})"

            class_def = SymbolDef(
                name=node.name,
                kind="class",
                lineno=node.lineno,
                signature=f"class {node.name}{bases_str}:",
                docstring=doc_line,
                references=class_refs,
            )

            # Methods inside class
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name in IGNORED_DUNDERS:
                        continue
                    method_doc = ast.get_docstring(item) or ""
                    method_doc_line = method_doc.strip().split("\n")[0] if method_doc else ""
                    method_refs = _extract_references(item)
                    method_sig = _format_function_signature(item)
                    method_def = SymbolDef(
                        name=f"{node.name}.{item.name}",
                        kind="method",
                        lineno=item.lineno,
                        signature=method_sig,
                        docstring=method_doc_line,
                        parent=node.name,
                        references=method_refs,
                    )
                    class_def.methods.append(method_def)

            file_symbols.classes.append(class_def)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in IGNORED_DUNDERS:
                continue
            fn_doc = ast.get_docstring(node) or ""
            fn_doc_line = fn_doc.strip().split("\n")[0] if fn_doc else ""
            fn_refs = _extract_references(node)
            fn_sig = _format_function_signature(node)
            fn_def = SymbolDef(
                name=node.name,
                kind="function",
                lineno=node.lineno,
                signature=fn_sig,
                docstring=fn_doc_line,
                references=fn_refs,
            )
            file_symbols.functions.append(fn_def)
        else:
            file_refs.update(_extract_references(node))

    file_symbols.file_references = file_refs
    return file_symbols


def compute_pagerank(
    graph: dict[str, set[str]],
    damping: float = DEFAULT_DAMPING,
    max_iter: int = MAX_ITER,
    tol: float = TOLERANCE,
) -> dict[str, float]:
    """
    Compute standard PageRank centrality on a directed graph.
    graph maps node -> set of target nodes (outgoing edges: Caller -> Callee).
    """
    nodes = list(graph.keys())
    n = len(nodes)
    if n == 0:
        return {}
    if n == 1:
        return {nodes[0]: 1.0}

    # Identify incoming edges and out-degrees
    incoming: dict[str, list[str]] = defaultdict(list)
    out_degree: dict[str, int] = {}

    for u in nodes:
        targets = [v for v in graph[u] if v in graph]
        out_degree[u] = len(targets)
        for v in targets:
            incoming[v].append(u)

    # Initialize uniform rank
    rank: dict[str, float] = {u: 1.0 / n for u in nodes}

    for _ in range(max_iter):
        new_rank: dict[str, float] = {}
        # Dangling node contribution (nodes with out-degree 0)
        dangling_sum = sum(rank[u] for u in nodes if out_degree[u] == 0)
        teleport = (1.0 - damping) / n + (damping * dangling_sum) / n

        diff = 0.0
        for u in nodes:
            in_sum = sum(rank[v] / out_degree[v] for v in incoming[u])
            val = teleport + damping * in_sum
            diff += abs(val - rank[u])
            new_rank[u] = val

        rank = new_rank
        if diff < tol:
            break

    total = sum(rank.values())
    if total > 0:
        rank = {k: v / total for k, v in rank.items()}

    return rank


def build_symbol_graph(
    file_symbol_list: list[FileSymbols],
) -> tuple[dict[str, set[str]], dict[str, SymbolDef], dict[str, FileSymbols]]:
    """
    Construct dependency graph linking files and symbols.
    Nodes consist of:
      - File nodes: "file:<rel_path>"
      - Symbol nodes: "sym:<rel_path>:<name>"
    """
    graph: dict[str, set[str]] = defaultdict(set)
    sym_lookup: dict[str, SymbolDef] = {}
    file_lookup: dict[str, FileSymbols] = {}

    name_to_syms: dict[str, list[str]] = defaultdict(list)

    for fs in file_symbol_list:
        file_key = f"file:{fs.rel_path}"
        graph[file_key] = set()
        file_lookup[file_key] = fs

        for sym in fs.all_symbols:
            sym_key = f"sym:{fs.rel_path}:{sym.name}"
            graph[sym_key] = set()
            sym_lookup[sym_key] = sym

            # Index by simple name (e.g. "count_tokens" or "MyClass")
            simple_name = sym.name.split(".")[-1]
            name_to_syms[simple_name].append(sym_key)
            if sym.name != simple_name:
                name_to_syms[sym.name].append(sym_key)

    # Add edges based on references (Caller -> Callee)
    for fs in file_symbol_list:
        file_key = f"file:{fs.rel_path}"

        for ref in fs.file_references:
            targets = name_to_syms.get(ref, [])
            # Discount overly generic names defined in many places
            if 0 < len(targets) <= 8:
                for target_sym in targets:
                    if target_sym != file_key:
                        graph[file_key].add(target_sym)

        for sym in fs.all_symbols:
            sym_key = f"sym:{fs.rel_path}:{sym.name}"
            for ref in sym.references:
                targets = name_to_syms.get(ref, [])
                if 0 < len(targets) <= 8:
                    for target_sym in targets:
                        if target_sym != sym_key:
                            graph[sym_key].add(target_sym)

    return graph, sym_lookup, file_lookup


def rank_repository_symbols(
    project_dir: Path | str = ".",
) -> list[FileSymbols]:
    """Scan project, build graph, compute PageRank, and return ranked FileSymbols."""
    base_path = Path(project_dir).resolve()
    if not base_path.exists():
        return []

    py_files: list[Path] = []
    for p in base_path.rglob("*.py"):
        try:
            rel = p.relative_to(base_path)
        except ValueError:
            rel = p

        if any(
            part.startswith(".")
            or part in ("build", "dist", "__pycache__", "venv", ".venv", "node_modules")
            for part in rel.parts
        ):
            continue
        if is_ignorable_for_context(rel):
            continue
        py_files.append(p)

    file_symbol_list: list[FileSymbols] = []
    for py_file in sorted(py_files):
        fs = extract_file_symbols(py_file, base_path)
        if fs and (fs.classes or fs.functions):
            file_symbol_list.append(fs)

    if not file_symbol_list:
        return []

    graph, sym_lookup, file_lookup = build_symbol_graph(file_symbol_list)
    scores = compute_pagerank(graph)

    for key, score in scores.items():
        if key in sym_lookup:
            sym_lookup[key].rank = score
        elif key in file_lookup:
            file_lookup[key].rank = score

    # Aggregate file scores: file rank + sum of all contained symbols
    for fs in file_symbol_list:
        fs.rank = fs.rank + sum(s.rank for s in fs.all_symbols)
        # Sort functions and methods by rank descending
        fs.functions.sort(key=lambda s: s.rank, reverse=True)
        for c in fs.classes:
            c.rank = c.rank + sum(m.rank for m in c.methods)
            c.methods.sort(key=lambda m: m.rank, reverse=True)
        fs.classes.sort(key=lambda c: c.rank, reverse=True)

    # Sort files by rank descending
    file_symbol_list.sort(key=lambda f: f.rank, reverse=True)
    return file_symbol_list


def format_repomap(
    ranked_files: list[FileSymbols],
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> str:
    """Format ranked repository symbols into a compact, token-bounded tree outline."""
    if not ranked_files:
        return "# Empty repository map (no Python symbols found)"

    lines: list[str] = []

    for fs in ranked_files:
        file_lines: list[str] = [f"{fs.rel_path}:"]

        # Add classes and their methods
        for c in fs.classes:
            c_line = f"  {c.signature}"
            if c.docstring and len(c.docstring) < 60:
                c_line += f"  # {c.docstring}"
            file_lines.append(c_line)
            for m in c.methods:
                m_line = f"    {m.signature}"
                file_lines.append(m_line)

        # Add top-level functions
        for f in fs.functions:
            f_line = f"  {f.signature}"
            if f.docstring and len(f.docstring) < 60:
                f_line += f"  # {f.docstring}"
            file_lines.append(f_line)

        # Greedy token budget check
        candidate_tokens = count_tokens("\n".join(lines + file_lines) + "\n")
        if candidate_tokens <= max_tokens:
            lines.extend(file_lines)
        else:
            # Try fitting file header and top symbols individually
            sub_lines = [f"{fs.rel_path}:"]
            for s_line in file_lines[1:]:
                test_lines = lines + sub_lines + [s_line]
                if count_tokens("\n".join(test_lines) + "\n") <= max_tokens:
                    sub_lines.append(s_line)
                else:
                    break
            if len(sub_lines) > 1:
                lines.extend(sub_lines)
            break

    return "\n".join(lines).strip()


def generate_repomap(
    project_dir: Path | str = ".",
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> str:
    """Convenience API to scan project and return formatted repomap under max_tokens."""
    ranked = rank_repository_symbols(project_dir)
    return format_repomap(ranked, max_tokens=max_tokens)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="PageRank AST-Based Symbol Map Generator (tools/repomap.py)"
    )
    parser.add_argument(
        "--project",
        default=".",
        help="Path to project root directory (default: current directory)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help=f"Strict token budget limit (default: {DEFAULT_MAX_TOKENS})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON map instead of formatted ASCII tree",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print diagnostic information to stderr",
    )

    args = parser.parse_args(argv)
    project_path = Path(args.project).resolve()

    if not project_path.exists():
        sys.stderr.write(f"Error: Project directory does not exist: {project_path}\n")
        return 1

    ranked_files = rank_repository_symbols(project_path)

    if args.json:
        formatted_text = format_repomap(ranked_files, max_tokens=args.max_tokens)
        est_tokens = count_tokens(formatted_text)
        data = {
            "project": str(project_path),
            "budget_tokens": args.max_tokens,
            "estimated_tokens": est_tokens,
            "total_files": len(ranked_files),
            "total_symbols": sum(len(f.all_symbols) for f in ranked_files),
            "files": [f.to_dict() for f in ranked_files],
            "repomap": formatted_text,
        }
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
    else:
        repomap_text = format_repomap(ranked_files, max_tokens=args.max_tokens)
        sys.stdout.write(repomap_text + "\n")

        if args.verbose:
            est_tokens = count_tokens(repomap_text)
            sys.stderr.write(
                f"[repomap] Output: {est_tokens} tokens / {args.max_tokens} max ({len(ranked_files)} files scanned)\n"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
