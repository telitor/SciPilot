import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[2]
MANAGE_PATH = ROOT / "deploy" / "manage.py"
SPEC = importlib.util.spec_from_file_location("scipilot_deploy_manage", MANAGE_PATH)
assert SPEC is not None and SPEC.loader is not None
deploy_manage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy_manage)


def valid_production_environment() -> dict[str, str]:
    return {
        "SCIPILOT_IMAGE_TAG": "c4d3d60abcde",
        "SCIPILOT_BIND_ADDRESS": "127.0.0.1",
        "SCIPILOT_PUBLIC_PORT": "8080",
        "SCIPILOT_INSTALL_OCR": "true",
        "SCIPILOT_PDF_OCR_ENABLED": "false",
        "SCIPILOT_ENV": "production",
        "LOCAL_DEMO_MODE": "false",
        "AUTH_AUTO_CONFIRM_EMAIL": "false",
        "SCIPILOT_DOCKER_EXECUTION_ENABLED": "false",
        "CORS_ORIGINS": "https://app.scipilot.cn",
        "PASSWORD_RESET_REDIRECT_URL": (
            "https://app.scipilot.cn/reset-password"
        ),
        "MAX_UPLOAD_MB": "25",
        "SUPABASE_URL": "https://project.supabase.co",
        "SUPABASE_PUBLISHABLE_KEY": "test-publishable-key",
        "SUPABASE_SECRET_KEY": "test-service-role-key",
    }


