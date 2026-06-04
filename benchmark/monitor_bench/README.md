# monitor_bench

Internal regression benchmark for Monitor. Each task launches Monitor
as a subprocess with a fixed prompt, then grades the resulting workspace
state, `:dump_metrics` JSON, and `:dump_history` JSON. Designed for "did
my change make Monitor better or worse?" — not for publishing
comparison scores.

## How it works

Each task lives at `tasks/<task_name>/task.py` and exports:

| symbol | meaning |
|---|---|
| `NAME` | display name |
| `TAGS` | list of strings for filtering and per-tag rollup (e.g. `["memory", "todo"]`) |
| `PROMPT` | the line fed to `monitor --script` |
| `setup(workspace)` | optional — seed fixture files in the per-task tempdir before Monitor launches |
| `grade(workspace, metrics, stdout, stderr, exit_code, history=None)` | return `(passed: bool, detail: str)` |

The runner generates a three-line script per (task, sample):

```
<PROMPT>
:dump_metrics <abs path inside workspace tempdir>
:dump_history <abs path inside workspace tempdir>
```

`--script` is synchronous line-by-line, so the dump lines fire only
after the prompt's entire tool-call chain finishes — that's the
contract the bench relies on. History is dumped LAST so it reflects the
final state of the session.

## Grader signature and `history` parameter

The grader has two backward-compatible forms:

```python
# Legacy / no transcript inspection:
def grade(workspace, metrics, stdout, stderr, exit_code):
    ...

# With transcript inspection (recommended for any task that grades
# on what the model said or which tools it called):
def grade(workspace, metrics, stdout, stderr, exit_code, history=None):
    # history is a list of message dicts:
    #   [{"role": "system", "content": "..."},
    #    {"role": "user", "content": "..."},
    #    {"role": "assistant", "content": "...", "tool_calls": [...]},
    #    {"role": "tool", "tool_call_id": "...", "content": "..."},
    #    ...]
    # None if :dump_history didn't fire (subprocess crashed before
    # reaching that script line).
    ...

# Alternate parameter name (also accepted):
def grade(workspace, metrics, stdout, stderr, exit_code, conversation_history=None):
    ...
```

The runner uses `inspect.signature` to detect which form your grader
uses and only passes `history` when you opt in.

## Running

```bash
# All tasks, 3 samples each, Monitor's default model:
python -m benchmark.monitor_bench.runner

# A specific task or tag substring:
python -m benchmark.monitor_bench.runner --tasks smoke
python -m benchmark.monitor_bench.runner --tasks memory todo

# Override sample count and timeout:
python -m benchmark.monitor_bench.runner --samples 5 --timeout 300

# Pin a model:
python -m benchmark.monitor_bench.runner --model gpt-5.4-mini
```

