
from monitor import config

from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

def get_active_tools(tool_descriptions: List[Dict[str, Any]], tool_state: Dict[str, bool]) -> List[Dict[str, Any]]:
    """
    Returns only the active tool descriptions.
    
    Args:
        tool_descriptions (List[Dict[str, Any]]): List of tool descriptions
        tool_state (Dict[str, bool]): Dictionary indicating activation state of tools
    
    Returns:
        List[Dict[str, Any]]: List of active tool descriptions
    """
    return [tool for tool in tool_descriptions if tool_state.get(tool['function']['name'], True)]

def disable_tools(tool_state: Dict[str, bool], tool_names: List[str]) -> Dict[str, bool]:
    """
    Disable specified tools by name.
    
    Args:
        tool_state (Dict[str, bool]): The tool state dictionary
        tool_names (List[str]): List of tool names to disable
        
    Returns:
        Dict[str, bool]: Dictionary of tool names and their disabled status
    """
    results = {}
    for name in tool_names:
        if name in tool_state:
            tool_state[name] = False
            results[name] = True
        else:
            results[name] = False
    return results

def enable_tools(tool_state: Dict[str, bool], tool_names: List[str]) -> Dict[str, bool]:
    """
    Enable specified tools by name.
    
    Args:
        tool_state (Dict[str, bool]): The tool state dictionary
        tool_names (List[str]): List of tool names to enable
        
    Returns:
        Dict[str, bool]: Dictionary of tool names and their enabled status
    """
    results = {}
    for name in tool_names:
        if name in tool_state:
            tool_state[name] = True
            results[name] = True
        else:
            results[name] = False
    return results

def list_tools(tool_descriptions: List[Dict[str, Any]], tool_state: Dict[str, bool], show_state: bool = True) -> Dict[str, Any]:
    """
    List all available tools and optionally their current state.
    
    Args:
        tool_descriptions (List[Dict[str, Any]]): List of tool descriptions
        tool_state (Dict[str, bool]): Dict mapping tool names to their active/inactive state
        show_state (bool): If True, includes the current state of each tool
        
    Returns:
        Dict[str, Any]: Dictionary containing tool information
    """
    tools_info = {}
    for tool in tool_descriptions:
        name = tool['function']['name']
        info = {
            'description': tool['function']['description'],
            'parameters': tool['function']['parameters']
        }
        if show_state:
            info['active'] = tool_state.get(name, True)
        tools_info[name] = info
    return tools_info

def add_tool(tool_descriptions: List[Dict[str, Any]], gemini_tool_descriptions: List[Dict[str, Any]], tool_state: Dict[str, bool], tool_definition: Dict[str, Any]) -> bool:
    """
    Add a new tool definition to the available tools.
    
    Args:
        tool_descriptions (List[Dict[str, Any]]): List of tool descriptions
        gemini_tool_descriptions (List[Dict[str, Any]]): List of gemini tool descriptions
        tool_state (Dict[str, bool]): Tool state dictionary
        tool_definition (Dict[str, Any]): Tool definition following the standard format
        
    Returns:
        bool: True if tool was added successfully, False otherwise
    """
    try:
        # Validate tool definition structure
        if not all(key in tool_definition for key in ['type', 'function']):
            logger.warning("Tool definition missing required keys: %s", tool_definition)
            return False
        if not all(key in tool_definition['function'] for key in ['name', 'description', 'parameters']):
            logger.warning("Tool 'function' missing required keys: %s", tool_definition)
            return False
            
        # Check if tool already exists
        tool_name = tool_definition['function']['name']
        if any(tool['function']['name'] == tool_name for tool in tool_descriptions):
            logger.info("Tool '%s' already exists and cannot be added again. (This may be normal behavior)", tool_name)
            return False
            
        # Add the tool
        tool_descriptions.append(tool_definition)
        gemini_tool_descriptions.append(tool_definition)
        tool_state[tool_name] = True
        return True
    except Exception as exc:
        logger.error("Exception occurred in add_tool(%s): %s", tool_definition, exc, exc_info=True)
        return False

