# [Optimization] XML Semantic Tagging for Claude and Gemini Provider Bundles

**Labels**: `enhancement`, `optimization`, `help wanted`

## Context & Motivation
Currently, `tools/kit.py` exports skills into Markdown files across all providers (`.claude/skills/`, `.cursor/skills/`).

However, leading frontier models—specifically **Anthropic Claude 3.5/3.7** and **Google Gemini 2.0**—are explicitly fine-tuned to parse structured XML tags with significantly higher semantic fidelity than unstructured Markdown headings. Research and documentation from Anthropic confirm that wrapping system instructions, skill guidelines, and worked examples in explicit XML tags reduces instruction confusion, prevents prompt injection, and minimizes tokens spent on ambiguous markdown formatting.

## Prior Art & Industry Standards
- **Anthropic Claude System Prompt Architecture**: Uses `<instructions>`, `<context>`, `<rules>`, and `<examples>` tags to delineate prompt components cleanly.
- **Repomix**: Uses `<file path="...">` XML wrappers which reduce parsing ambiguities for frontier LLMs.

## Proposed Solution
Enhance `tools/kit.py` to support an XML-wrapped export format specifically for Claude (`.claude/`) and Antigravity/Gemini targets:
```xml
<skill name="mkl-reproduce-bug">
  <description>Get a verifiable bug reproduction and fix validation.</description>
  <workflow>
    <step name="reproduce">Write a minimal standalone reproduction script.</step>
    <step name="verify">Run without project dependencies where possible.</step>
  </workflow>
  <example type="authored">
    ...
  </example>
</skill>
```

### Architecture
- Keep `skills/*/SKILL.md` as canonical Markdown for human readability and authoring.
- Add an AST/structural Markdown-to-XML converter inside `tools/kit.py` that activates when compiling for Claude or Gemini targets.
- Retain Markdown exports for Cursor and Codex where Markdown is standard.

## Implementation Tasks
- [ ] Add `markdown_to_xml(markdown_text: str) -> str` in `tools/kit.py`.
- [ ] Update `TARGETS["claude"]` exporter to output XML-structured skill definitions.
- [ ] Verify that model adherence to rules improves or remains stable on standard prompts.
- [ ] Add unit tests in `tests/test_kit.py` testing Markdown-to-XML serialization.

## Acceptance Criteria
- Running `python3 tools/kit.py sync` outputs clean, valid XML-structured skill files for `.claude/`.
- Exported files are byte-for-byte deterministic.
- All unit tests pass cleanly.
