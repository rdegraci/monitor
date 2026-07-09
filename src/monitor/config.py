# CONFIG FILE IO POLICY:
# All file and directory operations that perform IO (e.g. open, os.makedirs, os.path.exists) must be wrapped in try/except blocks.
# Any IO failure must be logged via logger.error with exc_info=True, and an exception must be raised to abort execution.
# Failures in reading/loading config do NOT return defaults or fall back: they are fatal errors.
# Path manipulations not touching disk (e.g. os.path.expanduser, os.path.join) may be left unwrapped unless they interact with the filesystem.
# Environment variable assignments (os.environ, etc.) are not IO and do not need exception wrapping.
# The intent: All config file IO errors are logged and detected immediately, never silently handled or ignored.

from __future__ import annotations

import os

from monitor._stubs import appdirs, yaml
import time
import logging
import json
import importlib.resources
import uuid
import shutil

from dotenv import find_dotenv, load_dotenv

from monitor.function_keys_loader import load_function_keys_config
from monitor.lib.rate_limiter import configure_rate_limiter
# NOTE: configure_tools (monitor.core.tools) and configure_protocol_engine
# (monitor.lib.protocol_engine) are imported LAZILY at their call sites below,
# not here. Both modules import `config` back, and core.tools pulls in
# tool_definitions → protocol_engine. A module-top import here makes `config`
# un-importable whenever one of those leaf modules is imported before config
# (e.g. `from monitor.lib import protocol_engine` in a test) — a partially
# initialized-module circular import. config is low-level; it should not eagerly
# import the higher-level modules it only invokes at runtime.
# configure_responses_adapter (monitor.core.llm_responses_adapter) is imported
# lazily at its call site too: it pulls core.tooling → tool_definitions →
# protocol_engine, the same cycle as configure_tools (see NOTE above).
from monitor.lib.redis_utils import configure_redis_utils
from monitor.lib.preferences import load_user_preferences_prompt
from monitor.lib.external_services import configure_external_services
# configure_protocol_engine is imported lazily at its call site (see NOTE above).
from monitor.lib.keyboard import configure_function_key_insertions
from monitor.lib.keyboard import configure_voice_to_text
from monitor.lib.ripgrep_search import configure_rip_grep

logger = logging.getLogger(__name__)

PENDING_LLM_PREFIXES: list[str] = []
SESSIONS_FOLDER = "sessions"


def enqueue_next_llm_prefix(prefix: str) -> None:
    """Queues a system notice prefix to prepend to the next LLM request.

    The prefix is stripped of leading/trailing whitespace. Empty values are ignored.

    Args:
        prefix: Prefix text to queue for the next model prompt.

    Returns:
        None.
    """
    if not isinstance(prefix, str):
        return
    cleaned = prefix.strip()
    if not cleaned:
        return
    PENDING_LLM_PREFIXES.append(cleaned)


def _safe_expanduser(path):
    """
    Safely expand user path (os.path.expanduser) only for str inputs.
    - If path is None: returns None.
    - If path is a str: returns os.path.expanduser(path), raising RuntimeError (chained) on expansion errors.
    - If path is not a str: returns None (coerce non-string values to None) and logs a warning indicating coercion.
    Any unexpected exception is logged and re-raised as RuntimeError to abort execution.
    """
    try:
        if path is None:
            return None
        if not isinstance(path, str):
            logger.warning(f"_safe_expanduser: Coercing non-string path {path!r} to None.")
            return None
        try:
            return os.path.expanduser(path)
        except Exception as e:
            logger.error(f"Path expansion failed for path '{path}': {e}", exc_info=True)
            raise RuntimeError(f"Error expanding path: {path}") from e
    except Exception as e:
        logger.error(f"Unexpected error in _safe_expanduser for path '{path}': {e}", exc_info=True)
        raise RuntimeError("Unexpected error in _safe_expanduser") from e


def find_config_file(filename):
    """
    Search for `filename` in both user and site config locations.

    If the file exists in the user config directory, return that path.
    Otherwise return the site config path if present. If the file does not
    exist in either location, raise FileNotFoundError.

    All file/directory existence checks are IO and errors are logged and raised.
    """
    try:
        site_config_dir = appdirs.site_config_dir("monitor")
        user_config_dir = appdirs.user_config_dir("monitor")
        site_path = os.path.join(site_config_dir, filename)
        user_path = os.path.join(user_config_dir, filename)

        try:
            user_exists = os.path.exists(user_path)
        except Exception as e:
            logger.error(f"File existence check failed for {user_path}: {e}", exc_info=True)
            raise RuntimeError(f"Failed to check if user config exists: {user_path}") from e

        try:
            site_exists = os.path.exists(site_path)
        except Exception as e:
            logger.error(f"File existence check failed for {site_path}: {e}", exc_info=True)
            raise RuntimeError(f"Failed to check if site config exists: {site_path}") from e

        if user_exists:
            return user_path
        elif site_exists:
            return site_path
        else:
            raise FileNotFoundError(
                f"{filename} not found in either {user_path} or {site_path}"
            )
    except Exception as e:
        logger.error(f"Error locating config file {filename}: {e}", exc_info=True)
        raise


# ===== New helper for model_config.json loading and validation =====


def _load_and_validate_model_config():
    """
    Loads and validates the monitor/model_config.json file. Returns a dict with the expected keys.
    All IO errors are logged (fatal) and abort module import.
    """
    # Build the path to the model_config.json (look in user config, then site config)
    config_filename = "model_config.json"
    try:
        try:
            config_path = find_config_file(config_filename)
        except FileNotFoundError as fnf:
            # Attempt to copy the packaged default into the user config dir
            try:
                user_config_dir = appdirs.user_config_dir("monitor")
            except Exception as e:
                logger.error(
                    f"Failed to determine user config dir for monitor: {e}", exc_info=True
                )
                raise RuntimeError("Cannot determine user config dir for monitor") from e

            try:
                os.makedirs(user_config_dir, exist_ok=True)
            except Exception as e:
                logger.error(
                    f"Failed to create user config directory {user_config_dir}: {e}",
                    exc_info=True,
                )
                raise RuntimeError(
                    f"Failed to create user config directory: {user_config_dir}"
                ) from e

            dest_path = os.path.join(user_config_dir, config_filename)
            try:
                # Attempt to open the packaged default resource and copy it to dest_path
                try:
                    with importlib.resources.open_binary("monitor", config_filename) as src:
                        try:
                            with open(dest_path, "wb") as dst:
                                try:
                                    shutil.copyfileobj(src, dst)
                                except Exception as e:
                                    logger.error(
                                        f"Failed to write default {config_filename} to {dest_path}: {e}",
                                        exc_info=True,
                                    )
                                    raise RuntimeError(
                                        f"Failed to write default model config to {dest_path}"
                                    ) from e
                        except Exception as e:
                            logger.error(
                                f"Failed to open destination file {dest_path} for writing: {e}",
                                exc_info=True,
                            )
                            raise RuntimeError(
                                f"Failed to open destination model config file: {dest_path}"
                            ) from e
                except FileNotFoundError as e:
                    logger.error(
                        f"Packaged default {config_filename} not found in package resources: {e}",
                        exc_info=True,
                    )
                    raise RuntimeError(
                        "Packaged default model_config.json not found in package resources"
                    ) from e
                except Exception as e:
                    logger.error(
                        f"Failed to access packaged default {config_filename}: {e}",
                        exc_info=True,
                    )
                    raise RuntimeError(
                        "Failed to access packaged default model_config.json"
                    ) from e
            except Exception:
                # Errors already logged and wrapped above; re-raise to outer handler
                raise

            logger.info(f"Copied default model_config.json to {dest_path}")
            config_path = dest_path
        except Exception as e:
            logger.error(f"Unable to locate {config_filename}: {e}", exc_info=True)
            raise RuntimeError(f"Cannot find model config: {config_filename}") from e

    except Exception as e:
        logger.error(
            f"Error preparing model config path for {config_filename}: {e}",
            exc_info=True,
        )
        raise

    # Attempt reading and parsing JSON
    try:
        with open(config_path, "r") as f:
            try:
                model_config = json.load(f)
            except json.JSONDecodeError as je:
                logger.error(f"model_config.json is not valid JSON: {je}", exc_info=True)
                raise RuntimeError(f"Malformed JSON in {config_filename}") from je
    except Exception as e:
        logger.error(
            f"Failed to load {config_filename} from {config_path}: {e}", exc_info=True
        )
        raise RuntimeError(f"Cannot load model config file: {config_path}") from e

    # Validation and type conversions for int keys
    # List of top-level mapping keys to load and check
    mapping_keys = [
        "conversation_history_mapping",
        "context_window_mapping",
        "output_window_mapping",
        "model_max_tpm",
        "openai_model_tpm_tier",
        "anthropic_model_tpm_tier",
        "xai_model_tpm_tier",
        "google_model_tpm_tier",
        "model_mapping",
    ]
    # Ensure these all exist in the JSON
    for key in mapping_keys:
        if key not in model_config:
            logger.error(f"{config_filename} missing required key: '{key}'")
            raise RuntimeError(f"{config_filename} missing required key: '{key}'")

    # For all *_tpm_tier mappings, convert keys to int
    for tier_name in [
        "openai_model_tpm_tier",
        "anthropic_model_tpm_tier",
        "xai_model_tpm_tier",
        "google_model_tpm_tier",
    ]:
        val = model_config[tier_name]
        if not isinstance(val, dict):
            logger.error(f"Key '{tier_name}' in {config_filename} must be a dictionary")
            raise RuntimeError(f"{tier_name} in {config_filename} must be a dict")
        # Convert string keys that are numeric to int, keep non-numeric keys as is
        int_val = {}
        for k, v in val.items():
            try:
                int_key = int(k)
            except Exception:
                int_key = k
            int_val[int_key] = v
        model_config[tier_name] = int_val

    # Optional: model_tpm_mapping
    if "model_tpm_mapping" in model_config:
        mtm = model_config["model_tpm_mapping"]
        if not isinstance(mtm, dict):
            logger.error(
                f"Key 'model_tpm_mapping' in {config_filename} must be a dictionary if present"
            )
            raise RuntimeError(
                f"model_tpm_mapping in {config_filename} must be a dict if present"
            )
        coerced_mtm = {}
        for mk, mv in mtm.items():
            if isinstance(mv, dict):
                # Coerce numeric-like keys to int
                int_val = {}
                for k, v in mv.items():
                    try:
                        int_key = int(k)
                    except Exception:
                        int_key = k
                    int_val[int_key] = v
                coerced_mtm[mk] = int_val
            elif isinstance(mv, str):
                # Leave as it is; will be resolved to provider tier dict later
                coerced_mtm[mk] = mv
            else:
                logger.error(
                    f"Invalid value type for model_tpm_mapping['{mk}'] in {config_filename}: expected dict or str, got {type(mv).__name__}"
                )
                raise RuntimeError(
                    f"Invalid value for model_tpm_mapping['{mk}']: must be dict or str"
                )
        model_config["model_tpm_mapping"] = coerced_mtm

    # For each mapping that is model_key -> int or str, just check they're dicts
    for k in [
        "conversation_history_mapping",
        "context_window_mapping",
        "output_window_mapping",
        "model_max_tpm",
        "model_mapping",
    ]:
        if not isinstance(model_config[k], dict):
            logger.error(f"Key '{k}' in {config_filename} must be a dictionary")
            raise RuntimeError(f"{k} in {config_filename} must be a dict")

    return model_config


# ===== Initialize (on import) model mappings using new loader =====

_MODEL_CONFIG_CACHE = None
conversation_history_mapping = None
context_window_mapping = None
output_window_mapping = None
model_max_tpm = None
openai_model_tpm_tier = None
anthropic_model_tpm_tier = None
xai_model_tpm_tier = None
google_model_tpm_tier = None
model_tpm_mapping = None
MODEL_MAPPING = None


def load_model_config():
    global _MODEL_CONFIG_CACHE
    global conversation_history_mapping, context_window_mapping, output_window_mapping
    global model_max_tpm, openai_model_tpm_tier, anthropic_model_tpm_tier, xai_model_tpm_tier
    global google_model_tpm_tier, model_tpm_mapping, MODEL_MAPPING
    try:
        _MODEL_CONFIG_CACHE = _load_and_validate_model_config()
        conversation_history_mapping = _MODEL_CONFIG_CACHE["conversation_history_mapping"]
        context_window_mapping = _MODEL_CONFIG_CACHE["context_window_mapping"]
        output_window_mapping = _MODEL_CONFIG_CACHE["output_window_mapping"]
        model_max_tpm = _MODEL_CONFIG_CACHE["model_max_tpm"]
        openai_model_tpm_tier = _MODEL_CONFIG_CACHE["openai_model_tpm_tier"]
        anthropic_model_tpm_tier = _MODEL_CONFIG_CACHE["anthropic_model_tpm_tier"]
        xai_model_tpm_tier = _MODEL_CONFIG_CACHE["xai_model_tpm_tier"]
        google_model_tpm_tier = _MODEL_CONFIG_CACHE["google_model_tpm_tier"]
        MODEL_MAPPING = _MODEL_CONFIG_CACHE["model_mapping"]

        # Resolve optional data-driven model_tpm_mapping if provided; otherwise, fallback to hard-coded mapping.
        raw_model_tpm_mapping = _MODEL_CONFIG_CACHE.get("model_tpm_mapping")
        if raw_model_tpm_mapping is not None:
            if not isinstance(raw_model_tpm_mapping, dict):
                logger.error(
                    f"model_tpm_mapping in model_config.json is not a dict (type: {type(raw_model_tpm_mapping).__name__})"
                )
                raise RuntimeError("model_tpm_mapping must be a dict")
            provider_map = {
                "openai": openai_model_tpm_tier,
                "anthropic": anthropic_model_tpm_tier,
                "xai": xai_model_tpm_tier,
                "google": google_model_tpm_tier,
            }
            resolved_mapping = {}
            for mk, mv in raw_model_tpm_mapping.items():
                if isinstance(mv, str):
                    if mv not in provider_map:
                        logger.error(
                            f"Invalid provider reference '{mv}' for model_tpm_mapping['{mk}']; expected one of {list(provider_map.keys())}"
                        )
                        raise RuntimeError(
                            f"Invalid provider reference for model_tpm_mapping['{mk}']: {mv}"
                        )
                    resolved_mapping[mk] = provider_map[mv]
                elif isinstance(mv, dict):
                    # Already coerced by loader
                    resolved_mapping[mk] = mv
                else:
                    logger.error(
                        f"Invalid value type for model_tpm_mapping['{mk}']: expected str or dict, got {type(mv).__name__}"
                    )
                    raise RuntimeError(f"Invalid value for model_tpm_mapping['{mk}']")
            model_tpm_mapping = resolved_mapping
            logger.info("Using data-driven model_tpm_mapping from model_config.json")
        else:
            # The rest of the mappings remain hardcoded (backward-compatible fallback)
            model_tpm_mapping = {
                "sonnet4": anthropic_model_tpm_tier,
                "sonnet35": anthropic_model_tpm_tier,
                "sonnet37": anthropic_model_tpm_tier,
                "4o-mini": openai_model_tpm_tier,
                "gpt4o": openai_model_tpm_tier,
                "o3-mini": openai_model_tpm_tier,
                "gpt41": openai_model_tpm_tier,
                "gpt5": openai_model_tpm_tier,
                "o3": openai_model_tpm_tier,
                "grok3": xai_model_tpm_tier,
                "grok4": xai_model_tpm_tier,
                "gemini20": google_model_tpm_tier,
                "gpt5-mini": openai_model_tpm_tier,
            }
            logger.warning(
                "Using fallback hard-coded model_tpm_mapping (no data-driven mapping provided)"
            )
    except Exception as _model_config_e:
        # Already logged in loader, but abort import
        raise


