# Benchmark Usage

This guide explains how to run the internal `monitor_bench` benchmark suite,
inspect the results, and compare runs before and after a change.

Primary implementation and detailed benchmark reference:
- `benchmark/monitor_bench/README.md`

## What the benchmark does

The benchmark runner launches Monitor as a subprocess for each task/sample pair,
feeds it a generated script, and collects:
- pass/fail grading,
- metrics dumped by `:dump_metrics`,
- conversation history dumped by `:dump_history`.

Results are written as JSON run artifacts under:
- `benchmark/monitor_bench/results/`

Current tasks with a `task.py` (and their tags) include:
- `smoke_dump_metrics` — `smoke`
- `seeded_bugfix_simple` — `edit`, `bugfix`, `seeded`
- `seeded_bugfix_multistep` — `edit`, `bugfix`, `multistep`, `seeded`
- `plan_then_execute_refactor` — `planning`, `edit`, `long_horizon`, `seeded`

## Run the benchmark

Run all benchmark tasks with the default sample count:

```bash
python -m benchmark.monitor_bench.runner
```

Run only selected tasks or tag substrings:

```bash
python -m benchmark.monitor_bench.runner --tasks smoke
python -m benchmark.monitor_bench.runner --tasks seeded_bugfix_multistep
python -m benchmark.monitor_bench.runner --tasks edit
python -m benchmark.monitor_bench.runner --tag planning
```

Override the sample count, timeout, or model:

```bash
python -m benchmark.monitor_bench.runner --samples 5 --timeout 300
python -m benchmark.monitor_bench.runner --model gpt-5.4-mini
```

### Default model behavior

If you do not pass `--model`, the runner uses Monitor's normal active model
selection. The benchmark runner itself does not hardcode a default model.

## View one run's summary

Render a summary report for one run JSON:

```bash
python -m benchmark.monitor_bench.report \
  benchmark/monitor_bench/results/run-<timestamp>.json
```

This is the fastest way to see:
- pass rate,
- average cost,
- average tool calls,
- average loop-detector trips.

## Inspect failures or individual tasks

Show only failed samples:

```bash
python -m benchmark.monitor_bench.inspect \
  benchmark/monitor_bench/results/run-<timestamp>.json \
  --failed-only
```

Inspect one task:

```bash
python -m benchmark.monitor_bench.inspect \
  benchmark/monitor_bench/results/run-<timestamp>.json \
  --task seeded_bugfix_multistep
```

Include serialized conversation history:

```bash
python -m benchmark.monitor_bench.inspect \
  benchmark/monitor_bench/results/run-<timestamp>.json \
  --task seeded_bugfix_multistep \
  --show-history
```

## Compare two runs

Use compare when you want to understand whether a code change improved or
regressed benchmark behavior.

Minimal compare:

```bash
python -m benchmark.monitor_bench.compare before.json after.json
```

Show only regressions:

```bash
python -m benchmark.monitor_bench.compare before.json after.json \
  --only-regressions
```

Focus on one task:

```bash
python -m benchmark.monitor_bench.compare before.json after.json \
  --task seeded_bugfix_multistep
```

Filter the compare input to tasks matching a tag substring:

```bash
python -m benchmark.monitor_bench.compare before.json after.json \
  --tag edit
```

Emit markdown or JSON output:

```bash
python -m benchmark.monitor_bench.compare before.json after.json \
  --format markdown
python -m benchmark.monitor_bench.compare before.json after.json \
  --format json
```

## Recommended workflow

A practical benchmark loop is:

1. Run a baseline benchmark.
2. Save the generated run JSON path.
3. Make your code change.
4. Run the same benchmark slice again.
5. Compare the two runs.
6. Inspect failures or regressions if needed.

Example:

```bash
python -m benchmark.monitor_bench.runner --tasks seeded_bugfix_multistep
python -m benchmark.monitor_bench.runner --tasks seeded_bugfix_multistep
python -m benchmark.monitor_bench.compare \
  benchmark/monitor_bench/results/run-1000.json \
  benchmark/monitor_bench/results/run-2000.json
```

## Smoke test the benchmark pipeline

Run the smoke task to confirm the benchmark pipeline itself is working:

```bash
python -m benchmark.monitor_bench.runner --tasks smoke
```

This is the quickest way to verify subprocess launch, script dispatch,
metrics dumping, history dumping, and result ingestion.

## Keep the temp workspace for debugging

By default, the per-sample workspace is removed after grading. To preserve it:

```bash
MONITOR_BENCH_KEEP_WORKSPACE=1 \
python -m benchmark.monitor_bench.runner --tasks smoke
```

The preserved workspace is useful for inspecting:
- `_bench_script.txt`
- `_bench_metrics.json`
- `_bench_history.json`
- any files created by the task setup or by Monitor during the run

## Where to look next

For benchmark task authoring, result-file details, and deeper implementation
notes, see:
- `benchmark/monitor_bench/README.md`
