import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from services.sandbox_execution_service import (
    SandboxCommandError,
    _output_evidence,
    docker_execution_enabled,
    parse_approved_command,
    validate_public_github_url,
)


class SandboxExecutionPolicyTests(unittest.TestCase):
    def test_python_script_and_pytest_commands_are_allowed(self):
        self.assertEqual(
            parse_approved_command("python train.py --epochs 1"),
            ["python", "train.py", "--epochs", "1"],
        )
        self.assertEqual(
            parse_approved_command("python -m pytest tests/test_model.py"),
            ["python", "-m", "pytest", "tests/test_model.py"],
        )

    def test_shell_control_characters_are_rejected(self):
        for command in (
            "python train.py && whoami",
            "python train.py | more",
            "python train.py > output.txt",
            "python $(whoami).py",
        ):
            with self.subTest(command=command):
                with self.assertRaises(SandboxCommandError):
                    parse_approved_command(command)

    def test_inline_python_and_unapproved_programs_are_rejected(self):
        for command in (
            "python -c print(1)",
            "bash run.sh",
            "powershell Get-Process",
            "pip install requests",
        ):
            with self.subTest(command=command):
                with self.assertRaises(SandboxCommandError):
                    parse_approved_command(command)

    def test_secret_like_command_arguments_are_rejected(self):
        with self.assertRaises(SandboxCommandError):
            parse_approved_command("python train.py --api-key example")

    def test_only_plain_public_github_https_urls_are_allowed(self):
        self.assertEqual(
            validate_public_github_url("https://github.com/openai/openai-python"),
            "https://github.com/openai/openai-python.git",
        )
        for url in (
            "http://github.com/openai/openai-python",
            "https://token@github.com/openai/openai-python",
            "https://example.com/openai/openai-python",
            "https://github.com/openai/openai-python?token=secret",
        ):
            with self.subTest(url=url):
                with self.assertRaises(SandboxCommandError):
                    validate_public_github_url(url)

    def test_execution_is_opt_in(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(docker_execution_enabled())
        with patch.dict(
            "os.environ", {"SCIPILOT_DOCKER_EXECUTION_ENABLED": "true"}, clear=True
        ):
            self.assertTrue(docker_execution_enabled())

    def test_only_small_tabular_outputs_are_captured_for_analysis(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "metrics.csv").write_text("epoch,loss\n1,0.5\n", encoding="utf-8")
            (root / "notes.txt").write_text("not tabular", encoding="utf-8")

            evidence, captured = _output_evidence(root, {})

        by_name = {item["name"]: item for item in evidence}
        self.assertTrue(by_name["metrics.csv"]["analyzable"])
        self.assertFalse(by_name["notes.txt"]["analyzable"])
        self.assertEqual([item.name for item in captured], ["metrics.csv"])
        self.assertEqual(captured[0].media_type, "text/csv")


if __name__ == "__main__":
    unittest.main()
