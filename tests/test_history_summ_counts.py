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
        # Simulate a long conversation that will be summarized
        self.history = [
            {"role": "system", "content": "System prompt."},
        ] + [{"role": "user", "content": f"User msg {i}"} for i in range(9)]
        self.config = DummyConfig()
        self.logger = DummyLogger()

    def test_prompt_counts_stale_after_reset(self):
        # Simulate prompt rendering BEFORE summarization
        original_count = len(self.history)
        prompt_before = format_prompt_display(
            conversation_count=original_count,
            tokens_remaining=self.config.MAX_TOKEN_COUNT - self.config.TOTAL_TOKEN_COUNT,
            cwd="/fakepath",
            model="gpt-test"
        )
        # Now summarize, which resets/constrains the conversation
        summary = "SUMMARY"
        def append_func(m, hist, count_func, update_func): hist.append(m)
        def set_token_count(val): self.config.TOTAL_TOKEN_COUNT = val
        reset_conversation_with_summary(
            summary=summary,
            system_prompt="System prompt.",
            user_input="New user input.",
            conversation_history=self.history,
            append_func=append_func,
            set_token_count_func=set_token_count,
            logger=self.logger,
            config=self.config,
        )
        # Prompt _counts_ must be recalculated after reset!
        # But in a buggy flow, prompt display could use old values.
        prompt_after = format_prompt_display(
            conversation_count=original_count,  # BUG: passing old value intentionally
            tokens_remaining=self.config.MAX_TOKEN_COUNT - self.config.TOTAL_TOKEN_COUNT,
            cwd="/fakepath",
            model="gpt-test"
        )
        # The displayed count WILL be wrong if caller reused the original_count var
        self.assertIn(f"H:{original_count}", prompt_after)  # surfaces that this can go stale
        # Now calculate the *live* new count
        live_count = len(self.history)
        true_prompt = format_prompt_display(
            conversation_count=live_count,
            tokens_remaining=self.config.MAX_TOKEN_COUNT - self.config.TOTAL_TOKEN_COUNT,
            cwd="/fakepath",
            model="gpt-test"
        )
        self.assertIn(f"H:{live_count}", true_prompt)
        self.assertNotEqual(
            prompt_after, true_prompt,
            "Prompt after summarization must display updated count, not stale one!"
        )

if __name__ == "__main__":
    unittest.main()
