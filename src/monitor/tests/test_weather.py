import unittest
from monitor.lib import weather

class TestWeather(unittest.TestCase):
    def test_get_current_weather_stub(self):
        """Test the stub weather response for any location"""
        result = weather.get_current_weather("New York, NY", unit="F")
        self.assertEqual(result, "The weather is 12F and cold.")

    def test_logging(self):
        """Test if fetching weather logs an info message (rudimentary check)"""
        import logging
        with self.assertLogs('lib.weather', level='INFO') as cm:
            _ = weather.get_current_weather("Toronto, ON")
        self.assertTrue(any("Fetching weather for Toronto, ON" in msg for msg in cm.output))

if __name__ == "__main__":
    unittest.main()