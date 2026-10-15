---
name: "mkl-adversarial-review"
description: "Conduct a bounded 3-turn adversarial code review debate (Author vs. Skeptic) to uncover subtle edge cases and race conditions under 1,500 tokens."
---

# Multi-agent adversarial code review

Conduct a disciplined, bounded 3-turn adversarial code review debate between an Author agent (defending the patch and underlying invariants) and a Skeptic agent (actively attempting to construct disproving inputs and failure modes). Prevent sycophantic rubber-stamping and endless bike-shedding by enforcing strict token budgets and stopping rules.

## Protocol & Turn Budget

The debate is strictly bounded to 3 turns and under 1,500 total output tokens (<= 300 tokens per turn):

1. **Turn 1: Skeptic Attack (<= 300 tokens)**:
   - Identify up to 2 concrete failure scenarios (such as concurrent race conditions, unhandled `None` states, resource leaks, or silent contract breaks).
   - Every claimed defect MUST include a concrete trigger scenario, input sequence, or counterexample. Vague style complaints are forbidden.

2. **Turn 2: Author Defense & Rebuttal (<= 300 tokens)**:
   - Cite specific invariants, types, or guards that prevent the claimed failure mode.
   - If the counterexample is valid and unhandled, explicitly concede the defect and propose the minimal guard.

3. **Turn 3: Joint Consensus Synthesis (<= 300 tokens)**:
   - Compile an actionable verdict table categorizing findings into Verified Blockers, Disproved Concerns, and Non-blocking Polish.

## Structured Verdict Table

Format the final turn as an actionable summary table:

| Category | Finding | Trigger Scenario | Actionable Fix / Resolution |
|:---|:---|:---|:---|
| **Verified Blocker** | Concurrent dictionary mutation | Multiple threads calling `cache.set()` during `cache.cleanup()` | Copy keys (`list(self._items.keys())`) or acquire reentrant lock before iteration |
| **Disproved Concern** | Null pointer on missing key | Request with omitted `auth` header | Guarded by early return on line 42 (`if not auth: return 401`) |
| **Non-blocking Polish** | Type annotation precision | Return type annotated as `dict` rather than `dict[str, Any]` | Widen parameter or add explicit key/value generic parameters |

## Worked Example: Concurrency Race Condition

### Turn 1 (Skeptic)
> **Defect**: `SessionCache.evict_expired()` mutates `self._entries` while an external worker thread calls `self.get()`.
> **Trigger**:
> ```python
> # Thread A: evicting expired keys
> for key, exp in self._entries.items():  # RuntimeError: dictionary changed size during iteration
>     if exp < now: del self._entries[key]
> # Thread B: concurrently calling cache.get("user_1")
> ```

### Turn 2 (Author)
> **Concession**: The concern is valid. While `get()` is read-only, mutating `self._entries` directly during iteration raises `RuntimeError` if an eviction occurs during concurrent reads.
> **Fix**: Snapshot keys before iteration:
> ```python
> for key in list(self._entries.keys()):
>     if self._entries.get(key, 0) < now:
>         self._entries.pop(key, None)
> ```

### Turn 3 (Consensus)
> **Verdict**: Block merge pending snapshot key iteration in `SessionCache.evict_expired()`.

## Anti-Patterns & Negative Guidance

- **No Polite Rubber-Stamping**: Never approve a complex change with generic "Looks great to me!" without inspecting edge cases, lock contention, and error paths.
- **No Unbounded Banter**: Do not exceed 3 turns or debate subjective naming or cosmetic style preferences. Conclude immediately after the synthesis table.
