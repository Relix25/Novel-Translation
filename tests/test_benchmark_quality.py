"""Structural citation checks, not proof of model quality or model access."""

import unittest

from tools.benchmark_quality import validate


class QualityAuditTests(unittest.TestCase):
    def setUp(self):
        self.cases = [
            {
                "blind_id": "B001",
                "source": "A real source clause.",
                "translation": "Une clause traduite.",
            }
        ]
        self.finding = {
            "source_quote": "source clause",
            "translation_quote": "clause traduite",
            "category": "meaning",
            "explanation": "Synthetic test justification.",
        }

    def test_exact_quotations_are_required(self):
        response = {
            "cases": [{"blind_id": "B001", "verdict": "errors", "findings": [self.finding]}]
        }
        self.assertEqual(validate(response, self.cases), response)
        for field in ("source_quote", "translation_quote"):
            invalid = {
                "cases": [
                    {
                        "blind_id": "B001",
                        "verdict": "errors",
                        "findings": [{**self.finding, field: "invented quotation"}],
                    }
                ]
            }
            with self.assertRaises(ValueError):
                validate(invalid, self.cases)

    def test_missing_duplicate_and_invented_cases_rejected(self):
        for ids in ([], ["B001", "B001"], ["B999"]):
            with self.assertRaises(ValueError):
                validate(
                    {
                        "cases": [
                            {"blind_id": identity, "verdict": "clean", "findings": []}
                            for identity in ids
                        ]
                    },
                    self.cases,
                )

    def test_omission_may_have_no_target_quote_but_clean_verdict_cannot_have_errors(self):
        omission = {**self.finding, "category": "omission", "translation_quote": ""}
        validate(
            {"cases": [{"blind_id": "B001", "verdict": "errors", "findings": [omission]}]},
            self.cases,
        )
        with self.assertRaises(ValueError):
            validate(
                {"cases": [{"blind_id": "B001", "verdict": "clean", "findings": [omission]}]},
                self.cases,
            )


if __name__ == "__main__":
    unittest.main()
