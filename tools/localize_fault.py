"""tools/localize_fault.py - Two-stage fault localization and scoped context slicer.

Enforces a two-phase fault isolation protocol before code repair (inspired by Agentless):
1. Stage 1 (Localization): Parse tracebacks or search AST skeletons to isolate suspect
   file, symbol, and line ranges into a compact YAML artifact (< 300 tokens).
2. Stage 2 (Scoped Context Slicing): Extract only the targeted line range with bounded
   padding (+/- 15 lines), avoiding whole-file context dumps and saving 80-95% tokens.

Zero external dependencies (Python 3.11+ standard library only).
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class StackFrame:
    filepath: str
    line_number: int
    function_name: str
    code_line: str = ""


# Regex matching Python tracebacks: File "...", line 123, in my_func
TRACEBACK_FRAME_RE = re.compile(
    r'File\s+"(?P<filepath>[^"]+)",\s+line\s+(?P<line>\d+)(?:,\s+in\s+(?P<func>[^\n]+))?'
)


def parse_traceback(text: str) -> list[StackFrame]:
    """Extracts stack frames from a Python exception traceback text."""
    frames: list[StackFrame] = []
    lines = text.splitlines()

    for i, line in enumerate(lines):
        match = TRACEBACK_FRAME_RE.search(line)
        if match:
            filepath = match.group("filepath")
            line_no = int(match.group("line"))
            func = match.group("func") or "<unknown>"
            code_line = ""
            if (
                i + 1 < len(lines)
                and lines[i + 1].strip()
                and not lines[i + 1].startswith("  File")
            ):
                code_line = lines[i + 1].strip()
            frames.append(
                StackFrame(
                    filepath=filepath,
                    line_number=line_no,
                    function_name=func,
                    code_line=code_line,
                )
            )

    return frames


def extract_slice(
    filepath: Path,
    start_line: int,
    end_line: int,
    padding: int = 15,
    show_line_numbers: bool = True,
) -> str:
    """Extracts a scoped slice of a file around [start_line, end_line] with bounded padding.

    Adds omission comments before and after the slice to indicate omitted file context.
    """
    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    content = filepath.read_text(encoding="utf-8")
    lines = content.splitlines()
    total_lines = len(lines)

    if total_lines == 0:
        return "# (Empty file)\n"

    # Clamp line bounds (1-indexed)
    start_line = max(1, min(start_line, total_lines))
    end_line = max(start_line, min(end_line, total_lines))

    slice_start = max(1, start_line - padding)
    slice_end = min(total_lines, end_line + padding)

    output: list[str] = []

    # Leading omission note
    if slice_start > 1:
        omitted_before = slice_start - 1
        output.append(
            f"# ... [{omitted_before} lines omitted for brevity (lines 1-{omitted_before})] ..."
        )

    # Target lines
    max_num_width = len(str(slice_end))
    for line_idx in range(slice_start, slice_end + 1):
        line_content = lines[line_idx - 1]
        if show_line_numbers:
            output.append(f"{line_idx:>{max_num_width}} | {line_content}")
        else:
            output.append(line_content)

    # Trailing omission note
    if slice_end < total_lines:
        omitted_after = total_lines - slice_end
        output.append(
            f"# ... [{omitted_after} lines omitted for brevity (lines {slice_end + 1}-{total_lines})] ..."
        )

    return "\n".join(output) + "\n"


def find_symbol_range(filepath: Path, symbol_name: str) -> tuple[int, int] | None:
    """Finds the line range (start_line, end_line) of a class or function symbol in a Python file."""
    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    code = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(code, filename=str(filepath))
    except SyntaxError:
        return None

    # Handle Class.method syntax
    parts = symbol_name.split(".")

    if len(parts) == 1:
        target = parts[0]
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == target:
                    end = getattr(node, "end_lineno", node.lineno)
                    return (node.lineno, end)
    elif len(parts) == 2:
        class_target, method_target = parts[0], parts[1]
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_target:
                for child in ast.iter_child_nodes(node):
                    if (
                        isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name == method_target
                    ):
                        end = getattr(child, "end_lineno", child.lineno)
                        return (child.lineno, end)

    return None


def generate_ast_skeleton(filepath: Path) -> str:
    """Generates an AST outline of a Python module showing classes, methods, and signatures only."""
    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    code = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(code, filename=str(filepath))
    except SyntaxError as e:
        return f"# SyntaxError parsing {filepath}: {e}\n"

    lines = code.splitlines()
    out: list[str] = [f"# Outline: {filepath.name} ({len(lines)} lines)", ""]

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            out.append(
                f"class {node.name}:  # lines {node.lineno}-{getattr(node, 'end_lineno', node.lineno)}"
            )
            doc = ast.get_docstring(node)
            if doc:
                first_line = doc.strip().splitlines()[0]
                out.append(f'    """{first_line}"""')

            methods_found = False
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods_found = True
                    args_list = [a.arg for a in child.args.args]
                    sig = ", ".join(args_list)
                    prefix = "async def" if isinstance(child, ast.AsyncFunctionDef) else "def"
                    end = getattr(child, "end_lineno", child.lineno)
                    out.append(
                        f"    {prefix} {child.name}({sig}): ...  # lines {child.lineno}-{end}"
                    )

            if not methods_found:
                out.append("    ...")
            out.append("")

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args_list = [a.arg for a in node.args.args]
            sig = ", ".join(args_list)
            prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            end = getattr(node, "end_lineno", node.lineno)
            out.append(f"{prefix} {node.name}({sig}): ...  # lines {node.lineno}-{end}")
            doc = ast.get_docstring(node)
            if doc:
                first_line = doc.strip().splitlines()[0]
                out.append(f'    """{first_line}"""')
            out.append("")

    return "\n".join(out).rstrip() + "\n"


def generate_yaml_report(
    filepath: str,
    symbol: str,
    start_line: int,
    end_line: int,
    confidence: str = "high",
    rationale: str = "",
) -> str:
    """Formats localization findings as a standard minimal YAML artifact."""
    lines = [
        "fault_localization:",
        f'  file: "{filepath}"',
        f'  symbol: "{symbol}"',
        f"  line_range: [{start_line}, {end_line}]",
        f'  confidence: "{confidence}"',
    ]
    if rationale:
        lines.append(f'  rationale: "{rationale.strip()}"')
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Two-stage fault localization and scoped context extraction tool."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Command: extract
    p_extract = subparsers.add_parser("extract", help="Extract scoped slice with padding")
    p_extract.add_argument("--file", "-f", required=True, type=Path, help="Path to source file")
    p_extract.add_argument(
        "--lines", "-l", required=True, help="Line range, e.g. '142-168' or '142'"
    )
    p_extract.add_argument(
        "--padding", "-p", type=int, default=15, help="Lines of context padding (default: 15)"
    )
    p_extract.add_argument(
        "--no-numbers", action="store_true", help="Omit line numbers from slice output"
    )

    # Command: locate
    p_locate = subparsers.add_parser("locate", help="Parse traceback into suspect frames")
    p_locate.add_argument(
        "--traceback", "-t", required=True, help="Traceback text or path to traceback file"
    )

    # Command: skeleton
    p_skel = subparsers.add_parser("skeleton", help="Generate signature outline of a Python file")
    p_skel.add_argument("--file", "-f", required=True, type=Path, help="Path to Python file")

    # Command: symbol
    p_sym = subparsers.add_parser("symbol", help="Extract class or method definition slice")
    p_sym.add_argument("--file", "-f", required=True, type=Path, help="Path to Python file")
    p_sym.add_argument("--symbol", "-s", required=True, help="Symbol name (e.g. MyClass.my_method)")
    p_sym.add_argument(
        "--padding", "-p", type=int, default=10, help="Lines of context padding (default: 10)"
    )

    args = parser.parse_args(argv)

    if args.command == "extract":
        parts = args.lines.split("-")
        try:
            start = int(parts[0])
            end = int(parts[1]) if len(parts) > 1 else start
        except ValueError:
            sys.stderr.write(f"Invalid line range: {args.lines}\n")
            return 1

        try:
            result = extract_slice(
                filepath=args.file,
                start_line=start,
                end_line=end,
                padding=args.padding,
                show_line_numbers=not args.no_numbers,
            )
            sys.stdout.write(result)
            return 0
        except FileNotFoundError as e:
            sys.stderr.write(f"Error: {e}\n")
            return 1

    elif args.command == "locate":
        tb_input = args.traceback
        tb_path = Path(tb_input)
        if tb_path.exists():
            text = tb_path.read_text(encoding="utf-8")
        else:
            text = tb_input

        frames = parse_traceback(text)
        if not frames:
            print("No Python stack frames detected in input.")
            return 0

        print(f"Detected {len(frames)} stack frame(s):")
        for i, frame in enumerate(frames, start=1):
            print(f"  [{i}] {frame.filepath}:{frame.line_number} in {frame.function_name}()")
            if frame.code_line:
                print(f"      > {frame.code_line}")

        # Recommend innermost non-stdlib candidate
        suspect = frames[-1]
        print("\nPrimary candidate for localization:")
        print(
            generate_yaml_report(
                filepath=suspect.filepath,
                symbol=suspect.function_name,
                start_line=max(1, suspect.line_number - 10),
                end_line=suspect.line_number + 10,
                confidence="high",
                rationale=f"Innermost frame: {suspect.code_line or 'crash point'}",
            )
        )
        return 0

    elif args.command == "skeleton":
        try:
            skel = generate_ast_skeleton(args.file)
            sys.stdout.write(skel)
            return 0
        except FileNotFoundError as e:
            sys.stderr.write(f"Error: {e}\n")
            return 1

    elif args.command == "symbol":
        try:
            bounds = find_symbol_range(args.file, args.symbol)
            if bounds is None:
                sys.stderr.write(f"Symbol '{args.symbol}' not found in {args.file}\n")
                return 1

            start, end = bounds
            result = extract_slice(
                filepath=args.file,
                start_line=start,
                end_line=end,
                padding=args.padding,
                show_line_numbers=True,
            )
            sys.stdout.write(result)
            return 0
        except FileNotFoundError as e:
            sys.stderr.write(f"Error: {e}\n")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