def get_model_reverse_mapping():
    """
    Returns a reverse mapping of MODEL_MAPPING: from full model string -> shorthand key (as string).
    Caveat: If multiple shorthand keys alias to the same model string, only the last alias key is kept in the mapping.
    Logs a warning for each duplicate (same model string for multiple keys), listing the duplicate model and conflicting shorthand keys.
    """
    if not isinstance(MODEL_MAPPING, dict):
        logger.warning(
            f"MODEL_MAPPING is not a dict (type: {type(MODEL_MAPPING).__name__}); returning empty reverse mapping."
        )
        return {}

    reverse = {}
    value_to_keys = {}
    for k, v in MODEL_MAPPING.items():
        if v in value_to_keys:
            value_to_keys[v].append(k)
        else:
            value_to_keys[v] = [k]
        reverse[v] = k
    for v, keys in value_to_keys.items():
        if len(keys) > 1:
            logger.warning(
                f"Duplicate model alias detected: model string '{v}' is mapped to multiple shorthand keys {keys}"
            )
    return reverse


MODEL = None
MODEL_CONTEXT_WINDOW = None
MODEL_OUTPUT_WINDOW = None
MODEL_INPUT_TIER = None
MODEL_MAX_TPM = None
MODEL_INPUT_WINDOW = None
# Responses API follow-up budgeting. These are the tunable knobs for the
# reserve-aware preflight policy used on chained/tool-result follow-up calls.
# Tool-schema and function_call_output shell reserves are intentionally NOT
# configured here; they are measured per request.
FOLLOWUP_BASE_SAFETY_RATIO = 0.85
FOLLOWUP_TOPLEVEL_RESERVE_TOKENS = 256
FOLLOWUP_HIDDEN_CHAIN_RESERVE_BY_CLASS = {
    "fresh_request": 0,
    "chained_user_followup": 2000,
    "tool_result_followup": 4000,
    "summarization_followup": 2000,
}
FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH = 1000
FOLLOWUP_HIDDEN_CHAIN_RESERVE_CAP_RATIO = 0.5
FOLLOWUP_DYNAMIC_CHAINED_RESERVE = True
FOLLOWUP_CHAINED_RESERVE_MIN_RT = 20
FOLLOWUP_CHAINED_RESERVE_MAX_RT = 45
FOLLOWUP_CHAINED_RESERVE_MAX_TOKENS = 8000
ENABLE_FOLLOWUP_TOOL_OMISSION_HINTS = False
FOLLOWUP_SHOW_RECOVERY_NOTICES = True
CONVERSATION_MAX_SIZE = None
RATE_LIMITING_CONFIG = None
MEMORY_SERVICES = None
# Redis memory TTLs (seconds). SHORT backs ambient auto-captures (SemanticStore);
# LONG backs explicit "remember this" writes (update_memory). Sized to span a
# working session: SHORT (1h) outlasts a task, LONG (4h) outlasts the whole
# session with margin but expires overnight so the next day starts clean.
# Overridable in config.yaml. MEMORY_CONTEXT_MAX_ENTRIES caps how many stored
# memories get prepended into the prompt each turn (cost guard); 0 = uncapped.
MEMORY_SHORT_TTL = 3600
MEMORY_LONG_TTL = 14400
MEMORY_CONTEXT_MAX_ENTRIES = 20
# Sub-agent memory sharing. The Redis memory pool is global (one keyspace, no
# session/project scoping), so sub-agents (monitor --agent) are walled off from
# it by DEFAULT (False): they get no memory read/write tools and no prepended
# memory context, so they can't read or pollute your pool. The gates live in
# core.tools.configure_tools and redis_utils.prepend_memory_to_history. To let
# sub-agents participate in shared memory it's a one-step opt-in: set
# SUBAGENT_MEMORY_SERVICES: true in your appdir config.yaml.
SUBAGENT_MEMORY_SERVICES = False
STARTUP_TIME = None
HISTORY_FILE = None
CONVERSATION_HISTORY: list = []
MAX_TOKEN_COUNT = None
OLD_MAX_TOKEN_COUNT = None
MACRO_DELIMITER_OPEN = None
MACRO_DELIMITER_CLOSE = None
MACRO_DELIMITER_ESCAPE = None
MACRO_FILE_PATH = None
SUMMARIZATION_CONFIG = None
EXTERNAL_SERVICES = None
# OLLAMA_CONFIG removed — local Ollama integration replaced by
# embedcodeserv's /analyze endpoint (server-side RAG).
TOTAL_TOKEN_COUNT = 0
NON_INTERACTIVE_COMMANDS_PATH = None
INTERACTIVE_COMMANDS_PATH = None
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_MAX_RETRIES = 3
REDIS_RETRY_INTERVAL = 1
PREFERENCE_PROMPT_FILE = None
REASONING_MODEL_PREFIX = None
REASONING_EFFORT = None
REASONING_MAX_COMPLETION_TOKENS = None
# Floor for the effort of an auto-bumped turn. None → use each heuristic's own
# target. When set, raises a bumped turn's effort to at least this level (never
# downgrades — see higher_reasoning_effort).
REASONING_BUMP_EFFORT = None
# Optional more-capable model swapped in for a single reasoning-bumped turn
# (transient, per-call). None → fall back to the corresponding MODEL* value.
ADV_REASONING_MODEL = None
ADV_REASONING_MODEL_OUTPUT_WINDOW = None
COMMIT_MODEL = None
COMMIT_REASONING_EFFORT = None
COMMIT_REASONING_MAX_COMPLETION_TOKENS = None
# Role-based model selection (smart orchestration). When set, the orchestrator
# (main instance with MONITOR_ENABLE_AGENT_ORCHESTRATION) and spawned --agent
# children run a different model/effort than the base MODEL. Applied at startup
# by apply_role_model_override(); unset → base MODEL / REASONING_EFFORT.
ORCHESTRATOR_MODEL = None
ORCHESTRATOR_REASONING_EFFORT = None
SUBAGENT_MODEL = None
SUBAGENT_REASONING_EFFORT = None
LAST_INPUT_WAS_VOICE = False
ARTIFACT_SERVER = None
JOKES_FILE = None
DIRECTIVES_DIR = None
# Single set of config knobs for the embedcodeserv Flask server (the unified
# indexing + retrieval + RAG service that backs :embed, :index, and :query).
# Previously this codebase had two parallel sets — CODE_LENS_HOST/PORT and
# ECS_HOST/PORT/TIMEOUT — that pointed at the same Flask server through
# different variable names; that historical split has been consolidated.
EMBEDCODESERV_HOST = None
EMBEDCODESERV_PORT = None
EMBEDCODESERV_TIMEOUT = None
ENABLE_AUTO_SUMMARIZE_ON_LIMIT = None
SESSION_ID = None
SUMMARY_TWITCH = None
SUMMARY_LINKEDIN = None
SUMMARY_TWITTER = None
SERVER_MODE = None
AGENT = False
# New globals for agent depth configuration
MONITOR_AGENT_DEPTH = 0
MONITOR_AGENT_MAX_DEPTH = 1
MONITOR_ENABLE_AGENT_ORCHESTRATION = False
SUBAGENT_WRITE_ACCESS = "none"
# Agent orchestration spawn caps + liveness. Maximally conservative SAFE
# defaults: at most ONE sub-agent ever, one at a time. Raise deliberately.
# (0 disables a cap.) Read from config.yaml / env in the loader below.
MONITOR_AGENT_MAX_BREADTH = 1
MONITOR_AGENT_MAX_TOTAL = 1
MONITOR_AGENT_HEARTBEAT_TIMEOUT = 45
MONITOR_AGENT_IDLE_TIMEOUT = 300
RESPONSES_API = None
TWITTER_CLIENT_API = None
TWITCH_CLIENT_API = None
LINKEDIN_CLIENT_API = None
DEFAULT_EXCLUDE_EXTENSIONS = None
DEFAULT_EXCLUDE_GLOBS = None
FUNCTION_KEY_INSERTIONS: dict[str, str] = {}
# Cost-display feature. SHOW_COST_ESTIMATE is read from config.yaml
# (default True if absent). SESSION_COST_USD accumulates the litellm-reported
# cost of each LLM response in this session; it resets to 0 on set_model().
# Display side is opt-out — set SHOW_COST_ESTIMATE: false in YAML to hide it.
SHOW_COST_ESTIMATE = None
# Pure cumulative session counters, parallel to each other:
#   - SESSION_TOTAL_TOKENS: tokens consumed across all LLM calls this session
#   - SESSION_COST_USD: USD cost of those tokens per litellm's rate tables
# Both reset on set_model() (rates differ between models) and on
# :reset_history (user-explicit fresh start). NEITHER resets on compaction —
# compaction shrinks history, but the tokens were already spent and the
# summarization call itself spends more.
SESSION_TOTAL_TOKENS = 0
SESSION_COST_USD = 0.0
# Per-model calibration store for :fuel_debug. Keyed by the model actually used
# for each round-trip — which may be ADV_REASONING_MODEL on a reasoning-bumped
# turn, not config.MODEL — so a transient single-turn model swap never pollutes
# another model's rate calibration. Each entry accumulates real provider usage:
#   cost_usd, total_tokens, cached_input_tokens, uncached_input_tokens,
#   output_tokens, effort_weighted_tokens, effort_weight_tokens.
# effort_weighted_tokens / effort_weight_tokens yield the token-weighted average
# reasoning multiplier, folding in single-turn upgrades the steady
# REASONING_EFFORT does not. Cleared on :reset_history (new session); persists
# across model switches since it is already keyed per model.
SESSION_CALIBRATION_BY_MODEL: dict[str, dict[str, float | int]] = {}
# F: fuel-tank gauge — a per-session cumulative-token budget, the draining
# counterpart to U:. Rendered before C: as F: = budget - SESSION_TOTAL_TOKENS,
# shown as the exact remaining token count plus percent. Unlike C: (a refillable
# window LEVEL bounded by the model context window), this is a fixed quota that
# only drains and is allowed to go negative — compaction does NOT refill it.
#
# The cap is normally DERIVED from a dollar/day target (see DAILY_COST_TARGET_USD
# below) so it auto-resizes per model and reasoning effort. SESSION_TOKEN_BUDGET
# here is an optional MANUAL OVERRIDE: set a positive int to pin the cap to an
# exact token count (bypassing the dollar derivation); leave None to derive.
SESSION_TOKEN_BUDGET = None
# Dollar/day budget the F: gauge targets. The token cap is computed as
# DAILY_COST_TARGET_USD / effective_rate, where the rate comes from
# MODEL_TOKEN_RATE_PER_MTOK (measured $/1M-tokens for the current model) or, for
# models not listed there, the anchor rate scaled by the model's published price
# ratio (so a cheaper model like gpt-5.4-mini auto-yields a larger tank), then
# multiplied by the reasoning-effort multiplier. Set to 0 / null to hide the
# gauge (unless SESSION_TOKEN_BUDGET is set). A STABLE per-model/effort rate is
# used (NOT the live realized rate), so the cap doesn't jitter within a session.
DAILY_COST_TARGET_USD = 5.0
# Measured effective rate ($ per 1M total tokens) per model, at the user's
# typical reasoning effort. Seeded from observation; extend/tune as you measure
# (T: / U: at session end). Keys are full model strings (e.g. "openai/gpt-5.4").
MODEL_TOKEN_RATE_PER_MTOK = {
    "openai/gpt-5.4": 1.0,  # observed ~$1/1M at medium reasoning
}
# Which MODEL_TOKEN_RATE_PER_MTOK entry to treat as the scaling anchor for models
# not explicitly listed: their rate = anchor_rate * (price_ratio from the
# pricing table). Should be a model you've actually measured.
TOKEN_RATE_ANCHOR_MODEL = "openai/gpt-5.4"
# Last-resort rate ($/1M) when neither a measured entry nor a table-based anchor
# scaling is available for the current model.
DEFAULT_TOKEN_RATE_PER_MTOK = 1.0
# Reasoning-effort rate multiplier, relative to medium (the rate anchor). Higher
# effort emits more output/reasoning tokens (billed at the output rate), raising
# the realized $/token → a smaller starting tank. Applies only to reasoning
# models (REASONING_MODEL_PREFIX in the model name); 1.0 otherwise. Rough
# defaults — tune from observation.
REASONING_EFFORT_RATE_MULTIPLIER = {
    "minimal": 0.5,
    "low": 0.75,
    "medium": 1.0,
    "high": 1.75,
}
# Number of auto-compaction events that have fired in the current session.
# Incremented after each successful partial-summary reset (soft-trigger and
# rate-limit paths). Surfaced in the H: indicator as "H:(N) <count>" so the
# user can see how aggressively compaction is firing. Resets alongside the
# cumulative cost counters on set_model() and :reset_history.
SESSION_COMPACTION_COUNT = 0
# Spend-telemetry counters for compaction behavior. These back the
# end-of-session [SPEND][SUMMARY] log line and keep the first telemetry rollout
# session-scoped, cheap, and grep-friendly in the existing log file.
SESSION_SPEND_COMPACTION_SKIPS = 0
SESSION_SPEND_COMPACTION_FAILURES = 0
# Responses-chain cost-tier telemetry (TELEMETRY-ONLY rollout; see
# RESPONSES_CHAIN_TIER_TOKENS and docs/cache/RESPONSES_CHAIN_BREAK.md).
# LAST_BILLED_INPUT_TOKENS is the provider-billed input size of the most recent
# Responses request — the only accurate measure of hidden-chain size, since
# visible history under-counts it. SESSION_TIER_CROSSINGS / SESSION_RESPONSES_REQUESTS
# let us compute the fraction of requests billed at the long-context 2x rate.
LAST_BILLED_INPUT_TOKENS = 0
SESSION_TIER_CROSSINGS = 0
SESSION_RESPONSES_REQUESTS = 0
SESSION_SPEND_COMPACTION_FALLBACKS = 0
SESSION_SPEND_SUMMARY_TOKENS_TOTAL = 0
SESSION_SPEND_LAST_COMPACTION_TS = None
SESSION_SPEND_MEMORY_CALLS = 0
SESSION_SPEND_MEMORY_SKIPS = 0
SESSION_SPEND_MEMORY_STORES = 0
SESSION_SPEND_MEMORY_NULLS = 0
SESSION_SPEND_MEMORY_FAILURES = 0
SESSION_SPEND_HELPER_CALLS = 0
SESSION_SPEND_OVERSIZE_TOOL_OUTPUTS = 0
SESSION_SPEND_TOOL_OUTPUT_TOKENS_TRIMMED = 0
# Cumulative count of tool calls dispatched this session — incremented in
# handle_tool_call for each tool call seen (whether it executed, errored,
# or was rejected by the loop detector). Surfaced via :dump_metrics so
# eval harnesses can grade efficiency without log-scraping. Resets on
# set_model() and :reset_history alongside the cost counters.
SESSION_TOOL_CALL_COUNT = 0
# Number of times the per-turn loop detector has refused a repeated tool
# call this session. Zero means the model never spun in a tight loop;
# any positive value is worth investigating in the eval transcript.
# Resets on set_model() and :reset_history.
SESSION_LOOP_DETECTOR_TRIPS = 0
# Cached project-instructions content (MONITOR.md + MONITOR_CONVENTIONS.md)
# loaded once and concatenated into the system prompt by build_system_prompt.
# None until first read; populated by _project_instructions_content() in
# lib/system_prompt.py. Cleared by configure_runtime_prompt_paths when paths
# change and by test helpers that need a fresh load. NOT reset on set_model
# or :reset_history — the project doesn't change with model swaps, and
# re-reading the same files for every session reset is wasteful.
PROJECT_INSTRUCTIONS_CONTENT = None
PROJECT_WIKI_PATH = None
PROJECT_WIKI_IDENTITY_PATH = None
# Per-turn reasoning-effort override. The harness sets this in
# prepare_query_context when the user's message matches complexity signals
# (e.g., refactor/audit/design/...) and the configured default is below
# "high". Read by call_litellm_completion as override-or-default. Cleared
# at the next user turn (set or cleared in prepare_query_context). Also
# cleared by set_model and :reset_history because it's turn-scoped state.
CURRENT_TURN_REASONING_OVERRIDE = None
# Per-turn collation/synthesis flag (smart orchestration). Set True in
# prepare_query_context when completed sub-agent results were folded into THIS
# turn, so the orchestrator transiently escalates to ORCHESTRATOR_MODEL for the
# synthesis call (see resolve_turn_model). Turn-scoped: reset each turn.
CURRENT_TURN_IS_COLLATION = False
# Active temporary tool groups for the CURRENT user turn only. Seeded from
# short-lived leases at query-prep time, widened for explicit intents on the
# current turn, then consumed by tool-catalog filtering. Cleared/reset on the
# next user turn, :reset_history, and set_model().
CURRENT_TURN_TOOL_GROUPS: set[str] = set()
# Base static tool profile advertised to the model on normal turns. The runtime
# :tools command changes this without editing config.yaml.
TOOL_PROFILE = "coding"
# When True, explicit user intent may temporarily widen the advertised tool set
# beyond TOOL_PROFILE for a small number of future turns.
ENABLE_TOOL_PROFILE_AUTO_WIDEN = True
# Number of FUTURE user turns a temporary widen persists after the triggering
# turn. 0 means current turn only.
TOOL_PROFILE_AUTO_WIDEN_TURNS = 2
# When True, explicit re-asks or actual use of a temporarily widened group's
# tools refresh that group's lease back to TOOL_PROFILE_AUTO_WIDEN_TURNS.
TOOL_PROFILE_AUTO_WIDEN_REFRESH_ON_USE = True
# Cap on simultaneously leased temporary groups. 0 disables the cap.
TOOL_PROFILE_AUTO_WIDEN_MAX_ACTIVE_GROUPS = 2
# Optional per-group future-turn lease overrides, keyed by internal group name.
TOOL_PROFILE_AUTO_WIDEN_TURNS_BY_GROUP: dict[str, int] = {}
# Optional internal group names that should never auto-widen from user intent.
TOOL_PROFILE_AUTO_WIDEN_DISABLED_GROUPS: list = []
# Whether to print notices when temporary tool groups are widened/expired.
SHOW_TOOL_PROFILE_NOTICES = True
# Temporary leased widen groups that remain active for upcoming turns. Mapping
# of internal group name -> remaining FUTURE user turns.
TOOL_PROFILE_GROUP_LEASES: dict[str, int] = {}
# Error-driven reasoning escalation. When True, a tool result that looks like a
# failure (test/build/lint error, traceback, non-zero exit) escalates
# reasoning_effort to "high" for the remainder of that user turn — so the model
# reasons harder about the fix only when there's proven trouble. One-way and
# pay-for-what-you-use (no cost on turns that don't fail). See
# lib/reasoning_escalation.py and the hook in core/tooling.handle_tool_call.
# Overridable in config.yaml.
ESCALATE_REASONING_ON_TOOL_FAILURE = True
# Cost-indicator color thresholds (USD). P (this turn) and W per-turn
# average get colored when they exceed these values: green (uncolored,
# default) → yellow → red. Defaults are calibrated for gpt-5.4 base /
# sonnet-4-6; on mini / haiku the colors stay silent because those models
# are cheap enough that typical turns don't approach these thresholds.
# Opus users should multiply by ~5x (see YAML config for guidance).
COST_P_YELLOW = 0.30
COST_P_RED = 0.80
COST_W_YELLOW = 0.30
COST_W_RED = 0.60
# Per-model pricing overrides for the cost-fallback path. Used by
# lib/model_pricing.estimate_cost_from_usage when litellm.completion_cost
# returns 0 for an unknown model. Populated from the YAML ``model_pricing:``
# block at startup; keyed by full model name; values are per-token rate dicts.
# See lib/model_pricing.py for the lookup precedence (override > shipped).
MODEL_PRICING_OVERRIDES: dict[str, dict[str, float]] = {}
# Per-turn cost ledger. Each entry is the accumulated USD cost for one
# user-message-bounded turn. A new 0.0 is appended each time the harness
# observes a fresh user message; all LLM calls between user messages
# (including tool-call rounds) add into the LAST entry. Used by the U:
# indicator to show "last 10 turns" and "last turn" alongside the
# cumulative session total. Resets on set_model() and :reset_history.
TURN_COSTS_USD: list[float] = []
# Per-turn round-trip ledger, parallel to TURN_COSTS_USD: one entry per turn
# (a bucket opens on each user message), incremented on every LLM completion in
# that turn. RT: in the prompt reads the last entry — how many model round-trips
# the previous turn took. Resets on set_model() and :reset_history.
TURN_ROUND_TRIPS: list[int] = []
# Per-turn cache-mix ledgers, parallel to TURN_COSTS_USD / TURN_ROUND_TRIPS.
# Each bucket accumulates provider-reported token composition across all model
# round-trips in that user-message-bounded turn so the cache display can show a
# turn aggregate instead of only the final completion. Resets on set_model() and
# :reset_history.
TURN_CACHED_INPUT_TOKENS: list[int] = []
TURN_UNCACHED_INPUT_TOKENS: list[int] = []
TURN_OUTPUT_TOKENS: list[int] = []
# How many recent turns to roll up for the middle dollar value in the U:
# indicator. 10 captures recent-trajectory context (was this a brief flurry
# or sustained spend?) without leaking back so far that the number looks
# like the cumulative total.
RECENT_TURN_WINDOW = 10

