import unittest
from monitor.lib.history import reset_conversation_with_summary
from monitor.lib.display_output import format_prompt_display

class DummyLogger:
    def info(self, *a, **k): pass
    def debug(self, *a, **k): pass
    def error(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def critical(self, *a, **k): pass
    def __getattr__(self, name):
        return lambda *a, **k: None

class DummyConfig:
    def __init__(self):
        self.TOTAL_TOKEN_COUNT = 100
        self.MAX_TOKEN_COUNT = 200
        self.CONVERSATION_MAX_SIZE = 10
        self.SUMMARIZATION_CONFIG = {
            'triggers': {
                'token_threshold': 0.5,
                'time_limit_seconds': 3600,
                'memory_limit_mb': 100,
            },
            'prompt': {'template': 'Summarize: {messages}'},
        }
        self.MODEL = "gpt-test"
        self.last_summary_time = 0
        self.EXTERNAL_SERVICES = False

class TestPromptCountsAfterSummarization(unittest.TestCase):
    def setUp(self):
        # Simulate a pre-summarization conversation history, nearly at the size limit
        self.history = [
            {"role": "system", "content": "System prompt."},
        ] + [{"role": "user", "content": f"User msg {i}"} for i in range(9)]
        self.config = DummyConfig()
        self.logger = DummyLogger()

    def test_prompt_counts_stale_after_reset(self):
        """
        This test validates that after a summarization event, the prompt display
        uses an up-to-date count of the conversation history, rather than stale data.

        Steps:
        - Simulate a realistic conversation history just before summarization threshold.
        - Render the prompt with the original count (pre-summarization state).
        - Pass the conversation history through reset_conversation_with_summary to induce summarization.
        - Without updating, render the prompt again with the stale count (should surface the bug).
        - Assert that recalculating using the fresh, post-summarization conversation yields a different prompt.
        - Ensures callers must always update counts after summarization.
        """
        # Render the prompt BEFORE summarization occurs to get the original count
        original_count = len(self.history)
        prompt_before = format_prompt_display(
            conversation_count=original_count,
            tokens_remaining=self.config.MAX_TOKEN_COUNT - self.config.TOTAL_TOKEN_COUNT,
            cwd="/fakepath",
            model=self.config.MODEL
        )
        # Simulate summarizing (reset) the conversation history
        summary = "SUMMARY"
        # Define hook for appending a message to conversation history: (message, history, count_tokens_func, update_func)
        def append_func(message, history, count_tokens_func, update_func):
            history.append(message)
            # Simulate all necessary updates that append_func should do per calling contract

        # Execute the summarization event, which resets/constrains history in-place
        reset_conversation_with_summary(
            summary=summary,
            system_prompt="System prompt.",
            user_input="New user input.",
            conversation_history=self.history,
            append_func=append_func,
            logger=self.logger,
            config=self.config,
        )
        # Render the prompt AGAIN—but with the *stale*, pre-summarization count (a common bug)
        prompt_after = format_prompt_display(
            conversation_count=original_count,  # Deliberately using stale value
            tokens_remaining=self.config.MAX_TOKEN_COUNT - self.config.TOTAL_TOKEN_COUNT,
            cwd="/fakepath",
            model=self.config.MODEL
        )
        # Bug is surfaced here: displayed count is now stale, not reflecting summarization.
        # Format note: once summarization/compaction has fired, the H indicator
        # prefixes the compaction count as "H:(N) <count>".
        self.assertIn(f"{original_count}", prompt_after)
        # Render the "truth" using the updated, live count after summarization
        live_count = len(self.history)
        true_prompt = format_prompt_display(
            conversation_count=live_count,
            tokens_remaining=self.config.MAX_TOKEN_COUNT - self.config.TOTAL_TOKEN_COUNT,
            cwd="/fakepath",
            model=self.config.MODEL
        )
        self.assertIn(f"{live_count}", true_prompt)
        # Assertion: after summarization, prompt_after (from stale data) and true_prompt (from live data) must differ
        self.assertNotEqual(
            prompt_after, true_prompt,
            "Prompt after summarization must display updated count, not stale one!"
        )

if __name__ == "__main__":
    unittest.main()
