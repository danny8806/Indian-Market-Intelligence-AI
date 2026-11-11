"""Deterministic classification tests: no network, no model, no trading."""
import unittest

from news_collector.classification import classify_event


class ClassificationTests(unittest.TestCase):
    def test_results_category_and_bullish_direction(self):
        category, sentiment, score = classify_event(
            "Thermax Limited Q2 results: net profit rose 20%")
        self.assertEqual(category, "financial_results")
        self.assertEqual(sentiment, "BULLISH")
        self.assertEqual(score, 3)

    def test_results_category_and_bearish_direction(self):
        category, sentiment, score = classify_event(
            "Infosys Q3 results: net profit fell 8%")
        self.assertEqual(category, "financial_results")
        self.assertEqual(sentiment, "BEARISH")
        self.assertEqual(score, 3)

    def test_mixed_direction_is_not_forced(self):
        category, sentiment, score = classify_event(
            "Company Q2 results: revenue rose but net profit fell")
        self.assertEqual(category, "financial_results")
        self.assertEqual(sentiment, "MIXED")
        self.assertEqual(score, 0)

    def test_undirected_headline_stays_unclear(self):
        category, sentiment, score = classify_event(
            "Board meeting to consider QIP issue")
        self.assertEqual(category, "fundraising")
        self.assertEqual(sentiment, "UNCLEAR")
        self.assertEqual(score, 0)

    def test_speculation_is_not_a_direction(self):
        category, sentiment, score = classify_event(
            "Net profit may rise next quarter, company says")
        self.assertEqual(category, "other")
        self.assertEqual(sentiment, "UNCLEAR")
        self.assertEqual(score, 0)

    def test_regulatory_and_order_categories(self):
        self.assertEqual(classify_event("SEBI imposes penalty on issuer")[0], "regulatory")
        self.assertEqual(classify_event("Company wins order worth Rs 500 crore")[0],
                         "orders_contracts")


if __name__ == "__main__":
    unittest.main()
