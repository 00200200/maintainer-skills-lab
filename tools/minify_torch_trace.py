"""PyTorch & ML traceback minifier.

Filters internal framework dispatcher frames (torch/nn/modules/*, torch/autograd/*)
to isolate user model code and tensor shape errors without burning prompt tokens.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Framework patterns to filter out of tracebacks
FRAMEWORK_PATTERNS = (
    "site-packages/torch/",
    "torch/nn/modules/",
    "torch/nn/functional.py",
    "torch/autograd/",
    "torch/_tensor.py",
    "torch/_ops.py",
    "torch/optim/",
    "torch/utils/data/",
    "site-packages/pytorch_lightning/",
    "site-packages/accelerate/",
    "site-packages/transformers/trainer.py",
)


def is_framework_frame(file_line: str) -> bool:
    """Return True if the frame path matches an internal framework dispatcher."""
    for pattern in FRAMEWORK_PATTERNS:
        if pattern in file_line:
            return True
    return False


def minify_trace(traceback_text: str) -> str:
    """Minify Python/PyTorch traceback to user frames and error messages."""
    lines = traceback_text.splitlines()
    if not lines:
        return ""

    output_lines: list[str] = []
    i = 0
    skipped_count = 0

    while i < len(lines):
        line = lines[i]

        # Check if line begins a frame definition: File "...", line ..., in ...
        if line.strip().startswith('File "') and '", line ' in line:
            # Collect this entire frame (header line + subsequent indented code lines)
            frame_lines = [line]
            j = i + 1
            while j < len(lines) and (
                lines[j].startswith("    ") or lines[j].strip().startswith("^")
            ):
                frame_lines.append(lines[j])
                j += 1

            if is_framework_frame(line):
                skipped_count += 1
            else:
                if skipped_count > 0:
                    output_lines.append(
                        f"  [... skipped {skipped_count} internal PyTorch/dispatcher frames ...]"
                    )
                    skipped_count = 0
                output_lines.extend(frame_lines)

            i = j
            continue

        # Non-frame lines (e.g. "Traceback ...", Exception lines, Notes)
        if skipped_count > 0:
            output_lines.append(
                f"  [... skipped {skipped_count} internal PyTorch/dispatcher frames ...]"
            )
            skipped_count = 0

        output_lines.append(line)
        i += 1

    if skipped_count > 0:
        output_lines.append(
            f"  [... skipped {skipped_count} internal PyTorch/dispatcher frames ...]"
        )

    return "\n".join(output_lines)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        print("Usage: python3 tools/minify_torch_trace.py [TRACEBACK_FILE | -]")
        return 0

    if args and args[0] != "-":
        path = Path(args[0])
        if not path.is_file():
            print(f"Error: file not found: {path}", file=sys.stderr)
            return 1
        content = path.read_text(encoding="utf-8")
    else:
        content = sys.stdin.read()

    print(minify_trace(content))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
