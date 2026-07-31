import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import finetuned_model_service as service


class FineTunedModelServiceTests(unittest.TestCase):
    def test_requires_all_backend_only_settings(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(service.is_finetuned_model_configured())

    def test_uses_lora_header_and_server_model_id(self):
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="带引用的回答 [1]"))]
        )
        settings = {
            "SCIPILOT_LLM_API_KEY": "test-key",
            "SCIPILOT_LLM_MODEL_ID": "test-model",
            "SCIPILOT_LLM_RESOURCE_ID": "test-resource",
            "SCIPILOT_LLM_BASE_URL": "https://example.test/v2",
        }

        with (
            patch.dict(os.environ, settings, clear=True),
            patch.object(service, "OpenAI", return_value=client) as openai,
        ):
            reply = service.call_finetuned_model(
                system_prompt="只依据证据回答",
                user_message="证据内容 [1]",
            )

        self.assertEqual(reply, "带引用的回答 [1]")
        openai.assert_called_once_with(
            api_key="test-key",
            base_url="https://example.test/v2/",
            timeout=120.0,
        )
        request = client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["model"], "test-model")
        self.assertEqual(request["extra_headers"], {"lora_id": "test-resource"})


if __name__ == "__main__":
    unittest.main()