# Auto-compaction soft-trigger threshold, as a fraction of the active model's
# input window. When the assembled prompt exceeds this fraction, the harness
# runs summarization proactively — well before the hard input-window ceiling
# — to bend the quadratic cost curve. 0.30 is the recommended default:
# meaningful savings on long sessions without compacting so often that cache
# invalidations or summary information-loss become net negative. The hard
# ceiling at core/llm.py:472 remains as a backstop for cases where
# compaction can't bring the prompt under (single huge tool result, etc.).
# Gated by ENABLE_AUTO_SUMMARIZE_ON_LIMIT — if that's false, neither soft
# nor hard summarization fires. Set this to 1.0 to disable the soft trigger
# and revert to compact-only-at-overflow behavior.
AUTO_COMPACT_THRESHOLD_RATIO = 0.30
# Per-model override of the compaction ratio, keyed by the fully-qualified model
# string (same keys as MODEL / MODEL_TOKEN_RATE_PER_MTOK). The active model
# (config.MODEL) is looked up here first; unlisted models use the scalar default
# above. Lets a model with an absolute cost cliff (e.g. gpt-5.4 base's 128K
# long-context tier) compact at a lower fraction than the global default without
# over-compacting other models. Resolved via effective_auto_compact_ratio().
AUTO_COMPACT_THRESHOLD_RATIO_BY_MODEL: dict[str, float] = {}


def effective_auto_compact_ratio(model=None):
    """The soft auto-compaction ratio for the active (or given) model.

    Returns the per-model override from ``AUTO_COMPACT_THRESHOLD_RATIO_BY_MODEL``
    when present and valid (in ``(0, 1]``), else the global
    ``AUTO_COMPACT_THRESHOLD_RATIO``. Keyed by the fully-qualified model string,
    defaulting to ``config.MODEL``.

    Args:
        model: Optional model name. When omitted, uses the active ``MODEL``.

    Returns:
        float: The effective compaction ratio.
    """
    resolved_model = model if model is not None else (MODEL or "")
    overrides = AUTO_COMPACT_THRESHOLD_RATIO_BY_MODEL
    if isinstance(overrides, dict):
        val = overrides.get(resolved_model)
        if isinstance(val, (int, float)) and not isinstance(val, bool) and 0 < val <= 1:
            return float(val)
    return AUTO_COMPACT_THRESHOLD_RATIO

# How many recent "turns" (user-message-bounded segments) to preserve
# verbatim when auto-compaction fires. Older history before this boundary is
# replaced with a single summary message. Trade-off: higher values keep more
# recent context intact (fewer re-reads, less detail loss) but compact less
# aggressively; lower values compact harder but the model may need to
# re-discover state. 6 is roughly the last ~3 user-assistant exchanges.
# Set to a very large number (e.g. 9999) to effectively disable compaction
# while keeping the soft-threshold trigger as a logging signal.
RECENT_TURNS_PRESERVED_ON_COMPACT = 6

# Absolute provider-billed input-token boundary at which gpt-5.4 base crosses
# into the long-context 2x pricing tier (input $2.50->$5.00/M, cached
# $0.25->$0.50/M — the multiplier applies to ALL tokens in the call, including
# the cached portion). This is an ABSOLUTE cost cliff, NOT a fraction of the
# model window, so it is tracked in tokens rather than via a ratio (the
# window-ratio compaction triggers watch VISIBLE history and never see the
# hidden Responses chain, which is what actually gets billed).
#
# As of this rollout it is TELEMETRY-ONLY: the usage-capture path in
# llm_responses_adapter records LAST_BILLED_INPUT_TOKENS and counts how often a
# request is billed at/above this boundary (SESSION_TIER_CROSSINGS). No behavior
# changes yet — the future chain-break gate (see docs/cache/RESPONSES_CHAIN_BREAK.md)
# will use this boundary (with a margin) to clear RESPONSE_ID and reset billed
# context back into the short-context tier.
RESPONSES_CHAIN_TIER_TOKENS = 128000

# How many recent "turns" (user-message-bounded segments) to keep tool
# bodies verbatim. Tool results and bulky tool-call argument strings in
# messages older than this boundary are demoted to short placeholders
# (sentinel-marked so we never re-demote on subsequent passes). Demotion
# operates in-place on CONVERSATION_HISTORY before each LLM call, so the
# savings show up in both token counts and the cached prefix on the next
# turn. Default 3 tiers naturally with the compaction threshold (6):
# turns 1-3 full content, turns 4-6 demoted bodies, turns 7+ subject to
# full summarization. Set to a large number to effectively disable demotion.
OLD_TOOL_BODY_TURNS_THRESHOLD = 3

# Cap on output tokens for non-reasoning model calls. Sent as
# max_completion_tokens to litellm so the provider truncates long
# completions instead of letting them run to whatever the model decides on
# its own. Default 8192 covers any reasonable coding response (~6K words);
# bump higher at runtime via :max_tokens N for long-form generation.
# Reasoning models (gpt-5-style) use REASONING_MAX_COMPLETION_TOKENS
# instead — they need a much larger budget because reasoning tokens count
# against the output cap.
MAX_COMPLETION_TOKENS = 8192

# Maximum consecutive LLM rounds that may return tool_calls within a single
# user turn before handle_tool_call aborts the chain. Counts ROUNDS, not
# individual tool calls — multiple tool calls in one model response count as
# one round. The counter resets when a new user message starts the next turn.
# 128 is generous: even an 8-10 item todo plan with view+edit+test per item
# rarely exceeds ~50 rounds. A half-way warning fires at MAX_TOOL_CALL_DEPTH //
# 2 to surface long autonomous chains before the hard abort.
MAX_TOOL_CALL_DEPTH = 128

# Per-turn loop detector: when the same (tool_name, sorted_args) signature
# fires this many times consecutively within one user turn, handle_tool_call
# rejects the call with an error message routed back to the model instead of
# executing it. 3 catches the common "re-read same file range" / "update_todo
# with no-op narration" pattern while still leaving headroom for legitimate
# repeats (e.g. polling a file). Counter resets when a new user message
# starts the next turn (_depth=0 entry). Set to 0 to disable entirely.
MAX_REPEATED_TOOL_CALLS = 3

# Blast-radius cap on the byte length of content the model can write in a
# single file-write tool call. UTF-8 encoded length of the payload
# parameter (contents / content / new_str) is compared against this
# value; over-cap calls are rejected with an error returned to the
# model. Read-side protection lives in LARGE_FILE_TOKEN_THRESHOLD; this
# is the symmetric write-side guard.
#
# Default 32K tokens for a single serialized tool result that gets fed back
# into the model loop. This is intentionally much smaller than the model
# context window; it bounds one tool's blast radius without constraining the
# full conversation budget. Set to 0 to disable entirely.
# Override via YAML key TOOL_OUTPUT_TOKEN_LIMIT.
TOOL_OUTPUT_TOKEN_LIMIT = 32768

# Default 1 MiB (1_048_576 bytes) — large enough for legitimate writes
# (vendored license, generated migration, lockfile up to ~1 MB), tight
# enough to catch hallucinated runaway writes before they fill disk or
# blow context budget on the next read. Set to 0 to disable entirely.
# Override via YAML key MAX_FILE_WRITE_BYTES.
MAX_FILE_WRITE_BYTES = 1_048_576

# Anthropic prompt-cache TTL for the system + tools breakpoints. Must be one
# of "5m" or "1h" (Anthropic's only supported values). Default is "1h": writes
# cost 2x base input (vs 1.25x for 5m) but cache survives 12x longer, which
# wins for any interactive session with >5min idle between asks. The final
# user-message breakpoint is intentionally left at the 5m default — it changes
# every turn, so a long TTL would buy nothing. User-tunable at runtime via the
# :ttl built-in command.
ANTHROPIC_CACHE_TTL = "1h"

OLLAMA = None
OLLAMA_MODEL = None
OLLAMA_BASE_URL = None
OLLAMA_MODEL_CONTEXT_WINDOW = None
OLLAMA_MODEL_OUTPUT_WINDOW = None
OLLAMA_MODEL_INPUT_WINDOW = None
OLLAMA_MODEL_INPUT_TIER = None
OLLAMA_MODEL_MAX_TPM = None
OLLAMA_TEMPERATURE = None
OLLAMA_TOP_P = None
OLLAMA_TOP_K = None


def _derive_ollama_model_settings(ollama_config, model_name):
    try:
        if not isinstance(ollama_config, dict):
            logger.error("OLLAMA config must be a dictionary")
            raise RuntimeError("OLLAMA config must be a dict")
        if not isinstance(model_name, str) or not model_name.strip():
            logger.error("OLLAMA model name must be a non-empty string")
            raise RuntimeError("OLLAMA model name must be a non-empty string")

        model_name = model_name.strip()
        context_window = ollama_config.get("CONTEXT_WINDOW")
        output_window = ollama_config.get("OUTPUT_WINDOW")

        if not isinstance(context_window, int) or context_window <= 0:
            logger.error(
                f"OLLAMA[{model_name!r}] CONTEXT_WINDOW must be a positive integer"
            )
            raise RuntimeError("Invalid OLLAMA CONTEXT_WINDOW")
        if not isinstance(output_window, int) or output_window <= 0:
            logger.error(
                f"OLLAMA[{model_name!r}] OUTPUT_WINDOW must be a positive integer"
            )
            raise RuntimeError("Invalid OLLAMA OUTPUT_WINDOW")

        input_window = context_window - output_window
        if input_window <= 0:
            logger.error(
                f"OLLAMA[{model_name!r}] computed MODEL_INPUT_WINDOW <= 0 "
                f"(context={context_window}, output={output_window})"
            )
            raise RuntimeError("Invalid OLLAMA input window")

        return context_window, output_window, input_window
    except Exception as e:
        logger.error(
            f"Failed to derive OLLAMA model settings for model {model_name!r}: {e}",
            exc_info=True,
        )
        raise


