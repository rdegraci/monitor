from monitor import config
from monitor.core.agent_tools import agent_create, agent_kill, agent_list, agent_logfile, agent_send, agent_gather

from monitor.lib.redis_utils import (
    save_to_memory,
    read_from_memory,
    update_memory,
    fetch_memory_keys_as_json,
    delete_from_memory
)

from monitor.lib.weather import get_current_weather
from monitor.lib.web_search import tavily_search
from monitor.lib.ripgrep_search import ripgrep_search_tool
from monitor.lib.modeling import train_model, evaluate_model
from monitor.lib.git import (
    perform_git_status,
    perform_git_diff,
    perform_git_diff_previous,
    perform_git_diff_file,
    perform_git_show
)
from monitor.lib.git_history import search_commit_history, blame_lines, perform_git_diff_range
from monitor.lib.os import (
    list_directory_contents,
    cat_file,
    create_file,
    file_type,
    make_directory,
    cat_file_range
)

from monitor.lib.db_storage import execute_duckdb, execute_psql, execute_mc
from monitor.lib.built_in_commands import deploy_model_command, monitor_model_performance_command, sessions_command

from monitor.lib.text_file_editor import (
    text_file_or_directory_view,
    text_file_create,
    text_file_str_replace_in_file,
    text_file_insert_text_at_line,
    str_replace_based_edit_tool,
)
from monitor.lib.tool_text import MODIFY_SOURCE_CODE_DESCRIPTION

from monitor.lib.tool_loading import add_weather_tools, add_memory_tools, add_text_file_editor_tools, get_first_segment, remove_openai_editor_tools
from monitor.lib.protocol_engine import modify_source_code
from monitor.lib.bulk_replace import bulk_replace_in_files
from monitor.lib.find_files import find_files
from monitor.lib.code_symbols import file_outline, find_symbol
from monitor.lib.test_runner import run_python_tests
from monitor.lib.type_checker import type_check_python
from monitor.lib.todo import (
    add_discovered_work,
    add_todo,
    clear_todos,
    delete_todo,
    get_task_context,
    list_todos,
    record_task_scope_change,
    save_task_checkpoint,
    set_task_acceptance,
    update_todo,
)

TOOL_STATE: dict[str, bool] = {}

# Callable registry keyed by tool name. Entries here are executable
# implementations; separate description catalogs control which tools are
# exposed to a given provider/model.
AVAILABLE_TOOLS = {
    "get_current_weather": get_current_weather,
    "save_to_memory": save_to_memory,
    "read_from_memory": read_from_memory,
    "update_memory": update_memory,
    "fetch_memory_keys_as_json": fetch_memory_keys_as_json,
    "delete_from_memory": delete_from_memory,
    "perform_git_status": perform_git_status,
    "perform_git_diff": perform_git_diff,
    "perform_git_diff_file": perform_git_diff_file,
    "perform_git_diff_previous": perform_git_diff_previous,
    "perform_git_show": perform_git_show,
    "search_commit_history": search_commit_history,
    "blame_lines": blame_lines,
    "perform_git_diff_range": perform_git_diff_range,
    "list_directory_contents": list_directory_contents,
    "cat_file": cat_file,
    "cat_file_range": cat_file_range,
    "create_file": create_file,
    "execute_psql": execute_psql,
    "file_type": file_type,
    "tavily_search": tavily_search,
    "ripgrep_search_tool": ripgrep_search_tool,
    "execute_duckdb": execute_duckdb,
    "execute_mc": execute_mc,
    "train_model": train_model,
    "evaluate_model": evaluate_model,
    "deploy_model": deploy_model_command,
    "monitor_model_performance": monitor_model_performance_command,
    "sessions": sessions_command,
    "modify_source_code": modify_source_code,
    "find_files": find_files,
    "file_outline": file_outline,
    "find_symbol": find_symbol,
    "run_python_tests": run_python_tests,
    "type_check_python": type_check_python,
    "text_file_or_directory_view": text_file_or_directory_view,
    "text_file_create": text_file_create,
    "text_file_str_replace_in_file": text_file_str_replace_in_file,
    "text_file_insert_text_at_line": text_file_insert_text_at_line,
    "bulk_replace_in_files": bulk_replace_in_files,
    # Anthropic-native editor dispatcher. Both names map to the same
    # implementation in the callable registry, while configure_tools()
    # decides which tool name, if any, is exposed for the active model.
    "str_replace_based_edit_tool": str_replace_based_edit_tool,
    "str_replace_editor": str_replace_based_edit_tool,
    "add_discovered_work": add_discovered_work,
    "add_todo": add_todo,
    "list_todos": list_todos,
    "update_todo": update_todo,
    "delete_todo": delete_todo,
    "clear_todos": clear_todos,
    "get_task_context": get_task_context,
    "set_task_acceptance": set_task_acceptance,
    "save_task_checkpoint": save_task_checkpoint,
    "record_task_scope_change": record_task_scope_change,
    "agent_create": agent_create,
    "agent_kill": agent_kill,
    "agent_list": agent_list,
    "agent_logfile": agent_logfile,
    "agent_send": agent_send,
# Gemini uses a separate tool-description catalog shape (`{name, description,
# parameters}`), distinct from the nested OpenAI/LiteLLM-style entries in
# TOOL_DESCRIPTIONS.
    "agent_gather": agent_gather,
    "make_directory": make_directory
}

