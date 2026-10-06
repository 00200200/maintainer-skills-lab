import json
from pathlib import Path

from tools.validate_output import format_correction_prompt, main, validate

ROOT = Path(__file__).resolve().parent.parent


def test_schemas_are_valid_json():
    triage_schema_path = ROOT / "skills/mkl-triage-issue/schema.json"
    review_schema_path = ROOT / "skills/mkl-review-pr/schema.json"

    assert triage_schema_path.is_file()
    assert review_schema_path.is_file()

    triage_schema = json.loads(triage_schema_path.read_text(encoding="utf-8"))
    review_schema = json.loads(review_schema_path.read_text(encoding="utf-8"))

    assert triage_schema.get("title") == "IssueTriageReport"
    assert review_schema.get("title") == "PullRequestReviewReport"


def test_validate_valid_triage_report():
    schema = json.loads((ROOT / "skills/mkl-triage-issue/schema.json").read_text(encoding="utf-8"))
    valid_data = {
        "summary": "Slug function preserves unwanted punctuation in ASCII mode",
        "category": "bug",
        "severity": "medium",
        "affected_version": "v1.2.0",
        "reproduction": {
            "expected": "Punctuation stripped",
            "observed": "Punctuation retained",
            "reproduced": True,
            "steps": ["Call slugify('hello, world!')", "Observe result contains comma"],
        },
        "evidence": [
            {
                "location": "src/utils.py:42",
                "finding": "Regex character class misses punctuation set",
                "is_hypothesis": False,
            }
        ],
        "missing_details": [],
        "potential_duplicates": [],
        "next_action": {
            "action": "accept_bug",
            "description": "Fix regex in slugify function and add regression test",
        },
    }

    errors = validate(valid_data, schema)
    assert errors == []


def test_validate_invalid_triage_report():
    schema = json.loads((ROOT / "skills/mkl-triage-issue/schema.json").read_text(encoding="utf-8"))
    invalid_data = {
        "summary": "Missing required fields and invalid enum",
        "category": "invalid_category",
        "severity": "unknown",
        "reproduction": {
            "expected": "Expected foo",
            "observed": "Observed bar",
            "reproduced": "not-a-bool",  # Type error
        },
        # Missing evidence and next_action
    }

    errors = validate(invalid_data, schema)
    assert any("category" in e and "not in allowed enum" in e for e in errors)
    assert any("reproduction.reproduced" in e and "expected type 'boolean'" in e for e in errors)
    assert any("missing required property 'evidence'" in e for e in errors)
    assert any("missing required property 'next_action'" in e for e in errors)


def test_validate_valid_pr_review_report():
    schema = json.loads((ROOT / "skills/mkl-review-pr/schema.json").read_text(encoding="utf-8"))
    valid_data = {
        "summary": "PR adds bounds check to ring buffer; 1 potential regression identified",
        "verdict": "request_changes",
        "reviewed_scope": {
            "base_ref": "main",
            "head_ref": "feat/ring-buffer",
            "files_inspected": ["src/buffer.py", "tests/test_buffer.py"],
        },
        "findings": [
            {
                "title": "Off-by-one error on buffer wraparound",
                "severity": "defect",
                "file": "src/buffer.py",
                "line": 88,
                "trigger": "Buffer capacity exact boundary write",
                "consequence": "Overwrites head entry before advancing pointer",
                "evidence": "Verified with test case buffer.write(bytes(capacity))",
                "suggested_fix": "Increment tail after modulo index computation",
            }
        ],
        "reproducibility": {
            "checked": True,
            "tool": "repro-lens",
            "findings_count": 0,
            "details": "Determinism verification passed cleanly",
        },
    }

    errors = validate(valid_data, schema)
    assert errors == []


def test_validate_invalid_pr_review_report():
    schema = json.loads((ROOT / "skills/mkl-review-pr/schema.json").read_text(encoding="utf-8"))
    invalid_data = {
        "summary": "Review without verdict",
        "verdict": "not_a_valid_verdict",
        "findings": [
            {
                "title": "Finding with missing required fields",
                "severity": "defect",
                # missing file, line, trigger, consequence
            }
        ],
    }

    errors = validate(invalid_data, schema)
    assert any("verdict" in e and "not in allowed enum" in e for e in errors)
    assert any("missing required property 'file'" in e for e in errors)
    assert any("missing required property 'trigger'" in e for e in errors)


def test_format_correction_prompt():
    errors = [
        "$.reproduction.reproduced: expected type 'boolean', got 'str'",
        "$.category: value 'random' not in allowed enum ['bug', 'feature']",
    ]
    prompt = format_correction_prompt(errors)
    assert "The previous output failed JSON schema validation" in prompt
    assert "$.reproduction.reproduced" in prompt
    assert "Do not repeat conversational preamble" in prompt


def test_cli_validate_output(tmp_path: Path, capsys):
    schema_path = tmp_path / "simple_schema.json"
    schema_path.write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["status"],
                "properties": {"status": {"type": "string"}},
            }
        ),
        encoding="utf-8",
    )

    # Valid string
    exit_code = main(["--schema", str(schema_path), "--string", '{"status": "ok"}'])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "OK:" in captured.out

    # Invalid file with diff-prompt
    bad_file = tmp_path / "bad.json"
    bad_file.write_text('{"status": 123}', encoding="utf-8")
    exit_code = main(["--schema", str(schema_path), "--diff-prompt", str(bad_file)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "The previous output failed JSON schema validation" in captured.out
    assert "expected type 'string', got 'int'" in captured.out
