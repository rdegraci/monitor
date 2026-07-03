from types import SimpleNamespace

from monitor.lib.ollama_adapter import adapt_ollama_chat_response


def test_adapt_ollama_chat_response_wraps_native_message() -> None:
    """Adapt a native Ollama message into legacy completion shape."""
    response = SimpleNamespace(
        message=SimpleNamespace(
            content="hello world",
            tool_calls=[SimpleNamespace(id="call-1", function=SimpleNamespace(name="create_file", arguments={"path": "/tmp/hello.txt", "contents": "hello world"}))],
        ),
        done=True,
        usage={"total_tokens": 12},
    )

    adapted = adapt_ollama_chat_response(response)

    assert adapted["choices"][0]["message"]["content"] == "hello world"
    assert adapted["choices"][0]["message"]["tool_calls"][0]["id"] == "call-1"
    assert adapted["choices"][0]["message"]["tool_calls"][0]["type"] == "function"
    assert adapted["choices"][0]["message"]["tool_calls"][0]["function"] == {
        "name": "create_file",
        "arguments": {"path": "/tmp/hello.txt", "contents": "hello world"},
    }
    assert adapted["choices"][0]["finish_reason"] == "tool_calls"
    assert adapted["usage"]["total_tokens"] == 12


def test_adapt_ollama_chat_response_generates_missing_tool_call_id() -> None:
    """Generate a non-empty fallback id when Ollama omits a tool-call id."""
    response = SimpleNamespace(
        message=SimpleNamespace(
            content="",
            tool_calls=[SimpleNamespace(function=SimpleNamespace(name="create_file", arguments={"path": "/tmp/hello.txt"}))],
        ),
        done=True,
    )

    adapted = adapt_ollama_chat_response(response)

    tool_call = adapted["choices"][0]["message"]["tool_calls"][0]
    assert tool_call["id"].startswith("ollama-tool-0-")
    assert tool_call["function"]["name"] == "create_file"
    assert adapted["choices"][0]["finish_reason"] == "tool_calls"


def test_adapt_ollama_chat_response_preserves_multiple_tool_calls() -> None:
    """Preserve multiple tool calls in a single Ollama assistant turn."""
    response = SimpleNamespace(
        message=SimpleNamespace(
            content="",
            tool_calls=[
                SimpleNamespace(
                    id="call-1",
                    function=SimpleNamespace(
                        name="create_file",
                        arguments={"path": "/tmp/hello.txt", "contents": "hello world"},
                    ),
                ),
                SimpleNamespace(
                    id="call-2",
                    function=SimpleNamespace(
                        name="create_file",
                        arguments={"path": "/tmp/goodbye.txt", "contents": "goodbye world"},
                    ),
                ),
            ],
        ),
        done=True,
    )

    adapted = adapt_ollama_chat_response(response)

    tool_calls = adapted["choices"][0]["message"]["tool_calls"]
    assert len(tool_calls) == 2
    assert tool_calls[0]["id"] == "call-1"
    assert tool_calls[0]["function"]["name"] == "create_file"
    assert tool_calls[1]["id"] == "call-2"
    assert tool_calls[1]["function"]["arguments"] == {
        "path": "/tmp/goodbye.txt",
        "contents": "goodbye world",
    }
    assert adapted["choices"][0]["finish_reason"] == "tool_calls"


def test_adapt_ollama_chat_response_returns_stop_without_tool_calls() -> None:
    """Return a stop finish reason when no tool calls are present."""
    response = SimpleNamespace(
        message=SimpleNamespace(content="final answer", tool_calls=None),
        done=True,
        done_reason="stop",
    )

    adapted = adapt_ollama_chat_response(response)

    assert adapted["choices"][0]["message"]["content"] == "final answer"
    assert "tool_calls" not in adapted["choices"][0]["message"]
    assert adapted["choices"][0]["finish_reason"] == "stop"
