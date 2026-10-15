#!/usr/bin/env python3
"""
Resilient Search/Replace Patch Applicator (tools/patch_applier.py)

A zero-dependency CLI tool and Python library for parsing and applying
targeted SEARCH/REPLACE blocks with a multi-tier resilient fallback cascade:
  - Tier 1: Exact substring match
  - Tier 2: Whitespace and CRLF line-ending normalization
  - Tier 3: Relative indentation matching and re-indentation
  - Tier 4: SequenceMatcher fuzzy block matching with ambiguity rejection

Supports standard search/replace blocks:
  <<<<<<< SEARCH
  original code
  =======
  updated code
  >>>>>>> REPLACE
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional, Tuple


SEARCH_START = "<<<<<<< SEARCH"
DIVIDER = "======="
REPLACE_END = ">>>>>>> REPLACE"


@dataclass
class PatchBlock:
    search: str
    replace: str
    file_path: Optional[str] = None
    line_hint: Optional[int] = None


@dataclass
class ApplyResult:
    file_path: str
    success: bool
    tier: Optional[int] = None
    similarity: float = 1.0
    matched_range: Optional[Tuple[int, int]] = None  # (start_line, end_line) 1-based
    diff: str = ""
    error: Optional[str] = None


def parse_patch_blocks(content: str) -> List[PatchBlock]:
    """
    Parses one or more SEARCH/REPLACE blocks from a string.
    Optionally extracts file path hints from lines directly preceding the block.
    """
    lines = content.splitlines(keepends=True)
    blocks: List[PatchBlock] = []
    
    i = 0
    pending_file: Optional[str] = None
    
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        
        # Check for possible file header comment or directive
        # e.g.: "### path/to/file.py", "# File: path/to/file.py", "path/to/file.py"
        file_match = re.match(r"^(?:#+|//+|\*+)?\s*(?:File:\s*|Filename:\s*)?([a-zA-Z0-9_\-./\\]+\.[a-zA-Z0-9]+)\s*$", stripped)
        if file_match and not stripped.startswith("<<<<<<<"):
            candidate = file_match.group(1).strip()
            # Only treat as file path if it contains a dot and not standard punctuation
            if candidate and not candidate.startswith("```"):
                pending_file = candidate

        if stripped == SEARCH_START or stripped.startswith(SEARCH_START):
            # Parse SEARCH block
            search_lines: List[str] = []
            i += 1
            found_divider = False
            while i < len(lines):
                cur_line = lines[i]
                if cur_line.strip() == DIVIDER or cur_line.strip().startswith(DIVIDER):
                    found_divider = True
                    i += 1
                    break
                search_lines.append(cur_line)
                i += 1
            
            if not found_divider:
                raise ValueError("Malformed patch block: found '<<<<<<< SEARCH' without matching '=======' divider.")
            
            # Parse REPLACE block
            replace_lines: List[str] = []
            found_end = False
            while i < len(lines):
                cur_line = lines[i]
                if cur_line.strip() == REPLACE_END or cur_line.strip().startswith(REPLACE_END):
                    found_end = True
                    i += 1
                    break
                replace_lines.append(cur_line)
                i += 1
            
            if not found_end:
                raise ValueError("Malformed patch block: found '=======' without matching '>>>>>>> REPLACE' terminator.")
            
            search_text = "".join(search_lines)
            replace_text = "".join(replace_lines)
            blocks.append(PatchBlock(search=search_text, replace=replace_text, file_path=pending_file))
            pending_file = None
            continue
        
        i += 1

    return blocks


def _compute_indent(line: str) -> str:
    match = re.match(r"^([ \t]*)", line)
    return match.group(1) if match else ""


def _strip_common_indent(lines: List[str]) -> Tuple[str, List[str]]:
    non_empty = [l for l in lines if l.strip()]
    if not non_empty:
        return "", lines
    common = os.path.commonprefix([_compute_indent(l) for l in non_empty])
    stripped = []
    for l in lines:
        if l.startswith(common):
            stripped.append(l[len(common):])
        else:
            stripped.append(l.lstrip())
    return common, stripped


def apply_patch_string(
    target_content: str,
    search_text: str,
    replace_text: str,
    threshold: float = 0.85,
) -> Tuple[bool, str, Optional[int], float, Optional[Tuple[int, int]], Optional[str]]:
    """
    Applies a single search/replace block to target_content using multi-tier fallback.

    Returns:
        (success, new_content, tier, similarity, (start_line, end_line), error_message)
    """
    if not search_text:
        return False, target_content, None, 0.0, None, "Empty search block."

    # Detect newline style of target
    newline = "\r\n" if "\r\n" in target_content else "\n"

    # =========================================================================
    # Tier 1: Exact Match
    # =========================================================================
    occurrences = target_content.count(search_text)
    if occurrences == 1:
        idx = target_content.find(search_text)
        new_content = target_content[:idx] + replace_text + target_content[idx + len(search_text):]
        start_line = target_content[:idx].count("\n") + 1
        s_lines_count = max(1, len(search_text.splitlines()))
        end_line = start_line + s_lines_count - 1
        return True, new_content, 1, 1.0, (start_line, end_line), None
    elif occurrences > 1:
        return False, target_content, 1, 1.0, None, f"Ambiguous exact match: found {occurrences} occurrences of search block."

    # =========================================================================
    # Tier 2: Whitespace & Line Ending Normalization
    # =========================================================================
    # Normalize CRLF to LF and trim trailing whitespace line-by-line
    target_lines = target_content.splitlines(keepends=True)
    search_lines = search_text.splitlines(keepends=True)
    replace_lines = replace_text.splitlines(keepends=True)

    norm_target = [l.rstrip("\r\n").rstrip() for l in target_lines]
    norm_search = [l.rstrip("\r\n").rstrip() for l in search_lines]

    # Find matches in normalized lines
    matches_tier2: List[int] = []
    s_len = len(norm_search)
    if s_len <= len(norm_target):
        for i in range(len(norm_target) - s_len + 1):
            if norm_target[i:i + s_len] == norm_search:
                matches_tier2.append(i)

    if len(matches_tier2) == 1:
        start_idx = matches_tier2[0]
        end_idx = start_idx + s_len
        # Ensure replacement lines have consistent newline
        formatted_replace = [l.rstrip("\r\n") + newline for l in replace_lines]
        new_lines = target_lines[:start_idx] + formatted_replace + target_lines[end_idx:]
        return True, "".join(new_lines), 2, 1.0, (start_idx + 1, end_idx), None
    elif len(matches_tier2) > 1:
        return False, target_content, 2, 1.0, None, f"Ambiguous normalized match: found {len(matches_tier2)} occurrences."

    # =========================================================================
    # Tier 3: Relative Indentation Matching
    # =========================================================================
    # Check if lines match content-wise with a uniform indentation delta
    search_common_indent, stripped_search = _strip_common_indent(search_lines)
    stripped_search_r = [l.rstrip("\r\n").rstrip() for l in stripped_search]

    matches_tier3: List[Tuple[int, str]] = []  # (start_idx, target_common_indent)
    for i in range(len(target_lines) - s_len + 1):
        window = target_lines[i:i + s_len]
        window_common_indent, stripped_window = _strip_common_indent(window)
        stripped_window_r = [l.rstrip("\r\n").rstrip() for l in stripped_window]
        
        if stripped_window_r == stripped_search_r:
            matches_tier3.append((i, window_common_indent))

    if len(matches_tier3) == 1:
        start_idx, target_indent = matches_tier3[0]
        end_idx = start_idx + s_len
        
        # Apply target indent to replace block
        replace_common_indent, stripped_replace = _strip_common_indent(replace_lines)
        reindented_replace = []
        for l in stripped_replace:
            if l.strip():
                reindented_replace.append(target_indent + l.rstrip("\r\n") + newline)
            else:
                reindented_replace.append(newline)
                
        new_lines = target_lines[:start_idx] + reindented_replace + target_lines[end_idx:]
        return True, "".join(new_lines), 3, 1.0, (start_idx + 1, end_idx), None
    elif len(matches_tier3) > 1:
        return False, target_content, 3, 1.0, None, f"Ambiguous relative-indentation match: found {len(matches_tier3)} occurrences."

    # =========================================================================
    # Tier 4: Fuzzy Sequence Matching (SequenceMatcher)
    # =========================================================================
    best_ratio = 0.0
    candidates: List[Tuple[float, int, int]] = []  # (ratio, start_idx, end_idx)
    
    # We compare sliding windows of length roughly s_len (allowing +- 2 lines)
    min_w = max(1, s_len - 2)
    max_w = min(len(target_lines), s_len + 2)
    search_block_joined = "".join(search_lines)
    
    for w in range(min_w, max_w + 1):
        for i in range(len(target_lines) - w + 1):
            window_chunk = "".join(target_lines[i:i + w])
            # Quick check: first non-empty lines should share some similarity
            ratio = difflib.SequenceMatcher(None, window_chunk, search_block_joined).ratio()
            if ratio >= threshold:
                candidates.append((ratio, i, i + w))
            if ratio > best_ratio:
                best_ratio = ratio

    if not candidates:
        return (
            False,
            target_content,
            4,
            best_ratio,
            None,
            f"No matching block found. Highest similarity was {best_ratio:.2f} (required >= {threshold:.2f}).",
        )

    # Sort candidates by ratio descending
    candidates.sort(key=lambda c: c[0], reverse=True)
    top_ratio, top_start, top_end = candidates[0]

    # Check for ambiguity among high-scoring candidates
    tied_candidates = [c for c in candidates if c[0] >= top_ratio - 0.03 and c[1] != top_start]
    if tied_candidates:
        return (
            False,
            target_content,
            4,
            top_ratio,
            None,
            f"Ambiguous fuzzy match: multiple candidate blocks found with similar high confidence ({top_ratio:.2f}).",
        )

    # Apply replacement on top candidate
    formatted_replace = [l.rstrip("\r\n") + newline for l in replace_lines]
    new_lines = target_lines[:top_start] + formatted_replace + target_lines[top_end:]
    return True, "".join(new_lines), 4, top_ratio, (top_start + 1, top_end), None


def generate_unified_diff(original: str, modified: str, file_path: str) -> str:
    """Generates a standard unified diff string."""
    orig_lines = original.splitlines(keepends=True)
    mod_lines = modified.splitlines(keepends=True)
    diff = difflib.unified_diff(
        orig_lines,
        mod_lines,
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
    )
    return "".join(diff)


def apply_patch_file(
    file_path: Path,
    patch_blocks: List[PatchBlock],
    dry_run: bool = False,
    backup: bool = False,
    threshold: float = 0.85,
) -> List[ApplyResult]:
    """Applies patch blocks to a file on disk."""
    results: List[ApplyResult] = []
    
    if not file_path.exists():
        return [ApplyResult(file_path=str(file_path), success=False, error=f"File not found: {file_path}")]

    try:
        current_content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        return [ApplyResult(file_path=str(file_path), success=False, error=f"Failed to read file: {e}")]

    working_content = current_content
    any_changed = False

    for block in patch_blocks:
        success, new_content, tier, similarity, matched_range, err = apply_patch_string(
            working_content,
            block.search,
            block.replace,
            threshold=threshold,
        )
        
        diff = generate_unified_diff(working_content, new_content, str(file_path)) if success else ""
        res = ApplyResult(
            file_path=str(file_path),
            success=success,
            tier=tier,
            similarity=similarity,
            matched_range=matched_range,
            diff=diff,
            error=err,
        )
        results.append(res)
        
        if not success:
            # Stop applying further blocks to this file if one block fails
            return results

        working_content = new_content
        any_changed = True

    if any_changed and not dry_run:
        try:
            if backup:
                backup_path = file_path.with_suffix(file_path.suffix + ".orig")
                backup_path.write_text(current_content, encoding="utf-8")

            # Atomic file write
            dir_name = file_path.parent
            with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tf:
                tf.write(working_content)
                temp_name = tf.name

            # Copy permissions
            orig_stat = os.stat(file_path)
            os.chmod(temp_name, orig_stat.st_mode)
            os.replace(temp_name, file_path)
        except Exception as e:
            results.append(ApplyResult(file_path=str(file_path), success=False, error=f"Failed to write file atomically: {e}"))

    return results


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resilient search/replace patch applicator with fuzzy matching heuristics."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: apply
    p_apply = subparsers.add_parser("apply", help="Apply a patch block to a specific file.")
    p_apply.add_argument("--file", "-f", required=True, type=Path, help="Target file path.")
    p_apply.add_argument("--patch", "-p", required=True, help="Patch text or path to patch file.")
    p_apply.add_argument("--dry-run", action="store_true", help="Preview changes without modifying disk.")
    p_apply.add_argument("--backup", action="store_true", help="Create .orig backup before modifying.")
    p_apply.add_argument("--threshold", type=float, default=0.85, help="Fuzzy matching threshold (default: 0.85).")
    p_apply.add_argument("--json", action="store_true", help="Output results in JSON format.")

    # Subcommand: stream
    p_stream = subparsers.add_parser("stream", help="Apply patch blocks from stdin stream.")
    p_stream.add_argument("--dry-run", action="store_true", help="Preview changes without modifying disk.")
    p_stream.add_argument("--backup", action="store_true", help="Create .orig backup before modifying.")
    p_stream.add_argument("--threshold", type=float, default=0.85, help="Fuzzy matching threshold (default: 0.85).")
    p_stream.add_argument("--json", action="store_true", help="Output results in JSON format.")

    args = parser.parse_args(argv)

    if args.command == "apply":
        # Resolve patch text
        patch_path = Path(args.patch)
        if patch_path.is_file():
            patch_content = patch_path.read_text(encoding="utf-8")
        else:
            patch_content = args.patch

        blocks = parse_patch_blocks(patch_content)
        if not blocks:
            # If no <<<<<<< SEARCH markers found, treat entire patch as search if divider is missing
            print("Error: No valid SEARCH/REPLACE blocks found in patch input.", file=sys.stderr)
            return 1

        results = apply_patch_file(
            file_path=args.file,
            patch_blocks=blocks,
            dry_run=args.dry_run,
            backup=args.backup,
            threshold=args.threshold,
        )

        all_ok = all(r.success for r in results)

        if args.json:
            print(json.dumps([asdict(r) for r in results], indent=2))
        else:
            for r in results:
                if r.success:
                    tier_desc = {1: "Exact", 2: "Normalized", 3: "Relative-Indent", 4: f"Fuzzy ({r.similarity:.2f})"}.get(r.tier, "Unknown")
                    print(f"✓ [{tier_desc}] Applied patch to {r.file_path} (lines {r.matched_range[0]}-{r.matched_range[1]})")
                    if args.dry_run and r.diff:
                        print(r.diff)
                else:
                    print(f"✗ Failed to apply patch to {r.file_path}: {r.error}", file=sys.stderr)

        return 0 if all_ok else 1

    elif args.command == "stream":
        patch_content = sys.stdin.read()
        blocks = parse_patch_blocks(patch_content)
        if not blocks:
            print("Error: No valid SEARCH/REPLACE blocks found in stdin stream.", file=sys.stderr)
            return 1

        # Group blocks by file path
        grouped: dict[str, List[PatchBlock]] = {}
        for b in blocks:
            if not b.file_path:
                print("Error: In stream mode, each SEARCH/REPLACE block must be preceded by a file path header.", file=sys.stderr)
                return 1
            grouped.setdefault(b.file_path, []).append(b)

        all_results: List[ApplyResult] = []
        for file_str, file_blocks in grouped.items():
            res = apply_patch_file(
                file_path=Path(file_str),
                patch_blocks=file_blocks,
                dry_run=args.dry_run,
                backup=args.backup,
                threshold=args.threshold,
            )
            all_results.extend(res)

        all_ok = all(r.success for r in all_results)

        if args.json:
            print(json.dumps([asdict(r) for r in all_results], indent=2))
        else:
            for r in all_results:
                if r.success:
                    tier_desc = {1: "Exact", 2: "Normalized", 3: "Relative-Indent", 4: f"Fuzzy ({r.similarity:.2f})"}.get(r.tier, "Unknown")
                    print(f"✓ [{tier_desc}] Applied patch to {r.file_path}")
                    if args.dry_run and r.diff:
                        print(r.diff)
                else:
                    print(f"✗ Failed to apply patch to {r.file_path}: {r.error}", file=sys.stderr)

        return 0 if all_ok else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
