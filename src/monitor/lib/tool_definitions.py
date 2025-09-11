from monitor import config

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
from monitor.lib.os import (
    list_directory_contents,
    cat_file,
    create_file,
    file_type,
    make_directory
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
from monitor.lib.todo import add_todo, list_todos, update_todo, clear_todos

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
    "list_directory_contents": list_directory_contents,
    "cat_file": cat_file,
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
    "text_file_or_directory_view": text_file_or_directory_view,
    "text_file_create": text_file_create,
    "text_file_str_replace_in_file": text_file_str_replace_in_file,
    "text_file_insert_text_at_line": text_file_insert_text_at_line,
    "add_todo": add_todo,
    "list_todos": list_todos,
    "update_todo": update_todo,
    "clear_todos": clear_todos,
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
            "description": "Display the contents of a file at the given path. Use this function when you need to know or examine the contents of a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The path to the file to display"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_type",
            "description": "Provides the file type of a given file at the specified path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The path to the file to check"
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
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    }
                },
                "required": ["query"]
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
                        "description": "The search term to look for. Note is a string search, do not treat it as a Regex."
                    },
                    "filetype": {
                        "type": "string",
                        "description": "Optional ripgrep type (e.g., 'py', 'js') to limit the search scope."
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
            "description": "Add a new todo item to the list for the given session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "The session identifier."},
                    "item": {"type": "string", "description": "The todo item description."},
                    "priority": {"type": "integer", "description": "Optional priority (higher number = higher priority).", "default": 0},
                    "notes": {"type": "string", "description": "Notes for the todo item."}
                },
                "required": ["session_id", "item", "priority", "notes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_todos",
            "description": "Retrieve the current todo list for the given session as a JSON array of items including a 'notes' field.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "The session identifier."}
                },
                "required": ["session_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_todo",
            "description": "Update the status of a todo item at the given index for the session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "The session identifier."},
                    "index": {"type": "integer", "description": "The index of the todo item to update (0-based)."},
                    "status": {"type": "string", "description": "The new status (e.g., 'done', 'in_progress').", "default": "done"},
                    "notes": {"type": "string", "description": "Optional notes to update for the todo item."}
                },
                "required": ["session_id", "index", "status", "notes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clear_todos",
            "description": "Clear the todo list for the given session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "The session identifier."}
                },
                "required": ["session_id"]
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
    "description": "Display the contents of a file at the given path. Use this function when you need to know or examine the contents of a file.",
    "name": "cat_file",
    "parameters": {
      "properties": {
        "path": {
          "description": "The path to the file to display",
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
    "description": "Searches for a term across files within the repository using ripgrep. Useful for quickly locating occurrences of a string or pattern in code or text files.",
    "name": "ripgrep_search_tool",
    "parameters": {
      "type": "object",
      "properties": {
        "term": {
          "type": "string",
          "description": "The search term to look for. Note is a string search, do not treat it as a Regex."
        },
        "filetype": {
          "type": "string",
          "description": "Optional ripgrep type (e.g., 'py', 'js') to limit the search scope."
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
    "description": "Add a new todo item to the list for the given session.",
    "name": "add_todo",
    "parameters": {
      "properties": {
        "session_id": {
          "description": "The session identifier.",
          "type": "string"
        },
        "item": {
          "description": "The todo item description.",
          "type": "string"
        },
        "priority": {
          "description": "Optional priority (higher number = higher priority).",
          "type": "integer",
          "default": 0
        },
        "notes": {
          "description": "Notes for the todo item.",
          "type": "string"
        }
      },
      "required": [
        "session_id",
        "item",
        "priority",
        "notes"
      ],
      "type": "object"
    }
  },
  {
    "description": "Retrieve the current todo list for the given session as a JSON array of items including a 'notes' field.",
    "name": "list_todos",
    "parameters": {
      "properties": {
        "session_id": {
          "description": "The session identifier.",
          "type": "string"
        }
      },
      "required": [
        "session_id"
      ],
      "type": "object"
    }
  },
  {
    "description": "Update the status of a todo item at the given index for the session.",
    "name": "update_todo",
    "parameters": {
      "properties": {
        "session_id": {
          "description": "The session identifier.",
          "type": "string"
        },
        "index": {
          "description": "The index of the todo item to update (0-based).",
          "type": "integer"
        },
        "status": {
          "description": "The new status (e.g., 'done', 'in_progress').",
          "type": "string",
          "default": "done"
        },
        "notes": {
          "description": "Optional notes to update for the todo item.",
          "type": "string"
        }
      },
      "required": [
        "session_id",
        "index",
        "status",
        "notes"
      ],
      "type": "object"
    }
  },
  {
    "description": "Clear the todo list for the given session.",
    "name": "clear_todos",
    "parameters": {
      "properties": {
        "session_id": {
          "description": "The session identifier.",
          "type": "string"
        }
      },
      "required": [
        "session_id"
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
  }
]
