"""
Tests for lib.rate_limiter
"""
import pytest
from monitor.lib import rate_limiter

class DummyLogger:
    def __init__(self):
        self.debug_msgs = []
        self.info_msgs = []
        self.warn_msgs = []
        self.error_msgs = []
        self.warning_msgs = []  # for 'warning' log method
    def debug(self, msg, *args):
        self.debug_msgs.append(msg % args if args else msg)
    def info(self, msg, *args):
        self.info_msgs.append(msg % args if args else msg)
    def warning(self, msg, *args):
        self.warning_msgs.append(msg % args if args else msg)
    def warn(self, msg, *args):  # For compat
        self.warn_msgs.append(msg % args if args else msg)
    def error(self, msg, *args):
        self.error_msgs.append(msg % args if args else msg)


def test_estimate_token_count_simple():
    assert rate_limiter.estimate_token_count('A quick brown fox') > 0
    assert rate_limiter.estimate_token_count('') == 0
    assert rate_limiter.estimate_token_count('Word') >= 1


def test_add_and_clean_usage():
    fake_time = [100.0]
    def now_fn():
        return fake_time[0]
    logger = DummyLogger()
    rl = rate_limiter.RateLimiter(logger, limit=100, window_seconds=10, now_fn=now_fn)
    rl.add_request(20)
    assert rl.get_current_usage() == 20
    fake_time[0] += 11  # advance past window
    assert rl.get_current_usage() == 0


def test_check_limit_and_wait():
    fake_time = [100.0]
    def now_fn():
        return fake_time[0]
    slept = []
    def sleep_fn(secs):
        slept.append(secs)
    logger = DummyLogger()
    rl = rate_limiter.RateLimiter(logger, limit=50, window_seconds=5, safety_factor=0.8, now_fn=now_fn, sleep_fn=sleep_fn)
    # Add a request under the threshold
    rl.add_request(10)
    can_proceed, cooldown = rl.check_limit(20)
    assert can_proceed is True
    # Add more to push over safety threshold
    rl.add_request(31)  # now at 41
    can_proceed2, cooldown2 = rl.check_limit(10)
    assert can_proceed2 is False
    assert cooldown2 > 0
    # Wait function should be called if over threshold
    waited = rl.wait_if_needed(10)
    assert waited is True
    assert slept[-1] == cooldown2


def test_exceed_maximum_allowed():
    fake_time = [100.0]
    def now_fn():
        return fake_time[0]
    logger = DummyLogger()
    rl = rate_limiter.RateLimiter(logger, limit=100, window_seconds=10, safety_factor=0.5, now_fn=now_fn)
    # Estimated tokens exceeds safety threshold of 50
    can_proceed, cooldown = rl.check_limit(75)
    assert can_proceed is None
    assert cooldown == 10


def test_rate_limit_no_records():
    fake_time = [100.0]
    def now_fn():
        return fake_time[0]
    logger = DummyLogger()
    rl = rate_limiter.RateLimiter(logger, limit=100, window_seconds=10, safety_factor=0.8, now_fn=now_fn)
    # Clear all token usage records
    rl.token_usage = []
    # Simulate usage right at safety threshold
    can_proceed, cooldown = rl.check_limit(81)
    assert can_proceed is None
    assert cooldown == 10

"""
This test suite covers:
- Token estimation
- RateLimiter time window logic
- Enforcement of thresholds and sleep cooldowns
- Over-limit single call logic
- Graceful handling of no-record scenario
"""