def configure_globals():
    global MODEL, MODEL_CONTEXT_WINDOW, MODEL_OUTPUT_WINDOW, MODEL_MAX_TPM, MODEL_INPUT_TIER, MODEL_INPUT_WINDOW
    global FOLLOWUP_BASE_SAFETY_RATIO, FOLLOWUP_TOPLEVEL_RESERVE_TOKENS
    global FOLLOWUP_HIDDEN_CHAIN_RESERVE_BY_CLASS, FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH
    global FOLLOWUP_HIDDEN_CHAIN_RESERVE_CAP_RATIO
    global CONVERSATION_MAX_SIZE, RATE_LIMITING_CONFIG, MEMORY_SERVICES, STARTUP_TIME
    global HISTORY_FILE, MAX_TOKEN_COUNT, OLD_MAX_TOKEN_COUNT
    global MACRO_DELIMITER_OPEN, MACRO_DELIMITER_CLOSE, MACRO_DELIMITER_ESCAPE, MACRO_FILE_PATH
    global SUMMARIZATION_CONFIG
    global EXTERNAL_SERVICES, MEMORY_SERVICES
    global INTERACTIVE_COMMANDS_PATH, NON_INTERACTIVE_COMMANDS_PATH
    global REDIS_HOST, PREFERENCE_PROMPT_FILE
    global MEMORY_SHORT_TTL, MEMORY_LONG_TTL, MEMORY_CONTEXT_MAX_ENTRIES
    global SUBAGENT_MEMORY_SERVICES
    global REASONING_MODEL_PREFIX, REASONING_EFFORT, REASONING_MAX_COMPLETION_TOKENS
    global REASONING_BUMP_EFFORT
    global ADV_REASONING_MODEL, ADV_REASONING_MODEL_OUTPUT_WINDOW
    global COMMIT_MODEL, COMMIT_REASONING_EFFORT, COMMIT_REASONING_MAX_COMPLETION_TOKENS
    global ORCHESTRATOR_MODEL, ORCHESTRATOR_REASONING_EFFORT
    global SUBAGENT_MODEL, SUBAGENT_REASONING_EFFORT
    global TOOL_PROFILE, ENABLE_TOOL_PROFILE_AUTO_WIDEN
    global TOOL_PROFILE_AUTO_WIDEN_TURNS, TOOL_PROFILE_AUTO_WIDEN_REFRESH_ON_USE
    global TOOL_PROFILE_AUTO_WIDEN_MAX_ACTIVE_GROUPS
    global TOOL_PROFILE_AUTO_WIDEN_TURNS_BY_GROUP, TOOL_PROFILE_AUTO_WIDEN_DISABLED_GROUPS
    global SHOW_TOOL_PROFILE_NOTICES
    global ESCALATE_REASONING_ON_TOOL_FAILURE
    global ARTIFACT_SERVER, EMBEDCODESERV_HOST, EMBEDCODESERV_PORT, EMBEDCODESERV_TIMEOUT, JOKES_FILE, DIRECTIVES_DIR
    global ENABLE_AUTO_SUMMARIZE_ON_LIMIT, SESSION_ID
    global SUMMARY_TWITCH, SUMMARY_LINKEDIN, SUMMARY_TWITTER, SERVER_MODE, AGENT, RESPONSES_API
    global SUBAGENT_WRITE_ACCESS
    global TWITTER_CLIENT_API, TWITCH_CLIENT_API, LINKEDIN_CLIENT_API
    global DEFAULT_EXCLUDE_EXTENSIONS, DEFAULT_EXCLUDE_GLOBS
    global MONITOR_AGENT_DEPTH, MONITOR_AGENT_MAX_DEPTH, MONITOR_ENABLE_AGENT_ORCHESTRATION
    global MONITOR_AGENT_MAX_BREADTH, MONITOR_AGENT_MAX_TOTAL, MONITOR_AGENT_HEARTBEAT_TIMEOUT
    global MONITOR_AGENT_IDLE_TIMEOUT
    global FUNCTION_KEY_INSERTIONS, SHOW_COST_ESTIMATE, TOOL_OUTPUT_TOKEN_LIMIT
    global CURRENT_TURN_TOOL_GROUPS, TOOL_PROFILE_GROUP_LEASES, SESSIONS_FOLDER
    global OLLAMA, OLLAMA_MODEL, OLLAMA_BASE_URL, OLLAMA_MODEL_CONTEXT_WINDOW, OLLAMA_MODEL_OUTPUT_WINDOW
    global OLLAMA_MODEL_INPUT_WINDOW, OLLAMA_MODEL_INPUT_TIER, OLLAMA_MODEL_MAX_TPM
    global OLLAMA_TEMPERATURE, OLLAMA_TOP_P, OLLAMA_TOP_K

    SESSION_ID = str(uuid.uuid4())

    yaml_config = load_yaml_config()

    OLLAMA = yaml_config.get("OLLAMA")
    if OLLAMA is not None and not isinstance(OLLAMA, dict):
        logger.error("OLLAMA configuration must be a mapping if present")
        raise RuntimeError("OLLAMA configuration must be a dict if present")

    MODEL = yaml_config.get("MODEL")
    MODEL_CONTEXT_WINDOW = yaml_config.get("MODEL_CONTEXT_WINDOW")
    MODEL_OUTPUT_WINDOW = yaml_config.get("MODEL_OUTPUT_WINDOW")

    if MODEL == "OLLAMA":
        if not isinstance(OLLAMA, dict):
            logger.error("MODEL is OLLAMA but top-level OLLAMA configuration is missing or invalid")
            raise RuntimeError("MODEL is OLLAMA but OLLAMA config is missing")
        ollama_model = OLLAMA.get("MODEL")
        if not isinstance(ollama_model, str) or not ollama_model.strip():
            logger.error("OLLAMA configuration requires a non-empty 'MODEL' string")
            raise RuntimeError("OLLAMA config missing MODEL")
        OLLAMA_MODEL = ollama_model.strip()
        ollama_base_url = OLLAMA.get("BASE_URL", "http://127.0.0.1:11434")
        if not isinstance(ollama_base_url, str) or not ollama_base_url.strip():
            logger.error("OLLAMA configuration 'BASE_URL' must be a non-empty string")
            raise RuntimeError("Invalid OLLAMA BASE_URL")
        OLLAMA_BASE_URL = ollama_base_url.strip()
        OLLAMA_TEMPERATURE = OLLAMA.get("TEMPERATURE")
        if not isinstance(OLLAMA_TEMPERATURE, (int, float)) and OLLAMA_TEMPERATURE is not None:
            logger.error("OLLAMA configuration 'TEMPERATURE' must be numeric when provided")
            raise RuntimeError("Invalid OLLAMA TEMPERATURE")
        OLLAMA_TOP_P = OLLAMA.get("TOP_P")
        if not isinstance(OLLAMA_TOP_P, (int, float)) and OLLAMA_TOP_P is not None:
            logger.error("OLLAMA configuration 'TOP_P' must be numeric when provided")
            raise RuntimeError("Invalid OLLAMA TOP_P")
        OLLAMA_TOP_K = OLLAMA.get("TOP_K")
        if not isinstance(OLLAMA_TOP_K, int) and OLLAMA_TOP_K is not None:
            logger.error("OLLAMA configuration 'TOP_K' must be an integer when provided")
            raise RuntimeError("Invalid OLLAMA TOP_K")
        (
            OLLAMA_MODEL_CONTEXT_WINDOW,
            OLLAMA_MODEL_OUTPUT_WINDOW,
            OLLAMA_MODEL_INPUT_WINDOW,
        ) = _derive_ollama_model_settings(OLLAMA, OLLAMA_MODEL)
        MODEL = f"ollama/{OLLAMA_MODEL}"
        MODEL_CONTEXT_WINDOW = OLLAMA_MODEL_CONTEXT_WINDOW
        MODEL_OUTPUT_WINDOW = OLLAMA_MODEL_OUTPUT_WINDOW
        MODEL_INPUT_WINDOW = OLLAMA_MODEL_INPUT_WINDOW
        MODEL_INPUT_TIER = None
        MODEL_MAX_TPM = None
        OLLAMA_MODEL_INPUT_TIER = None
        OLLAMA_MODEL_MAX_TPM = None
    else:
        OLLAMA_MODEL = None
        OLLAMA_BASE_URL = None
        OLLAMA_MODEL_CONTEXT_WINDOW = None
        OLLAMA_MODEL_OUTPUT_WINDOW = None
        OLLAMA_MODEL_INPUT_WINDOW = None
        OLLAMA_MODEL_INPUT_TIER = None
        OLLAMA_MODEL_MAX_TPM = None
        OLLAMA_TEMPERATURE = None
        OLLAMA_TOP_P = None
        OLLAMA_TOP_K = None

    # Safely compute input window
    if OLLAMA_MODEL is None:
        MODEL_INPUT_WINDOW = None
        if isinstance(MODEL_CONTEXT_WINDOW, int) and isinstance(MODEL_OUTPUT_WINDOW, int):
            iw = MODEL_CONTEXT_WINDOW - MODEL_OUTPUT_WINDOW
            if iw > 0:
                MODEL_INPUT_WINDOW = iw
            else:
                logger.warning(
                    f"Computed MODEL_INPUT_WINDOW <= 0 (context={MODEL_CONTEXT_WINDOW}, output={MODEL_OUTPUT_WINDOW}); disabling input budgeting"
                )
        else:
            logger.debug(
                f"Skipping MODEL_INPUT_WINDOW computation: MODEL_CONTEXT_WINDOW={MODEL_CONTEXT_WINDOW!r}, MODEL_OUTPUT_WINDOW={MODEL_OUTPUT_WINDOW!r}"
            )

    # MODEL_MAX_TPM, if it exists, will override the MODEL_INPUT_TIER
    # otherwise, MODEL_MAX_TPM will be set via MODEL_INPUT_TIER
    if OLLAMA_MODEL is None:
        MODEL_INPUT_TIER = yaml_config.get("MODEL_INPUT_TIER")
        MODEL_MAX_TPM = yaml_config.get("MODEL_MAX_TPM")
        if MODEL_MAX_TPM is None:
            # Guarded lookups: ensure reverse mapping and model_tpm_mapping are dicts before accessing,
            # and fall back to None if any lookup fails. This prevents runtime errors during startup.
            try:
                reversed_model = get_model_reverse_mapping().get(MODEL)
            except Exception as e:
                logger.error(
                    f"Failed to get reverse model mapping for MODEL '{MODEL}': {e}",
                    exc_info=True,
                )
                reversed_model = None

            model_tpm = None
            if isinstance(model_tpm_mapping, dict) and reversed_model in model_tpm_mapping:
                model_tpm = model_tpm_mapping.get(reversed_model)
            if isinstance(model_tpm, dict) and MODEL_INPUT_TIER in model_tpm:
                MODEL_MAX_TPM = model_tpm.get(MODEL_INPUT_TIER)
            else:
                # Could not determine MODEL_MAX_TPM from mappings; set to None to indicate unknown.
                logger.warning(
                    f"Could not determine MODEL_MAX_TPM for MODEL='{MODEL}', reversed_model='{reversed_model}', "
                    f"MODEL_INPUT_TIER='{MODEL_INPUT_TIER}'. MODEL_MAX_TPM set to None."
                )
                MODEL_MAX_TPM = None

    CONVERSATION_MAX_SIZE = yaml_config.get("CONVERSATION_MAX_SIZE")
    RATE_LIMITING_CONFIG = yaml_config.get(
        "rate_limiting",
        {
            "safety_factor": 0.6,
            "window_seconds": 60,
        },
    )
    STARTUP_TIME = time.strftime("%Y_%m_%d_%H_%M")

    history_config = yaml_config.get("history", {})
    HISTORY_FILE = _safe_expanduser(
        history_config.get("file", "~/.config/monitor/chat_history")
    )
    MAX_TOKEN_COUNT = MODEL_CONTEXT_WINDOW
    OLD_MAX_TOKEN_COUNT = MODEL_CONTEXT_WINDOW

    _followup_ratio_raw = yaml_config.get("FOLLOWUP_BASE_SAFETY_RATIO", 0.85)
    if (
        isinstance(_followup_ratio_raw, (int, float))
        and not isinstance(_followup_ratio_raw, bool)
        and 0 < float(_followup_ratio_raw) <= 1
    ):
        FOLLOWUP_BASE_SAFETY_RATIO = float(_followup_ratio_raw)
    else:
        logger.warning(
            "FOLLOWUP_BASE_SAFETY_RATIO=%r must be in (0, 1]; keeping default %.2f",
            _followup_ratio_raw,
            FOLLOWUP_BASE_SAFETY_RATIO,
        )

    _followup_top_raw = yaml_config.get("FOLLOWUP_TOPLEVEL_RESERVE_TOKENS", 256)
    try:
        _followup_top_val = int(_followup_top_raw)
        if _followup_top_val >= 0:
            FOLLOWUP_TOPLEVEL_RESERVE_TOKENS = _followup_top_val
        else:
            logger.warning(
                "FOLLOWUP_TOPLEVEL_RESERVE_TOKENS=%r must be >= 0; keeping default %d",
                _followup_top_raw,
                FOLLOWUP_TOPLEVEL_RESERVE_TOKENS,
            )
    except (TypeError, ValueError):
        logger.warning(
            "FOLLOWUP_TOPLEVEL_RESERVE_TOKENS=%r is not an integer; keeping default %d",
            _followup_top_raw,
            FOLLOWUP_TOPLEVEL_RESERVE_TOKENS,
        )

    _hidden_by_class_raw = yaml_config.get("FOLLOWUP_HIDDEN_CHAIN_RESERVE_BY_CLASS")
    if isinstance(_hidden_by_class_raw, dict):
        merged_hidden = dict(FOLLOWUP_HIDDEN_CHAIN_RESERVE_BY_CLASS)
        for key, value in _hidden_by_class_raw.items():
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                logger.warning(
                    "FOLLOWUP_HIDDEN_CHAIN_RESERVE_BY_CLASS[%r]=%r is not an integer; ignoring.",
                    key,
                    value,
                )
                continue
            if parsed < 0:
                logger.warning(
                    "FOLLOWUP_HIDDEN_CHAIN_RESERVE_BY_CLASS[%r]=%r must be >= 0; ignoring.",
                    key,
                    value,
                )
                continue
            merged_hidden[str(key)] = parsed
        FOLLOWUP_HIDDEN_CHAIN_RESERVE_BY_CLASS = merged_hidden
    elif _hidden_by_class_raw is not None:
        logger.warning(
            "FOLLOWUP_HIDDEN_CHAIN_RESERVE_BY_CLASS=%r is not a mapping; keeping defaults.",
            _hidden_by_class_raw,
        )

    _hidden_per_depth_raw = yaml_config.get("FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH", 1000)
    try:
        _hidden_per_depth_val = int(_hidden_per_depth_raw)
        if _hidden_per_depth_val >= 0:
            FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH = _hidden_per_depth_val
        else:
            logger.warning(
                "FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH=%r must be >= 0; keeping default %d",
                _hidden_per_depth_raw,
                FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH,
            )
    except (TypeError, ValueError):
        logger.warning(
            "FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH=%r is not an integer; keeping default %d",
            _hidden_per_depth_raw,
            FOLLOWUP_HIDDEN_CHAIN_RESERVE_PER_DEPTH,
        )

    _hidden_cap_ratio_raw = yaml_config.get("FOLLOWUP_HIDDEN_CHAIN_RESERVE_CAP_RATIO", 0.5)
    if (
        isinstance(_hidden_cap_ratio_raw, (int, float))
        and not isinstance(_hidden_cap_ratio_raw, bool)
        and 0 <= float(_hidden_cap_ratio_raw) <= 1
    ):
        FOLLOWUP_HIDDEN_CHAIN_RESERVE_CAP_RATIO = float(_hidden_cap_ratio_raw)
    else:
        logger.warning(
            "FOLLOWUP_HIDDEN_CHAIN_RESERVE_CAP_RATIO=%r must be in [0, 1]; keeping default %.2f",
            _hidden_cap_ratio_raw,
            FOLLOWUP_HIDDEN_CHAIN_RESERVE_CAP_RATIO,
        )

    macro_delims = yaml_config.get("macro_delimiters", {})
    MACRO_DELIMITER_OPEN = macro_delims.get("open", "{{")
    MACRO_DELIMITER_CLOSE = macro_delims.get("close", "}}")
    MACRO_DELIMITER_ESCAPE = macro_delims.get("escape", "\\")
    MACRO_FILE_PATH = _safe_expanduser(yaml_config.get("MACRO_FILE"))

    SUMMARIZATION_CONFIG = yaml_config.get(
        "summarization",
        {
            "triggers": {
                "token_threshold": 0.8,
                "memory_limit_mb": 100,
                "time_limit_seconds": 3600,
                "token_reduction_factor": 0.5,
                "safety_margin": 0.8,
            },
            "prompt": {
                "template": "Summarize the following conversation concisely, always using file paths that start in the current directory, for example ./, when capturing the main points and context: {messages}"
            },
        },
    )

    EXTERNAL_SERVICES = yaml_config.get("EXTERNAL_SERVICES", False)
    SHOW_COST_ESTIMATE = yaml_config.get("SHOW_COST_ESTIMATE", True)
    SUMMARY_TWITCH = yaml_config.get("SUMMARY_TWITCH", False)
    SUMMARY_LINKEDIN = yaml_config.get("SUMMARY_LINKEDIN", False)
    SUMMARY_TWITTER = yaml_config.get("SUMMARY_TWITTER", False)

    MEMORY_SERVICES = yaml_config.get("MEMORY_SERVICES", False)
    MEMORY_SHORT_TTL = yaml_config.get("MEMORY_SHORT_TTL", 3600)
    MEMORY_LONG_TTL = yaml_config.get("MEMORY_LONG_TTL", 14400)
    MEMORY_CONTEXT_MAX_ENTRIES = yaml_config.get("MEMORY_CONTEXT_MAX_ENTRIES", 20)
    SUBAGENT_MEMORY_SERVICES = yaml_config.get("SUBAGENT_MEMORY_SERVICES", False)
    # NOTE: Local Ollama config previously lived here and powered :query's
    # client-side RAG path. That path has been replaced by embedcodeserv's
    # /analyze endpoint (which runs Ollama server-side). The ``ollama``
    # block in YAML is now ignored — the harness no longer touches Ollama
    # directly.

    interactive_commands_path_cfg = yaml_config.get("INTERACTIVE_COMMANDS_PATH")
    INTERACTIVE_COMMANDS_PATH = _safe_expanduser(interactive_commands_path_cfg)

    non_interactive_commands_path_cfg = yaml_config.get("NON_INTERACTIVE_COMMANDS_PATH")
    NON_INTERACTIVE_COMMANDS_PATH = _safe_expanduser(non_interactive_commands_path_cfg)

    REDIS_HOST = os.getenv("REDIS_HOST", yaml_config.get("REDIS_HOST", "localhost"))

    PREFERENCE_PROMPT_FILE = _safe_expanduser(yaml_config.get("PREFERENCE_PROMPT_FILE"))

    REASONING_MODEL_PREFIX = yaml_config.get("REASONING_MODEL_PREFIX")
    REASONING_EFFORT = yaml_config.get("REASONING_EFFORT", "medium")
    REASONING_MAX_COMPLETION_TOKENS = yaml_config.get(
        "REASONING_MAX_COMPLETION_TOKENS", 25000
    )
    ESCALATE_REASONING_ON_TOOL_FAILURE = yaml_config.get(
        "ESCALATE_REASONING_ON_TOOL_FAILURE", True
    )
    _bump_effort_raw = yaml_config.get("REASONING_BUMP_EFFORT")
    if _bump_effort_raw is None:
        REASONING_BUMP_EFFORT = None
    # Floor for the effort of auto-bumped turns. Validate against known levels;
    # a typo silently sending a bad reasoning_effort to the provider is worse
    # than ignoring it.
    elif (
        isinstance(_bump_effort_raw, str)
        and _bump_effort_raw.lower() in {"minimal", "low", "medium", "high", "xhigh"}
    ):
        REASONING_BUMP_EFFORT = _bump_effort_raw.lower()
    else:
        logger.warning(
            "REASONING_BUMP_EFFORT=%r is not a valid effort level "
            "(minimal/low/medium/high/xhigh); ignoring.",
            _bump_effort_raw,
        )
        REASONING_BUMP_EFFORT = None

    # Optional single-turn reasoning-bump model swap. Unset → resolved to the
    # corresponding MODEL* value at the call site (llm_utils).
    _adv_reasoning_model_raw = yaml_config.get("ADV_REASONING_MODEL")
    if isinstance(_adv_reasoning_model_raw, str) and _adv_reasoning_model_raw.strip():
        _adv_reasoning_model = _adv_reasoning_model_raw.strip()
        _adv_reasoning_model_lc = _adv_reasoning_model.lower()
        if _adv_reasoning_model_lc == "ollama" or _adv_reasoning_model_lc.startswith("ollama/"):
            logger.error(
                f"ADV_REASONING_MODEL {_adv_reasoning_model!r} cannot resolve to Ollama or an ollama/<model> string"
            )
            raise RuntimeError("ADV_REASONING_MODEL may not target Ollama")
        ADV_REASONING_MODEL = _adv_reasoning_model
    else:
        ADV_REASONING_MODEL = _adv_reasoning_model_raw
    ADV_REASONING_MODEL_OUTPUT_WINDOW = yaml_config.get("ADV_REASONING_MODEL_OUTPUT_WINDOW")
    COMMIT_MODEL = yaml_config.get("COMMIT_MODEL")
    COMMIT_REASONING_EFFORT = yaml_config.get("COMMIT_REASONING_EFFORT")
    COMMIT_REASONING_MAX_COMPLETION_TOKENS = yaml_config.get(
        "COMMIT_REASONING_MAX_COMPLETION_TOKENS"
    )
    # Role-based model overrides (smart orchestration). Applied post-load by
    # apply_role_model_override() once config.AGENT is resolved.
    ORCHESTRATOR_MODEL = yaml_config.get("ORCHESTRATOR_MODEL")
    ORCHESTRATOR_REASONING_EFFORT = yaml_config.get("ORCHESTRATOR_REASONING_EFFORT")
    SUBAGENT_MODEL = yaml_config.get("SUBAGENT_MODEL")
    SUBAGENT_REASONING_EFFORT = yaml_config.get("SUBAGENT_REASONING_EFFORT")
    RESPONSES_API = yaml_config.get("RESPONSES_API")
    _tool_profile_raw = yaml_config.get("TOOL_PROFILE", "coding")
    if isinstance(_tool_profile_raw, str) and _tool_profile_raw.strip().lower() in {
        "minimal", "coding", "review", "full"
    }:
        TOOL_PROFILE = _tool_profile_raw.strip().lower()
    else:
        if _tool_profile_raw is not None:
            logger.warning(
                "TOOL_PROFILE=%r is invalid; keeping default %r.",
                _tool_profile_raw,
                TOOL_PROFILE,
            )
        TOOL_PROFILE = "coding"
    ENABLE_TOOL_PROFILE_AUTO_WIDEN = bool(
        yaml_config.get("ENABLE_TOOL_PROFILE_AUTO_WIDEN", True)
    )
    _tool_profile_turns_raw = yaml_config.get("TOOL_PROFILE_AUTO_WIDEN_TURNS")
    if _tool_profile_turns_raw is not None:
        try:
            TOOL_PROFILE_AUTO_WIDEN_TURNS = max(0, int(_tool_profile_turns_raw))
        except (TypeError, ValueError):
            logger.warning(
                "TOOL_PROFILE_AUTO_WIDEN_TURNS=%r is not an integer; keeping default %d",
                _tool_profile_turns_raw,
                TOOL_PROFILE_AUTO_WIDEN_TURNS,
            )
    TOOL_PROFILE_AUTO_WIDEN_REFRESH_ON_USE = bool(
        yaml_config.get("TOOL_PROFILE_AUTO_WIDEN_REFRESH_ON_USE", True)
    )
    _tool_profile_max_groups_raw = yaml_config.get("TOOL_PROFILE_AUTO_WIDEN_MAX_ACTIVE_GROUPS")
    if _tool_profile_max_groups_raw is not None:
        try:
            TOOL_PROFILE_AUTO_WIDEN_MAX_ACTIVE_GROUPS = max(
                0, int(_tool_profile_max_groups_raw)
            )
        except (TypeError, ValueError):
            logger.warning(
                "TOOL_PROFILE_AUTO_WIDEN_MAX_ACTIVE_GROUPS=%r is not an integer; keeping default %d",
                _tool_profile_max_groups_raw,
                TOOL_PROFILE_AUTO_WIDEN_MAX_ACTIVE_GROUPS,
            )
    _tool_profile_turns_by_group_raw = yaml_config.get("TOOL_PROFILE_AUTO_WIDEN_TURNS_BY_GROUP")
    TOOL_PROFILE_AUTO_WIDEN_TURNS_BY_GROUP = {}
    if isinstance(_tool_profile_turns_by_group_raw, dict):
        for _group, _raw_turns in _tool_profile_turns_by_group_raw.items():
            if not isinstance(_group, str) or not _group.strip():
                continue
            try:
                TOOL_PROFILE_AUTO_WIDEN_TURNS_BY_GROUP[_group.strip().lower()] = max(
                    0, int(_raw_turns)
                )
            except (TypeError, ValueError):
                logger.warning(
                    "TOOL_PROFILE_AUTO_WIDEN_TURNS_BY_GROUP[%r]=%r is not an integer; ignoring entry.",
                    _group,
                    _raw_turns,
                )
    elif _tool_profile_turns_by_group_raw is not None:
        logger.warning(
            "TOOL_PROFILE_AUTO_WIDEN_TURNS_BY_GROUP=%r is not a mapping; keeping default {}.",
            _tool_profile_turns_by_group_raw,
        )
    _tool_profile_disabled_groups_raw = yaml_config.get("TOOL_PROFILE_AUTO_WIDEN_DISABLED_GROUPS")
    TOOL_PROFILE_AUTO_WIDEN_DISABLED_GROUPS = []
    if isinstance(_tool_profile_disabled_groups_raw, list):
        TOOL_PROFILE_AUTO_WIDEN_DISABLED_GROUPS = [
            entry.strip().lower()
            for entry in _tool_profile_disabled_groups_raw
            if isinstance(entry, str) and entry.strip()
        ]
    elif _tool_profile_disabled_groups_raw is not None:
        logger.warning(
            "TOOL_PROFILE_AUTO_WIDEN_DISABLED_GROUPS=%r is not a list; keeping default [].",
            _tool_profile_disabled_groups_raw,
        )
    SHOW_TOOL_PROFILE_NOTICES = bool(
        yaml_config.get("SHOW_TOOL_PROFILE_NOTICES", True)
    )
    CURRENT_TURN_TOOL_GROUPS = set()
    TOOL_PROFILE_GROUP_LEASES = {}

    ARTIFACT_SERVER = os.getenv(
        "ARTIFACT_SERVER", yaml_config.get("ARTIFACT_SERVER", "http://localhost:2323/")
    )

    # Global list to store jokes told previously
    JOKES_FILE = _safe_expanduser(yaml_config.get("JOKES_FILE"))

    DIRECTIVES_DIR = _safe_expanduser(yaml_config.get("DIRECTIVES_DIR"))
    if DIRECTIVES_DIR:
        os.environ["DIRECTIVES_DIR"] = DIRECTIVES_DIR

    # embedcodeserv (single set of knobs for the unified indexing/retrieval/RAG
    # service that backs :embed, :index, :query). Env vars override YAML.
    EMBEDCODESERV_HOST = os.getenv(
        "EMBEDCODESERV_HOST", yaml_config.get("EMBEDCODESERV_HOST", "localhost")
    )
    EMBEDCODESERV_PORT = os.getenv(
        "EMBEDCODESERV_PORT", yaml_config.get("EMBEDCODESERV_PORT", "5010")
    )
    raw_timeout = os.getenv(
        "EMBEDCODESERV_TIMEOUT", yaml_config.get("EMBEDCODESERV_TIMEOUT", 90)
    )
    try:
        EMBEDCODESERV_TIMEOUT = int(raw_timeout)
    except Exception:
        logger.warning("Invalid EMBEDCODESERV_TIMEOUT value %r; defaulting to 90", raw_timeout)
        EMBEDCODESERV_TIMEOUT = 90
    ENABLE_AUTO_SUMMARIZE_ON_LIMIT = yaml_config.get("ENABLE_AUTO_SUMMARIZE_ON_LIMIT")
    SESSIONS_FOLDER = yaml_config.get("SESSIONS_FOLDER", SESSIONS_FOLDER)

    # Override the soft auto-compaction threshold from YAML if provided. Clamp
    # to (0, 1] to keep the trigger sane — 0 or negative would compact on
    # every turn, > 1 would never fire. Invalid values fall back to the
    # module-level default (0.30).
    global AUTO_COMPACT_THRESHOLD_RATIO, AUTO_COMPACT_THRESHOLD_RATIO_BY_MODEL
    _ratio_raw = yaml_config.get("AUTO_COMPACT_THRESHOLD_RATIO")
    if _ratio_raw is not None:
        try:
            _ratio_val = float(_ratio_raw)
            if 0.0 < _ratio_val <= 1.0:
                AUTO_COMPACT_THRESHOLD_RATIO = _ratio_val
            else:
                logger.warning(
                    "AUTO_COMPACT_THRESHOLD_RATIO=%r outside (0, 1]; keeping default %s",
                    _ratio_raw, AUTO_COMPACT_THRESHOLD_RATIO,
                )
        except (TypeError, ValueError):
            logger.warning(
                "AUTO_COMPACT_THRESHOLD_RATIO=%r is not a number; keeping default %s",
                _ratio_raw, AUTO_COMPACT_THRESHOLD_RATIO,
            )

    # Per-model overrides. Validate each entry independently; a bad entry is
    # dropped (warned) so the model falls back to the scalar default rather than
    # taking a garbage ratio.
    AUTO_COMPACT_THRESHOLD_RATIO_BY_MODEL = {}
    _ratio_map_raw = yaml_config.get("AUTO_COMPACT_THRESHOLD_RATIO_BY_MODEL")
    if _ratio_map_raw is not None:
        if isinstance(_ratio_map_raw, dict):
            for _m, _r in _ratio_map_raw.items():
                try:
                    _rv = float(_r)
                except (TypeError, ValueError):
                    logger.warning(
                        "AUTO_COMPACT_THRESHOLD_RATIO_BY_MODEL[%r]=%r is not a number; ignoring entry",
                        _m, _r,
                    )
                    continue
                if 0.0 < _rv <= 1.0:
                    AUTO_COMPACT_THRESHOLD_RATIO_BY_MODEL[_m] = _rv
                else:
                    logger.warning(
                        "AUTO_COMPACT_THRESHOLD_RATIO_BY_MODEL[%r]=%r outside (0, 1]; ignoring entry",
                        _m, _r,
                    )
        else:
            logger.warning(
                "AUTO_COMPACT_THRESHOLD_RATIO_BY_MODEL is not a dict (%s); ignoring",
                type(_ratio_map_raw).__name__,
            )

    # F: fuel-tank cap — optional MANUAL OVERRIDE (exact token count). Positive
    # int pins the cap; null/0/invalid leaves it unset so the cap derives from
    # DAILY_COST_TARGET_USD instead.
    global SESSION_TOKEN_BUDGET
    _budget_raw = yaml_config.get("SESSION_TOKEN_BUDGET")
    if _budget_raw is not None:
        try:
            _budget_val = int(_budget_raw)
            if _budget_val > 0:
                SESSION_TOKEN_BUDGET = _budget_val
            else:
                SESSION_TOKEN_BUDGET = None  # 0/negative → derive from dollar target
        except (TypeError, ValueError):
            logger.warning(
                "SESSION_TOKEN_BUDGET=%r is not an integer; ignoring (will derive)",
                _budget_raw,
            )

    # Dollar/day target the F: gauge sizes its token cap from.
    global DAILY_COST_TARGET_USD
    _target_raw = yaml_config.get("DAILY_COST_TARGET_USD")
    if _target_raw is not None:
        try:
            DAILY_COST_TARGET_USD = float(_target_raw)
        except (TypeError, ValueError):
            logger.warning(
                "DAILY_COST_TARGET_USD=%r is not a number; keeping default %s",
                _target_raw, DAILY_COST_TARGET_USD,
            )

    # Per-model measured rate map / anchor / default / effort multipliers. Dicts
    # and scalars are taken as-is when present (shallow-validated).
    global MODEL_TOKEN_RATE_PER_MTOK, TOKEN_RATE_ANCHOR_MODEL
    global DEFAULT_TOKEN_RATE_PER_MTOK, REASONING_EFFORT_RATE_MULTIPLIER
    _rate_map = yaml_config.get("MODEL_TOKEN_RATE_PER_MTOK")
    if isinstance(_rate_map, dict):
        MODEL_TOKEN_RATE_PER_MTOK = _rate_map
    _anchor = yaml_config.get("TOKEN_RATE_ANCHOR_MODEL")
    if isinstance(_anchor, str) and _anchor:
        TOKEN_RATE_ANCHOR_MODEL = _anchor
    _default_rate = yaml_config.get("DEFAULT_TOKEN_RATE_PER_MTOK")
    if _default_rate is not None:
        try:
            DEFAULT_TOKEN_RATE_PER_MTOK = float(_default_rate)
        except (TypeError, ValueError):
            logger.warning(
                "DEFAULT_TOKEN_RATE_PER_MTOK=%r is not a number; keeping default %s",
                _default_rate, DEFAULT_TOKEN_RATE_PER_MTOK,
            )
    _effort_mult = yaml_config.get("REASONING_EFFORT_RATE_MULTIPLIER")
    if isinstance(_effort_mult, dict):
        REASONING_EFFORT_RATE_MULTIPLIER = _effort_mult

    # Override RECENT_TURNS_PRESERVED_ON_COMPACT from YAML if provided. Clamp
    # to >= 1 (zero would preserve nothing, defeating the purpose). Invalid
    # values fall back to the module-level default.
    global RECENT_TURNS_PRESERVED_ON_COMPACT
    _k_raw = yaml_config.get("RECENT_TURNS_PRESERVED_ON_COMPACT")
    if _k_raw is not None:
        try:
            _k_val = int(_k_raw)
            if _k_val >= 1:
                RECENT_TURNS_PRESERVED_ON_COMPACT = _k_val
            else:
                logger.warning(
                    "RECENT_TURNS_PRESERVED_ON_COMPACT=%r must be >= 1; keeping default %d",
                    _k_raw, RECENT_TURNS_PRESERVED_ON_COMPACT,
                )
        except (TypeError, ValueError):
            logger.warning(
                "RECENT_TURNS_PRESERVED_ON_COMPACT=%r is not an integer; keeping default %d",
                _k_raw, RECENT_TURNS_PRESERVED_ON_COMPACT,
            )

    # Override RESPONSES_CHAIN_TIER_TOKENS from YAML if provided. Must be a
    # positive integer (the absolute long-context cost cliff, in tokens).
    # Invalid values fall back to the module-level default.
    global RESPONSES_CHAIN_TIER_TOKENS
    _tier_raw = yaml_config.get("RESPONSES_CHAIN_TIER_TOKENS")
    if _tier_raw is not None:
        try:
            _tier_val = int(_tier_raw)
            if _tier_val > 0:
                RESPONSES_CHAIN_TIER_TOKENS = _tier_val
            else:
                logger.warning(
                    "RESPONSES_CHAIN_TIER_TOKENS=%r must be > 0; keeping default %d",
                    _tier_raw, RESPONSES_CHAIN_TIER_TOKENS,
                )
        except (TypeError, ValueError):
            logger.warning(
                "RESPONSES_CHAIN_TIER_TOKENS=%r is not an integer; keeping default %d",
                _tier_raw, RESPONSES_CHAIN_TIER_TOKENS,
            )

    # Override OLD_TOOL_BODY_TURNS_THRESHOLD from YAML. Same clamp shape as
    # the related thresholds — must be >= 1 (zero would demote everything,
    # including the in-flight turn). Invalid values fall back to the default.
    # Override MAX_COMPLETION_TOKENS from YAML. Must be a positive integer.
    # Invalid values fall back to the module-level default.
    global MAX_COMPLETION_TOKENS
    _mct_raw = yaml_config.get("MAX_COMPLETION_TOKENS")
    if _mct_raw is not None:
        try:
            _mct_val = int(_mct_raw)
            if _mct_val >= 1:
                MAX_COMPLETION_TOKENS = _mct_val
            else:
                logger.warning(
                    "MAX_COMPLETION_TOKENS=%r must be >= 1; keeping default %d",
                    _mct_raw, MAX_COMPLETION_TOKENS,
                )
        except (TypeError, ValueError):
            logger.warning(
                "MAX_COMPLETION_TOKENS=%r is not an integer; keeping default %d",
                _mct_raw, MAX_COMPLETION_TOKENS,
            )

    # Override the four cost-color thresholds from YAML. Each must be a
    # positive number (USD); invalid values fall back to the module-level
    # defaults so a typo never silently kills the color signal.
    global COST_P_YELLOW, COST_P_RED, COST_W_YELLOW, COST_W_RED
    for _key, _attr_name in (
        ("COST_P_YELLOW", "COST_P_YELLOW"),
        ("COST_P_RED", "COST_P_RED"),
        ("COST_W_YELLOW", "COST_W_YELLOW"),
        ("COST_W_RED", "COST_W_RED"),
    ):
        _raw = yaml_config.get(_key)
        if _raw is None:
            continue
        try:
            _val = float(_raw)
            if _val > 0:
                globals()[_attr_name] = _val
            else:
                logger.warning(
                    "%s=%r must be > 0; keeping default %s",
                    _key, _raw, globals()[_attr_name],
                )
        except (TypeError, ValueError):
            logger.warning(
                "%s=%r is not a number; keeping default %s",
                _key, _raw, globals()[_attr_name],
            )

    # YAML ``model_pricing:`` block → MODEL_PRICING_OVERRIDES. YAML uses the
    # user-friendly per-million-tokens form; we convert to per-token here so
    # the lookup site can multiply directly without recomputing rates.
    # Format:
    #   model_pricing:
    #     "xai/grok-build-0.1":
    #       input_per_million_tokens:        1.00
    #       cached_input_per_million_tokens: 0.20
    #       output_per_million_tokens:       2.00
    global MODEL_PRICING_OVERRIDES
    _raw_pricing = yaml_config.get("model_pricing")
    if isinstance(_raw_pricing, dict):
        _overrides = {}
        for _model_name, _rates in _raw_pricing.items():
            if not isinstance(_model_name, str) or not isinstance(_rates, dict):
                logger.warning(
                    "model_pricing entry %r is malformed (must be dict of rates); skipping",
                    _model_name,
                )
                continue
            _per_token = {}
            for _src, _dst in (
                ("input_per_million_tokens", "input_per_token"),
                ("cached_input_per_million_tokens", "cached_input_per_token"),
                ("output_per_million_tokens", "output_per_token"),
            ):
                _val = _rates.get(_src)
                if isinstance(_val, (int, float)) and _val >= 0:
                    _per_token[_dst] = float(_val) / 1_000_000
                elif _val is not None:
                    logger.warning(
                        "model_pricing[%r].%s=%r is not a non-negative number; ignoring",
                        _model_name, _src, _val,
                    )
            if _per_token:
                _overrides[_model_name] = _per_token
        MODEL_PRICING_OVERRIDES = _overrides

    global OLD_TOOL_BODY_TURNS_THRESHOLD
    _demote_raw = yaml_config.get("OLD_TOOL_BODY_TURNS_THRESHOLD")
    if _demote_raw is not None:
        try:
            _demote_val = int(_demote_raw)
            if _demote_val >= 1:
                OLD_TOOL_BODY_TURNS_THRESHOLD = _demote_val
            else:
                logger.warning(
                    "OLD_TOOL_BODY_TURNS_THRESHOLD=%r must be >= 1; keeping default %d",
                    _demote_raw, OLD_TOOL_BODY_TURNS_THRESHOLD,
                )
        except (TypeError, ValueError):
            logger.warning(
                "OLD_TOOL_BODY_TURNS_THRESHOLD=%r is not an integer; keeping default %d",
                _demote_raw, OLD_TOOL_BODY_TURNS_THRESHOLD,
            )

    # Blast-radius cap for write tools. YAML override goes through the
    # same shape as OLD_TOOL_BODY_TURNS_THRESHOLD: int parse, range check,
    # warn-and-keep-default on bad input. 0 is allowed (disables the cap).
    global MAX_FILE_WRITE_BYTES
    _write_cap_raw = yaml_config.get("MAX_FILE_WRITE_BYTES")
    if _write_cap_raw is not None:
        try:
            _write_cap_val = int(_write_cap_raw)
            if _write_cap_val >= 0:
                MAX_FILE_WRITE_BYTES = _write_cap_val
            else:
                logger.warning(
                    "MAX_FILE_WRITE_BYTES=%r must be >= 0; keeping default %d",
                    _write_cap_raw, MAX_FILE_WRITE_BYTES,
                )
        except (TypeError, ValueError):
            logger.warning(
                "MAX_FILE_WRITE_BYTES=%r is not an integer; keeping default %d",
                _write_cap_raw, MAX_FILE_WRITE_BYTES,
            )

    # Per-tool serialized output cap before the result is fed back into the
    # next model request. 0 disables truncation. Invalid values fall back to
    # the module-level default.
    _tool_output_limit_raw = yaml_config.get("TOOL_OUTPUT_TOKEN_LIMIT")
    if _tool_output_limit_raw is not None:
        try:
            _tool_output_limit_val = int(_tool_output_limit_raw)
            if _tool_output_limit_val >= 0:
                TOOL_OUTPUT_TOKEN_LIMIT = _tool_output_limit_val
            else:
                logger.warning(
                    "TOOL_OUTPUT_TOKEN_LIMIT=%r must be >= 0; keeping default %d",
                    _tool_output_limit_raw, TOOL_OUTPUT_TOKEN_LIMIT,
                )
        except (TypeError, ValueError):
            logger.warning(
                "TOOL_OUTPUT_TOKEN_LIMIT=%r is not an integer; keeping default %d",
                _tool_output_limit_raw, TOOL_OUTPUT_TOKEN_LIMIT,
            )

    SERVER_MODE = yaml_config.get("SERVER_MODE")
    AGENT = yaml_config.get("AGENT", False)

    # Allow MONITOR_AGENT env var to override YAML when present.
    # Accept truthy values: '1', 'true', 'yes', 'on' (case-insensitive).
    try:
        _agent_env_val = os.getenv("MONITOR_AGENT")
    except Exception as _e:
        logger.error(f"Error reading MONITOR_AGENT environment variable: {_e}", exc_info=True)
        raise
    if _agent_env_val is not None:
        try:
            AGENT = str(_agent_env_val).strip().lower() in ("1", "true", "yes", "on")
        except Exception as _e:
            logger.error(f"Error parsing MONITOR_AGENT environment variable: {_e}", exc_info=True)
            raise

    # MONITOR_ENABLE_AGENT_ORCHESTRATION (bool) - enable orchestration features for agents.
    # Read from YAML default and allow environment override (truthy values '1','true','yes','on').
    try:
        MONITOR_ENABLE_AGENT_ORCHESTRATION = yaml_config.get("MONITOR_ENABLE_AGENT_ORCHESTRATION", False)
    except Exception as e:
        logger.error(f"Error reading MONITOR_ENABLE_AGENT_ORCHESTRATION from YAML: {e}", exc_info=True)
        raise
    try:
        _agent_orch_env = os.getenv("MONITOR_ENABLE_AGENT_ORCHESTRATION")
    except Exception as _e:
        logger.error(f"Error reading MONITOR_ENABLE_AGENT_ORCHESTRATION environment variable: {_e}", exc_info=True)
        raise
    if _agent_orch_env is not None:
        try:
            MONITOR_ENABLE_AGENT_ORCHESTRATION = str(_agent_orch_env).strip().lower() in ("1", "true", "yes", "on")
        except Exception as _e:
            logger.error(f"Error parsing MONITOR_ENABLE_AGENT_ORCHESTRATION environment variable: {_e}", exc_info=True)
            raise

    # SUBAGENT_WRITE_ACCESS (str) - write capability policy for sub-agents.
    # Environment overrides YAML. Accepted values: none, delegated, full.
    try:
        _subagent_write_access_raw = os.getenv(
            "SUBAGENT_WRITE_ACCESS",
            yaml_config.get("SUBAGENT_WRITE_ACCESS", "none"),
        )
    except Exception as e:
        logger.error(f"Error reading SUBAGENT_WRITE_ACCESS configuration: {e}", exc_info=True)
        raise

    try:
        _subagent_write_access = str(_subagent_write_access_raw).strip().lower()
    except Exception as e:
        logger.error(f"Error parsing SUBAGENT_WRITE_ACCESS value: {e}", exc_info=True)
        raise

    if _subagent_write_access in {"none", "delegated", "full"}:
        SUBAGENT_WRITE_ACCESS = _subagent_write_access
    else:
        logger.warning(
            "Invalid SUBAGENT_WRITE_ACCESS value %r; defaulting to 'none'",
            _subagent_write_access_raw,
        )
        SUBAGENT_WRITE_ACCESS = "none"

    # MONITOR_AGENT_DEPTH (int) - controls the agent recursion/depth behavior.
    # MONITOR_AGENT_MAX_DEPTH (int) - maximum allowed depth for agent operations.
    # Read from environment variables if present; otherwise fall back to YAML defaults (0 and 1).
    try:
        raw_agent_depth = os.getenv("MONITOR_AGENT_DEPTH", yaml_config.get("MONITOR_AGENT_DEPTH", 0))
    except Exception as e:
        logger.error(f"Error reading MONITOR_AGENT_DEPTH environment variable: {e}", exc_info=True)
        raise
    try:
        MONITOR_AGENT_DEPTH = int(raw_agent_depth)
    except Exception:
        logger.warning("Invalid MONITOR_AGENT_DEPTH value %r; defaulting to 0", raw_agent_depth)
        try:
            MONITOR_AGENT_DEPTH = int(yaml_config.get("MONITOR_AGENT_DEPTH", 0))
        except Exception:
            MONITOR_AGENT_DEPTH = 0

    try:
        raw_agent_max_depth = os.getenv("MONITOR_AGENT_MAX_DEPTH", yaml_config.get("MONITOR_AGENT_MAX_DEPTH", 1))
    except Exception as e:
        logger.error(f"Error reading MONITOR_AGENT_MAX_DEPTH environment variable: {e}", exc_info=True)
        raise
    try:
        MONITOR_AGENT_MAX_DEPTH = int(raw_agent_max_depth)
    except Exception:
        logger.warning("Invalid MONITOR_AGENT_MAX_DEPTH value %r; defaulting to 1", raw_agent_max_depth)
        try:
            MONITOR_AGENT_MAX_DEPTH = int(yaml_config.get("MONITOR_AGENT_MAX_DEPTH", 1))
        except Exception:
            MONITOR_AGENT_MAX_DEPTH = 1

    # MONITOR_AGENT_MAX_BREADTH (int) - max concurrent sub-agents (0 disables).
    # MONITOR_AGENT_MAX_TOTAL  (int) - max sub-agents per session (0 disables).
    # MONITOR_AGENT_HEARTBEAT_TIMEOUT (number, seconds) - mark a silent sub-agent
    # dirty (crashed/hung) after this long. env overrides config.yaml; both fall
    # back to the safe code defaults (1, 1, 45). Same env-over-YAML pattern as
    # the depth keys above.
    def _agent_int(key, default):
        try:
            raw = os.getenv(key, yaml_config.get(key, default))
            return int(raw)
        except Exception:
            logger.warning("Invalid %s value; defaulting to %r", key, default)
            return default

    MONITOR_AGENT_MAX_BREADTH = _agent_int("MONITOR_AGENT_MAX_BREADTH", 1)
    MONITOR_AGENT_MAX_TOTAL = _agent_int("MONITOR_AGENT_MAX_TOTAL", 1)
    try:
        MONITOR_AGENT_HEARTBEAT_TIMEOUT = float(
            os.getenv("MONITOR_AGENT_HEARTBEAT_TIMEOUT",
                      yaml_config.get("MONITOR_AGENT_HEARTBEAT_TIMEOUT", 45))
        )
    except Exception:
        logger.warning("Invalid MONITOR_AGENT_HEARTBEAT_TIMEOUT value; defaulting to 45")
        MONITOR_AGENT_HEARTBEAT_TIMEOUT = 45.0

    try:
        MONITOR_AGENT_IDLE_TIMEOUT = float(
            os.getenv("MONITOR_AGENT_IDLE_TIMEOUT",
                      yaml_config.get("MONITOR_AGENT_IDLE_TIMEOUT", 300))
        )
    except Exception:
        logger.warning("Invalid MONITOR_AGENT_IDLE_TIMEOUT value; defaulting to 300")
        MONITOR_AGENT_IDLE_TIMEOUT = 300.0

    TWITTER_CLIENT_API = os.getenv(
        "TWITTER_CLIENT_API",
        yaml_config.get("TWITTER_CLIENT_API", "http://localhost:7070/twitter/tweet"),
    )
    TWITCH_CLIENT_API = os.getenv(
        "TWITCH_CLIENT_API",
        yaml_config.get("TWITCH_CLIENT_API", "http://localhost:5050/send_message"),
    )
    LINKEDIN_CLIENT_API = os.getenv(
        "LINKEDIN_CLIENT_API",
        yaml_config.get("LINKEDIN_CLIENT_API", "http://localhost:6060/linkedin/article"),
    )

    # Parse DEFAULT_EXCLUDE_EXTENSIONS from environment variable if provided as a comma-separated string.
    # If the environment variable is absent or empty (after trimming), fall back to the YAML config/default.
    try:
        env_default_exclude_ext = os.getenv("DEFAULT_EXCLUDE_EXTENSIONS")
    except Exception as e:
        logger.error(f"Error reading DEFAULT_EXCLUDE_EXTENSIONS environment variable: {e}", exc_info=True)
        raise

    if env_default_exclude_ext is not None and env_default_exclude_ext.strip() != "":
        try:
            parsed_exts = [part.strip() for part in env_default_exclude_ext.split(",") if part.strip() != ""]
            if parsed_exts:
                DEFAULT_EXCLUDE_EXTENSIONS = parsed_exts
            else:
                DEFAULT_EXCLUDE_EXTENSIONS = yaml_config.get(
                    "DEFAULT_EXCLUDE_EXTENSIONS",
                    [
                        "png",
                        "jpg",
                        "jpeg",
                        "gif",
                        "pdf",
                        "zip",
                        "sqlite",
                        "db",
                        "lock",
                        "xcodeproj",
                        "storyboard",
                        "xib",
                        "bundle"
                    ]
                )
        except Exception as e:
            logger.error(f"Failed to parse DEFAULT_EXCLUDE_EXTENSIONS environment variable: {e}", exc_info=True)
            raise RuntimeError("Failed to parse DEFAULT_EXCLUDE_EXTENSIONS environment variable") from e
    else:
        DEFAULT_EXCLUDE_EXTENSIONS = yaml_config.get(
            "DEFAULT_EXCLUDE_EXTENSIONS",
            [
                "png",
                "jpg",
                "jpeg",
                "gif",
                "pdf",
                "zip",
                "sqlite",
                "db",
                "lock",
                "xcodeproj",
                "storyboard",
                "xib",
                "bundle"
            ]
        )

    # Parse DEFAULT_EXCLUDE_GLOBS from environment variable if provided as a comma-separated string.
    # If the environment variable is absent or empty (after trimming), fall back to the YAML config/default.
    try:
        env_default_exclude_globs = os.getenv("DEFAULT_EXCLUDE_GLOBS")
    except Exception as e:
        logger.error(f"Error reading DEFAULT_EXCLUDE_GLOBS environment variable: {e}", exc_info=True)
        raise

    if env_default_exclude_globs is not None and env_default_exclude_globs.strip() != "":
        try:
            parsed_globs = [part.strip() for part in env_default_exclude_globs.split(",") if part.strip() != ""]
            if parsed_globs:
                DEFAULT_EXCLUDE_GLOBS = parsed_globs
            else:
                DEFAULT_EXCLUDE_GLOBS = yaml_config.get(
                    "DEFAULT_EXCLUDE_GLOBS",
                    [
                        "node_modules/**",
                        ".venv/**",
                        "dist/**",
                        "build/**",
                        "Pods/**"
                    ]
                )
        except Exception as e:
            logger.error(f"Failed to parse DEFAULT_EXCLUDE_GLOBS environment variable: {e}", exc_info=True)
            raise RuntimeError("Failed to parse DEFAULT_EXCLUDE_GLOBS environment variable") from e
    else:
        DEFAULT_EXCLUDE_GLOBS = yaml_config.get(
            "DEFAULT_EXCLUDE_GLOBS",
            [
                "node_modules/**",
                ".venv/**",
                "dist/**",
                "build/**",
                "Pods/**"
            ]
        )

    try:
        FUNCTION_KEY_INSERTIONS = load_function_keys_config()
    except Exception as e:
        logger.error(f"Failed to load function keys config: {e}", exc_info=True)
        raise
    try:
        configure_function_key_insertions(FUNCTION_KEY_INSERTIONS)
    except Exception as e:
        logger.error(f"Failed to configure function key insertions: {e}", exc_info=True)
        raise

