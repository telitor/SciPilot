import unittest

from services.knowledge_graph_service import normalize_paper_graph


class KnowledgeGraphServiceTests(unittest.TestCase):
    def test_normalizes_model_entities_and_relations(self):
        graph = normalize_paper_graph(
            {
                "entities": [
                    {"id": "method", "label": "Self-Attention", "category": "method", "citation": "evidence", "page": 2}
                ],
                "relations": [
                    {"source": "paper", "target": "method", "relation": "uses", "strength": 0.9, "citation": "evidence", "page": 2}
                ],
            },
            title="Attention Is All You Need",
            authors=["Vaswani"],
            sections=[],
        )
        self.assertEqual([item["key"] for item in graph["entities"]], ["paper", "method"])
        self.assertEqual(graph["entities"][1]["page_start"], 2)
        self.assertEqual(graph["relations"][0]["relation"], "uses")
        self.assertEqual(graph["relations"][0]["page_start"], 2)

    def test_old_report_falls_back_to_authors_and_sections(self):
        graph = normalize_paper_graph(
            None,
            title="Demo Paper",
            authors=["Alice"],
            sections=[
                {"heading": "核心方法", "content": "使用图神经网络。", "citations": [{"text": "证据", "page": 3}]}
            ],
        )
        categories = {item["category"] for item in graph["entities"]}
        self.assertEqual(categories, {"paper", "author", "section"})
        self.assertEqual(len(graph["relations"]), 2)
        section = next(item for item in graph["entities"] if item["category"] == "section")
        self.assertEqual(section["page_start"], 3)

    def test_pages_outside_extracted_set_are_discarded(self):
        graph = normalize_paper_graph(
            {
                "entities": [
                    {"id": "method", "label": "Method", "category": "method", "page": 99}
                ]
            },
            title="Demo",
            authors=["Unknown"],
            sections=[],
            valid_pages={1, 2, 3},
        )

        self.assertIsNone(graph["entities"][1]["page_start"])


if __name__ == "__main__":
    unittest.main()
