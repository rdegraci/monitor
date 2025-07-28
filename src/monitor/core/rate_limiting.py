import logging

from monitor import config 

from monitor.lib.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

# Singleton instance for Core global use
logger.info("Creating global rate limiter instance with TPM limit of %s", config.MODEL_MAX_TPM)
RATE_LIMITER = RateLimiter(
	logger, 
	config.MODEL_MAX_TPM, 
	config.RATE_LIMITING_CONFIG['window_seconds'],
	config.RATE_LIMITING_CONFIG['safety_factor'],
	)