def remove_tool(tool_descriptions: List[Dict[str, Any]], tool_state: Dict[str, bool], tool_name: str) -> bool:
    """
    Remove a tool definition from the available tools.
    
    Args:
        tool_descriptions (List[Dict[str, Any]]): List of tool descriptions
        tool_state (Dict[str, bool]): Dictionary mapping tool names to state
        tool_name (str): Name of the tool to remove
        
    Returns:
        bool: True if tool was removed successfully, False otherwise
    """
    try:
        # Find and remove the tool
        for i, tool in enumerate(tool_descriptions):
            if tool['function']['name'] == tool_name:
                tool_descriptions.pop(i)
                tool_state.pop(tool_name, None)
                return True
        logger.info("Attempted to remove unknown tool: %s (this may be normal behavior)", tool_name)
        return False
    except Exception as exc:
        logger.error("Exception occurred in remove_tool(%s): %s", tool_name, exc, exc_info=True)
        return False

def inject_openai_properties(function_array: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Create OpenAI-compatible function descriptions by injecting required properties.
    
    Args:
        function_array: List of function descriptions in Anthropic format
        
    Returns:
        List of function descriptions with OpenAI-specific properties added
        
    Example:
        >>> openai_functions = inject_openai_properties(function_array)
        >>> openai_client.chat.completions.create(
        ...     model="gpt-4",
        ...     messages=[...],
        ...     functions=openai_functions
        ... )
    """
    openai_descriptions = []
    
    for desc in function_array:
        desc_copy = desc.copy()
        
        if "function" in desc_copy:
            desc_copy["function"] = desc_copy["function"].copy()
            desc_copy["function"]["strict"] = True
            desc_copy["function"]["parameters"] = desc_copy["function"]["parameters"].copy()
            desc_copy["function"]["parameters"]["additionalProperties"] = False
            
        openai_descriptions.append(desc_copy)
    
    return openai_descriptions

def inject_anthropic_properties(function_array: list) -> list:
    """
    Return a copy of ``function_array`` adapted for Anthropic's API:

    1. Flatten Anthropic-native tools (any entry whose ``type`` isn't
       ``"function"``) from the LiteLLM/OpenAI nested ``{type, function: {name,
       description, parameters}}`` shape into the flat ``{type, name}`` shape
       Anthropic expects. Without this Anthropic rejects native tools with
       ``tools.N.<type>.function: Extra inputs are not permitted``.
    2. Add ``cache_control`` to the last entry as an Anthropic prompt-cache
       breakpoint.

    C-1: previously this function mutated ``function_array`` and its last
    dict in place. Because the caller (``function_descriptions``) passes the
    module-global ``TOOL_DESCRIPTIONS`` by reference, that global was
    permanently polluted with a ``cache_control`` key on its last entry
    after any Anthropic call. After a model switch to OpenAI/Gemini/xAI,
    the key remained — mostly harmless (providers ignore extra keys) but
    state pollution that violates the harness's "configure-style functions
    must be idempotent and side-effect-free on shared state" invariant.
    The copy-first pattern is preserved below.

    Args:
        function_array (list): List of dictionaries containing function definitions

    Returns:
        list: Copy of ``function_array`` with native tools flattened and
        ``cache_control`` added to the final entry.
    """
    if not function_array or not isinstance(function_array, list):
        return function_array

    transformed = []
    for tool in function_array:
        if not isinstance(tool, dict):
            transformed.append(tool)
            continue
        tool_type = tool.get("type")
        if tool_type and tool_type != "function":
            # Anthropic-native protocol tool (e.g. text_editor_20250728);
            # strip the LiteLLM/OpenAI nesting and keep only {type, name}.
            fn = tool.get("function")
            name = fn.get("name") if isinstance(fn, dict) else None
            if name:
                transformed.append({"type": tool_type, "name": name})
            else:
                # Malformed native entry — let it through so the API failure
                # is loud and diagnosable rather than silently swallowed.
                transformed.append(tool)
        else:
            transformed.append(tool)

    if not transformed or not isinstance(transformed[-1], dict):
        return transformed

    last_copy = dict(transformed[-1])
    last_copy["cache_control"] = {"type": "ephemeral"}
    transformed[-1] = last_copy
    return transformed

def get_first_segment(model_string: str) -> str:
    """
    Takes a model string with segments separated by '/' and returns the first segment.
    
    Args:
        model_string (str): String containing segments separated by '/'
        
    Returns:
        str: First segment of the string before the first '/'
        
    Example:
        >>> get_first_segment("anthropic/claude-3-5-sonnet-20241022")
        'anthropic'
    """
    if not model_string:
        return ""
        
    segments = model_string.split('/')
    return segments[0] if segments else ""


def add_weather_tools(tool_descriptions: List[Dict[str, Any]], gemini_tool_descriptions: List[Dict[str, Any]], tool_state: Dict[str, bool]):
    add_tool(
        tool_descriptions,
        gemini_tool_descriptions,
        tool_state,
        {
            "type": "function",
            "function": {
                "name": "get_current_weather",
                "description": "Get the current weather in a given location",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "The city and state, e.g. San Francisco, CA"
                        },
                        "unit": {
                            "type": "string",
                            "enum": ["celsius", "fahrenheit"]
                        }
                    },
                    "required": ["location", "unit"]
                }
            }
        }
    )

def remove_weather_tools(tool_descriptions: List[Dict[str, Any]], tool_state: Dict[str, bool]):
    remove_tool(tool_descriptions, tool_state, "get_current_weather")
    
def add_memory_tools(tool_descriptions: List[Dict[str, Any]], gemini_tool_descriptions: List[Dict[str, Any]], tool_state: Dict[str, bool]):
    if not config.MEMORY_SERVICES:
        logger.info("Memory Tools not available. No MEMORY_SERVICES.")
        return 

    add_tool(
        tool_descriptions,
        gemini_tool_descriptions,
        tool_state,
        {
            "type": "function",
            "function": {
                "name": "save_to_memory",
                "description": "DEPRECATED — prefer update_memory. Save a value under the given key for later recall in this session.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Short descriptive key to store the value under."},
                        "value": {"type": "string", "description": "The value to remember."},
                        "ttl": {"type": "integer", "description": "How long to remember it, in seconds. ~900 (15 min) for short-term, up to ~1800 (30 min) for longer-lived facts."}
                    },
                    "required": ["key", "value", "ttl"]
                }
            }
        }
    )

    add_tool(
        tool_descriptions,
        gemini_tool_descriptions,
        tool_state,
        {
            "type": "function",
            "function": {
                "name": "read_from_memory",
                "description": "Recall a previously remembered fact by its key. Use to look up something stored earlier in this session via update_memory (or save_to_memory) — e.g. a user-stated preference, a project fact, or context from an earlier turn. The 'conversation:' namespace prefix is handled automatically.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "The key the value was remembered under."}
                    },
                    "required": ["key"]
                }
            }
        }
    )

    add_tool(
        tool_descriptions,
        gemini_tool_descriptions,
        tool_state,
        {
            "type": "function",
            "function": {
                "name": "update_memory",
                "description": "Remember an exchange so it can be recalled later in this session (canonical 'remember this' tool — prefer this over save_to_memory). Use when the user asks you to remember something, or when a fact stated in this turn (a preference, a project detail, context) will likely matter later but won't naturally be carried in the conversation history. Pass the user's statement as user_input and your acknowledgement/response as response; the key is derived automatically.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_input": {"type": "string", "description": "The user's statement — the thing being remembered (e.g. 'I prefer Swift over Python')."},
                        "response": {"type": "string", "description": "Your acknowledgement or how you'll act on it (e.g. 'Noted — I'll default to Swift examples')."}
                    },
                    "required": ["user_input", "response"]
                }
            }
        }
    )

    add_tool(
        tool_descriptions,
        gemini_tool_descriptions,
        tool_state,
        {
            "type": "function",
            "function": {
                "name": "fetch_memory_keys_as_json",
                "description": "List the keys of everything remembered so far in this session, as a JSON array. Use when you need to enumerate what the user has asked you to remember — e.g. to answer 'what do you remember about me?' or to find a stored key without recalling its value.",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        }
    )

    add_tool(
        tool_descriptions,
        gemini_tool_descriptions,
        tool_state,
        {
            "type": "function",
            "function": {
                "name": "delete_from_memory",
                "description": "Forget a previously remembered fact by its key. Use when the user asks you to forget something they earlier asked you to remember, or when a stored fact has become stale or wrong. The 'conversation:' prefix is handled automatically.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "The key of the memory to forget (e.g. 'favorite_color')."
                        }
                    },
                    "required": ["key"]
                }
            }
        }
    )

def remove_memory_tools(tool_descriptions: List[Dict[str, Any]], tool_state: Dict[str, bool]):
    remove_tool(tool_descriptions, tool_state, "fetch_memory_keys_as_json")
    remove_tool(tool_descriptions, tool_state, "update_memory")
    remove_tool(tool_descriptions, tool_state, "read_from_memory")
    remove_tool(tool_descriptions, tool_state, "save_to_memory")
    remove_tool(tool_descriptions, tool_state, "delete_from_memory")

def add_db_tools(tool_descriptions: List[Dict[str, Any]], gemini_tool_descriptions: List[Dict[str, Any]], tool_state: Dict[str, bool]):
    add_tool(
        tool_descriptions,
        gemini_tool_descriptions,
        tool_state,
        {
            "type": "function",
            "function": {
                "name": "execute_duckdb",
                "description": "Execute a SQL command in DuckDB and return the result",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The SQL command to execute inside DuckDB"
                        }
                    },
                    "required": ["command"]
                }
            }
        }
    )

    add_tool(
        tool_descriptions,
        gemini_tool_descriptions,
        tool_state,
        {
            "type": "function",
            "function": {
                "name": "execute_psql",
                "description": "Execute a command in psql, the PostgreSQL command-line interface",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The command to run inside of psql"
                        }
                    },
                    "required": ["command"]
                }
            }
        }
    )

    add_tool(
        tool_descriptions,
        gemini_tool_descriptions,
        tool_state,
        {
            "type": "function",
            "function": {
                "name": "execute_mc",
                "description": "Execute a command in mc, the MinIO command-line tool and return the result",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The mc command to execute, including any necessary arguments"
                        }
                    },
                    "required": ["command"]
                }
            }
        }
    )

def remove_db_tools(tool_descriptions: List[Dict[str, Any]], tool_state: Dict[str, bool]):
    remove_tool(tool_descriptions, tool_state, "execute_mc")
    remove_tool(tool_descriptions, tool_state, "execute_psql")
    remove_tool(tool_descriptions, tool_state, "execute_duckdb")


def add_modelling_tools(tool_descriptions: List[Dict[str, Any]], gemini_tool_descriptions: List[Dict[str, Any]], tool_state: Dict[str, bool]):
    add_tool(
        tool_descriptions,
        gemini_tool_descriptions,
        tool_state,
        {
            "type": "function",
            "function": {
                "name": "train_model",
                "description": "Train a machine learning model using specified parameters.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Path to the CSV file containing training data."
                        },
                        "model_type": {
                            "type": "string",
                            "enum": ["random_forest"],
                            "description": "Type of model to train."
                        },
                        "target_column": {
                            "type": "string",
                            "description": "The column name of target variable."
                        }
                    },
                    "required": ["file_path", "model_type", "target_column"]
                }
            }
        }
    )

    add_tool(
        tool_descriptions,
        gemini_tool_descriptions,
        tool_state,
        {
            "type": "function",
            "function": {
                "name": "evaluate_model",
                "description": "Evaluate a trained machine learning model and calculate Mean Squared Error.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "model": {
                            "type": "string",
                            "description": "Identifier for the trained model with a predict method."
                        },
                        "test_data": {
                            "type": "array",
                            "items": {
                                "type": "array",
                                "items": {
                                    "type": "number"
                                }
                            },
                            "description": "An array containing two arrays: the first is the feature dataset (X_test), and the second is the true target values (y_test) for evaluation."
                        }
                    },
                    "required": ["model", "test_data"]
                }
            }
        }
    )

    add_tool(
        tool_descriptions,
        gemini_tool_descriptions,
        tool_state,
        {
            "type": "function",
            "function": {
                "name": "deploy_model",
                "description": "Deploy a machine learning model to a specified platform as a web service.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "model_path": {
                            "type": "string",
                            "description": "Path to the serialized model file."
                        },
                        "endpoint_url": {
                            "type": "string",
                            "description": "Endpoint URL for deployment."
                        },
                        "deployment_platform": {
                            "type": "string",
                            "description": "Platform to deploy model, e.g., AWS, GCP, Azure."
                        }
                    },
                    "required": ["model_path", "endpoint_url", "deployment_platform"]
                }
            }
        }
    )

    add_tool(
        tool_descriptions,
        gemini_tool_descriptions,
        tool_state,
        {
            "type": "function",
            "function": {
                "name": "monitor_model_performance",
                "description": "Monitor the performance of a deployed model by tracking specified metrics.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "endpoint_url": {
                            "type": "string",
                            "description": "Endpoint URL for the deployed model."
                        },
                        "metrics_to_track": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of performance metrics to monitor."
                        }
                    },
                    "required": ["endpoint_url", "metrics_to_track"]
                }
            }
        }
    )

def remove_modelling_tools(tool_descriptions: List[Dict[str, Any]], tool_state: Dict[str, bool]):
    remove_tool(tool_descriptions, tool_state, 'train_model')
    remove_tool(tool_descriptions, tool_state, 'evaluate_model')
    remove_tool(tool_descriptions, tool_state, 'deploy_model')
    remove_tool(tool_descriptions, tool_state, 'monitor_model_performance')

def add_text_file_neutral_tools(tool_descriptions: List[Dict[str, Any]], gemini_tool_descriptions: List[Dict[str, Any]], tool_state: Dict[str, bool]):
    """Add the provider-neutral surgical text-edit tools.

    These four tools are plain local Python functions (no Anthropic-specific
    server-side semantics). They can be exposed to any provider — descriptions
    are written so the model prefers them over the slower, less-predictable
    natural-language ``modify_source_code`` fallback whenever the edit can be
    expressed as exact text.
    """
    add_tool(
        tool_descriptions,
        gemini_tool_descriptions,
        tool_state,
        {
            "type": "function",
            "function": {
                "name": "text_file_or_directory_view",
                "description": "View the contents of a file (with optional line range) or list the contents of a directory. Use for inspecting code before editing it. File output includes syntax highlighting and line numbers; directory output lists files and subdirectories.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "enum": ["view"],
                            "description": "The command type - must be 'view'"
                        },
                        "path": {
                            "type": "string",
                            "description": "The path to the file or directory to view"
                        },
                        "view_range": {
                            "type": "array",
                            "items": {
                                "type": "integer"
                            },
                            "minItems": 2,
                            "maxItems": 2,
                            "description": "Optional array of two integers [start_line, end_line] specifying the line range to view. Line numbers are 1-indexed. Use -1 for end_line to read to the end of the file. Only applies when viewing files, not directories.",
                            "default": None
                        }
                    },
                    "required": ["command", "path"],
                    "additionalProperties": False
                }
            }
        }
    )

    add_tool(
        tool_descriptions,
        gemini_tool_descriptions,
        tool_state,
        {
            "type": "function",
            "function": {
                "name": "text_file_create",
                "description": "Create a new file with the specified content. Fails if the file already exists. Parent directories are created automatically if missing. PREFER this over modify_source_code when you're creating a file from scratch with known content — it's deterministic, faster, and avoids invoking a secondary model.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "enum": ["create"],
                            "description": "The command type - must be 'create'"
                        },
                        "path": {
                            "type": "string",
                            "description": "The path where the new file should be created."
                        },
                        "content": {
                            "type": "string",
                            "description": "The content to write to the new file."
                        }
                    },
                    "required": ["path", "content"],
                    "additionalProperties": False
                }
            }
        }
    )

    add_tool(
        tool_descriptions,
        gemini_tool_descriptions,
        tool_state,
        {
            "type": "function",
            "function": {
                "name": "text_file_str_replace_in_file",
                "description": "Replace an exact string in a file with new content. The old_str must match exactly (whitespace, indentation, and newlines included) AND must match exactly once — the call fails on zero matches or multiple matches. If the snippet you want to change appears in more than one place, include surrounding context in old_str so the match is unique. PREFER this over modify_source_code for any precise edit where you know the exact text to change — it's deterministic, fast, and reviewable. Use modify_source_code only when the change genuinely can't be expressed as exact text replacement.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "enum": ["str_replace"],
                            "description": "The command type - must be 'str_replace'"
                        },
                        "path": {
                            "type": "string",
                            "description": "The path to the file to modify."
                        },
                        "old_str": {
                            "type": "string",
                            "description": "The exact string to find and replace. Must match exactly including all whitespace and indentation."
                        },
                        "new_str": {
                            "type": "string",
                            "description": "The new text to insert in place of the old text."
                        }
                    },
                    "required": ["path", "old_str", "new_str"],
                    "additionalProperties": False
                }
            }
        }
    )

    add_tool(
        tool_descriptions,
        gemini_tool_descriptions,
        tool_state,
        {
            "type": "function",
            "function": {
                "name": "text_file_insert_text_at_line",
                "description": "Insert new text at a specific line in a file. The text is inserted BEFORE the given 1-based line number — insert_line=1 inserts at the top of the file; insert_line=N+1 (where N is the file's current line count) appends to the end. PREFER this over modify_source_code for additions where you know exactly where to insert. Use modify_source_code only when the placement is genuinely fuzzy (e.g. 'add validation somewhere appropriate').",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "enum": ["insert"],
                            "description": "The command type - must be 'insert'"
                        },
                        "path": {
                            "type": "string",
                            "description": "The path to the file to modify."
                        },
                        "insert_line": {
                            "type": "integer",
                            "description": "The 1-based line number BEFORE which to insert the new text. Use 1 to insert at the top; use (current line count + 1) to append at the end.",
                            "minimum": 1
                        },
                        "new_str": {
                            "type": "string",
                            "description": "The text to insert."
                        }
                    },
                    "required": ["path", "insert_line", "new_str"],
                    "additionalProperties": False
                }
            }
        }
    )


# Anthropic releases ship distinct native editor tool names per model. Each
# entry maps a model-string fragment to the native tool the matching model
# expects. configure_tools uses these to decide between native and the
# provider-neutral surgical fallback.
# Each entry maps a model-string fragment to (tool_type, tool_name) for the
# Anthropic-native editor tool that release expects. ``tool_type`` is the
# Anthropic API protocol version (e.g. "text_editor_20250728"); ``tool_name``
# is the public function name the model emits in its tool calls. Multiple
# releases can share a name (e.g. "str_replace_based_edit_tool" used across
# several editor protocol versions).
_ANTHROPIC_NATIVE_GATES = (
    # (model substring, tool_type, tool_name)
    ("anthropic/claude-sonnet-4-20250514", "function", "str_replace_based_edit_tool"),
    ("anthropic/claude-3-7-sonnet-20250219", "function", "str_replace_editor"),
    ("anthropic/claude-opus-4-7", "text_editor_20250728", "str_replace_based_edit_tool"),
    ("anthropic/claude-sonnet-4-6", "text_editor_20250728", "str_replace_based_edit_tool"),
)


def add_anthropic_native_editor_tools(tool_descriptions: List[Dict[str, Any]], gemini_tool_descriptions: List[Dict[str, Any]], tool_state: Dict[str, bool]) -> bool:
    """Register Anthropic-native editor tool declarations for the matching model.

    Returns True if any native tool was added (i.e., the current ``config.MODEL``
    matches one of the gates), False otherwise. Callers use the return value to
    decide whether to fall back to the surgical text_file_* tools.
    """
    added_any = False
    for gate, tool_type, tool_name in _ANTHROPIC_NATIVE_GATES:
        if gate in (config.MODEL or ""):
            add_tool(
                tool_descriptions,
                gemini_tool_descriptions,
                tool_state,
                {
                    "type": tool_type,
                    "function": {
                        "name": tool_name,
                        "description": "Anthropic-defined text editor tool",
                        "parameters": {
                            "type": "object",
                            "properties": {}
                        }
                    }
                }
            )
            added_any = True
    return added_any


def remove_anthropic_native_editor_tools(tool_descriptions: List[Dict[str, Any]], tool_state: Dict[str, bool]):
    """Unconditionally remove all Anthropic-native editor declarations.

    Used by non-Anthropic provider branches AND by the anthropic branch as a
    strip-then-add step, so a runtime ``:model`` switch between two Anthropic
    models that share a tool name but differ in ``type`` (e.g. Sonnet 4
    "function" vs Opus 4.7 "text_editor_20250728") refreshes cleanly. Tool
    names are deduplicated because multiple gates can share a name.
    """
    for tool_name in {name for _, _, name in _ANTHROPIC_NATIVE_GATES}:
        remove_tool(tool_descriptions, tool_state, tool_name)


def remove_text_file_neutral_tools(tool_descriptions: List[Dict[str, Any]], tool_state: Dict[str, bool]):
    """Unconditionally remove the provider-neutral surgical text-file tools."""
    for name in (
        "text_file_or_directory_view",
        "text_file_create",
        "text_file_str_replace_in_file",
        "text_file_insert_text_at_line",
    ):
        remove_tool(tool_descriptions, tool_state, name)


def add_text_file_editor_tools(tool_descriptions: List[Dict[str, Any]], gemini_tool_descriptions: List[Dict[str, Any]], tool_state: Dict[str, bool]):
    """Backwards-compatible: register Anthropic-native (if matching) + neutral surgical."""
    add_anthropic_native_editor_tools(tool_descriptions, gemini_tool_descriptions, tool_state)
    add_text_file_neutral_tools(tool_descriptions, gemini_tool_descriptions, tool_state)


def remove_text_file_editor_tools(tool_descriptions: List[Dict[str, Any]], tool_state: Dict[str, bool]):
    """Backwards-compatible: remove Anthropic-native + neutral surgical."""
    remove_anthropic_native_editor_tools(tool_descriptions, tool_state)
    remove_text_file_neutral_tools(tool_descriptions, tool_state)

def remove_openai_editor_tools(tool_descriptions: List[Dict[str, Any]], tool_state: Dict[str, bool]):
    remove_tool(tool_descriptions, tool_state, 'modify_source_code')

def add_openai_editor_tools(tool_descriptions: List[Dict[str, Any]], gemini_tool_descriptions: List[Dict[str, Any]], tool_state: Dict[str, bool]):
    add_tool(
        tool_descriptions,
        gemini_tool_descriptions,
        tool_state,
        {
          "type": "function",
          "function": {
            "name": "modify_source_code",
            "description": (
                "Edit a source file via a natural-language modification_request. **Fallback tool.** "
                "Use ONLY when the change genuinely can't be expressed as exact text edits — e.g. fuzzy "
                "intent like 'make this idiomatic', or sweeping refactors across many sites in one pass. "
                "For precise edits where you know the target text, PREFER the surgical "
                "text_file_str_replace_in_file / text_file_insert_text_at_line / text_file_create tools: "
                "they are deterministic, faster, reviewable, and don't invoke a second LLM. "
                "If the file exists at source_file, it is modified in place; if it does not exist, it is created. "
                "Edge case: if your modification_request itself asks to *create* a file at a path that already "
                "exists, no change is made and the existing file is preserved."
            ),
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
        }
    )


def function_descriptions(tool_descriptions: List[Dict[str, Any]], gemini_tool_descriptions: List[Dict[str, Any]], model):
    if get_first_segment(model) == 'anthropic':
        return inject_anthropic_properties(tool_descriptions)
    if get_first_segment(model) == 'openai':
        return inject_openai_properties(tool_descriptions)
    if get_first_segment(model) == 'gemini':
        return gemini_tool_descriptions
    if get_first_segment(model) == 'xai':
        return tool_descriptions

    logger.warning(f"Unknown model {model}. Falling back to default tool_descriptions.")
    return tool_descriptions
    