LOGGING_CONFIG = None
LOGGING_LEVEL = None
LOG_FORMAT = None
LOG_DATE_FORMAT = None
LOG_MAX_BYTES = None
LOG_BACKUP_COUNT = None
CONSOLE_LOGGING_ENABLED = None
LOG_DIR = None
LOG_FILE_PATH = None
CONVERSATION_LOG_FILENAME = None
CONVERSATION_LOG_FILE = None


def configure_logging_globals():
    global LOGGING_CONFIG, LOGGING_LEVEL, LOG_FORMAT, LOG_DATE_FORMAT, LOG_MAX_BYTES, LOG_BACKUP_COUNT
    global CONSOLE_LOGGING_ENABLED, LOG_DIR, LOG_FILE_PATH, CONVERSATION_LOG_FILENAME, CONVERSATION_LOG_FILE

    try:
        LOGGING_CONFIG = get_logging_config()
    except Exception as e:
        logger.error(f"Failed to get logging config: {e}", exc_info=True)
        raise

    if not LOGGING_CONFIG["log_dir"]:
        raise RuntimeError(
            "LOG_DIR (log_dir) is missing in config.yaml and no default could be set."
        )
    if not LOGGING_CONFIG["app_log_filename"]:
        raise RuntimeError(
            "APP_LOG_FILENAME (app_log_filename) is missing in config.yaml and no default could be set."
        )
    if not LOGGING_CONFIG["format"]:
        raise RuntimeError(
            "LOG_FORMAT (format) is missing in config.yaml and no default could be set."
        )
    if not LOGGING_CONFIG["level"]:
        raise RuntimeError(
            "LOGGING_LEVEL (level) is missing in config.yaml and no default could be set."
        )
    if not LOGGING_CONFIG["encoding"]:
        raise RuntimeError(
            "LOG_ENCODING (encoding) is missing in config.yaml and no default could be set."
        )

    LOG_ENCODING = LOGGING_CONFIG.get("encoding")
    LOGGING_LEVEL = os.getenv("LOGGING_LEVEL", LOGGING_CONFIG["level"]).upper()
    LOG_FORMAT = LOGGING_CONFIG["format"]
    LOG_DATE_FORMAT = LOGGING_CONFIG["date_format"]
    LOG_MAX_BYTES = LOGGING_CONFIG["max_bytes"]
    LOG_BACKUP_COUNT = LOGGING_CONFIG["backup_count"]
    CONSOLE_LOGGING_ENABLED = (
        LOGGING_CONFIG["console_logging_enabled"]
        if LOGGING_CONFIG["console_logging_enabled"] is not None
        else True
    )
    LOG_DIR = LOGGING_CONFIG["log_dir"]
    try:
        if not os.path.exists(LOG_DIR):
            try:
                os.makedirs(LOG_DIR)
            except Exception as e:
                logger.error(
                    f"Failed to create log directory {LOG_DIR}: {e}", exc_info=True
                )
                raise RuntimeError(f"Failed to create log directory: {LOG_DIR}") from e
    except Exception as e:
        logger.error(f"Error checking existence of log dir {LOG_DIR}: {e}", exc_info=True)
        raise RuntimeError(f"Failed to check log dir existence: {LOG_DIR}") from e
    LOG_FILE_PATH = LOGGING_CONFIG["file_path"]

    # Helper to generate a filename with the current PID inserted either in place of {pid} or before file extension.
    def insert_pid_into_filename(filename, pid=None):
        """
        Inserts the process PID into the filename.
        - If '{pid}' appears anywhere in filename, it is replaced.
        - Otherwise, _{pid} is inserted before the extension.
        - Example: 'foo_{pid}.log' -> 'foo_1234.log'
        - Example: 'bar.log' -> 'bar_1234.log'
        """
        if pid is None:
            pid = os.getpid()
        base, ext = os.path.splitext(filename)
        if "{pid}" in filename:
            return filename.replace("{pid}", str(pid))
        else:
            return f"{base}_{pid}{ext}"

    # The conversation log file will always include the process PID in the filename.
    conversation_log_filename = LOGGING_CONFIG["conversation_log_filename"]
    pid_injected_conversation_filename = insert_pid_into_filename(
        conversation_log_filename, os.getpid()
    )
    try:
        CONVERSATION_LOG_FILENAME = os.path.join(
            LOG_DIR, f"{STARTUP_TIME}_{pid_injected_conversation_filename}"
        )
    except Exception as e:
        logger.error(f"Failed joining conversation log filename: {e}", exc_info=True)
        raise RuntimeError("Failed to create conversation log file name") from e
    try:
        CONVERSATION_LOG_FILE = open(
            CONVERSATION_LOG_FILENAME, "a", encoding=LOG_ENCODING or "utf-8"
        )
    except Exception as e:
        logger.error(
            f"Failed to open conversation log file: {CONVERSATION_LOG_FILENAME}: {e}",
            exc_info=True,
        )
        raise RuntimeError(
            f"Failed to open conversation log file: {CONVERSATION_LOG_FILENAME}"
        ) from e


