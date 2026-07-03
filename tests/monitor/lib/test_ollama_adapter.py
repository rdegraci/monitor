from monitor.lib.ollama_adapter import adapt_ollama_chat_response


def test_adapt_ollama_chat_response_wraps_native_message() -> None:
    """Adapt a native Ollama message into legacy completion shape."""
    response = {
        "message": {"content": "hello world"},
        "done": True,
        "usage": {"total_tokens": 12},
    }

    adapted = adapt_ollama_chat_response(response)

    assert adapted["choices"][0]["message"]["content"] == "hello world"
    assert adapted["choices"][0]["finish_reason"] == "stop"
    assert adapted["usage"]["total_tokens"] == 12
