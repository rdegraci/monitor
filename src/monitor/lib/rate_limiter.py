"""Modified rate limiter with a reduced safety factor to prevent hitting rate limits.
"""

import logging
import time
import re
from monitor import config
from datetime import datetime

logger = logging.getLogger(__name__)

ANTHROPIC_SAFETY_THRESHOLD_MULTIPLIER = 1.05

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
                raw_token_count = anthropic.count_tokens(text)
                # Anthropic counts tend to be conservative for this limiter's use case.
                adjusted_token_count = int(raw_token_count * 0.9)
                logger.debug(
                    "anthropic.count_tokens raw token count: %s, adjusted token count: %s",
                    raw_token_count,
                    adjusted_token_count,
                )
                return adjusted_token_count
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
        grace_buffer_seconds (float): Seconds added after a cooldown to reduce immediate back-to-back
            retries at the window edge. Defaults to GRACE_BUFFER_SECONDS (3.0).
    """

    GRACE_BUFFER_SECONDS = 3.0

    def __init__(self, logger, limit=800000, window_seconds=60, safety_factor=0.6, now_fn=None, sleep_fn=None, grace_buffer_seconds=None):
        """
        Initialize the rate limiter.

        Args:
            logger: Logger object for logging events.
            limit (int): Maximum tokens allowed in the window period (default: 800000)
            window_seconds (int): Time window in seconds (default: 60)
            safety_factor (float): Factor to apply to limit as a buffer (default: 0.6)
            now_fn (callable, optional): Function to obtain current time in seconds. Defaults to time.time.
            sleep_fn (callable, optional): Sleep function accepting seconds. Defaults to time.sleep.
            grace_buffer_seconds (float, optional): Seconds added after a cooldown to reduce immediate
                back-to-back retries at the window edge. Defaults to GRACE_BUFFER_SECONDS (3.0).
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
        self.grace_buffer_seconds = grace_buffer_seconds if grace_buffer_seconds is not None else self.GRACE_BUFFER_SECONDS

        logger.info("RateLimiter initialized with safety threshold of %s tokens", self.safety_threshold)

    def _get_effective_safety_threshold(self):
        model_name = getattr(config, "MODEL", None)
        model_name_str = str(model_name).lower() if model_name else ""
        if "anthropic" in model_name_str or "claude" in model_name_str:
            adjusted_threshold = self.safety_threshold * ANTHROPIC_SAFETY_THRESHOLD_MULTIPLIER
            self.logger.info(
                "[RATE LIMITING] Anthropic safety tuning active: base_threshold=%s, adjusted_threshold=%s, multiplier=%s",
                self.safety_threshold,
                adjusted_threshold,
                ANTHROPIC_SAFETY_THRESHOLD_MULTIPLIER,
            )
            return adjusted_threshold
        return self.safety_threshold

    def reset(self):
        """
        Clear all recorded token usage and warning state.

        Intended for use when the rate-limited resource is no longer comparable
        to the previously-recorded window — e.g., a model switch where the new
        model has different TPM limits, or an explicit history reset where the
        accumulated token totals no longer reflect what will be sent next.
        """
        self.logger.info(
            "[RATE LIMITING] Resetting rate-limiter window (cleared %s recorded entries)",
            len(self.token_usage),
        )
        self.token_usage = []
        self.last_warning_time = 0

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

        safety_threshold = self._get_effective_safety_threshold()

        if estimated_tokens > safety_threshold:
            self.logger.error(
                "Cannot process request: Estimated tokens for a single call (%d)"
                "exceed the configured safety threshold of (%d tokens, limit: %d, factor: %.2f). "
                "Reduce the request size, split it into smaller batches, or increase your "
                "rate limit configuration. No cooldown will help, this request is unprocessable in a single window.",
                estimated_tokens, safety_threshold, self.limit,
                safety_threshold / self.limit if self.limit else 0.0,
            )
            return None, self.window_seconds

        now = self.now_fn()
        self._clean_expired(now)

        current_usage = self.get_current_usage()
        projected_usage = current_usage + estimated_tokens

        self.logger.info("[RATE LIMITING] Projected usage: %s/%s (safety threshold: %s)", 
                         projected_usage, self.limit, safety_threshold)

        if projected_usage > safety_threshold:
            # If approaching limit, calculate recommended wait time
            if self.token_usage:
                # Threshold-sensitive cooldown calculation
                target_remaining = safety_threshold - estimated_tokens
                remaining = current_usage
                boundary_timestamp = None

                for ts, tokens in self.token_usage:
                    remaining -= tokens
                    if remaining <= target_remaining:
                        boundary_timestamp = ts
                        break

                if boundary_timestamp is not None:
                    expiry_boundary = boundary_timestamp + self.window_seconds
                    self.logger.debug(
                        "[RATE LIMITING] Cooldown diagnostics: oldest_active_token_timestamp=%s, active_usage_entries=%s, expiry_boundary=%s, boundary_timestamp_used=%s",
                        self.token_usage[0][0],
                        len(self.token_usage),
                        expiry_boundary,
                        boundary_timestamp,
                    )
                    time_to_free = expiry_boundary - now
                else:
                    oldest_time = self.token_usage[0][0]
                    expiry_boundary = oldest_time + self.window_seconds
                    self.logger.debug(
                        "[RATE LIMITING] Cooldown diagnostics: oldest_active_token_timestamp=%s, active_usage_entries=%s, expiry_boundary=%s, oldest_timestamp_fallback_used=%s",
                        oldest_time,
                        len(self.token_usage),
                        expiry_boundary,
                        oldest_time,
                    )
                    time_to_free = expiry_boundary - now

                cooldown_seconds = max(0, time_to_free)
                if cooldown_seconds > 0:
                    self.logger.debug(
                        "Applying post-cooldown grace buffer of %s seconds to reduce immediate back-to-back cooldowns",
                        self.grace_buffer_seconds,
                    )
                    cooldown_seconds += self.grace_buffer_seconds

                self.logger.debug(
                    "[RATE LIMITING] Cooldown until diagnostic: current_time=%s, cooldown_expires_at=%s, remaining_wait_seconds=%s",
                    now,
                    now + cooldown_seconds,
                    cooldown_seconds,
                )

                # Only log a warning once every 5 seconds to prevent spam
                if now - self.last_warning_time > 5:
                    tokens_to_clear = int(max(0, projected_usage - safety_threshold))
                    self.logger.warning(
                        "Token usage is projected at %d tokens after adding %d estimated tokens "
                        "(safety threshold: %d, limit: %d). Approximately %d tokens must clear. "
                        "Cooling down for %.1f seconds to remain under the API cap.",
                        projected_usage, estimated_tokens, int(safety_threshold), self.limit, tokens_to_clear, cooldown_seconds
                    )
                    self.last_warning_time = now

                self.logger.info("Rate limit cooldown needed: %s seconds", cooldown_seconds)
                return False, cooldown_seconds
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

        # Request too large
        if can_proceed is None:
            return None
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
