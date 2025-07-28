import logging

logger = logging.getLogger(__name__)

def get_current_weather(location, unit="F"):
    logger.info(f"Fetching weather for {location}")
    return "The weather is 12F and cold."
