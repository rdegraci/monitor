"""Model and tool descriptor helpers for LLM integrations."""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

OPENAI_PREFIX = "openai/"
TYPE_KEY = "type"
NAME_KEY = "name"
DESCRIPTION_KEY = "description"
DEFAULT_TOOL_TYPE = "function"
PARAMETERS_PROPERTIES_KEY = "properties"
PARAMETERS_REQUIRED_KEY = "required"
PARAMETERS_TYPE_OBJECT = "object"


def strip_openai_prefix(model_name):
    """Remove a leading ``openai/`` prefix from a model name.

    Args:
        model_name: The model name to normalize.

    Returns:
        The model name with a leading ``openai/`` removed when present.
        Returns the original value unchanged when it is falsy or not a string.
    """
    if not model_name or not isinstance(model_name, str):
        return model_name
    lower = model_name.lower()
    prefix = OPENAI_PREFIX
    if lower.startswith(prefix):
        return model_name[len(prefix) :]
    return model_name


def is_reasoning_model(model: Optional[str], prefix: Optional[str]) -> bool:
    """Check whether a model name contains a given reasoning prefix.

    Args:
        model: The model identifier to check.
        prefix: The substring indicating a reasoning model.

    Returns:
        True when both inputs are strings and ``prefix`` appears within
        ``model`` case-insensitively, otherwise False.
    """
    if not isinstance(model, str) or not isinstance(prefix, str):
        return False
    return prefix.lower() in model.lower()


_REASONING_EFFORT_RANK = {"minimal": 0, "low": 1, "medium": 2, "high": 3, "xhigh": 4}


def higher_reasoning_effort(effort, floor):
    """Return whichever reasoning-effort label ranks higher — a floor that never
    downgrades.

    Used to raise an auto-bumped turn's effort to a configured minimum
    (``REASONING_BUMP_EFFORT``) without ever weakening a higher bump such as the
    tool-failure escalation to ``"high"``.

    Args:
        effort: The current effort label (e.g. the heuristic/escalation target).
        floor: The configured minimum effort, or None/invalid to impose no floor.

    Returns:
        ``floor`` when it ranks strictly higher than ``effort`` (or when
        ``effort`` is unrecognized); otherwise ``effort`` unchanged. ``floor`` is
        ignored when None or not a known level.
    """
    floor_rank = _REASONING_EFFORT_RANK.get((floor or "").lower()) if isinstance(floor, str) else None
    if floor_rank is None:
        return effort
    effort_rank = _REASONING_EFFORT_RANK.get((effort or "").lower()) if isinstance(effort, str) else None
    if effort_rank is None or floor_rank > effort_rank:
        return floor
    return effort


def resolve_turn_model(base_model, adv_model, override_active, prefix,
                       *, orchestrator_model=None, collation_active=False):
    """Resolve the model actually used for a turn's LLM calls.

    Priority (first that applies wins):
      1. collation/synthesis turn -> ``orchestrator_model`` (phase-scoped
         escalation: the orchestrator runs base ``MODEL`` and swaps to the
         stronger model only while folding sub-agent results)
      2. reasoning override active -> ``adv_model``
      3. otherwise -> ``base_model``

    A target only swaps in if it is set, distinct from ``base_model``, and (like
    ``base_model``) reasoning-capable — otherwise sending ``reasoning_effort`` to
    it would error. Pure (no config access) so the call site (llm_utils) and the
    cost-attribution site (token_management) compute the same effective model.

    Args:
        base_model: The configured default model (config.MODEL).
        adv_model: The configured advanced-reasoning model, or None.
        override_active: Whether a per-turn reasoning override is set.
        prefix: REASONING_MODEL_PREFIX — models must contain it for a swap.
        orchestrator_model: ORCHESTRATOR_MODEL, or None.
        collation_active: Whether this turn folds sub-agent results (synthesis).

    Returns:
        str: the resolved model per the priority above.
    """
    def _swappable(target):
        return (
            isinstance(target, str)
            and target
            and target != base_model
            and is_reasoning_model(base_model, prefix)
            and is_reasoning_model(target, prefix)
        )

    if collation_active and _swappable(orchestrator_model):
        return orchestrator_model
    if override_active and _swappable(adv_model):
        return adv_model
    return base_model


