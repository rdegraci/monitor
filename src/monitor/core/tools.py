from monitor import config 

import logging
logger = logging.getLogger(__name__)

from monitor.lib.tool_loading import add_weather_tools, add_memory_tools, add_text_file_editor_tools, get_first_segment, remove_openai_editor_tools
from monitor.lib.tool_definitions import TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, TOOL_STATE

add_weather_tools(TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, TOOL_STATE)
add_memory_tools(TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, TOOL_STATE)

if get_first_segment(config.MODEL) == 'anthropic':
    add_text_file_editor_tools(TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, TOOL_STATE)
    remove_openai_editor_tools(TOOL_DESCRIPTIONS, TOOL_STATE)
for tool in TOOL_DESCRIPTIONS:
    function = tool.get('function')
    tool_name = function.get('name') if function else None
    if tool_name:
        TOOL_STATE[tool_name] = True
    else:
        logger.warning("Unable to get tool_name")
