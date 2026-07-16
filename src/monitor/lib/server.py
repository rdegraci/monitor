"""
src/monitor/lib/server.py

Flask server functionality extracted from app.py for modularity, maintenance,
and testability. Provides factories for creating and running the CLI API server.

This module also introduces a WSGI middleware that serializes all incoming HTTP
requests using a threading.Lock, ensuring only one request is processed at a time.
This is intended for single-user or test scenarios where deterministic, in-order
processing is desired.
"""
import json
import logging
import threading
import os
import time
import traceback
from typing import Any, Generator, Optional

from monitor.core.command_processing import internalize_command
from monitor import config
from monitor.lib.optional_deps import import_optional

logger = logging.getLogger(__name__)

# Populated lazily by ``_ensure_flask()`` so REPL startup does not require Flask.
Flask = None
request = None
jsonify = None
Response = None


def _ensure_flask() -> None:
    """Import Flask symbols or raise a clear optional-extra error."""
    global Flask, request, jsonify, Response
    if Flask is not None:
        return
    flask = import_optional("flask", feature="HTTP server mode")
    Flask = flask.Flask
    request = flask.request
    jsonify = flask.jsonify
    Response = flask.Response


class SingleRequestMiddleware:
    """
    WSGI middleware that serializes all HTTP requests using a threading.Lock.

    This ensures that only one request is processed at a time, providing
    single-user, single-threaded behavior even if the underlying WSGI server
    supports concurrency.

    The lock is held for the full lifetime of the request, including iteration
    over the response iterable, to ensure true serialization.
    """

    def __init__(self, app, logger: Optional[logging.Logger] = None):
        self.app = app
        self._lock = threading.Lock()
        self._logger = logger or logging.getLogger(__name__)

    def __call__(self, environ, start_response):
        self._logger.debug("Waiting to acquire request lock for serialized processing.")
        self._lock.acquire()
        self._logger.debug("Request lock acquired; processing request.")
        try:
            result = self.app(environ, start_response)
        except Exception:
            # If an exception occurs before we obtain the response iterable,
            # ensure the lock is released and re-raise so upstream handlers can deal with it.
            self._logger.debug(
                "Exception before response iterable created; releasing request lock."
            )
            self._lock.release()
            raise

        def _wrapped_response() -> Generator[Any, None, None]:
            """
            Generator that yields the response iterable's items and ensures
            the request lock is released exactly once in a finally block.

            This avoids accumulating the whole response in memory and prevents
            double-release of the lock in the face of exceptions.
            """
            try:
                for item in result:
                    yield item
            finally:
                try:
                    close = getattr(result, "close", None)
                    if callable(close):
                        try:
                            close()
                        except Exception:
                            self._logger.exception(
                                "Exception while closing the response iterable."
                            )
                finally:
                    self._logger.debug(
                        "Releasing request lock after response iteration."
                    )
                    self._lock.release()

        return _wrapped_response()


def convert_messages_to_command(
    messages: Optional[list[dict[str, Any]]]
) -> str:
    """
    Convert OpenAI-style chat messages into a single CLI command string.

    Returns the content of the last 'user' role message, searching backwards for efficiency.
    If no 'user' message exists, returns the content of the last message (of any role) if present.

    Supports both string content and list-form content (OpenAI-style content parts).
    - For list content: concatenates text parts in order, including direct strings
      and dict parts where type == "text" and part["text"] is str.
      Non-text parts are ignored.

    TODO: Support richer multimodal inputs (e.g., images, files) with configurable
          inclusion/exclusion policies.
    TODO: Add configuration to control which roles are considered or how content
          parts are joined (e.g., separators, normalization).
    Args:
        messages (list[dict[str, Any]] | None): OpenAI-style message list with
            dicts containing 'role' and 'content'.

    Returns:
        str: A best-effort command string extracted from the messages.
    """
    if not messages:
        return ""

    def _content_to_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for p in content:
                if isinstance(p, str):
                    parts.append(p)
                elif isinstance(p, dict):
                    try:
                        if p.get("type") == "text":
                            text = p.get("text")
                            if isinstance(text, str):
                                parts.append(text)
                    except Exception:
                        # Ignore malformed parts safely
                        continue
            return "".join(parts)
        return ""

    # Search backwards for the last 'user' role message.
    for m in reversed(messages):
        try:
            role = m.get("role")
            content = m.get("content")
        except AttributeError:
            continue
        if role == "user":
            text = _content_to_text(content)
            if isinstance(text, str):
                return text

    # Fallback to the last message content of any role, if available.
    last = messages[-1]
    content = last.get("content") if isinstance(last, dict) else None
    return _content_to_text(content)


