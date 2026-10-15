"""tools/structural_refactor.py - AST-based structural code refactoring tool.

Enables maintainer agents and developers to apply declarative structural rewrite
rules across a codebase without regenerating entire files. Supports ast-grep (sg)
when present, and falls back to a zero-dependency pure Python AST engine.

Zero external dependencies (Python 3.11+ standard library only).
"""

from __future__ import annotations

import argparse
import ast
import copy
import difflib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class RefactorResult:
    file: str
    matches_count: int
    diff: str
    additions: int
    deletions: int
    success: bool
    error: str | None = None


def has_native_ast_grep() -> bool:
    """Checks whether ast-grep (`sg` or `ast-grep`) binary is available on PATH."""
    return bool(shutil.which("ast-grep") or shutil.which("sg"))


def get_native_binary_path() -> str | None:
    """Returns the executable path of ast-grep or sg if installed."""
    return shutil.which("ast-grep") or shutil.which("sg")


def run_native_ast_grep(
    pattern: str, rewrite: str, target_path: Path, dry_run: bool = False
) -> subprocess.CompletedProcess[str] | None:
    """Delegates refactoring to native ast-grep binary if available."""
    binary = get_native_binary_path()
    if not binary:
        return None
    cmd = [binary, "run", "--pattern", pattern, "--rewrite", rewrite]
    if not dry_run:
        cmd.append("--update-all")
    cmd.append(str(target_path))
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


# =============================================================================
# Pure Python AST Structural Matching & Transformation
# =============================================================================


def _to_internal_metavars(pattern_str: str) -> str:
    """Replaces ast-grep metavariables ($VAR, $$$ARGS) with valid Python identifiers."""
    # Multi-variable: $$$ARGS -> __mkl_multi_ARGS__
    res = re.sub(r"\$\$\$([A-Za-z0-9_]+)", r"__mkl_multi_\1__", pattern_str)
    # Single-variable: $VAR -> __mkl_meta_VAR__
    res = re.sub(r"\$([A-Za-z0-9_]+)", r"__mkl_meta_\1__", res)
    return res


def _line_col_to_index(lines: list[str], lineno: int, col: int) -> int:
    """Converts 1-indexed lineno and 0-indexed column to character offset in source."""
    if lineno <= 0:
        return 0
    offset = sum(len(lines[i]) for i in range(min(lineno - 1, len(lines))))
    return offset + col


def _match_node(
    p_node: ast.AST | None,
    t_node: ast.AST | None,
    bindings: dict[str, ast.AST | list[ast.AST]],
) -> bool:
    """Recursively matches pattern AST against target AST, capturing metavariable bindings."""
    if p_node is None and t_node is None:
        return True
    if p_node is None or t_node is None:
        return False

    # Check for single metavariable: __mkl_meta_<name>__
    if (
        isinstance(p_node, ast.Name)
        and p_node.id.startswith("__mkl_meta_")
        and p_node.id.endswith("__")
    ):
        name = p_node.id[len("__mkl_meta_") : -2]
        if name in bindings:
            bound = bindings[name]
            if isinstance(bound, ast.AST):
                return ast.unparse(bound) == ast.unparse(t_node)
            return False
        bindings[name] = t_node
        return True

    # Same node type required
    if type(p_node) is not type(t_node):
        return False

    # Assert statements
    if isinstance(p_node, ast.Assert):
        assert isinstance(t_node, ast.Assert)
        if not _match_node(p_node.test, t_node.test, bindings):
            return False
        return _match_node(p_node.msg, t_node.msg, bindings)

    # Comparisons
    if isinstance(p_node, ast.Compare):
        assert isinstance(t_node, ast.Compare)
        if len(p_node.ops) != len(t_node.ops) or len(p_node.comparators) != len(t_node.comparators):
            return False
        for po, to in zip(p_node.ops, t_node.ops, strict=False):
            if type(po) is not type(to):
                return False
        if not _match_node(p_node.left, t_node.left, bindings):
            return False
        for pc, tc in zip(p_node.comparators, t_node.comparators, strict=False):
            if not _match_node(pc, tc, bindings):
                return False
        return True

    # Function & Method Calls
    if isinstance(p_node, ast.Call):
        assert isinstance(t_node, ast.Call)
        if not _match_node(p_node.func, t_node.func, bindings):
            return False

        # Multi-argument metavariable support: $$$ARGS
        if (
            len(p_node.args) == 1
            and isinstance(p_node.args[0], ast.Name)
            and p_node.args[0].id.startswith("__mkl_multi_")
            and p_node.args[0].id.endswith("__")
        ):
            mname = p_node.args[0].id[len("__mkl_multi_") : -2]
            bindings[mname] = list(t_node.args)
            bindings[f"{mname}__keywords"] = list(t_node.keywords)
            return True

        if len(p_node.args) != len(t_node.args):
            return False
        for pa, ta in zip(p_node.args, t_node.args, strict=False):
            if not _match_node(pa, ta, bindings):
                return False

        # Match keywords if specified in pattern
        if p_node.keywords:
            if len(p_node.keywords) != len(t_node.keywords):
                return False
            for pk, tk in zip(p_node.keywords, t_node.keywords, strict=False):
                if pk.arg != tk.arg or not _match_node(pk.value, tk.value, bindings):
                    return False
        return True

    # Attribute access (e.g. obj.attr)
    if isinstance(p_node, ast.Attribute):
        assert isinstance(t_node, ast.Attribute)
        if p_node.attr != t_node.attr:
            return False
        return _match_node(p_node.value, t_node.value, bindings)

    # Identifiers
    if isinstance(p_node, ast.Name):
        assert isinstance(t_node, ast.Name)
        return p_node.id == t_node.id

    # Literals & Constants
    if isinstance(p_node, ast.Constant):
        assert isinstance(t_node, ast.Constant)
        return p_node.value == t_node.value

    # Subscripts (e.g. obj[key])
    if isinstance(p_node, ast.Subscript):
        assert isinstance(t_node, ast.Subscript)
        if not _match_node(p_node.value, t_node.value, bindings):
            return False
        return _match_node(p_node.slice, t_node.slice, bindings)

    # Unary & Binary Operations
    if isinstance(p_node, ast.BinOp):
        assert isinstance(t_node, ast.BinOp)
        if type(p_node.op) is not type(t_node.op):
            return False
        return _match_node(p_node.left, t_node.left, bindings) and _match_node(
            p_node.right, t_node.right, bindings
        )

    # General fallback for identical subtrees
    return ast.unparse(p_node) == ast.unparse(t_node)


