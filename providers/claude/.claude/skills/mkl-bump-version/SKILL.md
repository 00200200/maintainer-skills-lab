---
name: "mkl-bump-version"
description: "Evaluate conventional commits since latest tag, determine next SemVer, and surgically update version files."
---

<skill name="mkl-bump-version">
  <description>Evaluate conventional commits since latest tag, determine next SemVer, and surgically update version files.</description>
  <context>
    Evaluate conventional commits since the latest git tag, compute the next SemVer 2.0 version, and update repository version files.
  </context>
  <workflow>
    <step name="preview-bump">
      Run dry-run evaluation to preview the proposed bump:
         ```bash
         python3 tools/bump_version.py --dry-run
         ```
    </step>
    <step name="verify-breaking-changes">
      - For `MAJOR` bumps, verify breaking changes are intentional before executing `--apply`.
         - Override unintended bumps using `--level <major|minor|patch>`.
    </step>
    <step name="apply-version-bump">
      ```bash
         python3 tools/bump_version.py --apply
         ```
    </step>
    <step name="output-constraint">
      Output a concise confirmation message and the git command to create the tag:
         ```bash
         git tag -a <tag> -m "Release <tag>"
         ```
         Keep output strictly under 100 tokens.
    </step>
  </workflow>
</skill>
