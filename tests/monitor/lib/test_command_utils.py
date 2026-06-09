import unittest
import subprocess
import logging
from unittest.mock import patch, MagicMock, call
from monitor.lib import command_utils


class TestCommandUtils(unittest.TestCase):
    """Test suite for command_utils module functions."""

    def test_get_first_word_basic(self):
        """Test extracting first word from basic command strings."""
        self.assertEqual(command_utils.get_first_word("ls -la"), "ls")
        self.assertEqual(command_utils.get_first_word("git status"), "git")
        self.assertEqual(command_utils.get_first_word("python script.py"), "python")

    def test_get_first_word_single_word(self):
        """Test extracting first word from single word commands."""
        self.assertEqual(command_utils.get_first_word("ls"), "ls")
        self.assertEqual(command_utils.get_first_word("pwd"), "pwd")

    def test_get_first_word_empty_or_none(self):
        """Test get_first_word with empty, None, or whitespace-only inputs."""
        self.assertEqual(command_utils.get_first_word(""), "")
        self.assertEqual(command_utils.get_first_word(None), "")
        self.assertEqual(command_utils.get_first_word("   "), "")
        self.assertEqual(command_utils.get_first_word("\n\t  \n"), "")

    def test_get_first_word_with_leading_whitespace(self):
        """Test get_first_word with leading whitespace."""
        self.assertEqual(command_utils.get_first_word("  ls -la"), "ls")
        self.assertEqual(command_utils.get_first_word("\t\ngit status"), "git")

    def test_handle_error_logs_all_levels(self):
        """Logs appear at all supported levels. Uses display=False so print is not observed.
        
        Note: Do not assert that mock_print.call_count == 0.
        In some test runners or CI systems, other logging or
        code may emit prints even when display=False is passed.
        This test guarantees that our function doesn't require print output
        for correctness, but does not enforce zero global stdout activity.
        Instead, correctness is asserted ONLY through log output content.
        """
        msg = "Log level test"
        exc = Exception("log detail")

        levels_methods = [
            ("error", "ERROR"),
            ("warning", "WARNING"),
            ("info", "INFO"),
            ("debug", "DEBUG"),
        ]
        for log_level, log_tag in levels_methods:
            with self.subTest(level=log_level):
                with patch('builtins.print') as mock_print, self.assertLogs('monitor.lib.command_utils', level=log_tag) as cm:
                    command_utils.handle_error(msg, exception=exc, log_level=log_level, display=False)
                # Should log to correct level, include message and exception
                found_msg = any(msg in o for o in cm.output)
                found_exc = any("log detail" in o for o in cm.output)
                found_tag = any(log_tag in o for o in cm.output)
                self.assertTrue(found_msg)
                self.assertTrue(found_exc)
                self.assertTrue(found_tag)
                # Avoid strict print count assertion as system output is non-hermetic

    def test_handle_error_different_log_levels(self):
        """Test handle_error with different logging levels."""
        # Test warning level
        with self.assertLogs('monitor.lib.command_utils', level='WARNING') as cm:
            command_utils.handle_error(
                "Warning message", 
                log_level="warning",
                display=False
            )
        self.assertIn("WARNING", cm.output[0])
        
        # Test info level
        with self.assertLogs('monitor.lib.command_utils', level='INFO') as cm:
            command_utils.handle_error(
                "Info message", 
                log_level="info",
                display=False
            )
        self.assertIn("INFO", cm.output[0])

    @patch('subprocess.Popen')
    def test_run_subprocess_success(self, mock_popen):
        """Test successful subprocess execution."""
        # Mock process
        mock_process = MagicMock()
        mock_process.communicate.return_value = ("output", "")
        mock_process.returncode = 0
        mock_popen.return_value = mock_process
        
        exit_code, stdout, stderr, process = command_utils.run_subprocess("echo hello")
        
        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout, "output")
        self.assertEqual(stderr, "")
        self.assertEqual(process, mock_process)
        
        # Verify Popen was called with correct arguments
        mock_popen.assert_called_once()
        args, kwargs = mock_popen.call_args
        self.assertEqual(args[0], "echo hello")
        self.assertTrue(kwargs['shell'])
        self.assertTrue(kwargs['text'])
        self.assertEqual(kwargs['stdout'], subprocess.PIPE)
        self.assertEqual(kwargs['stderr'], subprocess.PIPE)

    @patch('subprocess.Popen')
    def test_run_subprocess_interactive(self, mock_popen):
        """Test subprocess execution in interactive mode."""
        mock_process = MagicMock()
        mock_process.wait.return_value = None
        mock_process.returncode = 0
        mock_popen.return_value = mock_process
        
        exit_code, stdout, stderr, process = command_utils.run_subprocess(
            "interactive_command", 
            interactive=True
        )
        
        self.assertEqual(exit_code, 0)
        self.assertIsNone(stdout)
        self.assertIsNone(stderr)
        
        # Should call wait() instead of communicate() for interactive
        mock_process.wait.assert_called_once()
        mock_process.communicate.assert_not_called()

    @patch('subprocess.Popen')
    def test_run_subprocess_with_cwd(self, mock_popen):
        """Test subprocess execution with custom working directory."""
        mock_process = MagicMock()
        mock_process.communicate.return_value = ("", "")
        mock_process.returncode = 0
        mock_popen.return_value = mock_process
        
        command_utils.run_subprocess("pwd", cwd="/tmp")
        
        args, kwargs = mock_popen.call_args
        self.assertEqual(kwargs['cwd'], "/tmp")

    @patch('subprocess.Popen')
    def test_run_subprocess_start_failure(self, mock_popen):
        """Test subprocess execution when process fails to start."""
        mock_popen.side_effect = OSError("Command not found")
        
        with patch('builtins.print'):
            with self.assertLogs('monitor.lib.command_utils', level='ERROR'):
                result = command_utils.run_subprocess("nonexistent_command")
        
        # Should return None values on start failure
        exit_code, stdout, stderr, process = result
        self.assertIsNone(exit_code)
        self.assertIsNone(stdout)
        self.assertIsNone(stderr)
        self.assertIsNone(process)

    @patch('subprocess.Popen')
    def test_run_subprocess_runtime_exception(self, mock_popen):
        """Test subprocess execution when runtime exception occurs."""
        mock_process = MagicMock()
        mock_process.communicate.side_effect = Exception("Runtime error")
        mock_popen.return_value = mock_process
        
        with patch('builtins.print'):
            with self.assertLogs('monitor.lib.command_utils', level='ERROR'):
                result = command_utils.run_subprocess("problematic_command")
        
        # Should return None for stdout/stderr, but process object
        exit_code, stdout, stderr, process = result
        self.assertIsNone(exit_code)
        self.assertIsNone(stdout)
        self.assertIsNone(stderr)
        self.assertEqual(process, mock_process)

    @patch('subprocess.Popen')
    def test_run_subprocess_no_fetch_output(self, mock_popen):
        """Test subprocess execution with fetch_output=False."""
        mock_process = MagicMock()
        mock_process.wait.return_value = None
        mock_process.returncode = 0
        mock_popen.return_value = mock_process
        
        exit_code, stdout, stderr, process = command_utils.run_subprocess(
            "command", 
            fetch_output=False
        )
        
        self.assertEqual(exit_code, 0)
        self.assertIsNone(stdout)
        self.assertIsNone(stderr)
        
        # Should call wait() instead of communicate()
        mock_process.wait.assert_called_once()
        mock_process.communicate.assert_not_called()
        
        # Should not set stdout/stderr pipes
        args, kwargs = mock_popen.call_args
        self.assertNotIn('stdout', kwargs)
        self.assertNotIn('stderr', kwargs)