def load_environment_globals():
    load_environment_variables()
    configure_globals()
    configure_logging_globals()


def start_logging():
    from monitor.lib.logging import configure_logging

    configure_logging()


def configure_subsystems():
    from monitor.core.commands import load_terminal_commands
    from monitor.core.modes import configure_consultant

    configure_rip_grep(DEFAULT_EXCLUDE_EXTENSIONS, DEFAULT_EXCLUDE_GLOBS)

    configure_rate_limiter(
        logger,
        MODEL_MAX_TPM,
        RATE_LIMITING_CONFIG["window_seconds"],
        RATE_LIMITING_CONFIG["safety_factor"],
    )

    try:
        load_terminal_commands(INTERACTIVE_COMMANDS_PATH, NON_INTERACTIVE_COMMANDS_PATH)
    except Exception as e:
        logger.error(
            f"Failed to load public interactive commands from {NON_INTERACTIVE_COMMANDS_PATH}: {e}",
            exc_info=True,
        )

    # Guarded loading of user preferences prompt: skip if PREFERENCE_PROMPT_FILE is None
    if PREFERENCE_PROMPT_FILE is None:
        logger.warning("PREFERENCE_PROMPT_FILE is None; skipping load_user_preferences_prompt.")
    else:
        try:
            load_user_preferences_prompt(PREFERENCE_PROMPT_FILE)
        except Exception as e:
            logger.error(
                f"Failed to load user preferences prompt from {PREFERENCE_PROMPT_FILE}: {e}",
                exc_info=True,
            )

    configure_redis_utils(
        REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_MAX_RETRIES, REDIS_RETRY_INTERVAL
    )
    from monitor.core.tools import configure_tools  # lazy: see NOTE atop imports
    configure_tools()

    # configure_external_services can fail due to various non-fatal issues; log errors and continue.
    try:
        configure_external_services(
            ARTIFACT_SERVER,
            JOKES_FILE,
            TWITTER_CLIENT_API,
            TWITCH_CLIENT_API,
            LINKEDIN_CLIENT_API,
        )
    except Exception as e:
        logger.error(f"Error configuring external services: {e}", exc_info=True)
        # Continue execution despite external services configuration failure.

    from monitor.lib.protocol_engine import configure_protocol_engine  # lazy: see NOTE atop imports
    configure_protocol_engine()
    configure_consultant()
    configure_voice_to_text()
    from monitor.core.llm_responses_adapter import configure_responses_adapter  # lazy: see NOTE atop imports
    configure_responses_adapter()