def effective_turn_effort(steady_effort, override_effort, *,
                          collation_active=False, orchestrator_effort=None):
    """The reasoning effort for a turn.

    The per-turn override (if set) wins over the steady effort, then on a
    collation turn ``orchestrator_effort`` is applied as a FLOOR (never a
    downgrade — see ``higher_reasoning_effort``). Pure, so the call site and
    cost attribution agree on the effort.

    Args:
        steady_effort: config.REASONING_EFFORT.
        override_effort: config.CURRENT_TURN_REASONING_OVERRIDE, or None.
        collation_active: Whether this is a collation/synthesis turn.
        orchestrator_effort: ORCHESTRATOR_REASONING_EFFORT, applied as a floor
            on collation turns.

    Returns:
        The effective effort label.
    """
    base = override_effort or steady_effort
    if collation_active and isinstance(orchestrator_effort, str) and orchestrator_effort:
        return higher_reasoning_effort(base, orchestrator_effort)
    return base


def get_model_tail(model: str) -> str:
    """Return the substring after the last slash in a model string.

    Args:
        model: A model identifier like ``provider/name``.

    Returns:
        The portion after the final slash. If there is no slash, returns the
        trimmed input. Trailing slashes are ignored.
    """
    s = model.strip()
    if not s:
        return s
    s = s.rstrip("/")
    return s.split("/")[-1]


def get_model_head(model: str, mapping: Optional[Dict[str, Any]] = None) -> Optional[Any]:
    """Return the mapping value for the best-matching key in the model tail.

    Args:
        model: Model identifier string.
        mapping: Optional mapping of substrings to desired values.

    Returns:
        The value from ``mapping`` corresponding to the longest matching key,
        or None when no suitable key is found.
    """
    if not mapping:
        return None

    try:
        tail = get_model_tail(model) if isinstance(model, str) else str(model or "")
    except Exception:
        try:
            tail = str(model)
        except Exception:
            return None

    tail_lower = tail.lower()
    candidates = [
        key
        for key in mapping.keys()
        if isinstance(key, str) and key.lower() in tail_lower
    ]
    if not candidates:
        return None

    best_key = max(candidates, key=len)
    try:
        return mapping.get(best_key)
    except Exception:
        return None


def normalize_tool_descriptors(tool_list):
    """Normalize tool descriptor dicts into a flat, consistent shape.

    Args:
        tool_list: A list of tool descriptor entries.

    Returns:
        A normalized list of descriptor dictionaries.
    """
    if not tool_list:
        return tool_list

    normalized = []
    for idx, entry in enumerate(tool_list):
        try:
            if not isinstance(entry, dict):
                logger.debug(
                    "Skipping non-dict tool descriptor at index %s: %s",
                    idx,
                    type(entry),
                )
                continue

            nested = (
                entry.get("function")
                if isinstance(entry.get("function"), dict)
                else None
            )

            if nested:
                name = nested.get(NAME_KEY) or entry.get(NAME_KEY)
                description = (
                    nested.get(DESCRIPTION_KEY)
                    or entry.get(DESCRIPTION_KEY)
                    or ""
                )
                parameters = nested.get("parameters") or entry.get("parameters")
                type_val = (
                    entry.get(TYPE_KEY)
                    or nested.get(TYPE_KEY)
                    or DEFAULT_TOOL_TYPE
                )
            else:
                name = entry.get(NAME_KEY)
                description = entry.get(DESCRIPTION_KEY) or entry.get("doc") or ""
                parameters = entry.get("parameters")
                type_val = entry.get(TYPE_KEY) or DEFAULT_TOOL_TYPE

            if not name or not isinstance(name, str):
                logger.debug(
                    "Skipping tool descriptor without valid name at index %s: %s",
                    idx,
                    name,
                )
                continue

            if not isinstance(parameters, dict):
                parameters = {}

            parameters = dict(parameters)

            if parameters.get(TYPE_KEY) != PARAMETERS_TYPE_OBJECT:
                parameters[TYPE_KEY] = PARAMETERS_TYPE_OBJECT

            props = parameters.get(PARAMETERS_PROPERTIES_KEY)
            if not isinstance(props, dict):
                parameters[PARAMETERS_PROPERTIES_KEY] = {}

            if PARAMETERS_REQUIRED_KEY in parameters:
                req = parameters.get(PARAMETERS_REQUIRED_KEY)
                if isinstance(req, list):
                    pass
                elif hasattr(req, "__iter__") and not isinstance(
                    req, (str, bytes, dict)
                ):
                    try:
                        parameters[PARAMETERS_REQUIRED_KEY] = list(req)
                    except Exception:
                        parameters[PARAMETERS_REQUIRED_KEY] = []
                else:
                    parameters[PARAMETERS_REQUIRED_KEY] = []

            normalized.append(
                {
                    TYPE_KEY: type_val,
                    NAME_KEY: name,
                    DESCRIPTION_KEY: description or "",
                    "parameters": parameters,
                }
            )
        except Exception as error:
            logger.exception(
                "Error normalizing tool descriptor at index %s: %s",
                idx,
                error,
            )
            continue

    return normalized
