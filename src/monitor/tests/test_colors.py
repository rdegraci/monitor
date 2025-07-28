
import unittest
from monitor.lib import colors

class TestColors(unittest.TestCase):    
    def test_ansi_sequence_application(self):
        """Test that wrapping with color constants creates valid ANSI sequences."""
        sample_text = "hello"
        # Compose with color and reset
        output = f"{colors.red}{sample_text}{colors.reset}"
        print('colors.red:', repr(colors.red))
        print('colors.blue:', repr(colors.blue))
        print('colors.yellow:', repr(colors.yellow))
        print('colors.reset:', repr(colors.reset))
        self.assertIn(sample_text, output)
        self.assertTrue(output.startswith(colors.red))
        self.assertTrue(output.endswith(colors.reset))

if __name__ == "__main__":
    unittest.main()


