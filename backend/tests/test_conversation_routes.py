from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from api import routes


class ConversationRouteTests(unittest.TestCase):
    def test_list_conversations_includes_context_for_page_restore(self):
        query = MagicMock()
        query.select.return_value = query
        query.eq.return_value = query
        query.order.return_value = query
        query.range.return_value = query
        query.execute.return_value = SimpleNamespace(
            data=[
                {
                    "id": "conversation-1",
                    "agent_id": "agent-1",
                    "title": "Paper chat",
                    "module": "paper",
                    "context": {"paper_id": "paper-1"},
                }
            ],
            count=1,
        )
        service = MagicMock()
        service.table.return_value = query

        with patch.object(routes, "database", return_value=service):
            result = routes.list_conversations(
                module="paper",
                page=1,
                limit=20,
                user=SimpleNamespace(id="user-1"),
            )

        selected_columns = query.select.call_args.args[0]
        self.assertIn("context", selected_columns)
        self.assertEqual(result["items"][0]["context"]["paper_id"], "paper-1")
        self.assertEqual(result["items"][0]["messages"], [])

    def test_get_conversation_filters_messages_by_owner(self):
        query = MagicMock()
        query.select.return_value = query
        query.eq.return_value = query
        query.order.return_value = query
        query.execute.return_value = SimpleNamespace(
            data=[{"id": "message-1", "role": "user", "content": "hello"}]
        )
        service = MagicMock()
        service.table.return_value = query
        conversation = {
            "id": "conversation-1",
            "user_id": "user-1",
            "context": {},
        }

        with (
            patch.object(routes, "database", return_value=service),
            patch.object(routes, "require_owned_row", return_value=conversation) as owned,
        ):
            result = routes.get_conversation(
                "conversation-1",
                user=SimpleNamespace(id="user-1"),
            )

        owned.assert_called_once_with("conversations", "conversation-1", "user-1")
        query.eq.assert_any_call("conversation_id", "conversation-1")
        query.eq.assert_any_call("user_id", "user-1")
        self.assertEqual(result["messages"][0]["id"], "message-1")

    def test_professional_agent_receives_project_artifact_context(self):
        agent = {
            "id": "agent-1",
            "category": "problem-decomposition",
            "system_prompt": "system",
        }
        conversation = {
            "id": "conversation-1",
            "project_id": "project-1",
            "context": {},
        }

        with (
            patch.object(routes, "_paper_context_for_conversation", return_value=""),
            patch.object(routes, "_project_context_summary", return_value="项目已有问题树"),
            patch.object(routes, "_paper_knowledge_evidence", return_value=[]),
            patch.object(
                routes,
                "generate_reply_with_metadata",
                return_value={"text": "回答", "usage": {}},
            ) as generate,
        ):
            result = routes._professional_agent_answer(
                agent=agent,
                conversation=conversation,
                history=[{"role": "user", "content": "下一步怎么做？"}],
                user_id="user-1",
            )

        prompt = generate.call_args.kwargs["user_message"]
        self.assertIn("当前科研项目已有产物摘要", prompt)
        self.assertIn("项目已有问题树", prompt)
        self.assertEqual(result["retrieval_mode"], "project-artifact-context")


if __name__ == "__main__":
    unittest.main()