_VALID_REASONING_EFFORTS = {"minimal", "low", "medium", "high", "xhigh"}


def apply_role_model_override() -> None:
    """Switch MODEL / REASONING_EFFORT to the SUB-AGENT model at startup.

    Only ``--agent`` children take a whole-session role model
    (``SUBAGENT_MODEL`` / ``SUBAGENT_REASONING_EFFORT``). The orchestrator does
    NOT get a whole-session override — it runs the base ``MODEL`` and escalates
    to ``ORCHESTRATOR_MODEL`` *transiently, per collation turn* (see
    ``llm_model_utils.resolve_turn_model`` + ``CURRENT_TURN_IS_COLLATION``), so
    it "backs down to MODEL" between coordination turns.

    The model override goes through ``set_model`` (which accepts a full model
    string and re-derives context/output windows + TPM), so a dated name from
    ``model_config.json`` is required — an unresolvable name is logged and left
    on the base ``MODEL`` (no crash). Model and effort overrides apply
    independently. Must run AFTER ``config.AGENT`` is resolved and BEFORE
    subsystems that read ``MODEL_MAX_TPM`` (the rate limiter). Startup-safe:
    ``set_model``'s history/counter resets are no-ops on a fresh session.
    """
    global REASONING_EFFORT

    if not AGENT:
        return  # orchestrator/standalone keep base MODEL; only children override
    role, role_model, role_effort = "sub-agent", SUBAGENT_MODEL, SUBAGENT_REASONING_EFFORT

    if isinstance(role_model, str) and role_model and role_model != MODEL:
        if set_model(role_model):
            logger.info("Applied %s model override: MODEL=%s", role, MODEL)
        else:
            logger.warning(
                "%s model override %r is not resolvable (use a dated model name "
                "present in model_config.json); keeping MODEL=%s",
                role, role_model, MODEL,
            )

    if isinstance(role_effort, str) and role_effort:
        if role_effort.lower() in _VALID_REASONING_EFFORTS:
            REASONING_EFFORT = role_effort.lower()
            logger.info("Applied %s reasoning effort: %s", role, REASONING_EFFORT)
        else:
            logger.warning(
                "%s reasoning effort %r is not a valid level "
                "(minimal/low/medium/high/xhigh); ignoring",
                role, role_effort,
            )


def record_agent_usage(usage) -> None:
    """Fold a sub-agent's reported usage delta into THIS (orchestrator) session's
    totals (Stage 2 cost telemetry).

    Main-thread only — called from the injection-fold step, so config cost globals
    are never mutated from a listener reader thread. Best-effort: malformed input
    is ignored. Updates ``SESSION_COST_USD`` + ``SESSION_TOTAL_TOKENS`` (U:/T:
    status line and F: drain) and ``SESSION_CALIBRATION_BY_MODEL[model]`` (F:
    sizing and :fuel_debug per-model rate for the sub-agent model).
    """
    global SESSION_COST_USD, SESSION_TOTAL_TOKENS
    if not isinstance(usage, dict):
        return
    try:
        cost = float(usage.get("cost_usd", 0.0) or 0.0)
        tokens = int(usage.get("total_tokens", 0) or 0)
    except (TypeError, ValueError):
        return
    if cost <= 0 and tokens <= 0:
        return
    if cost > 0:
        SESSION_COST_USD = (SESSION_COST_USD or 0.0) + cost
    if tokens > 0:
        SESSION_TOTAL_TOKENS = (SESSION_TOTAL_TOKENS or 0) + tokens
    model = usage.get("model")
    if isinstance(model, str) and model:
        try:
            from monitor.lib.model_pricing import calibration_entry
            entry = calibration_entry(model, create=True)
            entry["cost_usd"] = (entry.get("cost_usd", 0.0) or 0.0) + cost
            entry["total_tokens"] = (entry.get("total_tokens", 0) or 0) + tokens
        except Exception:
            logger.debug("Failed to fold agent usage into calibration", exc_info=True)


