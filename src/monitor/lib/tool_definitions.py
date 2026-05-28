from monitor import config
from monitor.core.agent_tools import agent_create, agent_kill, agent_list, agent_logfile, agent_send

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
from monitor.lib.built_in_commands import deploy_model_command, monitor_model_performance_command

from monitor.lib.text_file_editor import (
    text_file_or_directory_view,
    text_file_create,
    text_file_str_replace_in_file,
    text_file_insert_text_at_line
)

from monitor.lib.tool_loading import add_weather_tools, add_memory_tools, add_text_file_editor_tools, get_first_segment, remove_openai_editor_tools
from monitor.lib.protocol_engine import modify_source_code
from monitor.lib.find_files import find_files
from monitor.lib.test_runner import run_python_tests
from monitor.lib.type_checker import type_check_python
from monitor.lib.todo import add_todo, list_todos, update_todo, delete_todo, clear_todos

TOOL_STATE = {}

# Dictionary of available LLM tool/functions for various tasks
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
    "modify_source_code": modify_source_code,
    "find_files": find_files,
    "run_python_tests": run_python_tests,
    "type_check_python": type_check_python,
    "text_file_or_directory_view": text_file_or_directory_view,
    "text_file_create": text_file_create,
    "text_file_str_replace_in_file": text_file_str_replace_in_file,
    "text_file_insert_text_at_line": text_file_insert_text_at_line,
    "add_todo": add_todo,
    "list_todos": list_todos,
    "update_todo": update_todo,
    "delete_todo": delete_todo,
    "clear_todos": clear_todos,
    "agent_create": agent_create,
    "agent_kill": agent_kill,
    "agent_list": agent_list,
    "agent_logfile": agent_logfile,
    "agent_send": agent_send,
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
            "description": "Find the commits that first introduced or later removed a specific piece of code or text across the repository's history. Use this to determine whether a bug or a line predates recent changes — e.g. 'when did this function/string first appear?' or 'was this already broken before my commits?'. Returns matching commits (short hash, date, subject), newest first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The exact code or text to look for across history."},
                    "regex": {"type": "boolean", "description": "Treat query as a regular expression instead of a literal string.", "default": False},
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
            "description": "Display the full contents of a file at the given filepath. Use this function when you need to know or examine the full contents of a file. Note: Does not support partial reading of the file.",
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
            "description": "Display a range of lines from a file at the given filepath. Use this function when you need to read a specific portion of a file by line numbers.",
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
        "description": (
            "Modifies the source code in place at the specified file path. "
            "The operation will overwrite or replace the file as needed to accomplish the requested modification. "
            "If the file does not exist, it will be created. "
            "This is the tool to use for all updates, replacements, refactoring, or complete rewrites of existing files."
        ),
        "parameters": {
          "type": "object",
          "properties": {
            "source_file": {
              "type": "string",
              "description": "The path to the file to modify or rewrite."
            },
            "modification_request": {
              "type": "string",
              "description": "A natural language description of how to modify the source code (e.g., 'add logging to track each step')."
            }
          },
          "notes": (
              "Attempting to create a file at an existing path will result in a NO-OP: "
              "the existing file will not be modified."
              ),
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
                    "Creates a new file with the provided content at the specified path. "
                    "If a file already exists at the path, this operation will NOT modify, overwrite, "
                    "or truncate the existing file. It is a safe way to create new files only. "
                    "For replacing or updating an existing file, use the 'modify_source_code' tool."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "contents": {
                            "description": "The content to write to the newly created file.",
                            "type": "string"
                        },
                    "path": {
                        "description": "The path (including filename) at which to create the new file.",
                        "type": "string"
                    }
                },
                "notes": (
                    "Attempting to create a file at an existing path will result in a NO-OP: "
                    "the existing file will not be modified."
                ),
                "required": ["path", "contents"]
              }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ripgrep_search_tool",
            "description": "Searches for a term across files within the repository using ripgrep. Useful for quickly locating occurrences of a string or pattern in code or text files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "term": {
                        "type": "string",
                        "description": "The search term to look for. Note: this is a string search, do not treat it as a Regex. (e.g. 'SomeStruct' or '\"struct SomeStruct\"' or '\"def function_name()\"')"
                    },
                    "filetype": {
                        "type": "string",
                        "description": "Optional ripgrep type (e.g., 'py', 'js', 'rb', 'swift') to limit the search scope."
                    },
                    "word": {
                        "type": "boolean",
                        "description": "Match whole words only (passes -w to ripgrep).",
                        "default": False
                    }
                },
                "required": ["term", "filetype", "word"]
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
                    "notes": {"type": "string", "description": "Notes for the todo item."}
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
                    "status": {"type": "string", "description": "New status, e.g. 'in_progress' or 'done'."},
                    "item": {"type": "string", "description": "New description text for the todo."},
                    "notes": {"type": "string", "description": "Notes to set on the todo."},
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
            "description": "Create a new agent session initialized with the provided prompt. Use this function to start or instantiate an agent that can be interacted with afterwards.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "The initial prompt or instruction for the new agent."
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
            "description": "Terminate or stop the specified agent session. Use this function to stop an agent safely.",
            "parameters": {
                "type": "object",
                "properties": {
                    "index": {
                        "type": "integer",
                        "description": "The index of the agent session to terminate."
                    }
                },
                "required": ["index"]
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
            "description": "Retrieve or stream the logfile for the specified agent session. Use this to obtain logs produced by agents for debugging or auditing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "index": {
                        "type": "integer",
                        "description": "The index of the agent logfile to retrieve."
                    }
                },
                "required": ["index"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "agent_send",
            "description": "Send a text message to the specified agent session. Use this function to provide input or commands to an active agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "index": {
                        "type": "integer",
                        "description": "The index of the agent session to send the message to."
                    },
                    "text": {
                        "type": "string",
                        "description": "The text message or command to send to the agent."
                    }
                },
                "required": ["index", "text"]
            }
        }
    }
]

