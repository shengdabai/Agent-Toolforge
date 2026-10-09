"""TDD tests for the citation-verifier core helper (stdlib only)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from citations import extract_citations, classify, audit  # noqa: E402


class TestExtractCitations(unittest.TestCase):
    def test_extracts_multiple_urls(self):
        text = (
            "First see https://example.org/a and also "
            "http://docs.python.org/3/ for details."
        )
        result = extract_citations(text)
        self.assertIn("https://example.org/a", result["urls"])
        self.assertIn("http://docs.python.org/3/", result["urls"])
        self.assertEqual(len(result["urls"]), 2)

    def test_extracts_source_annotations(self):
        text = "Claim one [Source: Smith 2020]. Claim two [Source: WHO Report]."
        result = extract_citations(text)
        self.assertIn("Smith 2020", result["sources"])
        self.assertIn("WHO Report", result["sources"])
        self.assertEqual(len(result["sources"]), 2)

    def test_extracts_urls_and_sources_together(self):
        text = "Evidence at https://nature.com/x [Source: Nature 2021]."
        result = extract_citations(text)
        self.assertEqual(result["urls"], ["https://nature.com/x"])
        self.assertEqual(result["sources"], ["Nature 2021"])

    def test_no_citations_returns_empty_lists(self):
        result = extract_citations("Plain prose with no references at all.")
        self.assertEqual(result["urls"], [])
        self.assertEqual(result["sources"], [])

    def test_dedupes_repeated_urls(self):
        text = "See https://a.com/x and again https://a.com/x here."
        result = extract_citations(text)
        self.assertEqual(result["urls"], ["https://a.com/x"])

    def test_strips_trailing_punctuation_from_url(self):
        text = "Reference (https://a.com/page)."
        result = extract_citations(text)
        self.assertEqual(result["urls"], ["https://a.com/page"])


class TestClassify(unittest.TestCase):
    def _fake_fetcher(self, mapping):
        def fetcher(url):
            return mapping.get(url)
        return fetcher

    def test_classifies_live_dead_unreachable(self):
        urls = [
            "https://live.com/a",
            "https://dead.com/b",
            "https://gone.com/c",
            "https://nohost.com/d",
        ]
        mapping = {
            "https://live.com/a": 200,
            "https://dead.com/b": 404,
            "https://gone.com/c": 503,
            "https://nohost.com/d": None,  # unreachable
        }
        result = classify(urls, self._fake_fetcher(mapping))
        self.assertEqual(result["https://live.com/a"], "live")
        self.assertEqual(result["https://dead.com/b"], "dead")
        self.assertEqual(result["https://gone.com/c"], "dead")
        self.assertEqual(result["https://nohost.com/d"], "unreachable")

    def test_2xx_is_live(self):
        urls = ["https://x.com/ok"]
        result = classify(urls, self._fake_fetcher({"https://x.com/ok": 204}))
        self.assertEqual(result["https://x.com/ok"], "live")

    def test_3xx_is_live(self):
        urls = ["https://x.com/redir"]
        result = classify(urls, self._fake_fetcher({"https://x.com/redir": 301}))
        self.assertEqual(result["https://x.com/redir"], "live")

    def test_fetcher_exception_is_unreachable(self):
        def boom(url):
            raise OSError("connection refused")
        result = classify(["https://x.com/boom"], boom)
        self.assertEqual(result["https://x.com/boom"], "unreachable")


class TestAudit(unittest.TestCase):
    def _fetcher(self, mapping):
        return lambda url: mapping.get(url)

    def test_audit_counts(self):
        text = (
            "A https://live.com/a [Source: Real Study]. "
            "B https://dead.com/b. "
            "C https://down.com/c."
        )
        mapping = {
            "https://live.com/a": 200,
            "https://dead.com/b": 404,
            "https://down.com/c": None,
        }
        result = audit(text, self._fetcher(mapping))
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["live"], 1)
        self.assertEqual(result["dead"], 1)
        self.assertEqual(result["unreachable"], 1)

    def test_audit_no_citations_all_zero(self):
        result = audit("No references here.", self._fetcher({}))
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["live"], 0)
        self.assertEqual(result["dead"], 0)
        self.assertEqual(result["unreachable"], 0)
        self.assertEqual(result["suspicious"], [])

    def test_placeholder_url_flagged_suspicious(self):
        text = "Per https://example.com/xxx the result holds."
        result = audit(text, self._fetcher({"https://example.com/xxx": 200}))
        self.assertIn("https://example.com/xxx", result["suspicious"])

    def test_invalid_arxiv_flagged_suspicious(self):
        text = "See arxiv.org/abs/9999.ABCDE for the proof."
        # Even if fetch would succeed, malformed arxiv id is suspicious.
        result = audit(text, self._fetcher({}))
        self.assertTrue(
            any("9999.ABCDE" in s or "arxiv" in s.lower() for s in result["suspicious"])
        )

    def test_invalid_doi_flagged_suspicious(self):
        text = "DOI: doi:99.9999/not-a-real-doi-format"
        result = audit(text, self._fetcher({}))
        self.assertTrue(len(result["suspicious"]) >= 1)

    def test_legit_url_not_suspicious(self):
        text = "Per https://www.nature.com/articles/s41586-020-2649-2 it holds."
        url = "https://www.nature.com/articles/s41586-020-2649-2"
        result = audit(text, self._fetcher({url: 200}))
        self.assertNotIn(url, result["suspicious"])

    def test_valid_arxiv_not_suspicious(self):
        text = "See https://arxiv.org/abs/2103.00020 for CLIP."
        url = "https://arxiv.org/abs/2103.00020"
        result = audit(text, self._fetcher({url: 200}))
        self.assertNotIn(url, result["suspicious"])


class TestB11Regressions(unittest.TestCase):
    def test_real_citations_are_not_flagged(self):
        text = ("See https://arxiv.org/pdf/2301.12345.pdf, "
                "https://arxiv.org/pdf/2301.12345v2.pdf#page=3, "
                "https://arxiv.org/abs/hep-th/9901001, arXiv:math.GT/0309136, "
                "https://www.nature.com/articles/food-security and "
                "https://latest.com/barcelona")
        self.assertEqual(audit(text, lambda u: 200)["suspicious"], [])

    def test_placeholders_and_bad_ids_still_flagged(self):
        text = ("https://example.com/paper https://docs.example.org/x "
                "https://real.org/foo https://real.org/a/TODO/b "
                "https://arxiv.org/abs/9999.ABCDE arXiv:1234 "
                "https://arxiv.org/pdf/notanid.pdf")
        flagged = audit(text, lambda u: 200)["suspicious"]
        for expected in ("https://example.com/paper",
                         "https://docs.example.org/x",
                         "https://real.org/foo", "https://real.org/a/TODO/b",
                         "arxiv:9999.ABCDE", "arxiv:1234", "arxiv:notanid"):
            self.assertIn(expected, flagged)

    def test_non_int_status_is_unreachable_not_crash_or_live(self):
        for bad in ("200", True, 200.0, object()):
            self.assertEqual(classify(["https://a.org"], lambda u: bad),
                             {"https://a.org": "unreachable"})


if __name__ == "__main__":
    unittest.main()
