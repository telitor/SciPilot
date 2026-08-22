import unittest
from urllib.error import HTTPError
from urllib.request import Request

from scripts.run_deployed_provider_smoke import _SameOriginHttpsRedirectHandler


class DeployedProviderSmokeRedirectTests(unittest.TestCase):
    def setUp(self):
        self.handler = _SameOriginHttpsRedirectHandler()
        self.request = Request(
            "https://api.example.test/api/v1/admin/evaluations/suites",
            headers={"Authorization": "Bearer administrator-token"},
        )

    def test_allows_same_origin_https_redirect(self):
        redirected = self.handler.redirect_request(
            self.request,
            None,
            302,
            "Found",
            {},
            "https://api.example.test:443/canonical/suites",
        )

        self.assertEqual(
            redirected.full_url,
            "https://api.example.test:443/canonical/suites",
        )
        self.assertEqual(
            redirected.get_header("Authorization"),
            "Bearer administrator-token",
        )

    def test_blocks_cross_origin_redirect_before_copying_authorization(self):
        with self.assertRaisesRegex(HTTPError, "unsafe deployed-smoke redirect"):
            self.handler.redirect_request(
                self.request,
                None,
                302,
                "Found",
                {},
                "https://collector.example.test/capture",
            )

    def test_blocks_https_downgrade_redirect(self):
        with self.assertRaisesRegex(HTTPError, "unsafe deployed-smoke redirect"):
            self.handler.redirect_request(
                self.request,
                None,
                302,
                "Found",
                {},
                "http://api.example.test/canonical/suites",
            )

    def test_blocks_redirect_with_embedded_credentials(self):
        with self.assertRaisesRegex(HTTPError, "unsafe deployed-smoke redirect"):
            self.handler.redirect_request(
                self.request,
                None,
                302,
                "Found",
                {},
                "https://user:password@api.example.test/canonical/suites",
            )


if __name__ == "__main__":
    unittest.main()
