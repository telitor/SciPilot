import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import finetuned_model_service as service
from services.external_service_reliability import (
    ExternalServiceError,
    reset_external_service_runtime_state,
)


class FineTunedModelServiceTests(unittest.TestCase):
    def setUp(self):
        reset_external_service_runtime_state()

    def test_requires_api_key_and_model_id(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(service.is_finetuned_model_configured())

        with patch.dict(
            os.environ,
            {
                "SCIPILOT_LLM_API_KEY": "test-key",
                "SCIPILOT_LLM_MODEL_ID": "test-model",
            },
            clear=True,
        ):
            self.assertTrue(service.is_finetuned_model_configured())
            self.assertFalse(service.is_lora_resource_configured())

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
        openai.assert_called_once()
        client_options = openai.call_args.kwargs
        self.assertEqual(client_options["api_key"], "test-key")
        self.assertEqual(client_options["base_url"], "https://example.test/v2/")
        self.assertEqual(client_options["timeout"].connect, 10.0)
        self.assertEqual(client_options["timeout"].read, 120.0)
        self.assertEqual(client_options["max_retries"], 0)
        request = client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["model"], "test-model")
        self.assertEqual(request["extra_headers"], {"lora_id": "test-resource"})

    def test_omits_lora_header_when_service_card_does_not_expose_resource(self):
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="第二轮回答"))]
        )
        settings = {
            "SCIPILOT_LLM_API_KEY": "test-key",
            "SCIPILOT_LLM_MODEL_ID": "test-model",
            "SCIPILOT_LLM_BASE_URL": "https://example.test/v2",
        }

        with (
            patch.dict(os.environ, settings, clear=True),
            patch.object(service, "OpenAI", return_value=client),
        ):
            reply = service.call_finetuned_model(
                messages=[
                    {"role": "system", "content": "你是科研助手"},
                    {"role": "user", "content": "记住代号 A"},
                    {"role": "assistant", "content": "已记住"},
                    {"role": "user", "content": "代号是什么？"},
                ]
            )

        self.assertEqual(reply, "第二轮回答")
        request = client.chat.completions.create.call_args.kwargs
        self.assertNotIn("extra_headers", request)
        self.assertEqual(len(request["messages"]), 4)
        self.assertEqual(request["messages"][-1]["content"], "代号是什么？")

    def test_history_must_end_with_user(self):
        with self.assertRaisesRegex(ValueError, "end with"):
            service._bounded_messages(
                [{"role": "assistant", "content": "没有最新问题"}]
            )

    def test_generation_timeout_is_not_replayed_without_idempotency_key(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            TimeoutError("must-not-leak"),
            RuntimeError("must-not-run"),
        ]
        settings = {
            "SCIPILOT_LLM_API_KEY": "test-key",
            "SCIPILOT_LLM_MODEL_ID": "test-model",
            "SCIPILOT_LLM_BASE_URL": "https://example.test/v2",
            "SCIPILOT_LLM_MAX_ATTEMPTS": "2",
            "SCIPILOT_LLM_BACKOFF_INITIAL_SECONDS": "0",
        }

        with (
            patch.dict(os.environ, settings, clear=True),
            patch.object(service, "OpenAI", return_value=client),
            self.assertRaises(ExternalServiceError) as caught,
        ):
            service.call_finetuned_model_with_metadata(user_message="hello")

        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.assertEqual(caught.exception.attempts, 1)
        self.assertEqual(caught.exception.kind, "timeout")
        self.assertNotIn("must-not-leak", str(caught.exception))
        self.assertNotIn("must-not-leak", str(caught.exception.run_summary))


if __name__ == "__main__":
    unittest.main()
