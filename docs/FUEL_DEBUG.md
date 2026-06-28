# `:fuel_debug` — calibrating the F: fuel gauge

`:fuel_debug` is a diagnostic command that explains how the session's **F:**
fuel-tank budget is derived and tells you what to put in your `config.yaml` so
that budget reflects your *real* spend instead of a guess.

It exists to calibrate two config knobs:

- **`MODEL_TOKEN_RATE_PER_MTOK`** — the measured `$ / 1,000,000 tokens` for a
  model at your steady reasoning effort. The command suggests this value
  directly.
- **`REASONING_EFFORT_RATE_MULTIPLIER`** — how much each reasoning effort costs
  relative to `medium`. The command doesn't print this one; you *derive* it by
  comparing observed rates across effort levels (see
  [Recipe B](#recipe-b-calibrating-reasoning_effort_rate_multiplier)).

> Run `:fuel_debug help` for an in-terminal field guide. Run `:fuel_debug`
> (no argument) for the live readout described below.

---

## Background: where the F: number comes from

The F: gauge is a per-session token quota that drains as you spend:

```
F: = session_token_budget - SESSION_TOTAL_TOKENS
session_token_budget = DAILY_COST_TARGET_USD / (effective_rate / 1_000_000)
effective_rate       = base_rate × effort_multiplier
```

- `base_rate` comes from `MODEL_TOKEN_RATE_PER_MTOK[model]` if present, else
  the anchor model's rate scaled by published-price ratio, else
  `DEFAULT_TOKEN_RATE_PER_MTOK`.
- `effort_multiplier` comes from `REASONING_EFFORT_RATE_MULTIPLIER[REASONING_EFFORT]`
  (1.0 for non-reasoning models).

If `MODEL_TOKEN_RATE_PER_MTOK` is wrong, F: is wrong. `:fuel_debug` measures the
right value from your actual session.

---

## Calibration data is **per model**

The harness accumulates calibration stats keyed by the model that *actually ran*
each round-trip (`SESSION_CALIBRATION_BY_MODEL`). Consequences:

- `:fuel_debug` reports the **active model** (`config.MODEL`). To calibrate a
  different model, run with it (or `:model <shorthand>`).
- A single-turn `ADV_REASONING_MODEL` swap is attributed to the *advanced*
  model, so it never pollutes the base model's rate.
- The store **persists across `:model` switches** (each model keeps its own
  bucket) and **resets on `:reset_history`** (new session).

---

## Reading the output

A representative readout (`MODEL: openai/gpt-5.4-mini-…`, steady `medium`):

```
=== Fuel debug ===
MODEL:                    openai/gpt-5.4-mini-2026-03-17
REASONING_EFFORT:        medium
REASONING_MODEL_PREFIX:  openai/gpt-5
Reasoning model match:   True
Configured calibration rate: 0.25
Base rate source:        configured_calibration_rate
Anchor model:            'openai/gpt-5.4-2026-03-05'
Anchor rate:             0.5
Heuristic blend weights:  cached=0.70 input=0.15 output=0.15
Theoretical blend:       0.42
Empirical session tokens: cached=1600000 input=300000 output=100000 total=2000000
Empirical confidence:    medium
Empirical blend weights: cached=0.8000 input=0.1500 output=0.0500
Empirical blend / 1M:    0.24
Effort multiplier (now):     1.0
Effort multiplier (session): 1.0000
Upgrade load:            +0.0% over steady effort (over 2000000 effort-weighted tokens)
Effective rate / 1M:     0.25
Session fuel budget:     20000000
SESSION_COST_USD (T:):   $0.500000  (session-wide, all models)
SESSION_TOTAL_TOKENS (U:): 2000000  (session-wide, all models)
Model calibration cost:  $0.500000  (this model only)
Model calibration tokens: 2000000  (this model only)
Observed rate / 1M:      0.250000 (medium confidence)
Normalized observed rate / 1M: 0.250000 (divided by session-average multiplier; assumes the multiplier table is correct)

--- Suggested calibration entry for MODEL_TOKEN_RATE_PER_MTOK ---
Basis: observed U:/T: normalized by session-average multiplier (medium confidence)
Suggested raw rate / 1M: 0.250000
Suggested config value:  0.25
Note: normalized by the session-average multiplier; assumes the reasoning multiplier table is correct.
YAML: openai/gpt-5.4-mini-2026-03-17: 0.25
```

> This sample is a clean steady-`medium` session (no bumps), so the session
> multiplier is `1.0000` and the normalized rate equals the observed rate. A
> session that bumped some turns to `high` would show `Upgrade load: +N%`, a
> session multiplier above `1.0`, and a **normalized rate below the observed
> rate** (the bump cost is divided back out to recover the medium baseline).

### Inputs

| Field | Meaning |
|---|---|
| `MODEL` / `REASONING_EFFORT` | Active model and its **steady** effort (single-turn bumps don't change this). |
| `Reasoning model match` | Whether `REASONING_MODEL_PREFIX` is in the model name. If true, effort multipliers apply. |
| `Configured calibration rate` | Current `MODEL_TOKEN_RATE_PER_MTOK[model]`, or `None`. The value you're tuning. |
| `Base rate source` | How the base rate was chosen: `configured_calibration_rate` → `anchor_ratio` → `default_token_rate`. |
| `Anchor model` / `Anchor rate` | The model whose rate is scaled by price ratio when this model isn't listed. |

### Rate estimates — least → most trustworthy

| Field | What it is |
|---|---|
| `Theoretical blend` | Published prices blended by **fixed assumed weights**. A pure guess; used before you've run enough. |
| `Empirical blend / 1M` | Published prices blended by **your session's actual token mix**. Better — it knows your cache ratio. |
| `Observed rate / 1M` | **Real dollars paid ÷ real tokens used** for this model. Ground truth. Needs this model's cost & tokens > 0. |

### Effort multipliers (reasoning models only)

| Field | What it is |
|---|---|
| `Effort multiplier (now)` | Multiplier for the **steady** effort. The live F: budget is sized with this (forward-looking). |
| `Effort multiplier (session)` | **Token-weighted average** actually incurred, folding in single-turn bumps (backward-looking). |
| `Upgrade load +X%` | How much your single-turn bumps raised cost over steady effort. Diagnostic, not config. |
| `Normalized observed rate / 1M` | Observed rate ÷ the session multiplier — recovers the **steady-effort baseline**, which is what `MODEL_TOKEN_RATE_PER_MTOK` should hold. Shown only for reasoning models when bumps occurred. |

> Both multiplier values come from the **configured** `REASONING_EFFORT_RATE_MULTIPLIER`
> table — they are *inputs*, not measurements. To *measure* the multiplier, see Recipe B.

### Totals & the suggestion

| Field | Meaning |
|---|---|
| `SESSION_COST_USD (T:)` / `SESSION_TOTAL_TOKENS (U:)` | Session-wide, **all models** (shown for context). |
| `Model calibration cost` / `tokens` | **This model only** — these drive the observed rate. |
| `Session fuel budget` | The current F: cap in tokens. |
| `Basis` | Which estimate the suggestion used (precedence below). |
| `Suggested config value` | Rounded rate to paste into `MODEL_TOKEN_RATE_PER_MTOK`. |
| `YAML` | Copy-paste-ready config line. |

**Suggestion precedence** (first that qualifies wins):

1. **Observed** `U:/T:` — once this model has ≥ 1M tokens. For reasoning models
   it's normalized by the session-average multiplier first.
2. **Empirical blend** — once the session mix has ≥ 1M tokens.
3. **Theoretical blend** — the starting guess. *Ignore for real calibration.*

**Rounding:** ≥ $10 → 1 decimal; ≥ $1 → 2 decimals; < $1 → nearest $0.05.

**Confidence** (by this model's accumulated tokens): `< 1M` low · `≥ 1M`
medium · `≥ 3M` high.

### Warning lines (stderr)

- **Fuel budget is `None`** — F: hidden; set `DAILY_COST_TARGET_USD` (+ a usable
  rate) or `SESSION_TOKEN_BUDGET`.
- **No rate estimate from any source** — pricing data missing for this model.
- **Observed vs empirical differ by > 25%** — published prices may be stale or
  your token mix is shifting; treat the suggestion as provisional.

---

## Initial Tuning Procedure

A step-by-step path from defaults to a calibrated F: gauge. **The ordering rule
is: calibrate the rate before the multiplier.** `MODEL_TOKEN_RATE_PER_MTOK` sets
the whole tank size and dominates; `REASONING_EFFORT_RATE_MULTIPLIER` only
modulates how fast F: drains on bumped turns and is a minor refinement.

### Step 0 — Start from the shipped defaults

- Leave `REASONING_EFFORT_RATE_MULTIPLIER` at its defaults (`high: 1.75`, etc.).
  It's a reasonable guess — good enough to begin.
- Set `MODEL`, `DAILY_COST_TARGET_USD`, and your reasoning config as normal.
- Just start working. Until you calibrate, F: uses anchor-scaling / defaults —
  approximate but harmless.

### Step 1 — Calibrate `MODEL_TOKEN_RATE_PER_MTOK` (do this first)

Pick one of two ways:

- **Simplest (use your normal config):** work a full session normally, and
  before quitting run `:fuel_debug`. Confirm `Basis` is `observed` (≥ 1M tokens,
  ideally `high` confidence), then paste the `YAML:` line into
  `MODEL_TOKEN_RATE_PER_MTOK`. This normalizes bump turns out using the
  *configured* multiplier, so it inherits a few percent from the `1.75` guess —
  fine for cost control.
- **Decoupled (optional, zero multiplier dependency):** run **one** session at
  steady `medium` with bumps off —

  ```yaml
  REASONING_BUMP_EFFORT:               # unset
  ESCALATE_REASONING_ON_TOOL_FAILURE: false
  ```

  The session multiplier is then `1.0`, so the observed rate **is** the medium
  baseline (no normalization involved). Paste it, then restore your normal
  config.

See [Recipe A](#recipe-a-calibrating-model_token_rate_per_mtok) for detail.

### Step 2 — Refine over a few days

- Just work; run `:fuel_debug` at the end of each session; nudge the rate if it
  drifted. Once two days agree, it's stable — re-check only occasionally, or when
  your workload pattern changes (caching, ratio of bumped turns).

### Step 3 — Calibrate the multiplier (optional polish)

- **Only if** the F: gauge feels consistently off, or you want precision. Many
  setups never do this — the shipped `1.75` is close enough.
- Run the per-effort sessions in
  [Recipe B](#recipe-b-calibrating-reasoning_effort_rate_multiplier) and update
  `REASONING_EFFORT_RATE_MULTIPLIER`.
- Then **re-run Step 1 once** so the rate suggestion is normalized with the
  corrected multiplier.

### Why this order

`MODEL_TOKEN_RATE_PER_MTOK` is the biggest lever (it sizes the tank). The
multiplier only affects drain on bumped turns, and bumped turns are a minority of
your tokens — so even a moderately-wrong `1.75` perturbs the rate suggestion by
only a few percent. Rate first; multiplier later, if ever.

---

## Recipe A: calibrating `MODEL_TOKEN_RATE_PER_MTOK`

This is the per-model `$ / 1M tokens` at steady effort. `:fuel_debug` suggests
it directly.

1. **Run a normal session** at your steady effort with a **representative
   workload** (the same kind of caching you usually get).
2. **Accumulate ≥ 3M tokens** for that model (aim for `high` confidence). Check
   `Model calibration tokens`.
3. Run `:fuel_debug`. Make sure **`Basis` is `observed` or `empirical`** — if it
   says `theoretical`, you haven't run enough; keep going.
4. Paste the `YAML:` line into `MODEL_TOKEN_RATE_PER_MTOK` in `config.yaml`.
5. Re-run periodically to refine — the more you run, the better it gets.

```yaml
MODEL_TOKEN_RATE_PER_MTOK:
  openai/gpt-5.4-2026-03-05: 0.50
  openai/gpt-5.4-mini-2026-03-17: 0.25   # ← from :fuel_debug
```

**Per model:** repeat for each model you run. Switch with `:model <shorthand>`,
accumulate tokens on it, then `:fuel_debug` reports that model's entry.

> **Key names must match what actually runs.** Use the same fully-qualified
> (dated) model string in `MODEL_TOKEN_RATE_PER_MTOK` that `model_config.json`
> maps to, or the lookup misses and F: silently falls back to anchor-scaling.

---

## Recipe B: calibrating `REASONING_EFFORT_RATE_MULTIPLIER`

The multiplier table is **relative to `medium`** (medium ≡ 1.0). `:fuel_debug`
doesn't print it, but you can measure it: the multiplier for an effort level is
simply the ratio of that level's observed rate to medium's.

```
multiplier[effort] = observed_rate(steady effort) / observed_rate(steady medium)
```

### Procedure

For a clean measurement you want each session to run **entirely at one effort**,
so temporarily disable the bumps that would change effort mid-session:

```yaml
REASONING_BUMP_EFFORT:               # unset
ESCALATE_REASONING_ON_TOOL_FAILURE: false
```

Then, **using the same model and a comparable workload** for each run:

1. **Baseline run** — `REASONING_EFFORT: medium`. Accumulate ≥ 1–3M tokens, run
   `:fuel_debug`, record the **raw `Observed rate / 1M`** line. Call it
   `R_medium`. (By definition `medium = 1.0`.)
2. **High run** — `REASONING_EFFORT: high`, fresh session (`:reset_history`).
   Accumulate tokens, record `R_high`. Then `multiplier[high] = R_high / R_medium`.
3. Repeat for `low`, `minimal`, `xhigh` as needed.
4. Write the ratios into `config.yaml`:

```yaml
REASONING_EFFORT_RATE_MULTIPLIER:
  minimal: 0.5
  low:     0.75
  medium:  1.0     # anchor — always 1.0
  high:    1.75    # = R_high / R_medium
  xhigh:   2.25
```

> **Use the raw `Observed rate / 1M`, not the suggestion or the "normalized"
> line.** The suggested value and the normalized observed rate already divide by
> the *configured* multiplier — using them to calibrate the multiplier would be
> circular. The raw observed rate is `cost ÷ tokens`, independent of the table.

### Why this works

Reasoning effort mainly changes how many **output/reasoning tokens** the model
emits, which are billed at the output rate. A higher effort therefore raises the
realized `$ / token`, and the ratio of realized rates *is* the multiplier.

### A quicker sanity check (not a measurement)

If you just want to see how much your bumps are costing, run normally and read
`Effort multiplier (session)` and `Upgrade load +X%`. Those are computed from the
*configured* table (so they confirm the table's effect, not its correctness), but
a large persistent `Upgrade load` is a useful signal that bumps are a real cost
factor — and that your `high` multiplier had better be accurate.

---

## Gotchas

- **Cache mix dominates `$/token`.** Calibrate from a session that resembles your
  normal one — not an unusual heavy- or zero-cache run. A `> 25%` observed-vs-
  empirical warning usually means the mix shifted.
- **Reset semantics.** `:reset_history` clears the per-model store (use it
  between effort runs in Recipe B). Switching models with `:model` does **not**
  clear it — each model keeps its own data.
- **Reasoning-model gate.** Multipliers and the normalized line only apply when
  `Reasoning model match` is `True` (the model name contains
  `REASONING_MODEL_PREFIX`).
- **F: sizes on steady effort.** The budget uses `Effort multiplier (now)`
  (forward-looking), not the session average. On heavy-bump days, actual spend
  can run slightly ahead of the gauge — expected, not a bug.
- **ADV swaps are attributed separately.** A single-turn swap to
  `ADV_REASONING_MODEL` accrues under that model's entry, so calibrate it by
  reading `:fuel_debug` while that model is active (or run it as the main model).
