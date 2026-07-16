import unittest
from unittest.mock import patch

from monitor import config
from monitor.lib.tool_definitions import TOOL_DESCRIPTIONS
from monitor.lib import tool_profiles as tp


class TestToolProfiles(unittest.TestCase):
    def test_default_profile_is_coding(self):
        self.assertEqual(tp.DEFAULT_TOOL_PROFILE, "coding")
        self.assertEqual(tp.normalize_profile_name(None), "coding")
        self.assertEqual(tp.normalize_profile_name("unknown"), "coding")

    def test_coding_profile_supports_repo_loop(self):
        self.assertTrue(tp.coding_profile_supports_repo_loop())
        allowed = tp.allowed_tool_names_for_profile("coding")
        self.assertTrue(tp.CODING_LOOP_READ_TOOLS & allowed)
        self.assertTrue(tp.CODING_LOOP_EDIT_TOOLS & allowed)
        self.assertTrue(tp.CODING_LOOP_VERIFY_TOOLS & allowed)
        self.assertIn("modify_source_code", allowed)
        self.assertIn("save_to_memory", allowed)
        self.assertIn("read_from_memory", allowed)

    def test_coding_profile_excludes_non_coding_groups(self):
        coding = tp.allowed_tool_names_for_profile("coding")
        non_coding = tp.non_coding_tool_names()
        self.assertFalse(coding & non_coding)
        self.assertIn("tavily_search", non_coding)
        self.assertIn("get_current_weather", non_coding)
        self.assertIn("agent_create", non_coding)
        self.assertIn("execute_duckdb", non_coding)
        self.assertNotIn("save_to_memory", non_coding)
        self.assertNotIn(tp.MEMORY_GROUP, tp.NON_CODING_GROUPS)
        self.assertIn(tp.MEMORY_GROUP, tp.PROFILE_GROUPS["coding"])

    def test_full_profile_includes_non_coding_tools(self):
        full = tp.allowed_tool_names_for_profile("full")
        self.assertTrue(tp.non_coding_tool_names().issubset(full))

    def test_review_profile_has_verify_without_edit(self):
        review = tp.allowed_tool_names_for_profile("review")
        self.assertTrue(tp.CODING_LOOP_VERIFY_TOOLS & review)
        self.assertFalse(tp.CODING_LOOP_EDIT_TOOLS & review)

    def test_described_tools_are_grouped(self):
        ungrouped = tp.ungrouped_described_tool_names(TOOL_DESCRIPTIONS)
        self.assertEqual(ungrouped, set())

    def test_filter_descriptors_for_coding_profile(self):
        filtered = tp.filter_descriptors_by_names(
            TOOL_DESCRIPTIONS,
            tp.allowed_tool_names_for_profile("coding"),
        )
        names = tp.described_tool_names(filtered)
        self.assertIn("run_python_tests", names)
        self.assertNotIn("tavily_search", names)
        self.assertNotIn("agent_create", names)
        # Memory tools are profile-allowed; descriptors are added at runtime when
        # MEMORY_SERVICES is enabled, so they may be absent from the static catalog.
        allowed = tp.allowed_tool_names_for_profile("coding")
        self.assertTrue(set(tp.TOOL_GROUPS[tp.MEMORY_GROUP]).issubset(allowed))

    def test_advertised_tool_descriptors_respect_profile(self):
        config.TOOL_PROFILE = "coding"
        config.CURRENT_TURN_TOOL_GROUPS = set()
        advertised = tp.advertised_tool_descriptors_for_current_turn(TOOL_DESCRIPTIONS)
        names = tp.described_tool_names(advertised)
        self.assertNotIn("agent_create", names)

    def test_full_profile_skips_filtering(self):
        config.TOOL_PROFILE = "full"
        advertised = tp.advertised_tool_descriptors_for_current_turn(TOOL_DESCRIPTIONS)
        self.assertEqual(
            len(tp.described_tool_names(advertised)),
            len(tp.described_tool_names(TOOL_DESCRIPTIONS)),
        )

    def test_explicit_auto_widen_adds_network_group(self):
        config.TOOL_PROFILE = "coding"
        config.ENABLE_TOOL_PROFILE_AUTO_WIDEN = True
        config.TOOL_PROFILE_AUTO_WIDEN_MAX_ACTIVE_GROUPS = 2
        config.TOOL_PROFILE_AUTO_WIDEN_DISABLED_GROUPS = []
        config.TOOL_PROFILE_GROUP_LEASES = {}
        config.CURRENT_TURN_TOOL_GROUPS = set()
        widened = tp.maybe_apply_explicit_auto_widen("please search the web for docs")
        self.assertIn(tp.NETWORK_GROUP, widened)
        self.assertIn(tp.NETWORK_GROUP, config.CURRENT_TURN_TOOL_GROUPS)

    def test_profile_schema_token_report_shows_coding_smaller_than_full(self):
        with patch.object(tp, "estimate_descriptor_schema_tokens", side_effect=lambda d: len(d)):
            report = tp.profile_schema_token_report(TOOL_DESCRIPTIONS)
        self.assertLess(
            report["coding"]["schema_tokens"],
            report["full"]["schema_tokens"],
        )
        self.assertLess(report["coding"]["tool_count"], report["full"]["tool_count"])

    def test_excluded_groups_for_coding_profile(self):
        excluded = set(tp.excluded_groups_for_profile("coding"))
        self.assertEqual(excluded, set(tp.NON_CODING_GROUPS))


if __name__ == "__main__":
    unittest.main()
