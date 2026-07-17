# Monitor Status Line

Monitor renders a live status line in the REPL and the TUI. Both front ends share
the same counters from `compute_prompt_display` in
`src/monitor/core/conversation.py`, filtered by status-line **mode**.

Mode logic lives in `src/monitor/lib/status_line.py`.

## Modes

Control with `:status` or `STATUS_LINE_MODE` in config (default **`coding`**):

```text
:status              # show current mode
:status minimal
:status coding
:status debug
```

| Mode | Fields shown |
|------|----------------|
| `minimal` | `H:` message count + `C:` cliff / context proximity % |
| `coding` | `H: C: U: (~T:$…) F:` — recommended day-to-day default |
| `debug` | Full gauges: `F: C: R: U: L: H: RT:` plus cache-mix second line |

When auto-compaction fires or you stay above the 2× pricing cliff for several
turns, Monitor prints a one-line recovery hint:

```text
Recovery: :break_chain · :compact · :reset_history
```

## Example (debug)

```text
F:39725156 (95.34%) C:260972 (96%) R:180000000 U:1941510 (~T:$0.406 W:$0.2383 P:$0.0373) L:74601 H:16 (10772) RT:5
```

Not every field appears on every turn. Some values are omitted when zero,
unavailable, or filtered out by the active mode.

## Field reference

| Field | Meaning | Notes |
| --- | --- | --- |
| `F:` | Remaining fuel / token budget | Often shown with a percentage. |
| `C:` | Context / cliff proximity | In `minimal`/`coding`, often a cliff %; full capacity in `debug`. |
| `R:` | Remaining rate / request capacity | `debug` only. |
| `U:` | Total usage so far | Includes cost annotation in parentheses. |
| `~T:$` | Total estimated cumulative cost | Tilde marks estimate. |
| `W:$` | Recent window cost | Rolling window of turns. |
| `P:$` | Previous-turn cost | Most recently completed turn. |
| `L:` | Last request token count | `debug` only. |
| `H:` | Retained history count | Non-system messages kept. |
| `H:(N)` | Compaction counter prefix | Compactions fired this session. |
| `(N)` after `H:` | Retained-history token count | Size re-sent on the next request. |
| `RT:` | Previous-turn round trips | `debug` only. |

## How to read it

- In `coding` mode, watch `C:` (pressure) and `U:` / `F:` (spend / fuel).
- Use `debug` when tuning compaction, rate limits, or cache behavior.
- Use `:help session` for `:break_chain`, `:compact`, and `:reset_history`.

## Related code

- `src/monitor/lib/status_line.py`
- `src/monitor/lib/display_output.py`
- `src/monitor/core/conversation.py`
- `src/monitor/config.py` (`STATUS_LINE_MODE`)
- `src/monitor/lib/token_management.py`
- `src/monitor/lib/model_pricing.py`
