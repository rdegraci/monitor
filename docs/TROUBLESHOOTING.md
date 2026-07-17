# Troubleshooting

Short fixes for common first-run and session problems. For the happy path, see
[`GETTING_STARTED.md`](GETTING_STARTED.md).

## Installation

| Symptom | What to try |
|---------|-------------|
| Import / missing optional package | Install the matching extra, e.g. `pip install '.[server]'`. Core `pip install .` is intentional and light. |
| Feature fails with an install hint | That extra was not installed; the message names the pip extra. |
| `file_outline` / `find_symbol` reports missing dependencies | Install `pip install '.[symbols]'`, then restart Monitor. |
| External binary missing | Install system tools as needed: `ripgrep`, `git`, `redis` (for memory), `duckdb` CLI, `ffmpeg` / PortAudio (voice). |

## Authentication and config

| Symptom | What to try |
|---------|-------------|
| Model calls fail / auth errors | Set a provider key in `~/.config/monitor/.env` or project `.env`. Load order: project `.env`, then user `.env` (user wins). |
| Unsure what is configured | `python -m monitor --check-config` — reports file presence, model, profile, budget, and key *presence* only (never key values). |
| Config looks wrong after upgrade | Seeding never overwrites existing files. Diff against packaged examples under `src/monitor/` if you need defaults back. |
| Wrong model | `python -m monitor --models`, then `--model <name>` or `:llm` in-session. |

Common env vars (presence only in `--check-config`): `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `XAI_API_KEY`, `GOOGLE_API_KEY`, `OPENROUTER_API_KEY`.

## Context pressure and spend

| Symptom | What to try |
|---------|-------------|
| Cliff / compaction warnings | `:break_chain`, `:compact`, or `:reset_history` — see `:help session`. |
| Status line too noisy / too quiet | `:status minimal` / `:status coding` / `:status debug`. |
| Turn looks stalled | Ensure `:activity on` (default in interactive REPL). Check logs for `[SPEND][TURN]`. |
| Tools missing (network/db/agent) | Default profile is `coding`. Use `:tools full` or ask for the capability (auto-widen). |

## Edits and tool loops

| Symptom | What to try |
|---------|-------------|
| NL editor notice | Model used `modify_source_code`; prefer replace/insert tools. |
| `[category]` tool failure | Follow the one-line recovery hint; details are in logs. |
| Model re-reads the same file forever | Path read budget (`MAX_PATH_READS_PER_TURN`); ask it to `ripgrep_search_tool` instead. |
| Symbol lookup reports unsupported language | Use ripgrep/file reads; supported symbol languages are shown by `:symbols langs`. |
| `[symbol_budget]` | Use results already returned, then inspect targeted files. Default cap is `MAX_SYMBOL_QUERIES_PER_TURN: 12`. |
| Symbol results seem stale | File mtime/size invalidates the cache. Use `:symbols cache` for counters; restart Monitor to clear the in-process layer. |

## Entry points

| Entry | Role |
|-------|------|
| `monitor` / `python -m monitor` | **Production** |
| `monitor-oop` / `python -m monitor_oop` | **Experimental** — do not use for primary onboarding |

## Still stuck

- `:dump_metrics` / `:cost_debug` for session counters
- Logs under `~/.config/monitor/logs` (typical Unix path)
- [`ARCHITECTURE.md`](ARCHITECTURE.md) for runtime layout
