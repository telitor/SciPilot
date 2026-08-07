import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import check_runtime_config
from services import supabase_service


class RuntimeConfigTests(unittest.TestCase):
    def test_supabase_missing_error_explains_restart(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(supabase_service.SupabaseConfigurationError) as error:
                supabase_service._required_env("SUPABASE_URL")
        self.assertIn("SUPABASE_URL", str(error.exception))
        self.assertIn("重新启动", str(error.exception))

    def test_preflight_accepts_legacy_supabase_key_names(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "SUPABASE_URL=https://project.supabase.co\n"
                "SUPABASE_ANON_KEY=anon-placeholder\n"
                "SUPABASE_SERVICE_ROLE_KEY=service-placeholder\n",
                encoding="utf-8",
            )
            with (
                patch.object(check_runtime_config, "ENV_PATH", env_path),
                patch.object(check_runtime_config.socket, "getaddrinfo", return_value=[]),
                patch.dict(os.environ, {}, clear=True),
            ):
                self.assertEqual(check_runtime_config.main(), 0)

    def test_preflight_rejects_unresolvable_supabase_host(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "SUPABASE_URL=https://missing-project.supabase.co\n"
                "SUPABASE_ANON_KEY=anon-placeholder\n"
                "SUPABASE_SERVICE_ROLE_KEY=service-placeholder\n",
                encoding="utf-8",
            )
            with (
                patch.object(check_runtime_config, "ENV_PATH", env_path),
                patch.object(
                    check_runtime_config.socket,
                    "getaddrinfo",
                    side_effect=OSError("DNS lookup failed"),
                ),
                patch.dict(os.environ, {}, clear=True),
            ):
                self.assertEqual(check_runtime_config.main(), 1)


if __name__ == "__main__":
    unittest.main()
