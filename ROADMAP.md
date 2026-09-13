# Roadmap

## First preview

- [x] Six skills and three native agent profiles.
- [x] List, validate, build, install, and uninstall commands.
- [x] An executable bug-to-regression-test example.
- [x] Grok Bot Issue Scout and Release Reporter recipes.
- [x] Installation tests and CI configuration.

## Writing catalogue

- [x] Eight distinct writing skills with inline worked examples: Humanizer, voice matching, README, tutorial, launch post, UX copy, PL/EN localization, and maintainer reply.
- [x] A writing editor agent that embeds humanization and voice-matching instructions.
- [x] Copyable Polish invocation prompts and acceptance scenarios for preserving facts, technical tokens, and uncertainty.
- [ ] Run independent live-client writing evaluations, including a natural draft that should remain unchanged and a source containing embedded instructions.
- [ ] Collect real writing samples and user feedback before adding more overlapping editing skills.

## Next increments

1. Test skill discovery and explicit invocation in real Codex, Claude Code, and Cursor sessions; record exact versions and limitations.
2. Add a TypeScript example and check its outputs independently.
3. Exercise Grok Bot setup and template import; only advertise a shared template after a successful round trip.
4. Test issue triage against incomplete reports and embedded instructions.
5. Add a release example with a real breaking change and migration notes.
6. Add cross-client discovery checks when more than one bundle is installed.
7. Collect external feedback and prioritize demonstrated failures.
8. Add per-skill installation with explicit agent dependency handling.
9. Add a Python/pytest variant of the dependency-free regression example.

Every skill should explain its purpose, give a runnable or inspectable example, and state the evidence behind its validation status. Add a new workflow only when it addresses a distinct need.
