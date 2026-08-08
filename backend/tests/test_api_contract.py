import os
import re
import unittest
from pathlib import Path
from typing import Any

os.environ.setdefault("RESEARCH_JOB_WORKER_ENABLED", "false")

from main import app


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_API_FILE = PROJECT_ROOT / "frontend" / "src" / "services" / "api.ts"
FRONTEND_SOURCE_ROOT = PROJECT_ROOT / "frontend" / "src"


def _canonical_path(path: str) -> str:
    path = re.sub(r"\$\{[^}]+\}", "{}", path)
    return re.sub(r"\{[^}]+\}", "{}", path)


def _frontend_api_calls(source: str) -> set[tuple[str, str]]:
    calls: set[tuple[str, str]] = set()
    pattern = re.compile(
        r"apiClient\.(get|post|patch|delete)"
        r"(?:<[\s\S]{0,240}?>)?\s*\(\s*"
        r"(?P<quote>['\"`])(?P<path>/[^'\"`]+)(?P=quote)",
    )
    for match in pattern.finditer(source):
        calls.add((match.group(1).lower(), _canonical_path(match.group("path"))))
    return calls


def _resolve_schema(openapi: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    reference = schema.get("$ref")
    if not reference:
        return schema
    name = reference.rsplit("/", 1)[-1]
    return openapi["components"]["schemas"][name]


class FrontendBackendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.openapi = app.openapi()
        cls.frontend_source = FRONTEND_API_FILE.read_text(encoding="utf-8")

    def operation(self, path: str, method: str) -> dict[str, Any]:
        return self.openapi["paths"][f"/api/v1{path}"][method.lower()]

    def request_schema(
        self,
        path: str,
        method: str = "post",
        content_type: str = "application/json",
    ) -> dict[str, Any]:
        operation = self.operation(path, method)
        body = operation["requestBody"]["content"][content_type]["schema"]
        return _resolve_schema(self.openapi, body)

    def response_schema(
        self,
        path: str,
        method: str = "get",
        status: str = "200",
    ) -> dict[str, Any]:
        operation = self.operation(path, method)
        schema = operation["responses"][status]["content"]["application/json"]["schema"]
        return _resolve_schema(self.openapi, schema)

    def test_every_frontend_http_call_exists_in_fastapi_openapi(self):
        backend_operations = {
            (method.lower(), _canonical_path(path.removeprefix("/api/v1")))
            for path, path_item in self.openapi["paths"].items()
            if path.startswith("/api/v1")
            for method in path_item
            if method.lower() in {"get", "post", "patch", "delete"}
        }
        frontend_operations = _frontend_api_calls(self.frontend_source)
        self.assertGreaterEqual(len(frontend_operations), 35)
        missing = sorted(frontend_operations - backend_operations)
        self.assertEqual(missing, [], f"Frontend calls missing backend routes: {missing}")

    def test_core_json_request_fields_match_frontend_payloads(self):
        expected_required = {
            ("/auth/login", "post"): {"email", "password"},
            ("/auth/register", "post"): {"email", "password", "username"},
            ("/chat", "post"): {"conversation_id", "agent_id", "message"},
            ("/conversations/{conversation_id}/messages", "post"): {"content"},
            ("/research/decompose", "post"): {"direction"},
            ("/experiments/generate-roadmap", "post"): {"question_id"},
            ("/code/analyze-repo", "post"): {"repo_url"},
        }
        for (path, method), required in expected_required.items():
            with self.subTest(path=path, method=method):
                schema = self.request_schema(path, method)
                self.assertTrue(required.issubset(set(schema.get("required", []))))
                self.assertTrue(required.issubset(set(schema.get("properties", {}))))

    def test_upload_contracts_require_file_and_keep_project_optional(self):
        for path in ("/papers/upload-async", "/papers/upload", "/results/analyze"):
            with self.subTest(path=path):
                schema = self.request_schema(path, content_type="multipart/form-data")
                required = set(schema.get("required", []))
                properties = set(schema.get("properties", {}))
                self.assertIn("file", required)
                self.assertIn("project_id", properties)
                self.assertNotIn("project_id", required)

        responses = self.operation("/papers/upload-async", "post")["responses"]
        self.assertIn("202", responses)

    def test_workflow_link_fields_are_optional_and_published(self):
        json_links = {
            "/research/decompose": "paper_id",
            "/code/analyze-repo": "roadmap_id",
        }
        for path, field in json_links.items():
            with self.subTest(path=path, field=field):
                schema = self.request_schema(path)
                self.assertIn(field, schema.get("properties", {}))
                self.assertNotIn(field, schema.get("required", []))

        result_schema = self.request_schema(
            "/results/analyze",
            content_type="multipart/form-data",
        )
        self.assertIn("repo_id", result_schema.get("properties", {}))
        self.assertNotIn("repo_id", result_schema.get("required", []))

    def test_p0_response_contracts_publish_frontend_required_fields(self):
        expected_required = {
            ("/papers/upload-async", "post", "202"): {
                "job_id", "paper_id", "status", "progress"
            },
            ("/jobs/{job_id}", "get", "200"): {
                "id", "job_type", "status", "progress", "attempts", "max_attempts"
            },
            ("/chat", "post", "200"): {
                "reply", "message", "citations", "knowledge_used", "agent"
            },
            ("/research/decompose", "post", "200"): {
                "id", "core_question", "sub_questions"
            },
            ("/experiments/generate-roadmap", "post", "200"): {
                "id", "objective", "steps", "baselines", "datasets"
            },
            ("/code/analyze-repo", "post", "200"): {
                "id", "repo_name", "repo_url", "file_tree", "dependencies", "steps"
            },
            ("/results/analyze", "post", "200"): {
                "id", "charts", "stats", "interpretation", "suggestions"
            },
        }
        for (path, method, status), required in expected_required.items():
            with self.subTest(path=path, method=method, status=status):
                schema = self.response_schema(path, method, status)
                self.assertTrue(required.issubset(set(schema.get("required", []))))
                self.assertTrue(required.issubset(set(schema.get("properties", {}))))

    def test_protected_frontend_routes_publish_authorization_header(self):
        public_paths = {
            "/auth/login",
            "/auth/register",
            "/auth/logout",
            "/agents",
            "/resources",
        }
        for method, canonical_path in _frontend_api_calls(self.frontend_source):
            if canonical_path in public_paths:
                continue
            matching_path = next(
                path
                for path in self.openapi["paths"]
                if path.startswith("/api/v1")
                and _canonical_path(path.removeprefix("/api/v1")) == canonical_path
                and method in self.openapi["paths"][path]
            )
            parameters = self.openapi["paths"][matching_path][method].get("parameters", [])
            names = {parameter.get("name") for parameter in parameters}
            self.assertIn(
                "authorization",
                names,
                f"{method.upper()} {canonical_path} is missing auth dependency",
            )

    def test_frontend_has_no_unsupported_websocket_contract(self):
        self.assertNotIn("new WebSocket", self.frontend_source)
        self.assertNotIn("VITE_WS_URL", self.frontend_source)

    def test_production_pages_do_not_import_mock_api(self):
        offenders = []
        for path in FRONTEND_SOURCE_ROOT.rglob("*.tsx"):
            source = path.read_text(encoding="utf-8")
            if "mockAPI" in source:
                offenders.append(str(path.relative_to(PROJECT_ROOT)))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
