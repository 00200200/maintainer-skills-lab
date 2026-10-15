"""tools/extract_type_diagnostics.py - Compact AST-scoped type diagnostic extractor.

Extracts localized, symbol-scoped type checker errors from mypy or pyright runs.
Reduces 2,000+ token raw compiler logs down to ultra-compact (< 150 tokens)
actionable diagnostic slices for self-healing AI coding agents.

Zero external dependencies (Python 3.11+ standard library only).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Match standard mypy error/warning/note lines:
# file.py:42: error: message [error-code]
# file.py:42:15: error: message [error-code]
# file.py:42: note: message
MYPY_LINE_PATTERN = re.compile(
    r"^(?P<file>[^:\n\r]+):(?P<line>\d+)(?::(?P<col>\d+))?:\s*(?P<severity>error|warning|note):\s*(?P<message>.+?)(?:\s*\[(?P<code>[a-zA-Z0-9_-]+)\])?$"
)

# Common fix recommendation mappings based on mypy error codes and pyright rules
FIX_RECOMMENDATIONS: dict[str, str] = {
    "union-attr": "Add guard 'if <symbol> is None: return ...' or check type before accessing attribute",
    "reportOptionalMemberAccess": "Add guard 'if <symbol> is None: return ...' before member access",
    "arg-type": "Widen parameter annotation to Sequence/Mapping or convert argument explicitly",
    "reportArgumentType": "Widen parameter annotation or cast argument to expected type",
    "return-value": "Widen function return type annotation (e.g. 'T | None') or return fallback",
    "reportReturnType": "Widen return type annotation or ensure all branches return expected type",
    "assignment": "Widen variable type annotation or use typing.cast()",
    "reportAssignmentType": "Adjust variable type annotation or cast assigned expression",
    "var-annotated": "Add explicit type annotation to variable declaration",
    "reportUnknownVariableType": "Add explicit type annotation to variable declaration",
    "name-defined": "Define symbol or import missing identifier before usage",
    "reportUndefinedVariable": "Import or define variable before referencing it",
    "attr-defined": "Verify attribute spelling or define attribute on class/protocol",
    "reportAttributeAccessIssue": "Verify attribute name or define Protocol attribute",
    "override": "Match overridden base class method signature and parameter types",
    "index": "Ensure object supports indexing or narrow from Optional before indexing",
    "reportIndexIssue": "Ensure container supports indexing or add None check",
    "call-arg": "Check function argument count and keyword parameter names against definition",
    "reportCallIssue": "Check parameter count and argument types against signature",
    "import": "Verify module import path or install type stubs (e.g. types-requests)",
    "reportMissingImports": "Verify module import path or add '# type: ignore[import]'",
}


@dataclass
class TypeDiagnostic:
    file: str
    line: int
    column: int | None = None
    severity: str = "error"
    message: str = ""
    code: str | None = None
    source_tool: str = "mypy"
    notes: list[str] = field(default_factory=list)
    symbol: str | None = None
    symbol_type: str | None = None
    context_code: str | None = None
    recommended_fix: str = ""


# =============================================================================
# AST Enclosing Scope & Symbol Extraction
# =============================================================================


def extract_symbol_and_scope(
    file_path: Path, target_line: int, max_context_lines: int = 15
) -> tuple[str | None, str | None, str | None]:
    """Extracts the enclosing AST function/class symbol and compact line context.

    Returns:
        (symbol_name, symbol_type, context_code)
    """
    if not file_path.exists() or not file_path.is_file():
        return None, None, None

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None, None

    lines = content.splitlines()
    total_lines = len(lines)
    if target_line < 1 or target_line > total_lines:
        return None, None, None

    symbol_name: str | None = None
    symbol_type: str | None = None
    start_line = max(1, target_line - 2)
    end_line = min(total_lines, target_line + 2)

    try:
        tree = ast.parse(content, filename=str(file_path))
        enclosing_stack: list[tuple[str, str, int, int]] = []

        class ScopeFinder(ast.NodeVisitor):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                end = getattr(node, "end_lineno", node.lineno)
                if node.lineno <= target_line <= end:
                    enclosing_stack.append((node.name, "function", node.lineno, end))
                self.generic_visit(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                end = getattr(node, "end_lineno", node.lineno)
                if node.lineno <= target_line <= end:
                    enclosing_stack.append((node.name, "async_function", node.lineno, end))
                self.generic_visit(node)

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                end = getattr(node, "end_lineno", node.lineno)
                if node.lineno <= target_line <= end:
                    enclosing_stack.append((node.name, "class", node.lineno, end))
                self.generic_visit(node)

        ScopeFinder().visit(tree)

        if enclosing_stack:
            # Deepest symbol
            names = [item[0] for item in enclosing_stack]
            symbol_name = ".".join(names)
            symbol_type = enclosing_stack[-1][1]
            node_start = enclosing_stack[-1][2]
            node_end = enclosing_stack[-1][3]

            # Keep context focused around error line while including function header
            if (node_end - node_start + 1) <= max_context_lines:
                start_line = node_start
                end_line = node_end
            else:
                # Include definition line and target line surroundings
                start_line = max(node_start, target_line - 4)
                end_line = min(node_end, target_line + 4)
    except SyntaxError:
        pass  # Fall back to line slice around target_line

    # Format context lines with line numbers
    context_slice = [
        f"{idx}: {lines[idx - 1]}"
        for idx in range(start_line, end_line + 1)
        if 1 <= idx <= total_lines
    ]
    context_code = "\n".join(context_slice) if context_slice else None
    return symbol_name, symbol_type, context_code


# =============================================================================
# Diagnostic Parsers
# =============================================================================


def determine_recommended_fix(code: str | None, message: str, symbol: str | None = None) -> str:
    """Generates a concise, deterministic repair recommendation for an error."""
    if code and code in FIX_RECOMMENDATIONS:
        fix = FIX_RECOMMENDATIONS[code]
        if symbol:
            target = symbol.split(".")[-1]
            fix = fix.replace("<symbol>", target)
        else:
            fix = fix.replace("<symbol>", "variable")
        return fix

    msg_lower = message.lower()
    if "has no attribute" in msg_lower or 'item "none"' in msg_lower:
        return "Add guard 'if <var> is None: return ...' or check type before accessing attribute"
    if "incompatible return value" in msg_lower or "expected return type" in msg_lower:
        return "Widen return type annotation or ensure all branches return expected type"
    if "incompatible type" in msg_lower and "expected" in msg_lower:
        return "Widen parameter annotation to Sequence/Mapping or convert argument"
    if "missing type annotation" in msg_lower:
        return "Add explicit type annotation to variable or function parameter"

    return "Verify type annotations or narrow symbol type before usage"


def parse_mypy_output(
    text: str, root_dir: Path | None = None, with_scope: bool = True
) -> list[TypeDiagnostic]:
    """Parses standard mypy text output into structured TypeDiagnostics."""
    diagnostics: list[TypeDiagnostic] = []
    current_diag: TypeDiagnostic | None = None

    for raw_line in text.splitlines():
        line_str = raw_line.strip()
        if not line_str or line_str.startswith("Found ") or line_str.startswith("Success:"):
            continue

        match = MYPY_LINE_PATTERN.match(line_str)
        if not match:
            continue

        file_str = match.group("file").strip()
        line_num = int(match.group("line"))
        col_str = match.group("col")
        col_num = int(col_str) if col_str else None
        severity = match.group("severity")
        message = match.group("message").strip()
        code = match.group("code")

        if severity == "note":
            if (
                current_diag
                and current_diag.file == file_str
                and abs(current_diag.line - line_num) <= 5
            ):
                current_diag.notes.append(message)
            continue

        # Create diagnostic entry
        file_path = Path(file_str)
        if root_dir and not file_path.is_absolute():
            resolved_path = (root_dir / file_path).resolve()
        else:
            resolved_path = file_path.resolve()

        sym_name: str | None = None
        sym_type: str | None = None
        ctx_code: str | None = None

        if with_scope and resolved_path.exists() and resolved_path.is_file():
            sym_name, sym_type, ctx_code = extract_symbol_and_scope(resolved_path, line_num)

        rec_fix = determine_recommended_fix(code, message, sym_name)

        diag = TypeDiagnostic(
            file=file_str,
            line=line_num,
            column=col_num,
            severity=severity,
            message=message,
            code=code,
            source_tool="mypy",
            symbol=sym_name,
            symbol_type=sym_type,
            context_code=ctx_code,
            recommended_fix=rec_fix,
        )
        diagnostics.append(diag)
        current_diag = diag

    return diagnostics


def parse_pyright_output(
    json_data: str | dict, root_dir: Path | None = None, with_scope: bool = True
) -> list[TypeDiagnostic]:
    """Parses pyright JSON output into structured TypeDiagnostics."""
    if isinstance(json_data, str):
        try:
            data = json.loads(json_data)
        except json.JSONDecodeError:
            return []
    else:
        data = json_data

    raw_items = data.get("generalDiagnostics", [])
    diagnostics: list[TypeDiagnostic] = []

    for item in raw_items:
        file_str = item.get("file", "")
        range_info = item.get("range", {}).get("start", {})
        # Pyright lines are 0-indexed
        line_num = int(range_info.get("line", 0)) + 1
        col_num = int(range_info.get("character", 0)) + 1
        severity = item.get("severity", "error")
        message = item.get("message", "").strip()
        rule = item.get("rule")

        file_path = Path(file_str)
        if root_dir and not file_path.is_absolute():
            resolved_path = (root_dir / file_path).resolve()
        else:
            resolved_path = file_path.resolve()

        sym_name: str | None = None
        sym_type: str | None = None
        ctx_code: str | None = None

        if with_scope and resolved_path.exists() and resolved_path.is_file():
            sym_name, sym_type, ctx_code = extract_symbol_and_scope(resolved_path, line_num)

        rec_fix = determine_recommended_fix(rule, message, sym_name)

        # Make file path relative if under root_dir for compact display
        display_file = file_str
        if root_dir:
            try:
                display_file = str(resolved_path.relative_to(root_dir.resolve()))
            except ValueError:
                pass

        diag = TypeDiagnostic(
            file=display_file,
            line=line_num,
            column=col_num,
            severity=severity,
            message=message,
            code=rule,
            source_tool="pyright",
            symbol=sym_name,
            symbol_type=sym_type,
            context_code=ctx_code,
            recommended_fix=rec_fix,
        )
        diagnostics.append(diag)

    return diagnostics


# =============================================================================
# Deduplication & Serialization
# =============================================================================


def deduplicate_diagnostics(
    diagnostics: list[TypeDiagnostic], max_per_symbol: int = 3
) -> list[TypeDiagnostic]:
    """Deduplicates diagnostics and caps error cascades from the same symbol."""
    seen_counts: dict[tuple[str, str | None], int] = {}
    deduped: list[TypeDiagnostic] = []

    for diag in diagnostics:
        key = (diag.file, diag.symbol)
        count = seen_counts.get(key, 0)
        if count >= max_per_symbol:
            continue
        seen_counts[key] = count + 1
        deduped.append(diag)

    return deduped


def format_xml(diagnostics: list[TypeDiagnostic]) -> str:
    """Renders diagnostics into ultra-compact, token-efficient XML blocks."""
    if not diagnostics:
        return '<type_errors count="0" status="CLEAN"/>\n'

    out: list[str] = [f'<type_errors count="{len(diagnostics)}">']
    for diag in diagnostics:
        code_attr = f' code="{diag.code}"' if diag.code else ""
        col_attr = f' col="{diag.column}"' if diag.column is not None else ""
        out.append(f'  <type_error file="{diag.file}" line="{diag.line}"{col_attr}{code_attr}>')
        if diag.symbol:
            sym_type_attr = f' type="{diag.symbol_type}"' if diag.symbol_type else ""
            out.append(f"    <symbol{sym_type_attr}>{diag.symbol}</symbol>")
        out.append(f"    <message>{diag.message}</message>")
        for note in diag.notes:
            out.append(f"    <note>{note}</note>")
        if diag.context_code:
            out.append("    <context>")
            for c_line in diag.context_code.splitlines():
                out.append(f"      {c_line}")
            out.append("    </context>")
        if diag.recommended_fix:
            out.append(f"    <recommended_fix>{diag.recommended_fix}</recommended_fix>")
        out.append("  </type_error>")
    out.append("</type_errors>")
    return "\n".join(out) + "\n"


def format_json(diagnostics: list[TypeDiagnostic]) -> str:
    """Renders diagnostics into structured JSON."""
    payload = {
        "status": "ERROR" if diagnostics else "CLEAN",
        "error_count": len(diagnostics),
        "diagnostics": [asdict(d) for d in diagnostics],
    }
    return json.dumps(payload, indent=2)


# =============================================================================
# CLI Main
# =============================================================================


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract compact, AST-scoped type diagnostics from mypy or pyright."
    )
    parser.add_argument(
        "--mypy-log",
        "-m",
        type=Path,
        help="Path to mypy text log file (defaults to stdin if not specified)",
    )
    parser.add_argument(
        "--pyright-json",
        "-p",
        type=Path,
        help="Path to pyright JSON output file",
    )
    parser.add_argument(
        "--format",
        choices=["auto", "mypy", "pyright"],
        default="auto",
        help="Input format (default: auto)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root directory for resolving file paths",
    )
    parser.add_argument(
        "--with-scope",
        dest="with_scope",
        action="store_true",
        default=True,
        help="Extract AST enclosing symbol and source context lines (default: true)",
    )
    parser.add_argument(
        "--no-scope",
        dest="with_scope",
        action="store_false",
        help="Disable AST enclosing symbol extraction",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON instead of compact XML",
    )
    parser.add_argument(
        "--max-per-symbol",
        type=int,
        default=3,
        help="Max error reports per symbol to suppress cascading errors (default: 3)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print only a single-line summary of findings",
    )

    args = parser.parse_args(argv)

    input_text = ""
    fmt = args.format

    if args.pyright_json:
        input_text = args.pyright_json.read_text(encoding="utf-8")
        fmt = "pyright"
    elif args.mypy_log:
        input_text = args.mypy_log.read_text(encoding="utf-8")
        fmt = "mypy"
    else:
        if not sys.stdin.isatty():
            input_text = sys.stdin.read()
        else:
            parser.print_help(sys.stderr)
            return 1

    # Auto-detect format if set to auto
    if fmt == "auto":
        stripped = input_text.strip()
        if (stripped.startswith("{") and "generalDiagnostics" in stripped) or (
            stripped.startswith("[")
        ):
            fmt = "pyright"
        else:
            fmt = "mypy"

    diagnostics: list[TypeDiagnostic] = []
    if fmt == "pyright":
        diagnostics = parse_pyright_output(
            input_text, root_dir=args.root, with_scope=args.with_scope
        )
    else:
        diagnostics = parse_mypy_output(input_text, root_dir=args.root, with_scope=args.with_scope)

    # Deduplicate and cap cascades
    diagnostics = deduplicate_diagnostics(diagnostics, max_per_symbol=args.max_per_symbol)

    if args.summary:
        print(f"Total type errors: {len(diagnostics)}")
        return 0 if not diagnostics else 1

    if args.json:
        sys.stdout.write(format_json(diagnostics) + "\n")
    else:
        sys.stdout.write(format_xml(diagnostics))

    return 0 if not diagnostics else 1


if __name__ == "__main__":
    sys.exit(main())
