import unittest

from api.normalization import normalized_string_list, parse_agent_json_object


class NormalizationTests(unittest.TestCase):
    def test_agent_json_accepts_fence_and_leading_explanation(self):
        raw = '分析如下：\n```json\n{"sections": []}\n```'
        self.assertEqual(parse_agent_json_object(raw), {"sections": []})

    def test_agent_json_rejects_non_object(self):
        self.assertIsNone(parse_agent_json_object('["not", "an", "object"]'))

    def test_string_list_is_bounded_and_deduplicated(self):
        self.assertEqual(
            normalized_string_list([" alpha ", "alpha", "beta", "gamma"], limit=2),
            ["alpha", "beta"],
        )


if __name__ == "__main__":
    unittest.main()
