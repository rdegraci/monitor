from monitor import config 

import logging
logger = logging.getLogger(__name__)

from monitor.lib.tool_loading import (
    add_weather_tools,
    add_memory_tools,
    add_text_file_editor_tools,
    add_text_file_neutral_tools,
    add_anthropic_native_editor_tools,
    remove_text_file_editor_tools,
    remove_text_file_neutral_tools,
    remove_anthropic_native_editor_tools,
    get_first_segment,
    remove_openai_editor_tools,
    add_openai_editor_tools,
)
from monitor.lib.tool_definitions import TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, TOOL_STATE

def configure_tools():
    add_weather_tools(TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, TOOL_STATE)

    # Wall sub-agents off from the shared Redis memory pool by default. The pool
    # is global (one keyspace, no session/project scoping), so a sub-agent with
    # memory tools could read the orchestrator's memories and write noise back
    # into the pool that later surfaces in the main session. Skip the tools when
    # running as a sub-agent unless SUBAGENT_MEMORY_SERVICES is explicitly on.
    # getattr default False means the gate holds even with the config commented
    # out. (The matching read/prepend path is gated in prepend_memory_to_history.)
    if config.AGENT and not getattr(config, "SUBAGENT_MEMORY_SERVICES", False):
        logger.info(
            "Sub-agent: memory tools gated off (SUBAGENT_MEMORY_SERVICES is off)."
        )
    else:
        add_memory_tools(TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, TOOL_STATE)

    # TC-3: dispatch on the model's provider prefix. Anthropic and openai
    # have incompatible editor-tool catalogs; Gemini uses GEMINI_TOOL_DESCRIPTIONS
    # separately and should not carry either provider's editor tools in
    # TOOL_DESCRIPTIONS. The previous code had only the anthropic and openai
    # branches as two independent `if` statements, so a switch to a Gemini
    # model (or an unrecognized provider) left whichever editor-tool set was
    # present beforehand, polluting the catalog.
    # get_first_segment handles None/empty model_string internally; call it
    # unconditionally so test mocks of get_first_segment are exercised.
    provider = get_first_segment(config.MODEL)
    if provider == 'anthropic':
        # Each Anthropic release ships a distinct native editor tool; if the
        # current model has a matching gate, use ONLY that native tool so the
        # model picks its trained-for protocol unambiguously. If no gate
        # matches (Opus, Haiku, or a newer release we haven't gated yet), fall
        # back to the provider-neutral surgical tools so the model still has
        # an editing pathway.
        #
        # Strip-then-add: two Anthropic releases can share a tool *name* but
        # differ in *type* (e.g. claude-sonnet-4 vs claude-opus-4-7 both name
        # "str_replace_based_edit_tool" but use different protocol types).
        # add_tool dedups by name, so a runtime :model switch between such
        # releases would otherwise keep the previous model's stale `type`.
        # Stripping first ensures the new tool's `type` lands cleanly.
        remove_anthropic_native_editor_tools(TOOL_DESCRIPTIONS, TOOL_STATE)
        has_native = add_anthropic_native_editor_tools(TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, TOOL_STATE)
        if has_native:
            remove_text_file_neutral_tools(TOOL_DESCRIPTIONS, TOOL_STATE)
        else:
            add_text_file_neutral_tools(TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, TOOL_STATE)
        remove_openai_editor_tools(TOOL_DESCRIPTIONS, TOOL_STATE)
    elif provider == 'openai':
        # OpenAI gets the provider-neutral surgical tools alongside
        # modify_source_code. Strip any leftover Anthropic-native declarations
        # so a runtime switch from an Anthropic model doesn't leave dangling
        # tool entries OpenAI's API would reject or ignore.
        add_text_file_neutral_tools(TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, TOOL_STATE)
        add_openai_editor_tools(TOOL_DESCRIPTIONS, GEMINI_TOOL_DESCRIPTIONS, TOOL_STATE)
        remove_anthropic_native_editor_tools(TOOL_DESCRIPTIONS, TOOL_STATE)
    elif provider == 'gemini':
        # Gemini relies on the parallel GEMINI_TOOL_DESCRIPTIONS catalog.
        # Strip both provider-specific editor sets from TOOL_DESCRIPTIONS
        # so neither anthropic-only nor openai-only editor tools leak through.
        remove_text_file_editor_tools(TOOL_DESCRIPTIONS, TOOL_STATE)
        remove_openai_editor_tools(TOOL_DESCRIPTIONS, TOOL_STATE)
    elif provider == 'xai':
        # xAI is OpenAI-API-compatible but function_descriptions returns
        # tool_descriptions unchanged for it — neither inject_anthropic_properties
        # nor inject_openai_properties is applied. Strip both provider-specific
        # editor sets so the catalog is neutral; Anthropic editor tools use
        # an Anthropic-specific schema that xAI rejects, and the OpenAI editor
        # tools aren't guaranteed to work cross-provider either.
        remove_text_file_editor_tools(TOOL_DESCRIPTIONS, TOOL_STATE)
        remove_openai_editor_tools(TOOL_DESCRIPTIONS, TOOL_STATE)
    else:
        logger.warning(
            "configure_tools: unrecognized provider prefix %r for MODEL=%r; "
            "leaving editor-tool catalog in its current state",
            provider, config.MODEL,
        )

    for tool in TOOL_DESCRIPTIONS:
        function = tool.get('function')
        tool_name = function.get('name') if function else None
        if tool_name:
            TOOL_STATE[tool_name] = True
        else:
            logger.warning("Unable to get tool_name")
