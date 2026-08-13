import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from api import routes
from api.schemas import ExperimentRoadmapRequest
from services import xunfei_agent_service


class StructuredAgentResultTests(unittest.TestCase):
    def test_parse_agent_json_object_accepts_fence_and_explanation(self):
        raw = '分析结果如下：\n```json\n{"steps": [{"task": "验证", "details": "运行测试"}]}\n```'

        result = routes._parse_agent_json_object(raw)

        self.assertEqual(result["steps"][0]["task"], "验证")

    def test_parse_agent_json_object_preserves_sections_when_graph_is_truncated(self):
        raw = """```json
{
  "title": "Attention Is All You Need",
  "authors": "Unknown",
  "sections": [
    {"title": "核心方法", "content": "Transformer", "page": 2}
  ],
  "graph": {
    "entities": [{"id": "paper", "label": "Transformer"}],
    "relations": [{
```"""

        result = routes._parse_agent_json_object(raw)

        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "Attention Is All You Need")
        self.assertEqual(result["sections"][0]["page"], 2)
        self.assertNotIn("graph", result)

    def test_normalize_research_tree_rejects_unstructured_reply(self):
        with self.assertRaises(HTTPException) as raised:
            routes._normalize_research_tree("普通文本", "研究方向")

        self.assertEqual(raised.exception.status_code, 502)

    def test_normalize_research_tree_sanitizes_agent_fields(self):
        raw = """{
          "core_question": "如何验证方法有效？",
          "sub_questions": [
            {
              "question": "数据是否足够？",
              "feasibility": "unexpected",
              "datasets": ["Dataset A"],
              "papers": ["Paper A"]
            }
          ]
        }"""

        result = routes._normalize_research_tree(raw, "fallback")

        self.assertEqual(result["sub_questions"][0]["feasibility"], "medium")
        self.assertEqual(result["sub_questions"][0]["datasets"], ["Dataset A"])
        self.assertTrue(result["sub_questions"][0]["id"])

    def test_normalize_roadmap_reindexes_steps_and_bounds_days(self):
        raw = """{
          "objective": "复现实验",
          "steps": [
            {"task": "准备", "details": "锁定环境", "estimated_days": 999}
          ],
          "tools": ["Python", "Docker"]
        }"""

        result = routes._normalize_roadmap(raw, "fallback")

        self.assertEqual(result["steps"][0]["step"], 1)
        self.assertEqual(result["steps"][0]["estimated_days"], 90)
        self.assertEqual(result["tools"], ["Python", "Docker"])

    def test_repository_file_tree_uses_real_paths(self):
        result = routes._repository_file_tree(
            [
                {"path": "src", "type": "tree"},
                {"path": "src/main.py", "type": "blob", "size": 120},
                {"path": "README.md", "type": "blob", "size": 30},
            ]
        )

        src = next(item for item in result if item["name"] == "src")
        self.assertEqual(src["children"][0]["path"], "src/main.py")
        self.assertEqual(src["children"][0]["size"], 120)

    def test_artifact_context_excerpt_keeps_workflow_facts(self):
        excerpt = routes._artifact_context_excerpt(
            {
                "artifact_type": "experiment-roadmap",
                "title": "缺陷预测实验",
                "content": {
                    "objective": "比较不同模型",
                    "steps": [
                        {"task": "准备数据", "details": "固定训练测试划分"},
                        {"task": "运行基线", "details": "记录统一指标"},
                    ],
                },
            }
        )

        self.assertIn("缺陷预测实验", excerpt)
        self.assertIn("比较不同模型", excerpt)
        self.assertIn("准备数据", excerpt)

    def test_roadmap_rejects_wrong_upstream_artifact_type(self):
        payload = ExperimentRoadmapRequest(
            question_id="artifact-1",
            objective="验证方法",
        )
        with patch.object(
            routes,
            "require_owned_row",
            return_value={"id": "artifact-1", "artifact_type": "code-reproduction"},
        ):
            with self.assertRaises(HTTPException) as raised:
                routes.generate_roadmap(
                    payload,
                    user=SimpleNamespace(id="user-1"),
                )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("研究问题拆解", raised.exception.detail)


class ProjectPlanningAgentConfigTests(unittest.TestCase):
    def test_project_planning_uses_independent_config(self):
        values = {
            "PROJECT_PLANNING_APP_ID": "app",
            "PROJECT_PLANNING_API_KEY": "key",
            "PROJECT_PLANNING_API_SECRET": "secret",
            "PROJECT_PLANNING_WS_URL": "wss://example.test/v1/assistants/project",
        }
        with patch.dict("os.environ", values, clear=False):
            config = xunfei_agent_service.get_xunfei_agent_config(
                "project-planning"
            )

        self.assertEqual(config["app_id"], "app")
        self.assertEqual(config["ws_url"], values["PROJECT_PLANNING_WS_URL"])


if __name__ == "__main__":
    unittest.main()
