"""`:agent list` / `:agent ls` — print a table of active screen sessions.

With ``--full`` flag, the table also includes Token and Meta columns.
"""

import logging
import os

from monitor.lib.terminal_commands_util import _color, user_feedback

logger = logging.getLogger(__name__)


def _extract_info(item, full_idx=None):
    """Normalize a single item from list_indexed_sessions into a dict
    with the keys the table renderer expects.

    Handles the three shapes the handler might return: ``(index, payload)``
    tuples (where payload may be a dict or an object), bare dicts, and
    bare objects. Missing keys become empty strings so the table layout
    stays stable.
    """
    info = {}
    if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], (int, str)):
        idx = item[0]
        payload = item[1]
    else:
        payload = item
        idx = None

    if isinstance(payload, dict):
        info['index'] = idx if idx is not None else payload.get('index') or payload.get('idx')
        info['name'] = payload.get('name') or payload.get('session_name') or payload.get('session')
        info['token'] = payload.get('token') or payload.get('screen_token') or payload.get('screen')
        info['state'] = payload.get('state') or payload.get('status')
        info['created_at'] = payload.get('created_at') or payload.get('created') or payload.get('ctime')
        info['meta_path'] = payload.get('meta_path') or payload.get('metadata_path') or payload.get('metadata')
    else:
        info['index'] = idx if idx is not None else getattr(payload, 'index', None) or getattr(payload, 'idx', None)
        info['name'] = getattr(payload, 'name', None) or getattr(payload, 'session_name', None) or (str(payload) if isinstance(payload, str) else None)
        info['token'] = getattr(payload, 'token', None) or getattr(payload, 'screen_token', None)
        info['state'] = getattr(payload, 'state', None) or getattr(payload, 'status', None)
        info['created_at'] = getattr(payload, 'created_at', None) or getattr(payload, 'created', None)
        info['meta_path'] = getattr(payload, 'meta_path', None) or getattr(payload, 'metadata_path', None) or getattr(payload, 'metadata', None)

    # Normalize Nones to empty strings for stable column widths.
    for k in ['index', 'name', 'token', 'state', 'created_at', 'meta_path']:
        if info.get(k) is None:
            info[k] = ""
    return info


def _color_for_state(state_text):
    """Map a state string to a color for the table cell. The mapping is
    deliberately loose — we substring-match common words because the
    handler doesn't pin a state enum."""
    st_lower = (state_text or "").lower()
    if "run" in st_lower or "attached" in st_lower or "up" in st_lower:
        return "green"
    if "detach" in st_lower or "detached" in st_lower:
        return "yellow"
    if "dead" in st_lower or "exit" in st_lower or "exited" in st_lower or "stop" in st_lower:
        return "red"
    return "blue"


def agent_list(tokens):
    """Print a table of active screen sessions.

    The handler's ``list_indexed_sessions(full=...)`` is preferred; if
    it's not implemented (AttributeError) the function falls back to
    ``list_sessions()`` with full=False.
    """
    from monitor.lib.terminal_commands import _SCREEN_HANDLER

    full = '--full' in tokens
    try:
        try:
            sessions = _SCREEN_HANDLER.list_indexed_sessions(full=full)
        except AttributeError:
            sessions = _SCREEN_HANDLER.list_sessions()
            full = False  # can't show full details if method absent

        if sessions is None:
            user_feedback("No screen sessions found.")
            return

        rows = []
        instance_id = getattr(_SCREEN_HANDLER, 'instance_id', None)
        sessions_file = getattr(_SCREEN_HANDLER, 'sessions_file', None)

        iterable = sessions.items() if isinstance(sessions, dict) else sessions
        for item in iterable:
            try:
                rows.append(_extract_info(item))
            except Exception:
                # Best-effort: fallback to string representation. Keeps
                # the rest of the table renderable when one row is weird.
                rows.append({
                    'index': '',
                    'name': str(item),
                    'token': '',
                    'state': '',
                    'created_at': '',
                    'meta_path': '',
                })

        # Compute column widths from the data + minimum-width floors.
        idx_width = max([len(str(r['index'])) for r in rows] + [5])
        name_width = max([len(r['name'] or "") for r in rows] + [12])
        token_width = max([len(r['token'] or "") for r in rows] + ([10] if full else [0]))
        state_width = max([len(r['state'] or "") for r in rows] + [6])
        created_width = max([len(r['created_at'] or "") for r in rows] + [10])
        meta_width = max([len(r['meta_path'] or "") for r in rows] + ([12] if full else [0]))

        # Header (instance + sessions-file basename if available).
        header_line = "Sessions"
        if instance_id:
            header_line += f" (instance: {instance_id})"
        print(header_line)
        if sessions_file:
            try:
                print(f"Sessions file: {os.path.basename(sessions_file)}")
            except Exception:
                print(f"Sessions file: {sessions_file}")

        # Table header + rows. Full mode adds Token + Meta columns.
        if full:
            header_fmt = f"{{:<{idx_width}}}  {{:<{name_width}}}  {{:<{token_width}}}  {{:<{state_width}}}  {{:<{created_width}}}  {{:<{meta_width}}}"
            print(header_fmt.format("Index", "Name", "Token", "State", "Created", "Meta"))
            print("-" * (idx_width + name_width + token_width + state_width + created_width + meta_width + 10))
            for r in rows:
                state_text = r['state'] or ""
                state_colored = _color(state_text, _color_for_state(state_text))
                print(header_fmt.format(str(r['index']), r['name'], r['token'], state_colored, r['created_at'], r['meta_path']))
        else:
            header_fmt = f"{{:<{idx_width}}}  {{:<{name_width}}}  {{:<{state_width}}}  {{:<{created_width}}}"
            print(header_fmt.format("Index", "Name", "State", "Created"))
            print("-" * (idx_width + name_width + state_width + created_width + 6))
            for r in rows:
                state_text = r['state'] or ""
                state_colored = _color(state_text, _color_for_state(state_text))
                print(header_fmt.format(str(r['index']), r['name'], state_colored, r['created_at']))
        return
    except Exception as e:
        logger.error(f"Error listing screen sessions: {e}", exc_info=True)
        user_feedback("Failed to list screen sessions. See logs for details.")
        return