def set_model(model_key: str) -> bool:
    """
    Changes the active model configuration at runtime.

    Behavior:
    - Recognizes either a shorthand key present in MODEL_MAPPING keys or a full model string present in MODEL_MAPPING values.
    - If MODEL_MAPPING is missing, not a dict, or empty, logs a warning and returns False without changing any globals.
    - If the provided model_key is unknown, logs a warning listing the unknown key and available keys, returns False, and does not modify any globals (including not clearing CONVERSATION_HISTORY).
    - On success, sets MODEL to the resolved full model string and derives related settings from context_window_mapping, output_window_mapping, conversation_history_mapping, model_max_tpm, and model_tpm_mapping using the shorthand key. If model_max_tpm or model_tpm_mapping lacks the needed entries, sets MODEL_MAX_TPM to None.
    - Sets MAX_TOKEN_COUNT accordingly, resets TOTAL_TOKEN_COUNT to 0, clears CONVERSATION_HISTORY, logs an info summary, and returns True.
    """
    global MODEL, MODEL_CONTEXT_WINDOW, MODEL_OUTPUT_WINDOW, MODEL_INPUT_WINDOW, MODEL_MAX_TPM, CONVERSATION_MAX_SIZE, MAX_TOKEN_COUNT, TOTAL_TOKEN_COUNT
    global CONVERSATION_HISTORY, RESPONSE_ID, SESSION_TOTAL_TOKENS, SESSION_COST_USD
    global SESSION_COMPACTION_COUNT, TURN_COSTS_USD, CURRENT_TURN_REASONING_OVERRIDE
    global SESSION_TOOL_CALL_COUNT, SESSION_LOOP_DETECTOR_TRIPS, TURN_ROUND_TRIPS
    global LAST_BILLED_INPUT_TOKENS, SESSION_TIER_CROSSINGS, SESSION_RESPONSES_REQUESTS
    global CURRENT_TURN_IS_COLLATION, CURRENT_TURN_TOOL_GROUPS, TOOL_PROFILE_GROUP_LEASES

    # Validate MODEL_MAPPING
    if not isinstance(MODEL_MAPPING, dict) or not MODEL_MAPPING:
        logger.warning("set_model: MODEL_MAPPING is not available or is empty; cannot set model.")
        return False

    mapped_key = None
    model_full = None

    if model_key in MODEL_MAPPING:
        mapped_key = model_key
        model_full = MODEL_MAPPING[model_key]
    elif model_key in MODEL_MAPPING.values():
        mapped_key = next((k for k, v in MODEL_MAPPING.items() if v == model_key), None)
        model_full = model_key if mapped_key is not None else None
    else:
        available = sorted(MODEL_MAPPING.keys())
        logger.info(f"set_model: Unknown model key '{model_key}'. Available keys: {available}")
        return False

    if mapped_key is None or model_full is None:
        available = sorted(MODEL_MAPPING.keys())
        logger.warning(
            f"set_model: Could not resolve model for key '{model_key}'. Available keys: {available}"
        )
        return False

    MODEL = model_full

    MODEL_CONTEXT_WINDOW = (
        context_window_mapping.get(mapped_key)
        if isinstance(context_window_mapping, dict)
        else None
    )
    MODEL_OUTPUT_WINDOW = (
        output_window_mapping.get(mapped_key)
        if isinstance(output_window_mapping, dict)
        else None
    )

    # Recompute MODEL_INPUT_WINDOW from the new model's context/output windows.
    # Previously this global was only computed at startup from YAML; a runtime
    # set_model() updated MODEL_CONTEXT_WINDOW and MODEL_OUTPUT_WINDOW but left
    # MODEL_INPUT_WINDOW pointing at the prior model's value. That stale value
    # is consumed by llm_responses_adapter.py's input-window gate and by the
    # C indicator's percent calculation, so the system would either reject
    # valid requests or allow over-budget ones after a model switch.
    if isinstance(MODEL_CONTEXT_WINDOW, int) and isinstance(MODEL_OUTPUT_WINDOW, int):
        iw = MODEL_CONTEXT_WINDOW - MODEL_OUTPUT_WINDOW
        MODEL_INPUT_WINDOW = iw if iw > 0 else None
        if MODEL_INPUT_WINDOW is None:
            logger.warning(
                f"set_model: Computed MODEL_INPUT_WINDOW <= 0 (context={MODEL_CONTEXT_WINDOW}, output={MODEL_OUTPUT_WINDOW}); disabling input budgeting"
            )
    else:
        MODEL_INPUT_WINDOW = None

    max_tpm_tier = model_max_tpm.get(mapped_key) if isinstance(model_max_tpm, dict) else None
    tpm_mapping = (
        model_tpm_mapping.get(mapped_key) if isinstance(model_tpm_mapping, dict) else None
    )
    MODEL_MAX_TPM = (
        tpm_mapping.get(max_tpm_tier)
        if isinstance(tpm_mapping, dict)
        and (max_tpm_tier in tpm_mapping if isinstance(tpm_mapping, dict) else False)
        else None
    )

    CONVERSATION_MAX_SIZE = (
        conversation_history_mapping.get(mapped_key)
        if isinstance(conversation_history_mapping, dict)
        else None
    )

    MAX_TOKEN_COUNT = MODEL_CONTEXT_WINDOW
    TOTAL_TOKEN_COUNT = 0
    # Reset cumulative session counters: rates change per model, so
    # accumulating across a model switch would mix prices/tokens of
    # different rates. Both reset together to stay consistent.
    SESSION_TOTAL_TOKENS = 0
    SESSION_COST_USD = 0.0
    # SESSION_CALIBRATION_BY_MODEL is intentionally NOT reset here: it is keyed
    # per model, so switching models cannot mix rates. It persists until a full
    # session reset (:reset_history).
    SESSION_COMPACTION_COUNT = 0
    SESSION_TOOL_CALL_COUNT = 0
    SESSION_LOOP_DETECTOR_TRIPS = 0
    LAST_BILLED_INPUT_TOKENS = 0
    SESSION_TIER_CROSSINGS = 0
    SESSION_RESPONSES_REQUESTS = 0
    TURN_COSTS_USD = []
    TURN_ROUND_TRIPS = []
    TURN_CACHED_INPUT_TOKENS = []
    TURN_UNCACHED_INPUT_TOKENS = []
    TURN_OUTPUT_TOKENS = []
    globals()["RESPONSE_ID"] = None
    CURRENT_TURN_REASONING_OVERRIDE = None
    CURRENT_TURN_IS_COLLATION = False
    CURRENT_TURN_TOOL_GROUPS = set()
    TOOL_PROFILE_GROUP_LEASES = {}

    if isinstance(CONVERSATION_HISTORY, list):
        CONVERSATION_HISTORY.clear()
    else:
        CONVERSATION_HISTORY = []

    # H1: clear the rate-limiter rolling window so prior-model token history
    # does not phantom-deny requests against the new model's TPM budget.
    try:
        from monitor.lib import rate_limiter as _rl
        if _rl.RATE_LIMITER is not None:
            _rl.RATE_LIMITER.reset()
    except Exception:
        logger.warning("set_model: failed to reset rate limiter window", exc_info=True)

    # S1: clear the Responses API previous_response_id. Response IDs are
    # session-scoped to the model that produced them; reusing a prior-model
    # ID against the new model's API will be rejected by the provider.
    globals()["RESPONSE_ID"] = None

    # S2: refresh the tool catalog. configure_tools() chooses between the
    # anthropic and openai editor tool sets based on the active model; a
    # switch between providers leaves the global TOOL_DESCRIPTIONS list with
    # the prior provider's tools.
    try:
        from monitor.core.tools import configure_tools  # lazy: see NOTE atop imports
        configure_tools()
    except Exception:
        logger.warning("set_model: failed to refresh tool catalog", exc_info=True)

    logger.info(
        f"set_model: Activated model '{MODEL}' "
        f"(CONTEXT_WINDOW={MODEL_CONTEXT_WINDOW}, OUTPUT_WINDOW={MODEL_OUTPUT_WINDOW}, "
        f"MAX_TPM={MODEL_MAX_TPM}, CONVERSATION_MAX_SIZE={CONVERSATION_MAX_SIZE}, "
        f"MAX_TOKEN_COUNT={MAX_TOKEN_COUNT}, TOTAL_TOKEN_COUNT={TOTAL_TOKEN_COUNT})"
    )

    return True


def _load_one_dotenv(dotenv_path, description=None, verbose=False):
    """
    Attempt to load a single .env file, logging success/failure. Used in load_environment_variables.
    Returns True if loaded, False otherwise.
    All file existence and load attempts are logged and exceptions are fatal.
    """
    try:
        if dotenv_path:
            try:
                dotenv_exists = os.path.exists(dotenv_path)
            except Exception as e:
                logger.error(
                    f"Error checking .env existence at {dotenv_path}: {e}", exc_info=True
                )
                raise RuntimeError(
                    f"Failed to check existence of dotenv file: {dotenv_path}"
                ) from e
            if dotenv_exists:
                try:
                    load_dotenv(dotenv_path, override=True)
                except Exception as e:
                    logger.error(
                        f"Failed loading dotenv file at {dotenv_path}: {e}", exc_info=True
                    )
                    raise RuntimeError(f"Failed loading dotenv: {dotenv_path}") from e
                if description:
                    logger.info(f"{description} loaded successfully from {dotenv_path}.")
                else:
                    logger.info(f".env file loaded successfully from {dotenv_path}.")
                return True
            else:
                if verbose:
                    if description:
                        logger.info(f"{description} not found at {dotenv_path}.")
                    else:
                        logger.info(f".env file not found at {dotenv_path}.")
                return False
        else:
            if verbose:
                if description:
                    logger.info(f"{description} path is None.")
                else:
                    logger.info(".env file path is None.")
            return False
    except Exception as e:
        logger.error(
            f"Exception during loading dotenv file at {dotenv_path}: {e}", exc_info=True
        )
        raise


def load_environment_variables(verbose=False):
    """
    Loads environment variables from these .env files in this order (if present):
    1. .env discovered via find_dotenv (nearest up the directory tree from CWD)
    2. ~/.config/monitor/.env

    ~/.config/monitor/.env variables will override variables set by project .env.
    Logs .env loading for audit/debug; does not exit if missing (defaults/secrets may be used).
    Returns:
        dict: {"cwd_env_loaded": bool, "home_env_loaded": bool}
    All .env file IO errors are logged and abort with exception.
    """
    status = {"cwd_env_loaded": False, "home_env_loaded": False}
    try:
        cwd_dotenv_path = find_dotenv()
    except Exception as e:
        logger.error(f"Error finding project .env via find_dotenv: {e}", exc_info=True)
        raise RuntimeError("Failed during find_dotenv for project .env") from e
    try:
        status["cwd_env_loaded"] = _load_one_dotenv(
            cwd_dotenv_path, description="Project .env", verbose=verbose
        )
    except Exception as e:
        logger.error(f"Exception loading cwd .env file: {e}", exc_info=True)
        raise
    home_dotenv_path = os.path.expanduser(os.path.join("~", ".config/monitor", ".env"))
    try:
        status["home_env_loaded"] = _load_one_dotenv(
            home_dotenv_path, description="Home secrets .env", verbose=verbose
        )
    except Exception as e:
        logger.error(f"Exception loading home .env file: {e}", exc_info=True)
        raise

    if not status["cwd_env_loaded"] and not status["home_env_loaded"]:
        logger.warning(
            "No .env files found/loaded: neither project .env nor ~/.config/monitor/.env was found. Falling back to defaults and system environment only."
        )
    return status


def load_yaml_config(file_path=None):
    """
    Load YAML configuration from a file.

    This function will load and parse a YAML configuration file. If file_path is None,
    the function will attempt to locate 'config.yaml' using find_config_file("config.yaml").
    All filesystem IO errors (finding, opening, reading, parsing) are logged via
    logger.error with exc_info=True and result in exceptions being raised to abort execution.

    Args:
        file_path (str | None): Path to the YAML file to load. If None, the function will
            try to discover 'config.yaml' via find_config_file.

    Returns:
        dict: Parsed YAML configuration mapping.

    Raises:
        RuntimeError: If the file cannot be found, opened, or parsed.
    """
    yaml_path = file_path
    try:
        if yaml_path is None:
            try:
                yaml_path = find_config_file("config.yaml")
            except Exception as e:
                logger.error(f"Unable to locate config.yaml: {e}", exc_info=True)
                raise RuntimeError("Cannot find config.yaml") from e
        try:
            with open(yaml_path) as f:
                try:
                    config = yaml.safe_load(f)
                except yaml.YAMLError as exc:
                    logger.error(f"Error parsing YAML file: {exc}", exc_info=True)
                    raise RuntimeError(
                        f"YAML parsing error in {yaml_path}: {exc}"
                    ) from exc
        except FileNotFoundError as e:
            logger.error(f"Configuration file {yaml_path} not found.", exc_info=True)
            raise RuntimeError(f"Configuration file {yaml_path} not found.") from e
        except Exception as e:
            logger.error(
                f"Failed opening configuration file {yaml_path}: {e}", exc_info=True
            )
            raise RuntimeError(f"Open error for {yaml_path}: {e}") from e

        # Validate that the parsed YAML is a mapping (dict). If YAML is empty or not a dict,
        # treat this as a fatal configuration error.
        if config is None or not isinstance(config, dict):
            logger.error(
                f"YAML file {yaml_path} did not produce a mapping (dict). Parsed value: {config!r}"
            )
            raise RuntimeError(
                f"YAML config {yaml_path} must contain a mapping at top level (got {type(config).__name__})."
            )

        return config
    except Exception as e:
        logger.error(f"Failed to load YAML config ({yaml_path}): {e}", exc_info=True)
        raise


def get_logging_config():
    """
    Retrieves logging configuration from the YAML config with sensible defaults.
    Directory creation is wrapped with exception handling.
    Any directory or file error is logged and aborts config loading.
    """
    try:
        config = load_yaml_config().get("logging", {})
    except Exception as e:
        logger.error(f"Error retrieving 'logging' config from YAML: {e}", exc_info=True)
        raise
    default_log_dir = os.path.join(os.path.expanduser("~"), ".config/monitor", "logs")
    try:
        log_dir = os.path.expanduser(config.get("log_dir", default_log_dir))
    except Exception as e:
        logger.error(f"Path expansion failed for log_dir: {e}", exc_info=True)
        raise RuntimeError("Error expanding log_dir path in logging config") from e
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception as e:
        logger.error(f"Failed to create log directory {log_dir}: {e}", exc_info=True)
        raise RuntimeError(f"Failed to create log directory {log_dir}: {e}") from e

    app_log_filename = config.get("app_log_filename", "app.log")
    conversation_log_filename = config.get("conversation_log_filename", "conversation.log")
    try:
        file_path = os.path.join(log_dir, f"{STARTUP_TIME}_{app_log_filename}")
    except Exception as e:
        logger.error(f"Path join failed for log file: {e}", exc_info=True)
        raise RuntimeError("Failed joining file path for log file") from e
    log_config = {
        "level": config.get("level", "INFO"),
        "format": config.get(
            "format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ),
        "date_format": config.get("date_format", "%Y-%m-%d %H:%M:%S"),
        "log_dir": log_dir,
        "app_log_filename": app_log_filename,
        "conversation_log_filename": conversation_log_filename,
        "console_logging_enabled": config.get("console_logging_enabled", True),
        "max_bytes": config.get("max_bytes", 10485760),
        "backup_count": config.get("backup_count", 5),
        "file_path": file_path,
        "encoding": config.get("encoding", "utf-8"),
    }
    return log_config