# List of fundamental LLM tool/function descriptions with parameters and descriptions
TOOL_DESCRIPTIONS = [
    {
        "type": "function",
        "function": {
            "name": "perform_git_status",
            "description": "Executes git status to get the current state of the repository, including staged, unstaged, and untracked files.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "perform_git_diff",
            "description": "Performs a git diff to identify changes compared to the previous commit. This is used to determine the difference between the working directory and the previous commit. This function should be used after modifying files to track updates and modifications effectively.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "perform_git_diff_file",
            "description": "Performs a git diff on a specified file to show changes compared to its previous commit. Useful for tracking updates and modifications to a specific file in a git repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The relative or absolute path to the file within the git repository to perform the diff on."
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "perform_git_diff_previous",
            "description": "Performs a `git diff HEAD^` to identify changes of the current commit compared to the previous commit. This function should be used to determine the difference between the current commit and its parent (the previous commit).",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "perform_git_show",
            "description": "Displays the changes introduced by a specific commit. This function executes 'git show' with the provided commit reference to show details about the commit including its metadata and the changes it introduced. Useful for examining the changes made in a particular commit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {
                        "type": "string",
                        "description": "The hash or branch name of the commit to show the git code changes."
                    }
                },
                "required": ["ref"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_commit_history",
            "description": "Find the commits that first introduced or later removed a specific piece of code or text across the repository's history. Use this to determine whether a bug or a line predates recent changes — e.g. 'when did this function/string first appear?' or 'was this already broken before my commits?'. Returns matching commits (short hash, date, subject), newest first. By default the query is treated as a literal string: special characters like '|', '\\b', '\\w', '\\d', '\\s', '(?', '[^' have no special meaning unless you also pass regex=true.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The exact code or text to look for across history."},
                    "regex": {"type": "boolean", "description": "Set true when the query uses regex syntax — pipes for OR (e.g. 'foo|bar'), word boundaries ('\\b'), character classes ('\\w', '\\d', '\\s'), or lookarounds ('(?...)'). Default is literal-string search.", "default": False},
                    "path": {"type": "string", "description": "Optional file or directory to limit the search to."},
                    "max_results": {"type": "integer", "description": "Maximum number of commits to return (newest first).", "default": 20}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "blame_lines",
            "description": "Show which commit last modified each line in a range of a file (git blame). Use to find when specific lines were last changed and in which commit — e.g. to check whether suspect lines came from your recent work or an older commit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "The file to blame."},
                    "start_line": {"type": "integer", "description": "First line of the range (1-based)."},
                    "end_line": {"type": "integer", "description": "Last line of the range (1-based, >= start_line)."}
                },
                "required": ["path", "start_line", "end_line"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "perform_git_diff_range",
            "description": "Show the diff between two commits, branches, or tags (git diff <base> <target>). Use to compare any two points in history — e.g. a known-good commit vs now, your branch point vs HEAD, or one release tag vs another — to see exactly what changed between them.",
            "parameters": {
                "type": "object",
                "properties": {
                    "base": {"type": "string", "description": "The starting ref (commit hash, branch, or tag)."},
                    "target": {"type": "string", "description": "The ending ref to compare against base."},
                    "path": {"type": "string", "description": "Optional file or directory to limit the diff to."}
                },
                "required": ["base", "target"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory_contents",
            "description": "List the contents of a directory at the given path. Use this function when you need to know the files (if any) in the directory at the given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The path to the directory to list. If the path is empty then the function will list the current working directory."
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cat_file",
            "description": "Display the full contents of a file at the given filepath. Use when you need the whole file. Do not call it repeatedly on the same path with different approaches to hunt for text — use ripgrep_search_tool instead.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The path to the file to display. (e.g. 'path/to/some/file')"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cat_file_range",
            "description": "Display a range of lines from a file. Use for a known line window. Do not slide ranges repeatedly across the same file looking for a string — use ripgrep_search_tool, then open one targeted range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The path to the file to display. (e.g. 'path/to/some/file')"
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "The 1-based line number to start reading from."
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "The 1-based line number to stop reading at (inclusive)."
                    }
                },
                "required": ["path", "start_line", "end_line"]
            }
        }
    },
    {
      "type": "function",
      "function": {
        "name": "modify_source_code",
        "description": MODIFY_SOURCE_CODE_DESCRIPTION,
        "parameters": {
          "type": "object",
          "properties": {
            "source_file": {
              "type": "string",
              "description": "The path to the file to modify or create."
            },
            "modification_request": {
              "type": "string",
              "description": "A natural language description of the change to apply (e.g., 'add logging to track each step')."
            }
          },
          "required": ["source_file", "modification_request"]
        }
      }
    },
    {
        "type": "function",
        "function": {
            "name": "find_files",
            "description": (
                "Find files by basename pattern, recursively, under a root directory. "
                "Always recurses. Common build/cache directories (.git, node_modules, "
                ".venv, __pycache__, DerivedData, .build, Pods, etc.) are pruned by "
                "default. Use this to locate files BEFORE reading them with cat_file. "
                "Pattern is a glob (*, ?, [...]) matched against each file's basename. "
                "Case-sensitive. To scope to a subdirectory, set `root` rather than "
                "embedding a path in the pattern."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": (
                            "Basename glob pattern, e.g. '*.py', 'test_*.swift', "
                            "'Manager*.swift'. A leading '**/' is stripped. Patterns "
                            "containing '/' are rejected — use `root` for directory scoping."
                        ),
                    },
                    "root": {
                        "type": "string",
                        "description": "Directory to search under. Defaults to cwd.",
                    },
                    "include_hidden": {
                        "type": "boolean",
                        "description": "If true, include hidden files and dirs. Default false.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Cap on number of results. Default 200.",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_outline",
            "description": (
                "Return a compact structural outline of one source file: classes, "
                "functions, methods, and types with line numbers and short signatures. "
                "Prefer this over paging cat_file / cat_file_range when you need to "
                "learn where definitions live before reading or editing. Requires the "
                "optional 'symbols' install extra. Supported: Python, JavaScript, "
                "TypeScript/TSX, Go, Rust, Swift."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to a single source file to outline.",
                    },
                    "kind": {
                        "type": "string",
                        "description": (
                            "Symbol kind filter: all (default), class, function, "
                            "method, or type."
                        ),
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Cap on returned symbols. Default 100, max 500.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_symbol",
            "description": (
                "Search a file or directory for symbol definitions by name "
                "(classes, functions, methods, types). Matches exact names first, "
                "then prefixes, then substrings. Prefer this to locate a definition "
                "across the repo; use file_outline for one file's full structure; "
                "use ripgrep_search_tool for textual references/usages. Requires "
                "the optional 'symbols' install extra. Supported: Python, "
                "JavaScript, TypeScript/TSX, Go, Rust, Swift."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Symbol name or fragment to find.",
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "File or directory to search under. Defaults to '.' (cwd)."
                        ),
                    },
                    "kind": {
                        "type": "string",
                        "description": (
                            "Symbol kind filter: all (default), class, function, "
                            "method, or type."
                        ),
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Cap on returned matches. Default 50, max 500.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python_tests",
            "description": (
                "Run pytest from the current working directory and return the exit code, "
                "a one-line summary, and the (tail-truncated) test output. Use this AFTER "
                "making code changes to verify them, or to investigate a specific failing "
                "test before fixing. SIDE EFFECT: tests can write files, touch databases, "
                "or send network requests — this is not a read-only operation. Prefer "
                "scoping with `path` (e.g. 'tests/monitor/lib/test_foo.py') over running "
                "the full suite."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Optional path or pattern to scope the test run. Defaults to "
                            "'tests/' if that directory exists in cwd, else '.'."
                        ),
                    },
                    "pytest_args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional list of additional pytest CLI flags, e.g. "
                            "['-k', 'test_foo'] or ['-x', '-v']. Leading '-' required."
                        ),
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "Max runtime before the test process is killed. Default 120.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type_check_python",
            "description": (
                "Run a Python type checker (mypy or pyright) on a path and return the exit "
                "code, summary, and tail-truncated output. Prefers mypy; falls back to pyright. "
                "Use AFTER making Python type-affecting changes to verify types still check, "
                "or to investigate a specific type error before fixing. Checker reads project "
                "config (mypy.ini, pyproject.toml [tool.mypy] / [tool.pyright], pyrightconfig.json) "
                "so strictness is project-defined. Read-only with respect to source (may write "
                "checker cache files like .mypy_cache/)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Path to check. Defaults to 'src/' if that directory exists in "
                            "cwd, else '.'."
                        ),
                    },
                    "checker": {
                        "type": "string",
                        "enum": ["mypy", "pyright"],
                        "description": (
                            "Force a specific checker. Default: auto-detect (prefers mypy)."
                        ),
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "Max runtime before checker is killed. Default 120.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
                "name": "create_file",
                "description": (
                    "Creates a file with the provided content at the specified path. "
                    "Behavior depends on `overwrite`: with `overwrite=false` (DEFAULT, SAFE) "
                    "the call refuses with an error when a file already exists at the path; "
                    "with `overwrite=true` the existing contents are REPLACED. "
                    "Use `overwrite=false` for genuinely new files. "
                    "Use `overwrite=true` ONLY when you have first viewed the existing file "
                    "(via text_file_or_directory_view) and explicitly intend a full replacement — "
                    "data loss is unrecoverable. For partial edits to an existing file, prefer "
                    "`text_file_str_replace_in_file` (deterministic, reviewable). "
                    "For fuzzy edits where exact text doesn't apply, use `modify_source_code`."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "contents": {
                            "description": "The content to write to the file.",
                            "type": "string"
                        },
                        "path": {
                            "description": "The path (including filename) at which to create or replace the file.",
                            "type": "string"
                        },
                        "overwrite": {
                            "description": (
                                "When false (default), refuse with an error if a file already exists. "
                                "When true, replace the existing file's contents. Only pass true when you "
                                "have already inspected the existing file and intend full replacement."
                            ),
                            "type": "boolean",
                            "default": False,
                        },
                },
                "required": ["path", "contents"]
              }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bulk_replace_in_files",
            "description": (
                "Deterministically replace text across one or more files in a single pass — "
                "the sanctioned tool for MECHANICAL multi-site edits (rename a symbol at every "
                "call site, delete a marker everywhere, bulk substitution). No LLM is involved, "
                "so it is exact and reproducible. "
                "Choose the right edit tool: a single unique edit → text_file_str_replace_in_file; "
                "a mechanical change repeated across many sites/files → THIS tool; a genuinely "
                "fuzzy change ('make this idiomatic') → modify_source_code. "
                "Match is LITERAL by default (set regex=False... i.e. literal=true); set literal=false "
                "for a Python regex. Use word_boundary=true for safe identifier renames (so 'count' "
                "does not match inside 'account'). The replacement text is literal — no regex "
                "backreference expansion. "
                "dry_run is TRUE by default: it returns the unified diff it WOULD make without writing. "
                "Re-issue with dry_run=false to apply. Every changed file is syntax/structure-verified "
                "before any write, and the batch is all-or-nothing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "old": {
                        "type": "string",
                        "description": "The text (or, when literal=false, the Python regex) to find. Must be non-empty."
                    },
                    "new": {
                        "type": "string",
                        "description": "The replacement text. Always literal — regex backreferences are NOT expanded."
                    },
                    "paths": {
                        "type": ["string", "array"],
                        "items": {"type": "string"},
                        "description": "A file path, a glob (e.g. 'src/**/*.py'), or a list of either. Globs support ** for recursion. Binary files and files outside the repo working tree are skipped."
                    },
                    "literal": {
                        "type": "boolean",
                        "description": "When true (default), 'old' is matched as literal text. When false, 'old' is a Python regular expression.",
                        "default": True
                    },
                    "word_boundary": {
                        "type": "boolean",
                        "description": "When true, match only whole words/identifiers (wraps the match in \\b...\\b). Use for symbol renames so 'count' does not match inside 'account'.",
                        "default": False
                    },
                    "expected_count": {
                        "type": "integer",
                        "description": "Optional safety latch: if provided, the operation aborts (writing nothing) unless exactly this many occurrences are found across all files."
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "When true (default), preview only — returns the diffs that WOULD be made and writes nothing. Set false to actually apply the change.",
                        "default": True
                    }
                },
                "required": ["old", "new", "paths"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ripgrep_search_tool",
            "description": "Searches for a pattern across files in the repository using ripgrep. By default, the pattern is treated as literal text (fixed-string search). Set regex=True when you need anchors (^/$), character classes, or alternation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "term": {
                        "type": "string",
                        "description": "The search pattern. Literal text by default; ripgrep regex when regex=True (e.g. '^def test_', 'TODO|FIXME')."
                    },
                    "filetype": {
                        "type": "string",
                        "description": "Optional ripgrep type (e.g., 'py', 'js', 'rb', 'swift') to limit the search scope."
                    },
                    "word": {
                        "type": "boolean",
                        "description": "Match whole words only (passes -w to ripgrep).",
                        "default": False
                    },
                    "regex": {
                        "type": "boolean",
                        "description": "When False (default), treat `term` as literal text. When True, interpret `term` as a ripgrep regex pattern (drops the -F flag). Use True for anchors, character classes, or alternation.",
                        "default": False
                    }
                },
                "required": ["term"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_todo",
            "description": "Add a new todo item to the current session's list. The session is determined automatically; do not pass it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item": {"type": "string", "description": "The todo item description."},
                    "priority": {"type": "integer", "description": "Higher number sorts earlier in list_todos.", "default": 0},
                    "notes": {"type": "string", "description": "Static supporting context for the todo — blockers, file pointers, gotchas (e.g. 'see auth_service.py:120', 'blocked on PR #42'). Do NOT use notes as a progress log; use `status` (pending/in_progress/done) for progress and `item` for the action itself. Notes should rarely change once written."}
                },
                "required": ["item"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_discovered_work",
            "description": "Add newly discovered required work to the current session's plan. Prefer this over add_todo when work emerges mid-task: it creates the todo and can also record scope growth in one step.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item": {"type": "string", "description": "The newly discovered work item to add to the plan."},
                    "priority": {"type": "integer", "description": "Higher number sorts earlier in list_todos.", "default": 0},
                    "notes": {"type": "string", "description": "Static supporting context for the newly discovered work."},
                    "material": {"type": "boolean", "description": "Set true when this discovered work materially expands the original ask.", "default": False},
                    "scope_summary": {"type": "string", "description": "Optional scope-growth summary to record alongside the new todo. Defaults to the todo item text when omitted and material/scope recording is requested."}
                },
                "required": ["item"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_todos",
            "description": "Retrieve the current session's todo list as a JSON array, sorted by priority (highest first); each item includes id, status, priority, and notes.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_todo",
            "description": "Update a todo addressed by its id (from add_todo or list_todos). Provide at least one of status, item, notes, or priority.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "The id of the todo to update."},
                    "status": {"type": "string", "description": "New status, e.g. 'pending', 'in_progress', 'done', 'blocked', or 'waiting'."},
                    "item": {"type": "string", "description": "New description text for the todo."},
                    "notes": {"type": "string", "description": "Static supporting context for the todo — blockers, file pointers, gotchas. Do NOT use notes as a progress log; use `status` for progress and `item` for the action itself. Update notes only when underlying context changes (e.g., a blocker is resolved), not to record what you just did."},
                    "priority": {"type": "integer", "description": "New priority (higher sorts earlier)."}
                },
                "required": ["id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_todo",
            "description": "Remove a single todo addressed by its id (from add_todo or list_todos).",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "The id of the todo to remove."}
                },
                "required": ["id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clear_todos",
            "description": "Clear the current session's entire plan (all todos).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_task_context",
            "description": "Retrieve lightweight session-scoped task context for long-running work: acceptance criteria, recent scope changes, and the latest resume checkpoint.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_task_acceptance",
            "description": "Set or replace the current session's acceptance criteria list for feature work. Use this early so completion is judged against explicit criteria, not just file edits.",
            "parameters": {
                "type": "object",
                "properties": {
                    "criteria": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "The acceptance criteria to satisfy before considering the task done."
                    }
                },
                "required": ["criteria"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_task_checkpoint",
            "description": "Save a lightweight resume checkpoint for the current session. Use when pausing mid-task, after a delegated failure, or after a meaningful intermediate milestone.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "What is already true now."},
                    "next_step": {"type": "string", "description": "The exact next action to resume with."},
                    "blockers": {"type": "string", "description": "Optional blockers or recovery notes."}
                },
                "required": ["summary", "next_step"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "record_task_scope_change",
            "description": "Record a discovered scope change for the current session. Use together with add_todo when new required work is discovered; surface material scope growth before silently absorbing it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "The newly discovered work or scope expansion."},
                    "material": {"type": "boolean", "description": "Whether the scope change is materially larger than the original ask.", "default": True}
                },
                "required": ["summary"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "make_directory",
            "description": "Create a directory (and parents) if needed at the given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The path to the directory to create."
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tavily_search",
            "description": "Performs a web search using Tavily API to get up-to-date information or additional context. Use this when you need current information or think a search could provide a better answer.",
            "parameters": {
              "properties": {
                "query": {
                  "description": "The search query",
                  "type": "string"
                }
              },
              "required": [
                "query"
              ],
              "type": "object"
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "agent_create",
            "description": "Spawn a background sub-agent initialized with the given prompt. Returns immediately with a session_name; the sub-agent runs in the background and its result is delivered to you on a later turn. By default the sub-agent is ONE-SHOT — it does the task, reports, and exits (use this for researchers / fan-out). Set persistent=true ONLY if you intend to send it follow-ups with agent_send; you must then agent_kill it when done.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "The initial prompt or instruction for the new sub-agent."
                    },
                    "persistent": {
                        "type": "boolean",
                        "description": "False (default) = one-shot: exits after reporting its result (self-reaping). True = stays alive for agent_send follow-ups; you must agent_kill it when finished.",
                        "default": False
                    }
                },
                "required": ["prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "agent_kill",
            "description": "Terminate a sub-agent session. Use this to stop a persistent sub-agent when you're done with it, or to cancel a runaway one.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session": {
                        "type": ["string", "integer"],
                        "description": "The session_name returned by agent_create (a 1-based index from the agent list also works)."
                    }
                },
                "required": ["session"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "agent_list",
            "description": "Returns a list of available agents and their metadata. Use this function to discover agents that can be invoked or inspected.",
            "parameters": {
                "type": "object",
                "properties": {
                    "full": {
                        "type": "boolean",
                        "description": "If true, return complete agent metadata including configuration and capabilities; otherwise return a summary list."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "agent_logfile",
            "description": "Get the logfile path for a sub-agent session, to inspect its full transcript.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session": {
                        "type": ["string", "integer"],
                        "description": "The session_name returned by agent_create (a 1-based index from the agent list also works)."
                    }
                },
                "required": ["session"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "agent_send",
            "description": "Send a follow-up message to a PERSISTENT sub-agent (one created with persistent=true). Use this to give it more work after its first result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session": {
                        "type": ["string", "integer"],
                        "description": "The session_name returned by agent_create (a 1-based index from the agent list also works)."
                    },
                    "text": {
                        "type": "string",
                        "description": "The text message or follow-up prompt to send to the agent."
                    }
                },
                "required": ["session", "text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "agent_gather",
            "description": (
                "Wait for one or more sub-agents to finish and return their results so you can "
                "aggregate them. This is how you ORCHESTRATE: fan out independent work by calling "
                "agent_create N times (each returns a session_name), then call agent_gather with "
                "those session_names. It BLOCKS until every listed agent finishes (reports a "
                "result, errors, or exits) or crashes, or until the timeout. "
                "Returns three buckets so nothing is hidden: 'ok' (each with the agent's result "
                "summary/data), 'failed' (each with a reason — e.g. a crash), and 'pending' (still "
                "running at timeout). Use this for independent, parallelizable subtasks; for "
                "sequential or single-step work, just do it yourself. You remain the sole writer of "
                "files — treat sub-agents as researchers and apply any changes yourself."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_ids": {
                        "type": ["string", "array"],
                        "items": {"type": "string"},
                        "description": "A session_name (or list of them) as returned by agent_create."
                    },
                    "timeout": {
                        "type": "number",
                        "description": "Max seconds to wait for all agents to finish (default 120).",
                        "default": 120
                    }
                },
                "required": ["agent_ids"]
            }
        }
    }
]

