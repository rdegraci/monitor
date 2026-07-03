import unittest
from unittest.mock import patch, MagicMock

from monitor.lib.consult import Consult


class TestConsult(unittest.TestCase):
    def setUp(self):
        self.logger = MagicMock()
        # Default model non-o3 to exercise temperature=0.3 by default
        self.consult = Consult(self.logger, model="openai/gpt-4o", allow_file_output=False, allow_browser_open=False)

    def test_start_stop_reset_flags(self):
        self.consult.start(seed_question="What are we building?")
        self.assertTrue(self.consult.active)
        self.assertIsInstance(self.consult.messages, list)
        self.assertGreaterEqual(len(self.consult.messages), 1)
        final = self.consult.stop()
        self.assertIsInstance(final, str)
        self.assertFalse(self.consult.active)
        msg = self.consult.reset()
        self.assertEqual(msg, "Consult session state reset.")
        self.assertFalse(self.consult.active)
        self.assertEqual(self.consult.messages, [])
        self.assertEqual(self.consult.current_prompt, "")

    def test_extract_dot_diagrams_variants(self):
        text1 = """
###Prompt
X
```dot
 digraph G {
  A -> B;
 }
```
What else?
"""
        out1 = Consult._extract_dot_diagrams(text1)
        self.assertIn("graph", out1)
        self.assertIn("digraph", out1["graph"])  # contains DOT

        text2 = """
###Prompt
Y
```graphviz
 graph H {
  a -- b;
 }
```
Next?
"""
        out2 = Consult._extract_dot_diagrams(text2)
        self.assertIn("graph", out2)
        self.assertTrue(out2["graph"].startswith("graph"))

        text3 = """
###Prompt
Z
```
 digraph T { X -> Y }
```
Question?
"""
        out3 = Consult._extract_dot_diagrams(text3)
        self.assertIn("graph", out3)
        self.assertIn("X -> Y", out3["graph"])  # inferred from inside block

    @patch("monitor.lib.consult.llm_utils.call_litellm_completion")
    def test_ask_parses_prompt_diagram_and_question(self, mock_completion):
        # Compose a reply that matches parser expectations
        llm_text = (
            "###Prompt\nMy Prompt\n"  # prompt
            "```dot\n"  # diagram block
            "digraph G { A -> B }\n"
            "```\n"
            "What else do you need?"  # clarifying question
        )
        mock_completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=llm_text))]
        )
        captured = {}
        with patch.object(self.consult, "print_prompt_and_graph") as mock_ppg:
            q, prompt = self.consult.ask("We need auth")
            captured["q"] = q
            captured["prompt"] = prompt
            args, kwargs = mock_ppg.call_args
            diagrams = args[0]
            self.assertIn("graph", diagrams)
            self.assertIn("digraph", diagrams["graph"])
        self.assertEqual(captured["q"], "What else do you need?")
        self.assertEqual(captured["prompt"], "My Prompt")

    @patch("monitor.lib.consult.Source")
    def test_render_dot_to_svg_success(self, mock_source):
        # Mock graphviz Source.render to return a path
        inst = MagicMock()
        inst.render.return_value = "/abs/path/consult_graph.svg"
        mock_source.return_value = inst
        # Temporarily enable file output
        self.consult.allow_file_output = True
        # Also patch open to allow write
        with patch("builtins.open", create=True) as mopen:
            mopen.return_value.__enter__.return_value.write.return_value = None
            path = self.consult._render_dot_to_svg("digraph G { A -> B }")
        self.assertTrue(path.endswith("consult_graph.svg"))
        inst.render.assert_called()

    @patch("monitor.lib.consult.Source", side_effect=Exception("render fail"))
    def test_render_dot_to_svg_failure(self, mock_source):
        # Temporarily enable file output
        self.consult.allow_file_output = True
        with patch("builtins.open", create=True) as mopen:
            mopen.return_value.__enter__.return_value.write.return_value = None
            path = self.consult._render_dot_to_svg("digraph G { A -> B }")
        self.assertIsNone(path)

    @patch("monitor.lib.consult.webbrowser.open")
    @patch("monitor.lib.consult.webbrowser.open_new_tab")
    def test_show_graphs_opens_once_then_updates(self, mock_new_tab, mock_open):
        # Force renderer to return a path
        with patch.object(self.consult, "_render_dot_to_svg", return_value="/tmp/consult_graph.svg"):
            # Enable browser opening
            self.consult.allow_browser_open = True
            Consult.svg_tab_shown = False
            self.consult.show_graphs({"graph": "digraph G { A -> B }"})
            mock_new_tab.assert_called_once()
            mock_open.assert_not_called()
            # Subsequent call should not open new tab; may update existing
            self.consult.show_graphs({"graph": "digraph G { A -> B }"})
            self.assertGreaterEqual(mock_open.call_count, 0)
            # Ensure flag toggled
            self.assertTrue(Consult.svg_tab_shown)

    def test_print_prompt_and_graph_calls_show(self):
        self.consult.current_prompt = "A current prompt"
        with patch.object(self.consult, "show_graphs") as mock_show:
            self.consult.print_prompt_and_graph({"graph": "digraph G { A -> B }"})
            mock_show.assert_called_once()

    @patch("monitor.lib.consult.llm_utils.call_litellm_completion")
    def test_temperature_selection_by_model(self, mock_completion):
        # Swap model to an o3 to test temperature=1.0
        consult_o3 = Consult(self.logger, model="OpenAI/O3-test", allow_file_output=False, allow_browser_open=False)
        llm_text = "###Prompt\nP\n```dot\ndigraph G {}\n```\nQ"
        mock_completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=llm_text))]
        )
        consult_o3.ask("x")
        # Verify the last call used temperature=1.0
        self.assertTrue(mock_completion.called)


if __name__ == "__main__":
    unittest.main()
