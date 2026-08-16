from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path

from hcr2.cli.app import CliApp, _should_use_legacy_dispatch


REPO_ROOT = Path(__file__).resolve().parent.parent
HCR2 = REPO_ROOT / "hcr2.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HCR2), *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def run_module(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "hcr2", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class CliHelpSmokeTests(unittest.TestCase):
    def assert_successful_help(self, result: subprocess.CompletedProcess[str], usage: str) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("Usage:\n", result.stdout)
        self.assertIn(f"  {usage}", result.stdout)
        self.assertIn("Commands:\n", result.stdout)
        self.assertIn("Options:\n", result.stdout)
        self.assertIn("-h, --help", result.stdout)

    def test_root_help_without_arguments(self) -> None:
        result = run_cli()
        self.assert_successful_help(result, "hcr2.py <entity> <command> [options]")
        for entity in (
            "vehicle",
            "player",
            "teamevent",
            "season",
            "match",
            "matchscore",
            "stats",
            "sheet",
            "video",
            "donations",
            "version",
        ):
            self.assertIn(entity, result.stdout)

    def test_root_help_flags(self) -> None:
        for flag in ("--help", "-h"):
            with self.subTest(flag=flag):
                result = run_cli(flag)
                self.assert_successful_help(result, "hcr2.py <entity> <command> [options]")

    def test_package_entrypoint_matches_script_help(self) -> None:
        script_result = run_cli("--help")
        module_result = run_module("--help")
        self.assertEqual(module_result.returncode, 0, module_result.stderr)
        self.assertEqual(module_result.stdout, script_result.stdout)
        self.assertEqual(module_result.stderr, script_result.stderr)

    def test_help_command_aliases(self) -> None:
        root_result = run_cli("help")
        entity_result = run_cli("help", "player")
        self.assert_successful_help(root_result, "hcr2.py <entity> <command> [options]")
        self.assert_successful_help(entity_result, "hcr2.py player <command> [options]")

    def test_typer_completion_is_not_legacy_dispatched(self) -> None:
        self.assertFalse(_should_use_legacy_dispatch(["--show-completion", "bash"]))
        self.assertFalse(_should_use_legacy_dispatch(["--install-completion", "bash"]))

    def test_entity_help_flags(self) -> None:
        entities = {
            "vehicle": "list",
            "player": "list-active",
            "teamevent": "show --id <id>",
            "season": "list --all",
            "match": "add <opponent>",
            "matchscore": "list-short",
            "stats": "perf",
            "sheet": "player export",
            "video": "roster --match <match_id>",
            "donations": "under",
        }
        for entity, expected_command in entities.items():
            with self.subTest(entity=entity):
                result = run_cli(entity, "--help")
                self.assert_successful_help(result, f"hcr2.py {entity} <command> [options]")
                self.assertIn(expected_command, result.stdout)

    def test_command_help_does_not_execute_command(self) -> None:
        commands = (
            ("vehicle", "list"),
            ("player", "list"),
            ("teamevent", "list"),
            ("season", "list"),
            ("match", "list"),
            ("matchscore", "list"),
            ("stats", "perf"),
            ("sheet", "player"),
            ("video", "roster"),
            ("donations", "list"),
        )
        for entity, command in commands:
            with self.subTest(entity=entity, command=command):
                result = run_cli(entity, command, "--help")
                self.assert_successful_help(result, f"hcr2.py {entity} <command> [options]")

    def test_version_command(self) -> None:
        result = run_cli("version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout.strip(), r"^\d+\.\d+\.\d+$")

    def test_dispatcher_accepts_explicit_argv(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            CliApp().dispatch(["--help"])
        self.assertIn("hcr2.py <entity> <command> [options]", buffer.getvalue())
