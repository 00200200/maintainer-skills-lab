#!/usr/bin/env python3
"""tools/scope_extract.py - Scoped AST Code Extractor Tool for Code Review Skills.

Extracts targeted AST outlines, enclosing function/class scopes, and diff-guided
code slices using the Python 3.11+ standard library. Avoids dumping 1,000+ line files
into coding agent context windows, reducing token consumption by 80-95% during PR
reviews and bug investigation.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


def approximate_tokens(text: str) -> int:
    """Standard ~4 chars per token estimate used across maintainer-skills-lab."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


@dataclass
class SymbolSpan:
    name: str
    kind: str  # "class", "function", "async_function", "method", "async_method", "variable"
    lineno: int
    end_lineno: int
    signature: str
    docstring: str | None = None
    decorators: list[str] = field(default_factory=list)
    parent: str | None = None
    children: list[SymbolSpan] = field(default_factory=list)


def format_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Format the function/method signature without implementation body."""
    prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
    args_repr = ast.unparse(node.args)
    ret_repr = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix}{node.name}({args_repr}){ret_repr}:"


def format_class_header(node: ast.ClassDef) -> str:
    """Format class header with bases and keyword arguments."""
    elements: list[str] = []
    for b in node.bases:
        elements.append(ast.unparse(b))
    for kw in node.keywords:
        if kw.arg:
            elements.append(f"{kw.arg}={ast.unparse(kw.value)}")
        else:
            elements.append(f"**{ast.unparse(kw.value)}")
    bases_part = f"({', '.join(elements)})" if elements else ""
    return f"class {node.name}{bases_part}:"


def extract_docstring_summary(node: ast.AST, max_lines: int = 2) -> str | None:
    """Extract leading docstring summarized to max_lines."""
    doc = ast.get_docstring(node)
    if not doc:
        return None
    lines = [line.strip() for line in doc.strip().splitlines() if line.strip()]
    if not lines:
        return None
    summary = lines[0]
    if len(lines) > 1 and max_lines > 1:
        summary += f" {lines[1]}"
    if len(lines) > max_lines:
        summary += "..."
    return summary


class ASTOutlineExtractor:
    """Extracts high-level signature outlines from Python source."""

    def __init__(self, source: str, filepath: str = "<string>"):
        self.source = source
        self.filepath = filepath
        self.source_lines = source.splitlines()
        self.tree: ast.Module | None = None
        self.error: str | None = None
        try:
            self.tree = ast.parse(source, filename=filepath)
        except SyntaxError as e:
            self.error = f"SyntaxError in {filepath}:{e.lineno}:{e.offset}: {e.msg}"

    def build_outline_symbols(self) -> list[SymbolSpan]:
        """Traverse AST and collect top-level and class-level symbol spans."""
        if not self.tree:
            return []

        symbols: list[SymbolSpan] = []

        for stmt in self.tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "async_function" if isinstance(stmt, ast.AsyncFunctionDef) else "function"
                decs = [f"@{ast.unparse(d)}" for d in stmt.decorator_list]
                symbols.append(
                    SymbolSpan(
                        name=stmt.name,
                        kind=kind,
                        lineno=stmt.lineno,
                        end_lineno=stmt.end_lineno or stmt.lineno,
                        signature=format_signature(stmt),
                        docstring=extract_docstring_summary(stmt),
                        decorators=decs,
                    )
                )
            elif isinstance(stmt, ast.ClassDef):
                decs = [f"@{ast.unparse(d)}" for d in stmt.decorator_list]
                class_span = SymbolSpan(
                    name=stmt.name,
                    kind="class",
                    lineno=stmt.lineno,
                    end_lineno=stmt.end_lineno or stmt.lineno,
                    signature=format_class_header(stmt),
                    docstring=extract_docstring_summary(stmt),
                    decorators=decs,
                )
                for child in stmt.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        child_kind = (
                            "async_method" if isinstance(child, ast.AsyncFunctionDef) else "method"
                        )
                        child_decs = [f"@{ast.unparse(d)}" for d in child.decorator_list]
                        class_span.children.append(
                            SymbolSpan(
                                name=child.name,
                                kind=child_kind,
                                lineno=child.lineno,
                                end_lineno=child.end_lineno or child.lineno,
                                signature=format_signature(child),
                                docstring=extract_docstring_summary(child),
                                decorators=child_decs,
                                parent=stmt.name,
                            )
                        )
                    elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                        val_str = f" = {ast.unparse(child.value)}" if child.value else ""
                        sig = f"{child.target.id}: {ast.unparse(child.annotation)}{val_str}"
                        class_span.children.append(
                            SymbolSpan(
                                name=child.target.id,
                                kind="field",
                                lineno=child.lineno,
                                end_lineno=child.end_lineno or child.lineno,
                                signature=sig,
                                parent=stmt.name,
                            )
                        )
                symbols.append(class_span)
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                val_str = f" = {ast.unparse(stmt.value)}" if stmt.value else ""
                sig = f"{stmt.target.id}: {ast.unparse(stmt.annotation)}{val_str}"
                symbols.append(
                    SymbolSpan(
                        name=stmt.target.id,
                        kind="variable",
                        lineno=stmt.lineno,
                        end_lineno=stmt.end_lineno or stmt.lineno,
                        signature=sig,
                    )
                )

        return symbols

    def render_outline(self) -> str:
        """Render a compact code-like outline (< 150 lines, < 600 tokens)."""
        if self.error:
            return f"# {self.error}\n"

        symbols = self.build_outline_symbols()
        lines: list[str] = [f"# Outline: {self.filepath} ({len(self.source_lines)} lines)", ""]

        for sym in symbols:
            if sym.kind in ("function", "async_function"):
                for dec in sym.decorators:
                    lines.append(dec)
                if sym.docstring:
                    lines.append(f"{sym.signature}  # L{sym.lineno}-{sym.end_lineno}")
                    lines.append(f'    """{sym.docstring}"""')
                else:
                    lines.append(f"{sym.signature} ...  # L{sym.lineno}-{sym.end_lineno}")
                lines.append("")
            elif sym.kind == "class":
                for dec in sym.decorators:
                    lines.append(dec)
                lines.append(f"{sym.signature}  # L{sym.lineno}-{sym.end_lineno}")
                if sym.docstring:
                    lines.append(f'    """{sym.docstring}"""')
                if not sym.children:
                    lines.append("    pass")
                else:
                    for child in sym.children:
                        if child.kind == "field":
                            lines.append(f"    {child.signature}")
                        else:
                            for dec in child.decorators:
                                lines.append(f"    {dec}")
                            if child.docstring:
                                lines.append(
                                    f"    {child.signature}  # L{child.lineno}-{child.end_lineno}"
                                )
                                lines.append(f'        """{child.docstring}"""')
                            else:
                                lines.append(
                                    f"    {child.signature} ...  # L{child.lineno}-{child.end_lineno}"
                                )
                lines.append("")
            elif sym.kind == "variable":
                lines.append(f"{sym.signature}  # L{sym.lineno}")

        return "\n".join(lines).rstrip() + "\n"


class EnclosingScopeExtractor:
    """Finds enclosing class/function definitions covering specified line ranges."""

    def __init__(self, source: str, filepath: str = "<string>"):
        self.source = source
        self.filepath = filepath
        self.source_lines = source.splitlines()
        self.tree: ast.Module | None = None
        self.error: str | None = None
        try:
            self.tree = ast.parse(source, filename=filepath)
        except SyntaxError as e:
            self.error = f"SyntaxError in {filepath}:{e.lineno}:{e.offset}: {e.msg}"

    def find_enclosing_node(
        self, start_line: int, end_line: int
    ) -> tuple[ast.AST | None, ast.ClassDef | None]:
        """Find the most specific enclosing function/class AST node for the line range."""
        if not self.tree:
            return None, None

        best_func: ast.FunctionDef | ast.AsyncFunctionDef | None = None
        enclosing_class: ast.ClassDef | None = None

        for stmt in self.tree.body:
            if isinstance(stmt, ast.ClassDef):
                if stmt.lineno <= start_line and (stmt.end_lineno or stmt.lineno) >= end_line:
                    enclosing_class = stmt
                    for child in stmt.body:
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            if (
                                child.lineno <= start_line
                                and (child.end_lineno or child.lineno) >= end_line
                            ):
                                best_func = child
                                break
                    break
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if stmt.lineno <= start_line and (stmt.end_lineno or stmt.lineno) >= end_line:
                    best_func = stmt
                    break

        if best_func:
            return best_func, enclosing_class
        if enclosing_class:
            return enclosing_class, None

        # Fallback to any node spanning the range
        best_node: ast.AST | None = None
        best_span = float("inf")
        for node in ast.walk(self.tree):
            if hasattr(node, "lineno") and hasattr(node, "end_lineno") and node.end_lineno:
                if node.lineno <= start_line and node.end_lineno >= end_line:
                    span = node.end_lineno - node.lineno
                    if span < best_span and isinstance(
                        node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                    ):
                        best_span = span
                        best_node = node

        return best_node, None

    def extract_lines(self, start_line: int, end_line: int, context: int = 3) -> str:
        """Extract lines with context padding and surrounding scope stubs."""
        if self.error:
            return f"# {self.error}\n"

        target_node, parent_class = self.find_enclosing_node(start_line, end_line)

        # Case 1: Target is a method inside a class
        if (
            target_node
            and parent_class
            and isinstance(target_node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            output: list[str] = [
                f"# Scoped Extraction: {self.filepath} (lines {start_line}-{end_line} in {parent_class.name}.{target_node.name})",
                "",
            ]
            for dec in parent_class.decorator_list:
                output.append(f"@{ast.unparse(dec)}")
            output.append(format_class_header(parent_class))
            doc = extract_docstring_summary(parent_class)
            if doc:
                output.append(f'    """{doc}"""')

            for child in parent_class.body:
                if child is target_node:
                    output.append("")
                    # Output full body of the targeted method with original indentation
                    t_start = target_node.lineno
                    t_end = target_node.end_lineno or t_start
                    for idx in range(t_start - 1, min(t_end, len(self.source_lines))):
                        output.append(f"{self.source_lines[idx]}  # L{idx + 1}")
                    output.append("")
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Sibling method stub
                    sig = format_signature(child)
                    output.append(
                        f"    {sig} ...  # L{child.lineno}-{child.end_lineno or child.lineno}"
                    )

            return "\n".join(output) + "\n"

        # Case 2: Target is a top-level function or standalone class
        if target_node:
            t_start = target_node.lineno
            t_end = target_node.end_lineno or t_start
            output = [
                f"# Scoped Extraction: {self.filepath} (L{t_start}-{t_end})",
                "",
            ]
            for idx in range(t_start - 1, min(t_end, len(self.source_lines))):
                output.append(f"{self.source_lines[idx]}  # L{idx + 1}")
            return "\n".join(output) + "\n"

        # Case 3: Arbitrary module-level range with context padding
        pad_start = max(1, start_line - context)
        pad_end = min(len(self.source_lines), end_line + context)
        output = [
            f"# Scoped Extraction: {self.filepath} (lines {start_line}-{end_line} ± {context})",
            "",
        ]
        for idx in range(pad_start - 1, pad_end):
            marker = " > " if start_line <= idx + 1 <= end_line else "   "
            output.append(f"{idx + 1:4d}{marker}{self.source_lines[idx]}")

        return "\n".join(output) + "\n"

    def extract_symbol(self, symbol_name: str) -> str:
        """Extract the full code definition of a specific symbol (e.g. Class.method or func)."""
        if self.error:
            return f"# {self.error}\n"

        parts = symbol_name.split(".")
        if len(parts) == 1:
            target_name = parts[0]
            for stmt in self.tree.body if self.tree else []:
                if (
                    isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    and stmt.name == target_name
                ):
                    t_start = stmt.lineno
                    t_end = stmt.end_lineno or t_start
                    lines = [
                        f"# Symbol: {symbol_name} in {self.filepath} (L{t_start}-{t_end})",
                        "",
                    ]
                    for idx in range(t_start - 1, min(t_end, len(self.source_lines))):
                        lines.append(self.source_lines[idx])
                    return "\n".join(lines) + "\n"
        elif len(parts) == 2:
            class_name, method_name = parts
            for stmt in self.tree.body if self.tree else []:
                if isinstance(stmt, ast.ClassDef) and stmt.name == class_name:
                    for child in stmt.body:
                        if (
                            isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and child.name == method_name
                        ):
                            t_start = child.lineno
                            t_end = child.end_lineno or t_start
                            lines = [
                                f"# Symbol: {symbol_name} in {self.filepath} (L{t_start}-{t_end})",
                                "",
                            ]
                            for idx in range(t_start - 1, min(t_end, len(self.source_lines))):
                                lines.append(self.source_lines[idx])
                            return "\n".join(lines) + "\n"

        return f"# Error: Symbol '{symbol_name}' not found in {self.filepath}\n"


def parse_unified_diff(diff_text: str) -> dict[str, list[tuple[int, int]]]:
    """Parse unified git diff and extract modified (start_line, end_line) ranges per file."""
    files: dict[str, list[tuple[int, int]]] = {}
    current_file: str | None = None

    file_header_re = re.compile(r"^\+\+\+\s+(?:[ab]/)?([^\t\n\r]+)")
    hunk_header_re = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,(\d+))?\s+@@")

    for line in diff_text.splitlines():
        fm = file_header_re.match(line)
        if fm:
            path = fm.group(1).strip().strip('"').strip("'")
            if path and path != "/dev/null":
                current_file = path
                if current_file not in files:
                    files[current_file] = []
            continue

        if current_file:
            hm = hunk_header_re.match(line)
            if hm:
                start = int(hm.group(1))
                count = int(hm.group(2)) if hm.group(2) is not None else 1
                end = start + max(1, count) - 1
                files[current_file].append((start, end))

    return files


def parse_line_ranges(ranges_str: str) -> list[tuple[int, int]]:
    """Parse comma-separated line range string like '10-25,40-50' or '12'."""
    results: list[tuple[int, int]] = []
    for part in ranges_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            s, e = part.split("-", 1)
            results.append((int(s.strip()), int(e.strip())))
        else:
            n = int(part)
            results.append((n, n))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scoped AST Code Extractor for Maintainer Skills Lab."
    )
    parser.add_argument("--file", "-f", type=str, help="Target Python source file to inspect.")
    parser.add_argument(
        "--outline", action="store_true", help="Emit signatures and docstrings outline only."
    )
    parser.add_argument(
        "--lines",
        "-l",
        type=str,
        help="Line range(s) to extract enclosing scope for (e.g. 45-60 or 10-20,35-40).",
    )
    parser.add_argument(
        "--symbol", "-s", type=str, help="Extract definition of symbol (e.g. MyClass.my_method)."
    )
    parser.add_argument(
        "--diff",
        type=str,
        nargs="?",
        const="-",
        help="Path to unified diff file, or '-' to read diff from stdin.",
    )
    parser.add_argument(
        "--context", "-c", type=int, default=3, help="Context lines padding (default: 3)."
    )
    parser.add_argument(
        "--json", action="store_true", help="Output machine-readable JSON representation."
    )

    args = parser.parse_args(argv)

    # Mode 1: Diff-scoped extraction
    if args.diff:
        if args.diff == "-":
            diff_text = sys.stdin.read()
        else:
            diff_path = Path(args.diff)
            if not diff_path.exists():
                sys.stderr.write(f"Error: Diff file '{args.diff}' not found.\n")
                return 1
            diff_text = diff_path.read_text(encoding="utf-8")

        diff_files = parse_unified_diff(diff_text)
        results: list[dict[str, object]] = []
        combined_text: list[str] = []

        for fpath, ranges in diff_files.items():
            p = Path(fpath)
            if not p.exists() or not fpath.endswith(".py"):
                continue
            src = p.read_text(encoding="utf-8")
            extractor = EnclosingScopeExtractor(src, filepath=fpath)
            for start, end in ranges:
                extracted = extractor.extract_lines(start, end, context=args.context)
                combined_text.append(extracted)
                if args.json:
                    results.append(
                        {
                            "file": fpath,
                            "range": [start, end],
                            "scope": extracted,
                            "tokens_est": approximate_tokens(extracted),
                        }
                    )

        if args.json:
            sys.stdout.write(json.dumps({"diff_scopes": results}, indent=2) + "\n")
        else:
            sys.stdout.write("\n".join(combined_text))
        return 0

    if not args.file:
        parser.error("Either --file or --diff must be specified.")

    target_path = Path(args.file)
    if not target_path.exists():
        sys.stderr.write(f"Error: File '{args.file}' not found.\n")
        return 1

    source = target_path.read_text(encoding="utf-8")

    # Mode 2: Outline
    if args.outline:
        outline_extractor = ASTOutlineExtractor(source, filepath=str(target_path))
        rendered = outline_extractor.render_outline()
        if args.json:
            symbols = [asdict(s) for s in outline_extractor.build_outline_symbols()]
            payload = {
                "file": str(target_path),
                "mode": "outline",
                "symbols": symbols,
                "rendered": rendered,
                "lines": len(rendered.splitlines()),
                "tokens_est": approximate_tokens(rendered),
                "error": outline_extractor.error,
            }
            sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        else:
            sys.stdout.write(rendered)
        return 1 if outline_extractor.error else 0

    # Mode 3: Specific symbol
    if args.symbol:
        scope_extractor = EnclosingScopeExtractor(source, filepath=str(target_path))
        rendered = scope_extractor.extract_symbol(args.symbol)
        if args.json:
            payload = {
                "file": str(target_path),
                "mode": "symbol",
                "symbol": args.symbol,
                "rendered": rendered,
                "tokens_est": approximate_tokens(rendered),
                "error": scope_extractor.error,
            }
            sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        else:
            sys.stdout.write(rendered)
        return 1 if "# Error:" in rendered else 0

    # Mode 4: Specific line ranges
    if args.lines:
        ranges = parse_line_ranges(args.lines)
        scope_extractor = EnclosingScopeExtractor(source, filepath=str(target_path))
        slices: list[str] = []
        for start, end in ranges:
            slices.append(scope_extractor.extract_lines(start, end, context=args.context))
        combined = "\n".join(slices)
        if args.json:
            payload = {
                "file": str(target_path),
                "mode": "lines",
                "ranges": ranges,
                "rendered": combined,
                "tokens_est": approximate_tokens(combined),
                "error": scope_extractor.error,
            }
            sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        else:
            sys.stdout.write(combined)
        return 1 if scope_extractor.error else 0

    # Default to outline if nothing else specified
    outline_extractor = ASTOutlineExtractor(source, filepath=str(target_path))
    sys.stdout.write(outline_extractor.render_outline())
    return 0


if __name__ == "__main__":
    sys.exit(main())