def _build_replacement_node(
    rewrite_ast: ast.AST, bindings: dict[str, ast.AST | list[ast.AST]]
) -> ast.AST:
    """Builds a new AST node substituting bound metavariables into the rewrite template."""
    cloned = copy.deepcopy(rewrite_ast)

    class Rewriter(ast.NodeTransformer):
        def visit_Name(self, node: ast.Name) -> ast.AST:
            if node.id.startswith("__mkl_meta_") and node.id.endswith("__"):
                name = node.id[len("__mkl_meta_") : -2]
                if name in bindings and isinstance(bindings[name], ast.AST):
                    return copy.deepcopy(bindings[name])
            return node

        def visit_Call(self, node: ast.Call) -> ast.AST:
            self.generic_visit(node)
            new_args: list[ast.expr] = []
            new_keywords = list(node.keywords)

            for arg in node.args:
                if (
                    isinstance(arg, ast.Name)
                    and arg.id.startswith("__mkl_multi_")
                    and arg.id.endswith("__")
                ):
                    mname = arg.id[len("__mkl_multi_") : -2]
                    if mname in bindings and isinstance(bindings[mname], list):
                        for item in bindings[mname]:
                            if isinstance(item, ast.expr):
                                new_args.append(copy.deepcopy(item))
                    kw_key = f"{mname}__keywords"
                    if kw_key in bindings and isinstance(bindings[kw_key], list):
                        for kw in bindings[kw_key]:
                            if isinstance(kw, ast.keyword):
                                new_keywords.append(copy.deepcopy(kw))
                    continue
                new_args.append(arg)

            node.args = new_args
            node.keywords = new_keywords
            return node

    return Rewriter().visit(cloned)


def refactor_source(
    source_code: str, pattern_str: str, rewrite_str: str
) -> tuple[str, int, str | None]:
    """Applies structural pattern and rewrite across Python source code.

    Returns:
        (transformed_code, matches_count, error_message)
    """
    if not source_code.strip():
        return source_code, 0, None

    internal_pat = _to_internal_metavars(pattern_str.strip())
    internal_rew = _to_internal_metavars(rewrite_str.strip())

    try:
        pat_module = ast.parse(internal_pat)
        rew_module = ast.parse(internal_rew)
    except SyntaxError as e:
        return source_code, 0, f"Pattern syntax error: {e}"

    if not pat_module.body or not rew_module.body:
        return source_code, 0, "Empty pattern or rewrite definition"

    # Determine whether pattern is a statement or an expression
    pat_stmt = pat_module.body[0]
    rew_stmt = rew_module.body[0]

    is_expr = isinstance(pat_stmt, ast.Expr) and isinstance(rew_stmt, ast.Expr)
    p_target = pat_stmt.value if is_expr else pat_stmt
    r_target = rew_stmt.value if is_expr else rew_stmt

    try:
        tree = ast.parse(source_code)
    except SyntaxError as e:
        return source_code, 0, f"Source file syntax error: {e}"

    lines = source_code.splitlines(keepends=True)
    matches: list[tuple[int, int, ast.AST, dict[str, ast.AST | list[ast.AST]]]] = []

    for node in ast.walk(tree):
        bindings: dict[str, ast.AST | list[ast.AST]] = {}
        if _match_node(p_target, node, bindings):
            lineno = getattr(node, "lineno", None)
            col_offset = getattr(node, "col_offset", None)
            end_lineno = getattr(node, "end_lineno", None)
            end_col_offset = getattr(node, "end_col_offset", None)

            if (
                lineno is not None
                and col_offset is not None
                and end_lineno is not None
                and end_col_offset is not None
            ):
                start_idx = _line_col_to_index(lines, lineno, col_offset)
                end_idx = _line_col_to_index(lines, end_lineno, end_col_offset)
                matches.append((start_idx, end_idx, node, bindings))

    if not matches:
        return source_code, 0, None

    # Sort matches in reverse order so slicing does not offset previous ranges
    matches.sort(key=lambda item: item[0], reverse=True)
    transformed = source_code

    for start_idx, end_idx, _, bindings in matches:
        replacement_node = _build_replacement_node(r_target, bindings)
        replacement_snippet = ast.unparse(replacement_node)
        transformed = transformed[:start_idx] + replacement_snippet + transformed[end_idx:]

    # Pre-commit safety check: compile transformed source
    try:
        compile(transformed, "<transformed>", "exec")
    except SyntaxError as e:
        return source_code, 0, f"Safety check failed: rewrite generated invalid syntax: {e}"

    return transformed, len(matches), None


