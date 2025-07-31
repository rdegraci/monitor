
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
            logger.warning("Tool '%s' already exists and cannot be added again.", tool_name)
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
        logger.warning("Attempted to remove unknown tool: %s", tool_name)
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
    Adds Anthropic-specific properties to the last dictionary in the provided list.
    
    Args:
        function_array (list): List of dictionaries containing function definitions
        
    Returns:
        list: Modified list with Anthropic properties added to the last dictionary
    """
    if not function_array or not isinstance(function_array, list):
        return function_array
        
    if function_array and isinstance(function_array[-1], dict):
        function_array[-1]["cache_control"] = {"type": "ephemeral"}
    
    return function_array

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
        logger.warning("Memory Tools not available. No MEMORY_SERVICES.")
        return 

    add_tool(
        tool_descriptions,
        gemini_tool_descriptions,
        tool_state,
        {
            "type": "function",
            "function": {
                "name": "save_to_memory",
                "description": "Save a value in Redis under the specified key. Optionally applies a Time-To-Live (TTL) to the key-value pair.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "The Redis key under which the value is stored."},
                        "value": {"type": "string", "description": "The value to be stored."},
                        "ttl": {"type": "integer", "description": "Optional time in seconds after which the key should expire. A minimum ttl value would be 900 for short term memory and a maximum value of 1800 for long term memory."}
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
                "description": "Retrieve a value from Redis based on the specified key.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "The Redis key from which to retrieve the value."}
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
                "description": "Save a new entry of user input and corresponding system response to Redis.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_input": {"type": "string", "description": "The user's input to be stored."},
                        "response": {"type": "string", "description": "The system's response to be stored."}
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
                "description": "Fetch all keys from Redis matching conversation:* and return them as a JSON array of strings.",
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
                "description": "Delete a value from Redis-based memory by specifying the key. Useful for forgetting facts, preferences, or conversation memory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "The key for the memory entry to delete (with or without the 'conversation:' prefix, e.g. 'favorite_color' or 'conversation:favorite_color')."
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

def add_text_file_editor_tools(tool_descriptions: List[Dict[str, Any]], gemini_tool_descriptions: List[Dict[str, Any]], tool_state: Dict[str, bool]):
    """
    Claude can use an Anthropic-defined text editor tool to view and modify text files, 
    helping you debug, fix, and improve your code or other text documents. This allows 
    Claude to directly interact with your files, providing hands-on assistance 
    rather than just suggesting changes.
    Note: These are Text editor tools for Claude 4
    """
    if "anthropic/claude-sonnet-4-20250514" in config.MODEL:
        add_tool(
            tool_descriptions,
            gemini_tool_descriptions,
            tool_state,
            {
                "type": "function",
                "function": {
                    "name": "str_replace_based_edit_tool",
                    "description": "Anthropic-defined text editor tool",
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                }
            }
        )
    
    if "anthropic/claude-3-7-sonnet-20250219" in config.MODEL:
        add_tool(
            tool_descriptions,
            gemini_tool_descriptions,
            tool_state,
            {
                "type": "function",
                "function": {
                    "name": "str_replace_editor",
                    "description": "Anthropic-defined text editor tool",
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
                "name": "text_file_or_directory_view",
                "description": "View the contents of a file with optional line range or list the contents of a directory. When viewing files, supports syntax highlighting and line numbers. When viewing directories, lists all contained files and subdirectories.",
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
                "description": "Create a new file with the specified content. Will fail if the file already exists.",
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
                "description": "Replace a specific string in a file with new content. The old string must match exactly including whitespace and newlines.",
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
                            "description": " The new text to insert in place of the old text."
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
                "description": "Insert text at a specific location in a file.",
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
                            "description": "The line number after which to insert the text (0 for beginning of file).",
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

def remove_text_file_editor_tools(tool_descriptions: List[Dict[str, Any]], tool_state: Dict[str, bool]):
    if "anthropic/claude-sonnet-4-20250514" in config.MODEL:
        remove_tool(tool_descriptions, tool_state, 'str_replace_based_edit_tool')
    if "anthropic/claude-3-7-sonnet-20250219" in config.MODEL:
        remove_tool(tool_descriptions, tool_state, 'str_replace_editor')
    remove_tool(tool_descriptions, tool_state, 'text_file_or_directory_view')
    remove_tool(tool_descriptions, tool_state, 'text_file_create')
    remove_tool(tool_descriptions, tool_state, 'text_file_str_replace_in_file')
    remove_tool(tool_descriptions, tool_state, 'text_file_insert_text_at_line')

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
    