class DeploymentArtifactTests(unittest.TestCase):
    def test_required_deployment_artifacts_exist(self):
        expected = (
            ROOT / ".dockerignore",
            ROOT / "backend" / "Dockerfile",
            ROOT / "frontend" / "Dockerfile",
            ROOT / "frontend" / "nginx.conf",
            ROOT / "deploy" / "compose.yaml",
            ROOT / "deploy" / ".env.example",
            ROOT / "deploy" / "README.md",
            MANAGE_PATH,
        )
        self.assertEqual([str(path) for path in expected if not path.is_file()], [])

    def test_backend_image_is_locked_non_root_and_ocr_capable(self):
        dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("requirements.lock", dockerfile)
        self.assertIn("python -m pip check", dockerfile)
        self.assertIn("poppler-utils", dockerfile)
        self.assertIn("tesseract-ocr-eng", dockerfile)
        self.assertIn("ARG SCIPILOT_INSTALL_OCR=true", dockerfile)
        self.assertIn("USER 10001:10001", dockerfile)
        self.assertIn("/api/v1/health", dockerfile)

    def test_frontend_image_builds_spa_and_runs_nginx_non_root(self):
        dockerfile = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("npm ci", dockerfile)
        self.assertIn("npm run build", dockerfile)
        self.assertIn("VITE_API_BASE_URL=/api/v1", dockerfile)
        self.assertIn("USER 101:101", dockerfile)
        nginx = (ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")
        self.assertIn("proxy_pass http://backend:8000", nginx)
        self.assertIn("try_files $uri $uri/ /index.html", nginx)
        self.assertIn("location = /healthz", nginx)
        self.assertIn("access_log /dev/stdout", nginx)

    def test_compose_keeps_backend_private_and_applies_runtime_guards(self):
        compose = yaml.safe_load(
            (ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")
        )
        backend = compose["services"]["backend"]
        frontend = compose["services"]["frontend"]
        self.assertNotIn("ports", backend)
        self.assertEqual(backend["expose"], ["8000"])
        self.assertIn("ports", frontend)
        self.assertEqual(
            frontend["depends_on"]["backend"]["condition"], "service_healthy"
        )
        for service in (backend, frontend):
            self.assertTrue(service["read_only"])
            self.assertIn("no-new-privileges:true", service["security_opt"])
            self.assertEqual(service["cap_drop"], ["ALL"])
            self.assertIn("healthcheck", service)
            self.assertEqual(service["logging"]["options"]["max-size"], "10m")
            self.assertEqual(service["logging"]["options"]["max-file"], "5")

    def test_docker_context_excludes_secrets_and_large_research_inputs(self):
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        self.assertIn("**/.env", dockerignore)
        self.assertIn("KnowledgeBase", dockerignore)
        self.assertIn("*.pdf", dockerignore)
        self.assertIn("deploy/.state", dockerignore)


class DeploymentPreflightTests(unittest.TestCase):
    def test_docker_component_versions_are_parsed_and_bounded(self):
        self.assertEqual(deploy_manage._version_tuple("v2.20.3"), (2, 20, 3))
        self.assertEqual(deploy_manage._version_tuple("Docker 24.0"), (24, 0, 0))
        with self.assertRaises(deploy_manage.DeploymentError):
            deploy_manage._version_tuple("unknown")

    def test_valid_production_configuration_passes(self):
        issues, _warnings = deploy_manage.validate_environment(
            valid_production_environment()
        )
        self.assertEqual(issues, [])

    def test_preflight_rejects_insecure_or_ambiguous_settings(self):
        values = valid_production_environment()
        values.update(
            {
                "SCIPILOT_IMAGE_TAG": "latest",
                "LOCAL_DEMO_MODE": "true",
                "AUTH_AUTO_CONFIRM_EMAIL": "true",
                "SCIPILOT_DOCKER_EXECUTION_ENABLED": "true",
                "CORS_ORIGINS": "*",
                "PASSWORD_RESET_REDIRECT_URL": "http://localhost/reset-password",
                "MAX_UPLOAD_MB": "200",
            }
        )
        issues, _warnings = deploy_manage.validate_environment(values)
        joined = "\n".join(issues)
        self.assertIn("immutable", joined)
        self.assertIn("LOCAL_DEMO_MODE", joined)
        self.assertIn("AUTH_AUTO_CONFIRM_EMAIL", joined)
        self.assertIn("SCIPILOT_DOCKER_EXECUTION_ENABLED", joined)
        self.assertIn("CORS_ORIGINS", joined)
        self.assertIn("PASSWORD_RESET_REDIRECT_URL", joined)
        self.assertIn("MAX_UPLOAD_MB", joined)

    def test_preflight_rejects_placeholder_credentials(self):
        values = valid_production_environment()
        values["SUPABASE_URL"] = "https://your-project-ref.supabase.co"
        values["SUPABASE_SECRET_KEY"] = "your_secret_key"
        issues, _warnings = deploy_manage.validate_environment(values)
        joined = "\n".join(issues)
        self.assertIn("SUPABASE_URL", joined)
        self.assertIn("secret/service-role key", joined)

    def test_preflight_rejects_ocr_without_runtime_packages(self):
        values = valid_production_environment()
        values["SCIPILOT_INSTALL_OCR"] = "false"
        values["SCIPILOT_PDF_OCR_ENABLED"] = "true"
        issues, _warnings = deploy_manage.validate_environment(values)
        self.assertIn(
            "SCIPILOT_PDF_OCR_ENABLED requires SCIPILOT_INSTALL_OCR=true", issues
        )

    def test_preflight_requires_tls_for_core_and_paid_provider_endpoints(self):
        values = valid_production_environment()
        values.update(
            {
                "SUPABASE_URL": "http://project.supabase.internal",
                "SCIPILOT_LLM_BASE_URL": "http://maas.example.test/v2",
                "XFYUN_KB_BASE_URL": "http://chatdoc.example.test",
                "PROBLEM_DECOMPOSITION_WS_URL": "ws://agent.example.test/chat",
                "XF_AGENT_WS_PATH": "ws://paper-agent.example.test/chat",
            }
        )
        issues, _warnings = deploy_manage.validate_environment(values)
        joined = "\n".join(issues)
        self.assertIn("SUPABASE_URL", joined)
        self.assertIn("SCIPILOT_LLM_BASE_URL", joined)
        self.assertIn("XFYUN_KB_BASE_URL", joined)
        self.assertIn("PROBLEM_DECOMPOSITION_WS_URL", joined)
        self.assertIn("XF_AGENT_WS_PATH", joined)

    def test_release_tag_cannot_reuse_recorded_or_built_images(self):
        with (
            patch.object(deploy_manage, "_run") as run,
            self.assertRaisesRegex(deploy_manage.DeploymentError, "already recorded"),
        ):
            deploy_manage._assert_release_tag_unused(
                "release-a",
                environment={},
                state={"current": "release-a", "previous": "release-b"},
            )
        run.assert_not_called()

        with (
            patch.object(
                deploy_manage,
                "_run",
                return_value=SimpleNamespace(stdout="sha256:already-built\n"),
            ),
            self.assertRaisesRegex(deploy_manage.DeploymentError, "will not be rebuilt"),
        ):
            deploy_manage._assert_release_tag_unused(
                "release-c",
                environment={},
                state={"current": None, "previous": None},
            )

    def test_failed_release_restores_last_known_good_before_returning_error(self):
        args = SimpleNamespace(
            env_file=Path("deploy/.env"),
            tag="release-new",
            pull=False,
            timeout=30,
        )
        values = valid_production_environment()
        with (
            patch.object(deploy_manage, "_preflight", return_value=(values, {})),
            patch.object(
                deploy_manage,
                "_load_state",
                return_value={"current": "release-good", "previous": "release-old"},
            ),
            patch.object(deploy_manage, "_assert_release_tag_unused"),
            patch.object(
                deploy_manage,
                "_run",
                side_effect=[
                    subprocess.CompletedProcess([], 0),
                    deploy_manage.DeploymentError("new release did not become healthy"),
                ],
            ),
            patch.object(deploy_manage, "_activate_existing_release") as activate,
            patch.object(deploy_manage, "_save_state") as save_state,
            self.assertRaisesRegex(
                deploy_manage.DeploymentError, "automatically restored"
            ),
        ):
            deploy_manage.release(args)

        self.assertEqual(activate.call_args.kwargs["tag"], "release-good")
        save_state.assert_not_called()

    def test_state_write_failure_also_restores_last_known_good(self):
        args = SimpleNamespace(
            env_file=Path("deploy/.env"),
            tag="release-new",
            pull=False,
            timeout=30,
        )
        values = valid_production_environment()
        with (
            patch.object(deploy_manage, "_preflight", return_value=(values, {})),
            patch.object(
                deploy_manage,
                "_load_state",
                return_value={"current": "release-good", "previous": "release-old"},
            ),
            patch.object(deploy_manage, "_assert_release_tag_unused"),
            patch.object(
                deploy_manage,
                "_run",
                return_value=subprocess.CompletedProcess([], 0),
            ),
            patch.object(deploy_manage, "verify"),
            patch.object(
                deploy_manage,
                "_save_state",
                side_effect=deploy_manage.DeploymentError("state is read-only"),
            ),
            patch.object(deploy_manage, "_activate_existing_release") as activate,
            self.assertRaisesRegex(
                deploy_manage.DeploymentError, "automatically restored"
            ),
        ):
            deploy_manage.release(args)

        self.assertEqual(activate.call_args.kwargs["tag"], "release-good")

    def test_release_verification_requires_liveness_and_core_readiness(self):
        with (
            patch.object(deploy_manage.time, "monotonic", return_value=10.0),
            patch.object(deploy_manage, "_verify_endpoint") as probe,
        ):
            deploy_manage.verify(
                {"SCIPILOT_BIND_ADDRESS": "127.0.0.1", "SCIPILOT_PUBLIC_PORT": "8080"},
                timeout=30,
            )

        self.assertEqual(
            [call.args[0] for call in probe.call_args_list],
            [
                "http://127.0.0.1:8080/healthz",
                "http://127.0.0.1:8080/api/v1/health",
                "http://127.0.0.1:8080/api/v1/readiness",
            ],
        )

    def test_env_parser_rejects_duplicate_names_without_echoing_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("TOKEN=first\nTOKEN=second\n", encoding="utf-8")
            with self.assertRaises(deploy_manage.DeploymentError) as error:
                deploy_manage.load_env_file(path)
        self.assertIn("Duplicate environment variable TOKEN", str(error.exception))
        self.assertNotIn("first", str(error.exception))
        self.assertNotIn("second", str(error.exception))


if __name__ == "__main__":
    unittest.main()
