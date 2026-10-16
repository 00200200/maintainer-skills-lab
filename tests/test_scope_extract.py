"""Unit tests for tools/scope_extract.py."""

from __future__ import annotations

import io
import json
import textwrap
from contextlib import redirect_stdout
from pathlib import Path

from tools.scope_extract import (
    ASTOutlineExtractor,
    EnclosingScopeExtractor,
    approximate_tokens,
    main,
    parse_line_ranges,
    parse_unified_diff,
)

SAMPLE_CODE = textwrap.dedent(
    '''
    """Module docstring for sample."""

    import os
    from typing import Any

    GLOBAL_TIMEOUT: int = 30

    @decorator_one
    @decorator_two(option=True)
    def calculate_metrics(data: list[float], scale: float = 1.0) -> dict[str, float]:
        """Compute summary statistics for data."""
        mean = sum(data) / len(data) if data else 0.0
        return {"mean": mean * scale}

    async def fetch_async_data(url: str, retry: int = 3) -> str:
        """Fetch remote payload asynchronously."""
        return f"result from {url}"

    @dataclass
    class PipelineRunner(BaseRunner, Protocol):
        """Runner class for executing pipeline stages."""
        max_workers: int = 4
        verbose: bool = False

        def __init__(self, name: str) -> None:
            self.name = name

        @property
        def is_active(self) -> bool:
            """Check if runner is currently active."""
            return True

        async def run_step(self, step_id: int) -> bool:
            """Execute a single pipeline step."""
            step_calc = step_id * 2
            return step_calc > 0

        def shutdown(self) -> None:
            """Terminate all active workers."""
            pass
    '''
).strip()


def test_approximate_tokens():
    assert approximate_tokens("") == 0
    assert approximate_tokens("abc") == 1
    assert approximate_tokens("a" * 400) == 100


def test_parse_line_ranges():
    assert parse_line_ranges("10-25") == [(10, 25)]
    assert parse_line_ranges("5,12-18,30") == [(5, 5), (12, 18), (30, 30)]
    assert parse_line_ranges("   ") == []


def test_ast_outline_extractor_basic():
    extractor = ASTOutlineExtractor(SAMPLE_CODE, filepath="sample.py")
    assert extractor.error is None
    outline = extractor.render_outline()

    assert "# Outline: sample.py" in outline
    assert (
        "def calculate_metrics(data: list[float], scale: float=1.0) -> dict[str, float]:" in outline
    )
    assert "@decorator_one" in outline
    assert "@decorator_two(option=True)" in outline
    assert "async def fetch_async_data(url: str, retry: int=3) -> str:" in outline
    assert "class PipelineRunner(BaseRunner, Protocol):" in outline
    assert "max_workers: int = 4" in outline
    assert "def shutdown(self) -> None:" in outline
    # Implementation bodies should be omitted
    assert "step_calc = step_id * 2" not in outline
    assert "mean = sum(data) / len(data)" not in outline


def test_ast_outline_token_and_line_compression():
    # Generate a realistic 1,000-line file with 6 classes and 160-line method bodies
    large_code_parts = ['"""Large generated module with complex implementations."""\n']
    for i in range(6):
        large_body = "\n".join(f"        val_{k} = value * {k} + {i}" for k in range(160))
        large_code_parts.append(
            f'''
class ServiceHandler{i}:
    """Handler for service {i} operations."""
    service_id: int = {i}

    def process_{i}(self, value: int, label: str = "default") -> bool:
        """Process item {i} with extensive internal logic."""
{large_body}
        return val_0 > 0

    def validate_{i}(self) -> None:
        """Validate state of handler."""
        pass
'''
        )
    large_code = "\n".join(large_code_parts)
    assert len(large_code.splitlines()) >= 1000

    extractor = ASTOutlineExtractor(large_code, filepath="large_module.py")
    outline = extractor.render_outline()
    outline_lines = outline.splitlines()

    # Acceptance criteria: under 150 lines, under 600 tokens
    assert len(outline_lines) < 150
    assert approximate_tokens(outline) < 600


