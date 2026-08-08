"""Secret-safe configuration validation for onboarding (PLAN Phase 8).

Reports whether Monitor is ready for a coding session: config files, model,
tool profile, daily budget, and API-key *presence* — never key values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple

from monitor import config

# Provider env vars commonly required for day-to-day coding. Presence only.
_PROVIDER_KEY_ENV = (
    ("OpenAI", "OPENAI_API_KEY"),
    ("Anthropic", "ANTHROPIC_API_KEY"),
    ("xAI / Grok", "XAI_API_KEY"),
    ("Google", "GOOGLE_API_KEY"),
    ("OpenRouter", "OPENROUTER_API_KEY"),
)

SEEDED_CONFIG_FILES: Tuple[Tuple[str, str], ...] = (
    ("config.yaml.example", "config.yaml"),
    ("macros.json", "macros.json"),
    ("preferences.prompt", "preferences.prompt"),
    ("model_config.json", "model_config.json"),
    ("non_interactive_commands.json", "non_interactive_commands.json"),
    ("interactive_commands.json", "interactive_commands.json"),
    ("function_keys.json", "function_keys.json"),
    ("directives/echo.prompt", "directives/echo.prompt"),
    ("directives/greet.prompt", "directives/greet.prompt"),
)


@dataclass
class CheckItem:
    """One validation row for human-readable reports."""

    label: str
    ok: bool
    detail: str
    level: str = "info"  # info | warn | error


@dataclass
class CheckReport:
    """Aggregate result of ``check_configuration``."""

    items: List[CheckItem] = field(default_factory=list)
    config_dir: str = ""

    @property
    def ok(self) -> bool:
        return not any(item.level == "error" for item in self.items)

    @property
    def warnings(self) -> int:
        return sum(1 for item in self.items if item.level == "warn")


def _mask_present(value: Optional[str]) -> str:
    if value and str(value).strip():
        return "set"
    return "missing"


def _provider_keys_present() -> List[Tuple[str, str, bool]]:
    rows = []
    for label, env_name in _PROVIDER_KEY_ENV:
        present = bool(os.environ.get(env_name, "").strip())
        rows.append((label, env_name, present))
    return rows


def check_configuration(*, config_dir: Optional[str] = None) -> CheckReport:
    """Validate runtime readiness without exposing secret values.

    Args:
        config_dir: Optional override for the user config directory (tests).

    Returns:
        CheckReport with status rows for files, model, profile, budget, and keys.
    """
    from monitor._stubs import appdirs

    report = CheckReport()
    report.config_dir = config_dir or appdirs.user_config_dir("monitor")

    # Seeded files — presence only.
    missing_files = []
    for _src, dest_name in SEEDED_CONFIG_FILES:
        path = os.path.join(report.config_dir, dest_name)
        if os.path.isfile(path):
            report.items.append(
                CheckItem(f"config file {dest_name}", True, path, "info")
            )
        else:
            missing_files.append(dest_name)
            report.items.append(
                CheckItem(
                    f"config file {dest_name}",
                    False,
                    "missing (will be seeded on next `python -m monitor` start)",
                    "warn",
                )
            )

    model = getattr(config, "MODEL", None)
    if isinstance(model, str) and model.strip():
        report.items.append(CheckItem("MODEL", True, model.strip(), "info"))
    else:
        report.items.append(
            CheckItem("MODEL", False, "not set — configure model_config.json or --model", "error")
        )

    profile = getattr(config, "TOOL_PROFILE", None) or "coding"
    report.items.append(
        CheckItem("TOOL_PROFILE", True, str(profile), "info")
    )

    status_mode = getattr(config, "STATUS_LINE_MODE", None) or "coding"
    report.items.append(
        CheckItem("STATUS_LINE_MODE", True, str(status_mode), "info")
    )

    budget = getattr(config, "DAILY_COST_TARGET_USD", None)
    if isinstance(budget, (int, float)) and budget > 0:
        report.items.append(
            CheckItem("DAILY_COST_TARGET_USD", True, f"${float(budget):.2f}/day", "info")
        )
    else:
        report.items.append(
            CheckItem(
                "DAILY_COST_TARGET_USD",
                False,
                "unset or non-positive — fuel gauge may be hidden",
                "warn",
            )
        )

    key_rows = _provider_keys_present()
    any_key = any(present for _label, _env, present in key_rows)
    for label, env_name, present in key_rows:
        report.items.append(
            CheckItem(
                f"{label} ({env_name})",
                present,
                _mask_present(os.environ.get(env_name) if present else None),
                "info" if present else "warn",
            )
        )
    if not any_key:
        report.items.append(
            CheckItem(
                "provider API keys",
                False,
                "no known provider key found in the environment — set one in ~/.config/monitor/.env",
                "error",
            )
        )

    entry = "monitor / python -m monitor"
    report.items.append(
        CheckItem(
            "production entry point",
            True,
            f"{entry} (monitor_oop / monitor-oop is experimental)",
            "info",
        )
    )

    if missing_files and not any_key:
        # Keep ok=False already from missing keys; nothing else to do.
        pass

    return report


def format_check_report(report: CheckReport) -> str:
    """Render a CheckReport as plain text for the terminal."""
    lines = [
        "Monitor configuration check",
        f"Config directory: {report.config_dir}",
        "",
    ]
    for item in report.items:
        mark = "OK" if item.ok else item.level.upper()
        lines.append(f"  [{mark}] {item.label}: {item.detail}")
    lines.append("")
    if report.ok:
        lines.append("Ready for a coding session. Run: python -m monitor")
        lines.append("Then try: :help   or ask the model to inspect a file in this repo.")
    else:
        lines.append("Not ready yet. Fix items marked ERROR, then re-run: python -m monitor --check-config")
    if report.warnings:
        lines.append(f"({report.warnings} warning(s) — session may still work for some providers.)")
    return "\n".join(lines)


def print_check_report(report: Optional[CheckReport] = None) -> int:
    """Print a configuration check and return a process exit code (0 = ok)."""
    report = report or check_configuration()
    print(format_check_report(report))
    return 0 if report.ok else 1