# =============================================================================
# File & Directory Operations
# =============================================================================


def refactor_file(
    file_path: Path, pattern_str: str, rewrite_str: str, dry_run: bool = False
) -> RefactorResult:
    """Refactors a single file on disk, returning diff and statistics."""
    try:
        original = file_path.read_text(encoding="utf-8")
    except OSError as e:
        return RefactorResult(
            file=str(file_path),
            matches_count=0,
            diff="",
            additions=0,
            deletions=0,
            success=False,
            error=str(e),
        )

    transformed, count, err = refactor_source(original, pattern_str, rewrite_str)
    if err:
        return RefactorResult(
            file=str(file_path),
            matches_count=0,
            diff="",
            additions=0,
            deletions=0,
            success=False,
            error=err,
        )

    if count == 0:
        return RefactorResult(
            file=str(file_path),
            matches_count=0,
            diff="",
            additions=0,
            deletions=0,
            success=True,
        )

    # Compute diff
    orig_lines = original.splitlines(keepends=True)
    trans_lines = transformed.splitlines(keepends=True)
    diff_lines = list(
        difflib.unified_diff(
            orig_lines,
            trans_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
        )
    )
    diff_text = "".join(diff_lines)

    additions = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))

    if not dry_run:
        file_path.write_text(transformed, encoding="utf-8")

    return RefactorResult(
        file=str(file_path),
        matches_count=count,
        diff=diff_text,
        additions=additions,
        deletions=deletions,
        success=True,
    )


def refactor_paths(
    target_path: Path,
    pattern_str: str,
    rewrite_str: str,
    dry_run: bool = False,
    file_pattern: str = "*.py",
) -> list[RefactorResult]:
    """Applies structural refactoring across a file or directory tree."""
    results: list[RefactorResult] = []

    if target_path.is_file():
        results.append(refactor_file(target_path, pattern_str, rewrite_str, dry_run=dry_run))
        return results

    if target_path.is_dir():
        for path in sorted(target_path.rglob(file_pattern)):
            if path.is_file() and not any(part.startswith(".") for part in path.parts):
                res = refactor_file(path, pattern_str, rewrite_str, dry_run=dry_run)
                if res.matches_count > 0 or not res.success:
                    results.append(res)

    return results


# =============================================================================
# CLI Interface
# =============================================================================


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Structural code search and rewrite using AST patterns."
    )
    parser.add_argument(
        "--pattern",
        "-p",
        required=True,
        help="Structural pattern to search for (e.g. '$LOGGER.warn($$$ARGS)')",
    )
    parser.add_argument(
        "--rewrite",
        "-r",
        required=True,
        help="Structural pattern to rewrite with (e.g. '$LOGGER.warning($$$ARGS)')",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=Path.cwd(),
        help="Target file or directory path (default: current directory)",
    )
    parser.add_argument(
        "--lang",
        default="python",
        choices=["python"],
        help="Target programming language (default: python)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes as unified diff without modifying files on disk",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON summary",
    )

    args = parser.parse_args(argv)

    results = refactor_paths(
        args.path,
        args.pattern,
        args.rewrite,
        dry_run=args.dry_run,
    )

    total_matches = sum(r.matches_count for r in results)
    modified_files = [r for r in results if r.matches_count > 0]
    total_additions = sum(r.additions for r in results)
    total_deletions = sum(r.deletions for r in results)

    if args.json:
        payload = {
            "status": "success" if all(r.success for r in results) else "error",
            "dry_run": args.dry_run,
            "total_matches": total_matches,
            "files_modified_count": len(modified_files),
            "additions": total_additions,
            "deletions": total_deletions,
            "files": [asdict(r) for r in results if r.matches_count > 0 or not r.success],
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 0 if all(r.success for r in results) else 1

    # Text / Diff output
    if not modified_files:
        print(f"No matches found for pattern: {args.pattern}")
        return 0

    for r in modified_files:
        if r.diff:
            sys.stdout.write(r.diff)

    mode_label = "DRY-RUN: Would modify" if args.dry_run else "Modified"
    print(
        f"\n{mode_label} {len(modified_files)} file(s), "
        f"{total_matches} replacement(s) "
        f"(+{total_additions}, -{total_deletions})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