def test_enclosing_scope_method():
    extractor = EnclosingScopeExtractor(SAMPLE_CODE, filepath="sample.py")
    # Line inside run_step is around lines 38-40
    lines = SAMPLE_CODE.splitlines()
    run_step_line = next(i + 1 for i, line in enumerate(lines) if "step_calc = step_id" in line)

    scoped = extractor.extract_lines(run_step_line, run_step_line)
    assert "PipelineRunner.run_step" in scoped
    assert "class PipelineRunner(BaseRunner, Protocol):" in scoped
    assert "step_calc = step_id * 2" in scoped
    # Sibling method should appear as stub
    assert "def shutdown(self) -> None: ...  # L" in scoped


def test_enclosing_scope_top_level_function():
    extractor = EnclosingScopeExtractor(SAMPLE_CODE, filepath="sample.py")
    lines = SAMPLE_CODE.splitlines()
    calc_line = next(i + 1 for i, line in enumerate(lines) if "mean = sum(data)" in line)

    scoped = extractor.extract_lines(calc_line, calc_line)
    assert "def calculate_metrics" in scoped
    assert "mean = sum(data)" in scoped


def test_extract_symbol():
    extractor = EnclosingScopeExtractor(SAMPLE_CODE, filepath="sample.py")

    # Method symbol
    res_method = extractor.extract_symbol("PipelineRunner.run_step")
    assert "async def run_step(self, step_id: int) -> bool:" in res_method
    assert "step_calc = step_id * 2" in res_method

    # Function symbol
    res_func = extractor.extract_symbol("calculate_metrics")
    assert "def calculate_metrics" in res_func
    assert 'return {"mean": mean * scale}' in res_func

    # Non-existent symbol
    res_missing = extractor.extract_symbol("NonExistentClass.foo")
    assert "# Error: Symbol 'NonExistentClass.foo' not found" in res_missing


def test_parse_unified_diff():
    diff_text = textwrap.dedent(
        """
        --- a/src/service.py
        +++ b/src/service.py
        @@ -20,5 +20,7 @@
         def helper():
        +    new_check()
             return True
        --- a/tests/test_service.py
        +++ b/tests/test_service.py
        @@ -45,3 +45,5 @@
         def test_helper():
        +    assert helper() is True
        """
    )
    diff_files = parse_unified_diff(diff_text)
    assert "src/service.py" in diff_files
    assert diff_files["src/service.py"] == [(20, 26)]
    assert "tests/test_service.py" in diff_files
    assert diff_files["tests/test_service.py"] == [(45, 49)]


def test_syntax_error_handling(tmp_path: Path):
    bad_code = "def broken_syntax(:\n    return 42\n"
    extractor = ASTOutlineExtractor(bad_code, filepath="bad.py")
    assert extractor.error is not None
    assert "SyntaxError in bad.py" in extractor.error
    outline = extractor.render_outline()
    assert "# SyntaxError in bad.py" in outline


def test_cli_outline_and_json(tmp_path: Path):
    sample_file = tmp_path / "test_module.py"
    sample_file.write_text(SAMPLE_CODE, encoding="utf-8")

    # CLI outline mode
    f = io.StringIO()
    with redirect_stdout(f):
        ret = main(["--file", str(sample_file), "--outline"])
    assert ret == 0
    assert "def calculate_metrics" in f.getvalue()

    # CLI json mode
    f_json = io.StringIO()
    with redirect_stdout(f_json):
        ret = main(["--file", str(sample_file), "--outline", "--json"])
    assert ret == 0
    data = json.loads(f_json.getvalue())
    assert data["mode"] == "outline"
    assert len(data["symbols"]) >= 3
    assert data["tokens_est"] > 0

    # CLI lines mode
    f_lines = io.StringIO()
    with redirect_stdout(f_lines):
        ret = main(["--file", str(sample_file), "--lines", "10-15"])
    assert ret == 0
    assert "Scoped Extraction:" in f_lines.getvalue()

    # CLI symbol mode
    f_sym = io.StringIO()
    with redirect_stdout(f_sym):
        ret = main(["--file", str(sample_file), "--symbol", "fetch_async_data"])
    assert ret == 0
    assert "async def fetch_async_data" in f_sym.getvalue()
