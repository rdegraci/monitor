
"""
Modified rate limiter with a reduced safety factor to prevent hitting rate limits.
"""

import logging
import time
import re
from monitor import config
from datetime import datetime

logger = logging.getLogger(__name__)

def estimate_token_count(text):
    """
    Estimate the number of tokens in a text string.

    This method uses the configured model to select the most accurate
    token counting logic. For OpenAI models, tiktoken is used (if available).
    For Anthropic, anthropic.count_tokens is used (if available).
    For Google Gemini and unknown models, a 4-char-per-token heuristic is used.

    This function retains robust logging and fallback code for unsupported or 
    missing packages.

    Args:
        text (str): The text to estimate tokens for
        
    Returns:
        int: Estimated token count
    """
    logger.debug("Estimating token count for text: length=%s", len(text) if text else 0)
    if not text:
        logger.debug("Empty text provided, returning 0 tokens")
        return 0

    model_name = getattr(config, "MODEL", None)
    model_name_str = str(model_name).lower() if model_name else ""
    logger.debug("Estimating tokens for model: %s", model_name_str)

    # OpenAI models: Prefer tiktoken
    # Note: xai/grok uses an algorithm similar to openai
    if any(model_key in model_name_str for model_key in ('gpt-', 'openai', 'xai/grok')):
        try:
            import tiktoken
            encoding = None
            # tiktoken encoding logic depends on model name
            try:
                encoding = tiktoken.encoding_for_model(model_name)
            except Exception:
                encoding = tiktoken.get_encoding("cl100k_base")
            token_count = len(encoding.encode(text))
            logger.debug("tiktoken estimated token count: %s", token_count)
            return token_count
        except ImportError as e:
            logger.warning("tiktoken not installed or import failed: %s. Falling back to heuristic.", str(e))
        except Exception as e:
            logger.warning("tiktoken could not calculate tokens: %s. Falling back to heuristic.", str(e))

    # Anthropic models: Prefer anthropic.count_tokens if available
    if "anthropic" in model_name_str or "claude" in model_name_str:
        try:
            import anthropic
            if hasattr(anthropic, "count_tokens"):
                token_count = anthropic.count_tokens(text)
                logger.debug("anthropic.count_tokens estimated token count: %s", token_count)
                return token_count
        except ImportError as e:
            logger.warning("anthropic not installed or import failed: %s. Falling back to heuristic.", str(e))
        except Exception as e:
            logger.warning("anthropic.count_tokens failed: %s. Falling back to heuristic.", str(e))

    # Gemini/Google models: log warning, use 4-char-per-token heuristic
    if "gemini" in model_name_str or "google" in model_name_str:
        logger.warning("Token estimation for Google Gemini is approximate, using 4-char-per-token heuristic.")
        est = max(1, len(text) // 4)
        logger.debug("Heuristic 4-char-per-token estimated token count: %s", est)
        return est

    # Heuristic fallback (from legacy)
    words = len(re.findall(r'\b\w+\b', text))
    spaces = len(re.findall(r'\s', text))
    punctuation = len(re.findall(r'[^\w\s]', text))

    logger.debug("Token calculation components: words=%s, spaces=%s, punctuation=%s", 
                 words, spaces, punctuation)

    estimated_tokens = (words * 1.3) + (spaces * 0.25) + (punctuation * 0.75)
    result = int(estimated_tokens * 1.1)
    logger.debug("Estimated token count (fallback heuristic): %s", result)
    return result

class RateLimiter:
    """
    Token-based rate limiter for API calls.
    
    Tracks token usage over a sliding window and enforces
    cooldown periods when approaching rate limits.

    Args:
        logger: Logger object for logging events.
        limit (int): Maximum tokens allowed in the window period (default: 800000)
        window_seconds (int): Time window in seconds (default: 60)
        safety_factor (float): Factor to apply to limit as a buffer (default: 0.6)
        now_fn (callable): Optional function that returns the current time in seconds. Defaults to time.time.
        sleep_fn (callable): Optional function that accepts seconds and sleeps. Defaults to time.sleep.
    """

    def __init__(self, logger, limit=800000, window_seconds=60, safety_factor=0.6, now_fn=None, sleep_fn=None):
        """
        Initialize the rate limiter.

        Args:
            logger: Logger object for logging events.
            limit (int): Maximum tokens allowed in the window period (default: 800000)
            window_seconds (int): Time window in seconds (default: 60)
            safety_factor (float): Factor to apply to limit as a buffer (default: 0.6)
            now_fn (callable, optional): Function to obtain current time in seconds. Defaults to time.time.
            sleep_fn (callable, optional): Sleep function accepting seconds. Defaults to time.sleep.
        """
        logger.debug("Initializing RateLimiter: limit=%s, window_seconds=%s, safety_factor=%s", 
                    limit, window_seconds, safety_factor)

        self.logger = logger
        self.limit = limit
        self.window_seconds = window_seconds
        self.safety_threshold = limit * safety_factor
        self.token_usage = []  # List of (timestamp, tokens) tuples
        self.last_warning_time = 0

        self.now_fn = now_fn if now_fn is not None else time.time
        self.sleep_fn = sleep_fn if sleep_fn is not None else time.sleep

        logger.info("RateLimiter initialized with safety threshold of %s tokens", self.safety_threshold)

    def add_request(self, tokens):
        """
        Record token usage for a request and clean up expired entries.

        Args:
            tokens (int): Number of tokens used in the request
        """
        self.logger.debug("Adding request with %s tokens to usage tracker", tokens)

        now = self.now_fn()
        self.token_usage.append((now, tokens))
        self._clean_expired(now)

        current_usage = sum(tokens for _, tokens in self.token_usage)
        self.logger.debug("Current token usage after adding request: %s/%s", 
                         current_usage, self.limit)

    def _clean_expired(self, now):
        """
        Remove token usage records older than the window.

        Args:
            now (float): Current time in seconds
        """
        self.logger.debug("Cleaning expired token usage records: window=%s seconds", 
                         self.window_seconds)

        cutoff = now - self.window_seconds
        before_count = len(self.token_usage)
        self.token_usage = [(t, tokens) for t, tokens in self.token_usage if t >= cutoff]
        after_count = len(self.token_usage)

        if before_count != after_count:
            self.logger.debug("Removed %s expired token usage records", 
                             before_count - after_count)

    def get_current_usage(self):
        """
        Get the current token usage in the window.

        Returns:
            int: Total tokens used in current window
        """
        self.logger.debug("Getting current token usage")

        now = self.now_fn()
        self._clean_expired(now)
        current_usage = sum(tokens for _, tokens in self.token_usage)

        self.logger.debug("Current token usage: %s/%s", current_usage, self.limit)
        return current_usage

    def check_limit(self, estimated_tokens):
        """
        Check if adding estimated_tokens would exceed the rate limit.

        Args:
            estimated_tokens (int): Estimated tokens for next operation

        Returns:
            tuple: (can_proceed, cooldown_seconds)
        """
        self.logger.info("[RATE LIMITING] Checking rate limit for operation with %s estimated tokens", 
                         estimated_tokens)

        if estimated_tokens > self.safety_threshold:
            self.logger.error(
                "Cannot process request: Estimated tokens for a single call (%d)"
                "exceed the configured safety threshold of (%d tokens, limit: %d, factor: %.2f). "
                "Reduce the request size, split it into smaller batches, or increase your "
                "rate limit configuration. No cooldown will help, this request is unprocessable in a single window.",
                estimated_tokens, self.safety_threshold, self.limit,
                self.safety_threshold / self.limit if self.limit else 0.0,
            )
            return False, self.window_seconds

        now = self.now_fn()
        self._clean_expired(now)

        current_usage = self.get_current_usage()
        projected_usage = current_usage + estimated_tokens

        self.logger.info("[RATE LIMITING] Projected usage: %s/%s (safety threshold: %s)", 
                         projected_usage, self.limit, self.safety_threshold)

        if projected_usage > self.safety_threshold:
            # If approaching limit, calculate recommended wait time
            if self.token_usage:
                oldest_time = self.token_usage[0][0]
                time_to_free = (oldest_time + self.window_seconds) - now

                # Only log a warning once every 5 seconds to prevent spam
                if now - self.last_warning_time > 5:
                    self.logger.warning(
                        "Token usage is at %d tokens in the last %ds (limit: %d, safety threshold: %d). "
                        "This may temporarily exceed the configured limit due to request bursts. "
                        "Cooling down for %.1f seconds to remain under the API cap.",
                        current_usage, self.window_seconds, self.limit, self.safety_threshold, round(time_to_free, 1)
                    )
                    self.last_warning_time = now

                # Add extra buffer time to ensure we're well under the limit
                time_to_free += 3.0  # Add 3 seconds extra buffer

                self.logger.info("Rate limit cooldown needed: %s seconds", round(time_to_free, 1))
                return False, max(0, time_to_free)
            else:
                self.logger.error("Rate limit approaching but no token usage records found. Logic error.")
                return False, self.window_seconds  # Default cooldown

        self.logger.debug("[RATE LIMITING] Rate limit check passed, operation can proceed")
        return True, 0

    def wait_if_needed(self, estimated_tokens):
        """
        Wait if the rate limit would be exceeded.

        Args:
            estimated_tokens (int): Estimated tokens for next operation

        Returns:
            bool: True if waited, False if proceeded immediately
        """
        self.logger.debug("Checking if wait is needed for operation with %s estimated tokens", 
                         estimated_tokens)

        can_proceed, wait_time = self.check_limit(estimated_tokens)

        if not can_proceed:
            self.logger.info("Initiating cooldown period of %s seconds", round(wait_time, 1))
            self.sleep_fn(wait_time)
            self.logger.info("Cooldown period completed, resuming operations")
            return True

        self.logger.debug("No cooldown needed, proceeding immediately")
        return False


RATE_LIMITER=None

def configure_rate_limiter(logger, max_tmp, window_seconds, safety_factor):
    global RATE_LIMITER
    RATE_LIMITER = RateLimiter(
        logger, 
        max_tmp, 
        window_seconds,
        safety_factor,
        )