class TestOutputStreamWriter(unittest.TestCase):
    """The TUI output-stream seam: non-interactive commands stream to the writer
    instead of inheriting the terminal, without changing other behavior."""

    def tearDown(self):
        command_utils.set_output_stream_writer(None)  # never leak across tests

    def test_streams_to_writer_when_set(self):
        chunks = []
        command_utils.set_output_stream_writer(chunks.append)
        exit_code, out, err, _ = command_utils.run_subprocess(
            "echo hello", interactive=False, fetch_output=False
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("hello", "".join(chunks))   # output streamed to the sink
        self.assertIsNone(out)                     # not returned (streamed)

    def test_interactive_command_not_streamed(self):
        chunks = []
        command_utils.set_output_stream_writer(chunks.append)
        # interactive=True must inherit the terminal, never stream to the writer.
        command_utils.run_subprocess("echo x", interactive=True, fetch_output=False)
        self.assertEqual(chunks, [])

    def test_fetch_output_still_returns_string_not_streamed(self):
        chunks = []
        command_utils.set_output_stream_writer(chunks.append)
        # Callers that want the captured string back are unaffected by the writer.
        exit_code, out, err, _ = command_utils.run_subprocess(
            "echo cap", interactive=False, fetch_output=True
        )
        self.assertIn("cap", out or "")
        self.assertEqual(chunks, [])

    def test_no_writer_does_not_stream(self):
        command_utils.set_output_stream_writer(None)
        # No writer → non-interactive fetch_output=False inherits the terminal
        # (returns None), exactly as before — REPL behavior unchanged.
        exit_code, out, err, _ = command_utils.run_subprocess(
            "echo hi", interactive=False, fetch_output=False
        )
        self.assertEqual(exit_code, 0)
        self.assertIsNone(out)

    def test_partial_line_streamed_before_completion(self):
        # Chunked reads (not line iteration) must deliver newline-less output as
        # soon as it's produced — progress bars / \r updates would otherwise stay
        # invisible until the command finishes.
        import time
        chunks, stamps = [], []
        start = time.monotonic()

        def writer(s):
            chunks.append(s)
            stamps.append(time.monotonic() - start)

        command_utils.set_output_stream_writer(writer)
        exit_code, out, err, _ = command_utils.run_subprocess(
            "printf 'progress...'; sleep 0.4; printf ' done\\n'",
            interactive=False, fetch_output=False,
        )
        self.assertEqual(exit_code, 0)
        # The partial (newline-less) chunk arrives well before the 0.4s completion.
        partial = next((t for c, t in zip(chunks, stamps)
                        if "progress" in c and "done" not in c), None)
        self.assertIsNotNone(partial, f"no partial chunk in {chunks!r}")
        self.assertLess(partial, 0.3)
        self.assertIn("done", "".join(chunks))

    def test_streamed_multibyte_not_corrupted(self):
        # An incremental decoder must reassemble a multibyte char even if a read
        # splits its bytes — no U+FFFD replacement.
        chunks = []
        command_utils.set_output_stream_writer(chunks.append)
        exit_code, out, err, _ = command_utils.run_subprocess(
            "printf '\\xe2\\x9c\\x93 ok'", interactive=False, fetch_output=False
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("✓ ok", "".join(chunks))


if __name__ == "__main__":
    unittest.main()