Results land in `results/run-<unix_timestamp>.json` and contain the full
per-sample transcript as well as metrics — see [Result file shape](#result-file-shape) below.
Pass the file to the report renderer for a markdown summary table:

```bash
python -m benchmark.monitor_bench.report results/run-1780540158.json
```

## What the numbers mean

The runner reports four signals per task / per tag / overall:

| signal | source | what it tells you |
|---|---|---|
| **Pass rate** | `grade()` return value | did the task succeed |
| **Avg cost** | `session_cost_usd` from `:dump_metrics` | dollars per attempt |
| **Avg tool calls** | `session_tool_call_count` | tool-loop efficiency — more is worse for the same task |
| **Avg loop trips** | `session_loop_detector_trips` | how often the model spun on the same call. >0 is always worth investigating |

Two important caveats:

1. **N=3 samples per task** is for catching obvious regressions, not for
   statistical significance. Single-task swings of 1/3 are noise.
2. **Samples with `metrics=None`** (subprocess crashed before
   `:dump_metrics` fired) count as failures in pass rate but are
   excluded from cost / tool-call averages — otherwise crashed runs
   would look "cheap" and mask real regressions.

## Result file shape

Each run JSON is self-contained — you can hand it to an LLM for
post-hoc analysis without needing any other files. Per-sample structure:

```json
{
  "task": "memory_recall",
  "tags": ["memory"],
  "sample": 1,
  "passed": false,
  "detail": "expected response to mention 'Redis' but didn't",
  "exit_code": 0,
  "timed_out": false,
  "duration_seconds": 27.4,
  "metrics": {
    "schema_version": 1,
    "session_cost_usd": 0.0234,
    "session_total_tokens": 4521,
    "session_tool_call_count": 6,
    "session_loop_detector_trips": 0,
    "session_compaction_count": 0,
    ...
  },
  "conversation_history": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "Recall what we said about Redis."},
    {"role": "assistant", "content": null, "tool_calls": [...]},
    {"role": "tool", "tool_call_id": "...", "content": "..."},
    {"role": "assistant", "content": "Final answer..."}
  ],
  "stderr_tail": "...",
  "error": null
}
```

## Using results for LLM-driven analysis

For "did pass-rate change?", the markdown summary from `report.py` is
enough — no LLM needed. For harder questions, hand the full
`results/run-*.json` to a model. Useful prompt shapes:

- **Diff two runs**: "Compare `before.json` and `after.json`. Which
  tasks regressed? Which got cheaper? Are any failures consistent
  across samples (real regression) vs flaky (1/3)?"
- **Root-cause a flaky task**: "Task X passed sample 0 and 2 but failed
  sample 1. Look at the three conversation_history transcripts and tell
  me what was different about the failing one."
- **Tool-efficiency audit**: "Show me tasks where `session_tool_call_count`
  is unusually high or `session_loop_detector_trips > 0`. For each, scan
  the transcript for patterns of redundant tool calls."

You can run Monitor itself as the analyst (it has Read access and can
ingest the JSON directly), or use a separate LLM. Either works.

## Adding a task

```bash
mkdir benchmark/monitor_bench/tasks/my_new_task
```

```python
# benchmark/monitor_bench/tasks/my_new_task/task.py
NAME = "my_new_task"
TAGS = ["memory", "tricky"]
PROMPT = "Recall what we said about Redis in the previous session."

def setup(workspace):
    # Optional: seed fixture files / state in the workspace.
    # Skipped if not defined.
    pass

def grade(workspace, metrics, stdout, stderr, exit_code, history=None):
    if exit_code != 0:
        return False, f"non-zero exit: {exit_code}"
    if metrics is None:
        return False, "no metrics"

    # Inspect the final assistant message for the keyword we expected.
    if history is None:
        return False, "no history (subprocess crashed before :dump_history)"
    final = next(
        (m for m in reversed(history) if m.get("role") == "assistant" and m.get("content")),
        None,
    )
    if not final or "redis" not in final["content"].lower():
        return False, "expected final answer to mention Redis"
    return True, "mentioned Redis"
```

## Debugging a failing task

By default the per-sample tempdir is cleaned up after grading. To keep
it around for inspection:

```bash
MONITOR_BENCH_KEEP_WORKSPACE=1 python -m benchmark.monitor_bench.runner --tasks <name>
```

The runner prints the tempdir path; cd into it to inspect the generated
script (`_bench_script.txt`), the metrics JSON (`_bench_metrics.json`),
the history JSON (`_bench_history.json`), and any files the prompt or
setup() created.

## Smoke test

`tasks/smoke_dump_metrics/` exists to verify the bench pipeline itself.
Its prompt is `:macros` — a built-in command, no LLM call — so the task
costs $0 to run and exercises only subprocess launch, `--script`
dispatch, `:dump_metrics`, `:dump_history`, and the runner's JSON
ingestion. If this fails, the rest of the bench is broken; if it
passes, the failure of another task is genuinely about that task or
about Monitor.

```bash
python -m benchmark.monitor_bench.runner --tasks smoke
```

The smoke task's expected `conversation_history` is empty (`[]`) — pure
built-in prompts never invoke the LLM, so `CONVERSATION_HISTORY` stays
untouched. The grader checks only the plumbing (file fired, list shape),
not the content.