GEMINI_TOOL_DESCRIPTIONS = [
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
    "description": "Find the commits that first introduced or later removed a specific piece of code or text across the repository's history. Use this to determine whether a bug or a line predates recent changes — e.g. 'when did this function/string first appear?' or 'was this already broken before my commits?'. Returns matching commits (short hash, date, subject), newest first.",
    "name": "search_commit_history",
    "parameters": {
      "properties": {
        "query": {"description": "The exact code or text to look for across history.", "type": "string"},
        "regex": {"description": "Treat query as a regular expression instead of a literal string.", "type": "boolean", "default": False},
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
    "description": "Display the full contents of a file at the given path. Use this function when you need to know or examine the full contents of a file. Note: Does not support partial reading of the file.",
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
    "description": "Display a range of lines from a file at the given filepath. Use this function when you need to read a specific portion of a file by line numbers.",
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
    "description": "Creates a new file with the provided content, but does not modify or overwrite existing files. Use this function only when you need to create a file that does not already exist.",
    "parameters": {
      "properties": {
        "contents": {
          "description": "The content to write to the newly created file.",
          "type": "string"
        },
        "path": {
          "description": "The path to the file to be created. If the file already exists, no action will be taken.",
          "type": "string"
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
    "description": "Modifies source code in place according to a specified request and returns the result. The original file is overwritten with the modified version. Use this tool for large scripts that exceed context length limits.",
    "name": "modify_source_code",
    "parameters": {
      "properties": {
        "modification_request": {
          "description": "A natural language description of how to modify the source code (e.g., 'add logging to track each step').",
          "type": "string"
        },
        "source_file": {
          "description": "The file path of the source code to modify in place.",
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
    "description": "Searches for a term across files within the repository using ripgrep. Useful for quickly locating occurrences of a string or pattern in code or text files.",
    "name": "ripgrep_search_tool",
    "parameters": {
      "type": "object",
      "properties": {
        "term": {
          "type": "string",
          "description": "The search term to look for. Note: this is a string search, do not treat it as a Regex. (e.g. 'SomeStruct' or '\"struct SomeStruct\"' or '\"def function_name()\"')"
        },
        "filetype": {
          "type": "string",
          "description": "Optional ripgrep type (e.g., 'py', 'js', 'rb', 'swift') to limit the search scope."
        },
        "word": {
          "type": "boolean",
          "description": "Match whole words only (passes -w to ripgrep).",
          "default": False
        }
      },
      "required": [
        "term",
        "filetype",
        "word"
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
          "description": "Notes for the todo item.",
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
          "description": "New status, e.g. 'in_progress' or 'done'.",
          "type": "string"
        },
        "item": {
          "description": "New description text for the todo.",
          "type": "string"
        },
        "notes": {
          "description": "Notes to set on the todo.",
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
    "description": "Terminate or stop the specified agent session. Use this function to stop an agent safely.",
    "name": "agent_kill",
    "parameters": {
      "properties": {
        "index": {
          "description": "The index of the agent session to terminate.",
          "type": "integer"
        }
      },
      "required": [
        "index"
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
    "description": "Retrieve or stream the logfile for the specified agent session. Use this to obtain logs produced by agents for debugging or auditing.",
    "name": "agent_logfile",
    "parameters": {
      "properties": {
        "index": {
          "description": "The index of the agent logfile to retrieve.",
          "type": "integer"
        }
      },
      "required": [
        "index"
      ],
      "type": "object"
    }
  },
  {
    "description": "Send a text message to the specified agent session. Use this function to provide input or commands to an active agent.",
    "name": "agent_send",
    "parameters": {
      "properties": {
        "index": {
          "description": "The index of the agent session to send the message to.",
          "type": "integer"
        },
        "text": {
          "description": "The text message or command to send to the agent.",
          "type": "string"
        }
      },
      "required": [
        "index",
        "text"
      ],
      "type": "object"
    }
  }
]