GEMINI_TOOL_DESCRIPTIONS = [
  {
    "description": (
        "Deterministically replace text across one or more files in a single pass — the "
        "sanctioned tool for MECHANICAL multi-site edits (rename a symbol everywhere, bulk "
        "substitution). No LLM involved, so it is exact and reproducible. Single unique edit "
        "→ text_file_str_replace_in_file; mechanical repeat across many sites → THIS tool; "
        "fuzzy change → modify_source_code. Literal by default; set literal=false for a Python "
        "regex. Use word_boundary=true for safe identifier renames. Replacement text is literal. "
        "dry_run is TRUE by default (preview diffs, no write); set dry_run=false to apply. Every "
        "changed file is verified before writing and the batch is all-or-nothing."
    ),
    "name": "bulk_replace_in_files",
    "parameters": {
      "properties": {
        "old": {
          "description": "Text (or Python regex when literal=false) to find. Non-empty.",
          "type": "string"
        },
        "new": {
          "description": "Replacement text. Literal — no regex backreference expansion.",
          "type": "string"
        },
        "paths": {
          "description": "A file path, a glob (e.g. 'src/**/*.py'), or a list of either. Binary and out-of-tree files are skipped.",
          "type": "string"
        },
        "literal": {
          "description": "True (default) matches 'old' literally; false treats it as a Python regex.",
          "type": "boolean"
        },
        "word_boundary": {
          "description": "True matches whole identifiers only (so 'count' does not match 'account').",
          "type": "boolean"
        },
        "expected_count": {
          "description": "Optional latch: abort writing nothing unless exactly this many matches are found.",
          "type": "integer"
        },
        "dry_run": {
          "description": "True (default) previews diffs without writing; false applies the change.",
          "type": "boolean"
        }
      },
      "required": ["old", "new", "paths"],
      "type": "object"
    }
  },
  {
    "description": "Executes git status to get the current state of the repository, including staged, unstaged, and untracked files.",
    "name": "perform_git_status"
  },
  {
    "description": "Performs a git diff to identify changes compared to the previous commit. This is used to determine the difference between the working directory and the previous commit. This function should be used after modifying files to track updates and modifications effectively.",
    "name": "perform_git_diff"
  },
  {
    "description": "Performs a git diff on a specified file to show changes compared to its previous commit. Useful for tracking updates and modifications to a specific file in a git repository.",
    "name": "perform_git_diff_file",
    "parameters": {
      "properties": {
        "path": {
          "description": "The relative or absolute path to the file within the git repository to perform the diff on.",
          "type": "string"
        }
      },
      "required": [
        "path"
      ],
      "type": "object"
    }
  },
  {
    "description": "Performs a `git diff HEAD^` to identify changes of the current commit compared to the previous commit. This function should be used to determine the difference between the current commit and its parent (the previous commit).",
    "name": "perform_git_diff_previous"
  },
  {
    "description": "Find the commits that first introduced or later removed a specific piece of code or text across the repository's history. Use this to determine whether a bug or a line predates recent changes — e.g. 'when did this function/string first appear?' or 'was this already broken before my commits?'. Returns matching commits (short hash, date, subject), newest first. By default the query is treated as a literal string: special characters like '|', '\\b', '\\w', '\\d', '\\s', '(?', '[^' have no special meaning unless you also pass regex=true.",
    "name": "search_commit_history",
    "parameters": {
      "properties": {
        "query": {"description": "The exact code or text to look for across history.", "type": "string"},
        "regex": {"description": "Set true when the query uses regex syntax — pipes for OR (e.g. 'foo|bar'), word boundaries ('\\b'), character classes ('\\w', '\\d', '\\s'), or lookarounds ('(?...)'). Default is literal-string search.", "type": "boolean", "default": False},
        "path": {"description": "Optional file or directory to limit the search to.", "type": "string"},
        "max_results": {"description": "Maximum number of commits to return (newest first).", "type": "integer", "default": 20}
      },
      "required": ["query"],
      "type": "object"
    }
  },
  {
    "description": "Show which commit last modified each line in a range of a file (git blame). Use to find when specific lines were last changed and in which commit — e.g. to check whether suspect lines came from your recent work or an older commit.",
    "name": "blame_lines",
    "parameters": {
      "properties": {
        "path": {"description": "The file to blame.", "type": "string"},
        "start_line": {"description": "First line of the range (1-based).", "type": "integer"},
        "end_line": {"description": "Last line of the range (1-based, >= start_line).", "type": "integer"}
      },
      "required": ["path", "start_line", "end_line"],
      "type": "object"
    }
  },
  {
    "description": "Show the diff between two commits, branches, or tags (git diff <base> <target>). Use to compare any two points in history — e.g. a known-good commit vs now, your branch point vs HEAD, or one release tag vs another — to see exactly what changed between them.",
    "name": "perform_git_diff_range",
    "parameters": {
      "properties": {
        "base": {"description": "The starting ref (commit hash, branch, or tag).", "type": "string"},
        "target": {"description": "The ending ref to compare against base.", "type": "string"},
        "path": {"description": "Optional file or directory to limit the diff to.", "type": "string"}
      },
      "required": ["base", "target"],
      "type": "object"
    }
  },
  {
    "description": "List the contents of a directory at the given path. Use this function when you need to know the files (if any) in the directory at the given path.",
    "name": "list_directory_contents",
    "parameters": {
      "properties": {
        "path": {
          "description": "The path to the directory to list. If the path is empty then the function will list the current working directory.",
          "type": "string"
        }
      },
      "required": [
        "path"
      ],
      "type": "object"
    }
  },
  {
    "description": "Display the full contents of a file at the given path. Use when you need the whole file. Do not call it repeatedly on the same path to hunt for text — use ripgrep_search_tool instead.",
    "name": "cat_file",
    "parameters": {
      "properties": {
        "path": {
          "description": "The path to the file to display. (e.g. 'path/to/some/file')",
          "type": "string"
        }
      },
      "required": [
        "path"
      ],
      "type": "object"
    }
  },
  {
    "description": "Display a range of lines from a file. Use for a known line window. Do not slide ranges repeatedly across the same file looking for a string — use ripgrep_search_tool, then open one targeted range.",
    "name": "cat_file_range",
    "parameters": {
      "properties": {
        "path": {
          "description": "The path to the file to display. (e.g. 'path/to/some/file')",
          "type": "string"
        },
        "start_line": {
          "description": "The 1-based line number to start reading from.",
          "type": "integer"
        },
        "end_line": {
          "description": "The 1-based line number to stop reading at (inclusive).",
          "type": "integer"
        }
      },
      "required": [
        "path",
        "start_line",
        "end_line"
      ],
      "type": "object"
    }
  },
  {
    "name": "create_file",
    "description": (
        "Creates a file with the provided content. With overwrite=false (default, safe) "
        "refuses if the file already exists; with overwrite=true replaces the existing "
        "contents. Use overwrite=true ONLY after viewing the existing file (data loss "
        "is unrecoverable). For partial edits, prefer text_file_str_replace_in_file."
    ),
    "parameters": {
      "properties": {
        "contents": {
          "description": "The content to write to the file.",
          "type": "string"
        },
        "path": {
          "description": "The path (including filename) at which to create or replace the file.",
          "type": "string"
        },
        "overwrite": {
          "description": (
              "When false (default), refuse if a file already exists. When true, replace "
              "the existing file's contents. Only pass true when you intend full replacement."
          ),
          "type": "boolean",
          "default": False
        }
      },
      "required": ["path", "contents"],
      "type": "object"
    }
  },
  {
    "description": "Provides the file type of a given file at the specified path.",
    "name": "file_type",
    "parameters": {
      "properties": {
        "path": {
          "description": "The path to the file to check",
          "type": "string"
        }
      },
      "required": [
        "path"
      ],
      "type": "object"
    }
  },
  {
    "description": "Performs a web search using Tavily API to get up-to-date information or additional context. Use this when you need current information or think a search could provide a better answer.",
    "name": "tavily_search",
    "parameters": {
      "properties": {
        "query": {
          "description": "The search query",
          "type": "string"
        }
      },
      "required": [
        "query"
      ],
      "type": "object"
    }
  },
  {
    "description": MODIFY_SOURCE_CODE_DESCRIPTION,
    "name": "modify_source_code",
    "parameters": {
      "properties": {
        "modification_request": {
          "description": "A natural language description of the change to apply (e.g., 'add logging to track each step').",
          "type": "string"
        },
        "source_file": {
          "description": "The path to the file to modify or create.",
          "type": "string"
        }
      },
      "required": [
        "source_file",
        "modification_request"
      ],
      "type": "object"
    }
  },
  {
    "description": (
        "Find files by basename pattern, recursively, under a root directory. "
        "Excludes common build/cache dirs by default (.git, node_modules, "
        ".venv, __pycache__, DerivedData, .build, Pods, etc.). Use `root` to "
        "scope to a subdirectory; patterns with '/' are rejected."
    ),
    "name": "find_files",
    "parameters": {
      "type": "object",
      "properties": {
        "pattern": {
          "type": "string",
          "description": "Basename glob pattern, e.g. '*.py' or 'test_*.swift'."
        },
        "root": {
          "type": "string",
          "description": "Directory to search. Defaults to cwd."
        },
        "include_hidden": {
          "type": "boolean",
          "description": "If true, include hidden files. Default false."
        },
        "max_results": {
          "type": "integer",
          "description": "Cap on number of results. Default 200."
        }
      },
      "required": ["pattern"]
    }
  },
  {
    "description": (
        "Return a compact structural outline of one source file (classes, functions, "
        "methods, types with line numbers). Prefer over paging cat_file when locating "
        "definitions. Requires the optional 'symbols' extra. Supported: Python, "
        "JavaScript, TypeScript/TSX, Go, Rust, Swift."
    ),
    "name": "file_outline",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "description": "Path to a single source file to outline."
        },
        "kind": {
          "type": "string",
          "description": "Filter: all, class, function, method, or type."
        },
        "max_results": {
          "type": "integer",
          "description": "Cap on returned symbols. Default 100."
        }
      },
      "required": ["path"]
    }
  },
  {
    "description": (
        "Search a file or directory for symbol definitions by name. Exact matches "
        "rank first, then prefixes, then substrings. Prefer over paging cat_file; "
        "use ripgrep for textual references. Requires the optional 'symbols' extra. "
        "Supported: Python, JavaScript, TypeScript/TSX, Go, Rust, Swift."
    ),
    "name": "find_symbol",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "Symbol name or fragment to find."
        },
        "path": {
          "type": "string",
          "description": "File or directory scope. Defaults to '.'."
        },
        "kind": {
          "type": "string",
          "description": "Filter: all, class, function, method, or type."
        },
        "max_results": {
          "type": "integer",
          "description": "Cap on returned matches. Default 50."
        }
      },
      "required": ["query"]
    }
  },
  {
    "description": (
        "Run pytest from the current working directory and return the exit code, "
        "a one-line summary, and the (tail-truncated) test output. SIDE EFFECT: "
        "tests can write files, touch databases, or send network requests. "
        "Prefer scoping with `path` over full-suite runs."
    ),
    "name": "run_python_tests",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "description": "Optional path or pattern to scope the run."
        },
        "pytest_args": {
          "type": "array",
          "items": {"type": "string"},
          "description": "Optional list of additional pytest CLI flags."
        },
        "timeout_seconds": {
          "type": "integer",
          "description": "Max runtime before the test process is killed."
        }
      },
      "required": []
    }
  },
  {
    "description": (
        "Run a Python type checker (mypy or pyright) and return exit code, summary, "
        "and tail-truncated output. Prefers mypy; falls back to pyright. "
        "Reads project config for strictness. Read-only with respect to source."
    ),
    "name": "type_check_python",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "description": "Path to check. Defaults to 'src/' if present, else '.'."
        },
        "checker": {
          "type": "string",
          "description": "Force checker: 'mypy' or 'pyright'. Default: auto-detect."
        },
        "timeout_seconds": {
          "type": "integer",
          "description": "Max runtime before checker is killed. Default 120."
        }
      },
      "required": []
    }
  },
  {
    "description": "Searches for a pattern across files in the repository using ripgrep. Literal text by default; set regex=True for anchors, character classes, or alternation.",
    "name": "ripgrep_search_tool",
    "parameters": {
      "type": "object",
      "properties": {
        "term": {
          "type": "string",
          "description": "The search pattern. Literal text by default; ripgrep regex when regex=True."
        },
        "filetype": {
          "type": "string",
          "description": "Optional ripgrep type (e.g., 'py', 'js', 'rb', 'swift') to limit the search scope."
        },
        "word": {
          "type": "boolean",
          "description": "Match whole words only (passes -w to ripgrep).",
          "default": False
        },
        "regex": {
          "type": "boolean",
          "description": "When False (default), treat `term` as literal text. When True, interpret as ripgrep regex (drops -F).",
          "default": False
        }
      },
      "required": [
        "term"
      ],
      "type": "object"
    }
  },
  {
    "description": "Add a new todo item to the current session's list. The session is determined automatically; do not pass it.",
    "name": "add_todo",
    "parameters": {
      "properties": {
        "item": {
          "description": "The todo item description.",
          "type": "string"
        },
        "priority": {
          "description": "Higher number sorts earlier in list_todos.",
          "type": "integer",
          "default": 0
        },
        "notes": {
          "description": "Static supporting context for the todo — blockers, file pointers, gotchas (e.g. 'see auth_service.py:120', 'blocked on PR #42'). Do NOT use notes as a progress log; use `status` (pending/in_progress/done) for progress and `item` for the action itself. Notes should rarely change once written.",
          "type": "string"
        }
      },
      "required": [
        "item"
      ],
      "type": "object"
    }
  },
  {
    "description": "Add newly discovered required work to the current session's plan. Prefer this over add_todo when work emerges mid-task: it creates the todo and can also record scope growth in one step.",
    "name": "add_discovered_work",
    "parameters": {
      "properties": {
        "item": {
          "description": "The newly discovered work item to add to the plan.",
          "type": "string"
        },
        "priority": {
          "description": "Higher number sorts earlier in list_todos.",
          "type": "integer",
          "default": 0
        },
        "notes": {
          "description": "Static supporting context for the newly discovered work.",
          "type": "string"
        },
        "material": {
          "description": "Set true when this discovered work materially expands the original ask.",
          "type": "boolean",
          "default": False
        },
        "scope_summary": {
          "description": "Optional scope-growth summary to record alongside the new todo. Defaults to the todo item text when omitted and material/scope recording is requested.",
          "type": "string"
        }
      },
      "required": [
        "item"
      ],
      "type": "object"
    }
  },
  {
    "description": "Retrieve the current session's todo list as a JSON array, sorted by priority (highest first); each item includes id, status, priority, and notes.",
    "name": "list_todos",
    "parameters": {
      "properties": {},
      "required": [],
      "type": "object"
    }
  },
  {
    "description": "Update a todo addressed by its id (from add_todo or list_todos). Provide at least one of status, item, notes, or priority.",
    "name": "update_todo",
    "parameters": {
      "properties": {
        "id": {
          "description": "The id of the todo to update.",
          "type": "string"
        },
        "status": {
          "description": "New status, e.g. 'pending', 'in_progress', 'done', 'blocked', or 'waiting'.",
          "type": "string"
        },
        "item": {
          "description": "New description text for the todo.",
          "type": "string"
        },
        "notes": {
          "description": "Static supporting context for the todo — blockers, file pointers, gotchas. Do NOT use notes as a progress log; use `status` for progress and `item` for the action itself. Update notes only when underlying context changes (e.g., a blocker is resolved), not to record what you just did.",
          "type": "string"
        },
        "priority": {
          "description": "New priority (higher sorts earlier).",
          "type": "integer"
        }
      },
      "required": [
        "id"
      ],
      "type": "object"
    }
  },
  {
    "description": "Remove a single todo addressed by its id (from add_todo or list_todos).",
    "name": "delete_todo",
    "parameters": {
      "properties": {
        "id": {
          "description": "The id of the todo to remove.",
          "type": "string"
        }
      },
      "required": [
        "id"
      ],
      "type": "object"
    }
  },
  {
    "description": "Clear the current session's entire plan (all todos).",
    "name": "clear_todos",
    "parameters": {
      "properties": {},
      "required": [],
      "type": "object"
    }
  },
  {
    "description": "Retrieve lightweight session-scoped task context for long-running work: acceptance criteria, recent scope changes, and the latest resume checkpoint.",
    "name": "get_task_context",
    "parameters": {
      "properties": {},
      "required": [],
      "type": "object"
    }
  },
  {
    "description": "Set or replace the current session's acceptance criteria list for feature work. Use this early so completion is judged against explicit criteria, not just file edits.",
    "name": "set_task_acceptance",
    "parameters": {
      "properties": {
        "criteria": {
          "description": "The acceptance criteria to satisfy before considering the task done.",
          "items": {
            "type": "string"
          },
          "type": "array"
        }
      },
      "required": [
        "criteria"
      ],
      "type": "object"
    }
  },
  {
    "description": "Save a lightweight resume checkpoint for the current session. Use when pausing mid-task, after a delegated failure, or after a meaningful intermediate milestone.",
    "name": "save_task_checkpoint",
    "parameters": {
      "properties": {
        "summary": {
          "description": "What is already true now.",
          "type": "string"
        },
        "next_step": {
          "description": "The exact next action to resume with.",
          "type": "string"
        },
        "blockers": {
          "description": "Optional blockers or recovery notes.",
          "type": "string"
        }
      },
      "required": [
        "summary",
        "next_step"
      ],
      "type": "object"
    }
  },
  {
    "description": "Record a discovered scope change for the current session. Use together with add_todo when new required work is discovered; surface material scope growth before silently absorbing it.",
    "name": "record_task_scope_change",
    "parameters": {
      "properties": {
        "summary": {
          "description": "The newly discovered work or scope expansion.",
          "type": "string"
        },
        "material": {
          "description": "Whether the scope change is materially larger than the original ask.",
          "type": "boolean",
          "default": True
        }
      },
      "required": [
        "summary"
      ],
      "type": "object"
    }
  },
  {
    "description": "Create a directory (and parents) if needed at the given path.",
    "name": "make_directory",
    "parameters": {
      "properties": {
        "path": {
          "description": "The path to the directory to create.",
          "type": "string"
        }
      },
      "required": [
        "path"
      ],
      "type": "object"
    }
  },
  {
    "description": "Terminate a sub-agent session (stop a persistent one when done, or cancel a runaway).",
    "name": "agent_kill",
    "parameters": {
      "properties": {
        "session": {
          "description": "The session_name returned by agent_create (a 1-based list index also works).",
          "type": "string"
        }
      },
      "required": [
        "session"
      ],
      "type": "object"
    }
  },
  {
    "description": "Returns a list of available agents and their metadata. Use this function to discover agents that can be invoked or inspected.",
    "name": "agent_list",
    "parameters": {
      "properties": {
        "full": {
          "description": "If true, return complete agent metadata including configuration and capabilities; otherwise return a summary list.",
          "type": "boolean"
        }
      },
      "type": "object"
    }
  },
  {
    "description": "Get the logfile path for a sub-agent session, to inspect its full transcript.",
    "name": "agent_logfile",
    "parameters": {
      "properties": {
        "session": {
          "description": "The session_name returned by agent_create (a 1-based list index also works).",
          "type": "string"
        }
      },
      "required": [
        "session"
      ],
      "type": "object"
    }
  },
  {
    "description": "Send a follow-up message to a PERSISTENT sub-agent (created with persistent=true).",
    "name": "agent_send",
    "parameters": {
      "properties": {
        "session": {
          "description": "The session_name returned by agent_create (a 1-based list index also works).",
          "type": "string"
        },
        "text": {
          "description": "The text/follow-up prompt to send to the agent.",
          "type": "string"
        }
      },
      "required": [
        "session",
        "text"
      ],
      "type": "object"
    }
  },
  {
    "description": (
        "Wait for one or more sub-agents to finish and return their results so you can aggregate "
        "them. Fan out independent work via agent_create (each returns a session_name), then call "
        "agent_gather with those session_names. Blocks until every agent finishes or crashes, or "
        "until timeout. Returns 'ok' (with each result), 'failed' (with reasons), and 'pending' "
        "buckets — nothing is hidden. You remain the sole file writer; treat sub-agents as "
        "researchers and apply changes yourself."
    ),
    "name": "agent_gather",
    "parameters": {
      "properties": {
        "agent_ids": {
          "description": "A session_name (or list of them) as returned by agent_create.",
          "type": "string"
        },
        "timeout": {
          "description": "Max seconds to wait for all agents to finish (default 120).",
          "type": "number"
        }
      },
      "required": ["agent_ids"],
      "type": "object"
    }
  }
]
