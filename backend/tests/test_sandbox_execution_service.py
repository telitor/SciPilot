import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from services.sandbox_execution_service import (
    SandboxCommandError,
    _container_limits,
    _gpu_slot,
    _output_evidence,
    _run_checked_with_disk_quota,
    _safe_subprocess_environment,
    _workspace_size,
    docker_execution_enabled,
    parse_approved_command,
    resolve_execution_policy,
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
        self.assertEqual(parse_approved_command("Rscript analysis.R"), ["Rscript", "analysis.R"])
        self.assertEqual(parse_approved_command("julia train.jl"), ["julia", "train.jl"])
        self.assertEqual(parse_approved_command("node report.mjs"), ["node", "report.mjs"])

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

    def test_script_entrypoint_cannot_escape_the_repository(self):
        for command in (
            "python ../train.py",
            "python /tmp/train.py",
            "python .scipilot-deps/hook.py",
            "Rscript C:\\temp\\analysis.R",
            "node ../report.mjs",
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

    def test_output_evidence_never_follows_a_symlink_outside_workspace(self):
        with TemporaryDirectory() as temp_dir, TemporaryDirectory() as outside_dir:
            root = Path(temp_dir)
            outside = Path(outside_dir) / "host-secret"
            outside.write_bytes(b"must-not-be-captured")
            link = root / "loot.json"
            try:
                link.symlink_to(outside)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symbolic links are unavailable: {exc}")

            evidence, captured = _output_evidence(root, {})

        self.assertNotIn("loot.json", {item["name"] for item in evidence})
        self.assertEqual(captured, [])

    def test_workspace_quota_counts_git_and_dependency_bytes(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").mkdir()
            (root / ".scipilot-deps").mkdir()
            (root / ".git" / "pack").write_bytes(b"g" * 17)
            (root / ".scipilot-deps" / "wheel").write_bytes(b"d" * 23)

            self.assertEqual(_workspace_size(root), 40)

    def test_repository_preparation_is_stopped_when_quota_is_exceeded(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaises(SandboxCommandError):
                _run_checked_with_disk_quota(
                    [
                        sys.executable,
                        "-c",
                        "from pathlib import Path; Path('large.bin').write_bytes(b'x' * 4096)",
                    ],
                    timeout=10,
                    cwd=root,
                    disk_root=root,
                    max_disk_bytes=1024,
                )

    def test_git_preparation_environment_disables_prompts_and_lfs_smudge(self):
        with patch.dict(os.environ, {"PATH": os.environ.get("PATH", "")}, clear=True):
            environment = _safe_subprocess_environment()

        self.assertEqual(environment["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(environment["GIT_LFS_SKIP_SMUDGE"], "1")
        self.assertEqual(environment["GCM_INTERACTIVE"], "Never")

    def test_image_dataset_and_gpu_requests_are_operator_allow_listed(self):
        with TemporaryDirectory() as temp_dir:
            environment = {
                "image": "rocker/r-ver:4.4.1",
                "datasets": ["iris-v1"],
                "gpu": "0",
            }
            operator_environment = {
                "SCIPILOT_DOCKER_IMAGE": "python:3.11-slim",
                "SCIPILOT_DOCKER_ALLOWED_IMAGES": "python:3.11-slim,rocker/r-ver:4.4.1",
                "SCIPILOT_DATASET_MOUNTS_JSON": '{"iris-v1": "' + temp_dir.replace("\\", "\\\\") + '"}',
                "SCIPILOT_DOCKER_GPU_ENABLED": "true",
            }
            with patch.dict("os.environ", operator_environment, clear=True):
                policy = resolve_execution_policy(environment)

        self.assertEqual(policy.image, "rocker/r-ver:4.4.1")
        self.assertEqual(policy.dataset_mounts[0][0], "iris-v1")
        self.assertEqual(policy.gpu_devices, "0")

    def test_unapproved_image_dataset_and_gpu_are_rejected(self):
        with patch.dict(
            "os.environ",
            {
                "SCIPILOT_DOCKER_IMAGE": "python:3.11-slim",
                "SCIPILOT_DOCKER_ALLOWED_IMAGES": "python:3.11-slim",
            },
            clear=True,
        ):
            for environment in (
                {"image": "python:latest"},
                {"datasets": ["private-data"]},
                {"gpu": True},
            ):
                with self.subTest(environment=environment):
                    with self.assertRaises(SandboxCommandError):
                        resolve_execution_policy(environment)

    def test_dataset_mount_is_read_only_and_gpu_flag_is_explicit(self):
        with TemporaryDirectory() as temp_dir:
            args = _container_limits(
                Path(temp_dir),
                "run-1",
                dataset_mounts=(("iris-v1", Path(temp_dir)),),
                gpu_devices="0",
            )

        self.assertIn(f"type=bind,source={Path(temp_dir)},target=/datasets/iris-v1,readonly", args)
        self.assertEqual(args[args.index("--gpus") + 1], "device=0")

    def test_gpu_slot_is_released_after_the_run(self):
        with TemporaryDirectory() as temp_dir:
            with patch.dict(
                "os.environ",
                {"SCIPILOT_GPU_SLOT_DIR": temp_dir},
                clear=True,
            ):
                with _gpu_slot("0") as slot:
                    self.assertEqual(slot, "slot-0")
                    self.assertTrue((Path(temp_dir) / "slot-0.lock").is_file())
                self.assertFalse((Path(temp_dir) / "slot-0.lock").exists())


if __name__ == "__main__":
    unittest.main()