def _result_to_text(result: Any) -> str:
    """
    Coerce an internal command result into a plain text string.

    Tries common keys when the result is a dictionary. Falls back to a JSON
    string or str() representation.

    Args:
        result (Any): The result returned by internalize_command().

    Returns:
        str: A text representation of the result.
    """
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        # Prefer explicit error string, then output string; otherwise, avoid dumping dicts.
        for key in ("error", "output"):
            val = result.get(key)
            if isinstance(val, str):
                return val
        # Fall back to JSON string with a size cap to avoid blank responses.
        try:
            dumped = json.dumps(result, ensure_ascii=False)
            # TODO: Make the size cap configurable.
            cap = 8192  # ~8 KiB
            if len(dumped) > cap:
                return dumped[:cap] + "…"
            return dumped
        except Exception:
            # If JSON serialization fails, continue to str() fallback below.
            pass
    try:
        return str(result)
    except Exception:
        return repr(result)


def make_flask_app():
    """
    Create and configure the Flask application for the CLI API.

    Returns:
        Flask: The configured Flask application, with WSGI middleware applied
               to serialize (single-thread) all incoming HTTP requests.
    """
    _ensure_flask()
    app = Flask(__name__)

    @app.before_request
    def _enforce_v1_api_key():
        """Validate Bearer API key for /v1 endpoints.

        If MONITOR_SERVER_API_KEY is set, require Authorization: Bearer <token>
        to match.

        Returns:
            Response | tuple | None: 401 JSON error on auth failure; otherwise
            None to continue processing.
        """
        if not request.path.startswith("/v1/"):
            return None

        required_key = os.environ.get("MONITOR_SERVER_API_KEY", "").strip()
        if not required_key:
            return None

        # TODO: Make the Bearer realm value configurable.
        realm = 'monitor'

        auth_header = request.headers.get("Authorization", "")
        prefix = "Bearer "
        if not auth_header.startswith(prefix):
            return (
                jsonify({"error": "Missing or invalid Authorization header"}),
                401,
                {"WWW-Authenticate": f'Bearer realm="{realm}"'},
            )

        token = auth_header[len(prefix) :].strip()
        if token != required_key:
            return (
                jsonify({"error": "Unauthorized"}),
                401,
                {"WWW-Authenticate": f'Bearer realm="{realm}"'},
            )
        return None

    @app.route("/v1/models", methods=["GET"])
    def list_models():
        """
        List available models and return the active model.

        Returns an OpenAI-compatible /v1/models payload where each entry
        contains only standard fields (id, object, owned_by). The active
        model is provided via the top-level 'active_model' field; no per-item
        active flag is included.

        Returns:
            Response: JSON payload compatible with OpenAI /v1/models.
        """
        model_mapping = getattr(config, "MODEL_MAPPING", {}) or {}
        active_model = getattr(config, "MODEL", None)

        data = []
        for model_id in model_mapping.keys():
            data.append(
                {
                    "id": model_id,
                    "object": "model",
                    "owned_by": "monitor",
                }
            )

        payload = {
            "object": "list",
            "data": data,
            "active_model": active_model,
        }
        return jsonify(payload), 200

    @app.route("/v1/chat/completions", methods=["POST"])
    def chat_completions():
        """
        Create chat completions in an OpenAI-compatible format.

        This endpoint adapts the application CLI to a chat interface by
        converting OpenAI-style chat messages to a single CLI command, invoking
        internalize_command(), and formatting the result into a compatible
        response. Streaming over Server-Sent Events (SSE) is supported when
        the 'stream' flag is true.

        Returns:
            Response: JSON or SSE stream, status 200 on success, 400 for bad
            input, 500 for unexpected errors (with traceback in debug/dev).
        """
        try:
            data = request.get_json(silent=True) or {}
        except Exception:
            return jsonify({"error": "Invalid JSON payload"}), 400

        messages = data.get("messages")
        if not isinstance(messages, list) or not messages:
            return jsonify({"error": "Field 'messages' must be a non-empty list"}), 400

        stream = bool(data.get("stream", False))

        try:
            command = convert_messages_to_command(messages)
        except Exception as exc:
            logger.error(
                f"Failed to convert messages to command: {exc}", exc_info=True
            )
            if app.debug or app.env == "development":
                tb = traceback.format_exc()
                return (
                    jsonify(
                        {"error": f"Bad messages format: {str(exc)}", "traceback": tb}
                    ),
                    400,
                )
            return jsonify({"error": "Bad messages format"}), 400

        try:
            result = internalize_command(command)
            final_text = _result_to_text(result)
            created = int(time.time())
            completion_id = f"chatcmpl-{int(time.time() * 1000)}"
            model_id = getattr(config, "MODEL", "monitor-model")

            if stream:
                def generate() -> Generator[str, None, None]:
                    """
                    Generator that yields SSE chat completion chunks.

                    Yields:
                        str: SSE data lines terminated by double newlines.
                    """
                    # Initial role frame
                    first_chunk = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model_id,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"role": "assistant"},
                                "finish_reason": None,
                            }
                        ],
                    }
                    yield f"data: {json.dumps(first_chunk)}\n\n"

                    # Stream content in small pieces.
                    chunk_size = 48
                    for i in range(0, len(final_text), chunk_size):
                        piece = final_text[i : i + chunk_size]
                        data_chunk = {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": model_id,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": piece},
                                    "finish_reason": None,
                                }
                            ],
                        }
                        yield f"data: {json.dumps(data_chunk)}\n\n"

                    # Final frame indicating stop
                    done_chunk = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model_id,
                        "choices": [
                            {"index": 0, "delta": {}, "finish_reason": "stop"}
                        ],
                    }
                    yield f"data: {json.dumps(done_chunk)}\n\n"
                    yield "data: [DONE]\n\n"

                return Response(
                    generate(),
                    mimetype="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "X-Accel-Buffering": "no",
                        "Connection": "keep-alive",
                    },
                )

            payload = {
                "id": completion_id,
                "object": "chat.completion",
                "created": created,
                "model": model_id,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": final_text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            }
            return jsonify(payload), 200
        except Exception as exc:
            logger.error(f"Error processing chat completion: {exc}", exc_info=True)
            if app.debug or app.env == "development":
                tb = traceback.format_exc()
                return jsonify({"error": str(exc), "traceback": tb}), 500
            return jsonify({"error": str(exc)}), 500

    @app.route("/cli", methods=["POST"])
    def cli():
        data = request.get_json(silent=True) or {}
        command = data.get("command")
        if not command:
            return jsonify({"error": "Missing 'command' field"}), 400
        normalized_command = command.lower().strip()
        if normalized_command in ("/exit", "exit"):
            logger.info(
                "Received exit command via API; initiating shutdown sequence."
            )
            # Capture the shutdown callback from the current request context.
            shutdown_callback = request.environ.get("werkzeug.server.shutdown")

            if shutdown_callback is None:
                logger.warning(
                    "werkzeug.server.shutdown not available; unable to trigger graceful shutdown."
                )
                return jsonify({"message": "Server shutting down..."}), 200

            def _shutdown_server(cb):
                """
                Attempt a graceful shutdown of the development server.

                We avoid calling os._exit(0) to enable graceful teardown and
                improve testability (e.g., letting in-flight responses finish
                and allowing test harnesses to assert post-conditions).
                """
                try:
                    cb()
                    logger.debug(
                        "Called werkzeug.server.shutdown() successfully."
                    )
                except Exception as exc:
                    logger.error(f"Error calling werkzeug shutdown: {exc}")

            threading.Thread(
                target=_shutdown_server,
                args=(shutdown_callback,),
                daemon=True,
            ).start()
            return jsonify({"message": "Server shutting down..."}), 200
        try:
            result = internalize_command(command)
            return jsonify(result), 200
        except Exception as exc:
            logger.error(
                f"Error processing command via API: {exc}", exc_info=True
            )
            if app.debug or app.env == "development":
                tb = traceback.format_exc()
                return jsonify({"error": str(exc), "traceback": tb}), 500
            else:
                return jsonify({"error": str(exc)}), 500

    # Wrap the Flask app with middleware to ensure single-request processing.
    app.wsgi_app = SingleRequestMiddleware(app.wsgi_app, logger=logger)
    logger.info(
        "SingleRequestMiddleware enabled: requests will be processed one at a time."
    )
    return app


def create_flask_server(host: str, port: int):
    """
    Create and run the Flask development server for the CLI API.

    Args:
        host (str): Host interface to bind the server to.
        port (int): Port number to listen on.

    Returns:
        Flask: The Flask application instance (after the server stops).
    """
    local_hosts = {"127.0.0.1", "localhost"}
    if host not in local_hosts:
        warning_header = "!!! SECURITY WARNING !!!"
        if host == "0.0.0.0":
            warning_detail = (
                f"Flask server is listening on '0.0.0.0', which exposes the /cli and /v1 API "
                f"endpoints on ALL network interfaces. This can be very insecure if not protected!"
            )
        else:
            warning_detail = (
                f"Flask server is listening on '{host}', which may be accessible from outside localhost. "
                f"The /cli and /v1 endpoints receive arbitrary commands and requests and could be exploited if publicly reachable."
            )
        warning_footer = (
            "Restrict the host address to 127.0.0.1 or use proper network security controls!"
        )
        full_warning = (
            f"\n{warning_header}\n{warning_detail}\n{warning_footer}\n"
            "-------------------------------------------------------"
        )
        print(full_warning)
        logger.warning(full_warning)

    single_user_banner = (
        "\n=== SINGLE-USER SERIALIZED MODE ===\n"
        "All HTTP requests will be processed one at a time.\n"
        "Intended for single-user or test scenarios.\n"
        "-----------------------------------------------"
    )
    print(single_user_banner)
    logger.info(single_user_banner)

    app = make_flask_app()
    logger.info(f"Starting Flask server on {host}:{port}")
    app.run(host=host, port=port, use_reloader=False)
    logger.info("Flask server stopped.")
    return app
