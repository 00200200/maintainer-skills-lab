# [Feature] Interactive Terminal Dashboard & Skill Manager (`tools/dashboard.py`)

**Labels**: `enhancement`, `dx`, `good first issue`

## Context & Motivation
Maintainers and developers working with Maintainer Skills Lab currently manage skills using multiple CLI commands (`kit.py check`, `kit.py sync`, `kit.py install`, `skill_watch.py`).

Having an interactive, lightweight terminal user interface (TUI) allows developers to visually inspect installed skills, see token footprints, check prompt cache estimates, and toggle provider exports with a single keystroke.

## Prior Art & Industry Standards
- **Lazygit / k9s / Rich CLI**: Interactive, zero-friction terminal tools that drastically lower the barrier to entry for contributors.
- **Claude Code CLI**: Rich terminal rendering with clear status indicators.

## Proposed Solution
Create `tools/dashboard.py` (using standard library `curses` or optional `rich`):
- Displays a list of all 17 skills and 6 agent profiles.
- Shows estimated token count, supported providers, and status.
- Keybindings:
  - `s` - Run `kit.py sync`
  - `c` - Run `kit.py check`
  - `t` - Profile tokens
  - `q` - Quit

## Implementation Tasks
- [ ] Create `tools/dashboard.py`.
- [ ] Implement skill listing and token visualization.
- [ ] Add shortcuts to trigger existing `kit.py` actions.
- [ ] Add unit test ensuring non-interactive invocation exits cleanly.

## Acceptance Criteria
- Running `python3 tools/dashboard.py` displays a responsive, clean terminal overview of the library.
- Exits cleanly on `q` or `Ctrl+C`.
