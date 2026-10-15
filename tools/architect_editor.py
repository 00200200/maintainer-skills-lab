"""tools/architect_editor.py - Two-model Architect & Editor pipeline engine.

Implements the Aider-inspired Architect & Editor pattern:
- Architect: Premium reasoning model (e.g. Claude 3.7 / o3) outputs a concise
  change specification (< 400 tokens) with invariant guarantees.
- Editor: Fast, cost-efficient model (e.g. Haiku / GPT-4o-mini) executes mechanical
  search-and-replace blocks, saving 70%+ in token costs.

Zero external dependencies (Python 3.11+ standard library only).
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class ChangeInstruction:
    file: str
    intent: str
    search_block: str
    replace_block: str


@dataclass
class ArchitectHandoff:
    task_id: str
    target_files: list[str]
    invariant_summary: str
    changes: list[ChangeInstruction] = field(default_factory=list)


def parse_handoff_json(text: str) -> ArchitectHandoff:
    """Parses an ArchitectHandoff object from a JSON string or file."""
    data = json.loads(text)
    changes = [
        ChangeInstruction(
            file=c["file"],
            intent=c.get("intent", ""),
            search_block=c["search_block"],
            replace_block=c["replace_block"],
        )
        for c in data.get("changes", [])
    ]
    return ArchitectHandoff(
        task_id=data.get("task_id", "unnamed_task"),
        target_files=data.get("target_files", []),
        invariant_summary=data.get("invariant_summary", ""),
        changes=changes,
    )


def serialize_handoff(handoff: ArchitectHandoff) -> str:
    """Serializes an ArchitectHandoff object into formatted JSON."""
    return json.dumps(asdict(handoff), indent=2) + "\n"


def apply_search_replace(
    file_path: Path,
    search_block: str,
    replace_block: str,
    fuzzy_whitespace: bool = True,
) -> tuple[bool, str]:
    """Applies a search-and-replace edit to a file.

    Returns (success: bool, message: str).
    """
    if not file_path.exists():
        return False, f"Target file not found: {file_path}"

    content = file_path.read_text(encoding="utf-8")

    # 1. Exact match
    if search_block in content:
        new_content = content.replace(search_block, replace_block, 1)
        file_path.write_text(new_content, encoding="utf-8")
        return True, "Exact match applied successfully."

    # 2. Fuzzy whitespace tolerance (stripping trailing whitespace per line)
    if fuzzy_whitespace:
        norm_content = "\n".join(line.rstrip() for line in content.splitlines())
        norm_search = "\n".join(line.rstrip() for line in search_block.splitlines())
        norm_replace = "\n".join(line.rstrip() for line in replace_block.splitlines())

        if norm_search in norm_content:
            new_content = norm_content.replace(norm_search, norm_replace, 1)
            file_path.write_text(new_content, encoding="utf-8")
            return True, "Fuzzy match applied with normalized whitespace."

    return False, f"Search block could not be located in {file_path}."


def validate_python_syntax(file_path: Path) -> tuple[bool, str]:
    """Validates that a modified Python file parses without syntax errors."""
    if not file_path.suffix == ".py":
        return True, "Skipping syntax check (not a Python file)."

    content = file_path.read_text(encoding="utf-8")
    try:
        ast.parse(content, filename=str(file_path))
        return True, "Syntax valid."
    except SyntaxError as e:
        return False, f"SyntaxError in {file_path}:{e.lineno}: {e.msg}"


def estimate_token_savings(
    total_file_tokens: int,
    architect_tokens: int = 350,
    editor_tokens: int = 250,
    frontier_rate_per_m: float = 15.0,
    editor_rate_per_m: float = 1.0,
) -> dict[str, float | str]:
    """Calculates cost difference between single-model rewrite vs dual-model handoff."""
    # Single model regenerates the entire file + explanation
    single_model_tokens = total_file_tokens + 500
    single_model_cost = (single_model_tokens / 1_000_000) * frontier_rate_per_m

    # Dual model: Architect generates change spec (350 tokens) on frontier model,
    # Editor generates diff (250 tokens) on cheap model
    dual_cost_architect = (architect_tokens / 1_000_000) * frontier_rate_per_m
    dual_cost_editor = (editor_tokens / 1_000_000) * editor_rate_per_m
    total_dual_cost = dual_cost_architect + dual_cost_editor

    savings_percent = (
        ((single_model_cost - total_dual_cost) / single_model_cost * 100.0)
        if single_model_cost > 0
        else 0.0
    )

    return {
        "single_model_tokens": single_model_tokens,
        "single_model_cost_usd": round(single_model_cost, 5),
        "dual_model_cost_usd": round(total_dual_cost, 5),
        "savings_percent": round(savings_percent, 1),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Two-model Architect & Editor orchestration and patch runner."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Command: apply
    p_apply = subparsers.add_parser("apply", help="Apply ArchitectHandoff JSON to target files")
    p_apply.add_argument(
        "--handoff", "-i", required=True, type=Path, help="Path to handoff JSON file"
    )
    p_apply.add_argument(
        "--dry-run", action="store_true", help="Simulate edits without modifying files on disk"
    )

    # Command: estimate
    p_est = subparsers.add_parser("estimate", help="Estimate token and cost savings")
    p_est.add_argument(
        "--file-tokens", type=int, default=3000, help="Total token size of files being modified"
    )

    args = parser.parse_args(argv)

    if args.command == "apply":
        if not args.handoff.exists():
            sys.stderr.write(f"Handoff file not found: {args.handoff}\n")
            return 1

        try:
            handoff = parse_handoff_json(args.handoff.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError) as e:
            sys.stderr.write(f"Error parsing handoff JSON: {e}\n")
            return 1

        print(f"Applying ArchitectHandoff: {handoff.task_id} ({len(handoff.changes)} change(s))")
        print(f"Invariants: {handoff.invariant_summary}\n")

        all_ok = True
        for change in handoff.changes:
            target = Path(change.file)
            print(f"Target: {target} (Intent: {change.intent})")
            if args.dry_run:
                print("  [DRY-RUN] Would apply search/replace block.")
                continue

            success, msg = apply_search_replace(target, change.search_block, change.replace_block)
            if not success:
                print(f"  [FAIL] {msg}")
                all_ok = False
                continue

            syn_ok, syn_msg = validate_python_syntax(target)
            if not syn_ok:
                print(f"  [SYNTAX ERROR] {syn_msg}")
                all_ok = False
            else:
                print(f"  [OK] {msg} ({syn_msg})")

        return 0 if all_ok else 1

    elif args.command == "estimate":
        res = estimate_token_savings(args.file_tokens)
        print("📊 Dual-Model Cost & Token Optimization:")
        print(
            f"   Single Frontier Model: {res['single_model_tokens']} tokens (${res['single_model_cost_usd']})"
        )
        print(f"   Architect & Editor:    ${res['dual_model_cost_usd']}")
        print(f"   Estimated Savings:     {res['savings_percent']}%\n")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
