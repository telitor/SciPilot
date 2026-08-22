import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from websocket import WebSocketTimeoutException


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import xunfei_agent_service as service
from services.external_service_reliability import (
    ExternalServiceError,
    reset_external_service_runtime_state,
)


class XunfeiAgentReliabilityTests(unittest.TestCase):
    def setUp(self):
        reset_external_service_runtime_state()

    def test_generation_connect_timeout_is_not_automatically_replayed(self):
        environment = {
            "XF_AGENT_MAX_ATTEMPTS": "2",
            "XF_AGENT_BACKOFF_INITIAL_SECONDS": "0",
            "XF_AGENT_CONNECT_TIMEOUT_SECONDS": "4",
            "XF_AGENT_READ_TIMEOUT_SECONDS": "7",
        }

        with (
            patch.dict(os.environ, environment, clear=True),
            patch.object(
                service,
                "create_connection",
                side_effect=[
                    WebSocketTimeoutException("credential=must-not-leak"),
                    RuntimeError("must-not-run"),
                ],
            ) as connect,
            self.assertRaises(ExternalServiceError) as caught,
        ):
            service.call_xunfei_agent_with_config_metadata(
                user_id="user-1",
                user_message="question",
                app_id="app-id",
                api_key="api-key",
                api_secret="api-secret",
                ws_url="wss://agent.example.test/v1/chat",
            )

        self.assertEqual(connect.call_count, 1)
        self.assertEqual(connect.call_args.kwargs["timeout"], 4)
        self.assertEqual(caught.exception.attempts, 1)
        self.assertEqual(caught.exception.kind, "timeout")
        self.assertNotIn("must-not-leak", str(caught.exception))
        self.assertNotIn("must-not-leak", str(caught.exception.run_summary))

    def test_provider_error_is_not_retried_and_does_not_expose_request_id(self):
        websocket = MagicMock()
        websocket.recv.return_value = json.dumps(
            {
                "header": {
                    "code": 10013,
                    "status": 2,
                    "sid": "provider-secret-request-id",
                },
                "payload": {},
            }
        )

        with (
            patch.dict(
                os.environ,
                {
                    "XF_AGENT_MAX_ATTEMPTS": "3",
                    "XF_AGENT_BACKOFF_INITIAL_SECONDS": "0",
                },
                clear=True,
            ),
            patch.object(service, "create_connection", return_value=websocket) as connect,
            self.assertRaises(ExternalServiceError) as caught,
        ):
            service.call_xunfei_agent_with_config_metadata(
                user_id="user-1",
                user_message="question",
                app_id="app-id",
                api_key="api-key",
                api_secret="api-secret",
                ws_url="wss://agent.example.test/v1/chat",
            )

        self.assertEqual(connect.call_count, 1)
        self.assertEqual(caught.exception.provider_code, 10013)
        self.assertEqual(caught.exception.attempts, 1)
        self.assertNotIn("provider-secret-request-id", str(caught.exception))
        self.assertNotIn("api-secret", str(caught.exception.run_summary))

    def test_invalid_websocket_url_is_permanent_and_never_connects(self):
        with (
            patch.dict(os.environ, {"XF_AGENT_MAX_ATTEMPTS": "3"}, clear=True),
            patch.object(service, "create_connection") as connect,
            self.assertRaises(ExternalServiceError) as caught,
        ):
            service.call_xunfei_agent_with_config_metadata(
                user_id="user-1",
                user_message="question",
                app_id="app-id",
                api_key="api-key",
                api_secret="api-secret",
                ws_url="https://not-a-websocket.example.test/chat",
            )

        connect.assert_not_called()
        self.assertEqual(caught.exception.kind, "invalid_response")
        self.assertEqual(caught.exception.attempts, 1)


if __name__ == "__main__":
    unittest.main()
