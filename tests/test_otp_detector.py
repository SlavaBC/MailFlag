"""Offline OTP regression suite driven by an editable JSON corpus."""

import json
from collections import Counter
from pathlib import Path
import unittest

from mailflag.core.otp import MessageType, classify


CORPUS_PATH = Path(__file__).with_name("data") / "otp_regression.json"
DOCUMENT = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
# Accept both the original bare list and the extensible v1 document containing
# human-readable metadata plus the actual case list.
CASES = DOCUMENT["cases"] if isinstance(DOCUMENT, dict) else DOCUMENT
METADATA = DOCUMENT.get("metadata", {}) if isinstance(DOCUMENT, dict) else {}


class OtpRegression(unittest.TestCase):
    def test_corpus_schema_and_coverage(self):
        self.assertGreaterEqual(len(CASES), 50)
        required = {"id", "category", "subject", "body", "expected_type",
                    "expected_code", "comment"}
        self.assertTrue(all(required <= case.keys() for case in CASES))
        self.assertEqual(len({case["id"] for case in CASES}), len(CASES))
        counts = Counter(case["category"] for case in CASES)
        types = Counter(case["expected_type"] for case in CASES)
        self.assertGreaterEqual(types["OTP"], 5)
        self.assertGreaterEqual(types["NORMAL"], 20)
        if counts["false_positive_trap"]:
            self.assertGreaterEqual(counts["false_positive_trap"], 8)
        elif any(str(case["id"]).startswith("v3-") for case in CASES):
            self.assertGreaterEqual(types["NORMAL"], 100)
        else:
            # v2 divides adversarial NORMAL cases into more precise categories.
            adversarial = sum(
                count for name, count in counts.items()
                if name.endswith("_nonotp") or name in {
                    "dev_nonotp", "security_nonotp", "verification_nonotp",
                    "error_code", "non_auth_code", "keyword_without_code",
                }
            )
            self.assertGreaterEqual(adversarial, 20)
        if METADATA:
            self.assertEqual(METADATA.get("case_count"), len(CASES))
            self.assertEqual(METADATA.get("otp_count"), types["OTP"])
            self.assertEqual(METADATA.get("normal_count"), types["NORMAL"])

    def test_regression_metrics(self):
        metrics = Counter()
        for case in CASES:
            actual = classify(case["subject"], case["body"]).type
            expected_otp = case["expected_type"] == MessageType.OTP.value
            actual_otp = actual is MessageType.OTP
            metrics["true_positive" if expected_otp and actual_otp else
                    "false_negative" if expected_otp else
                    "false_positive" if actual_otp else
                    "true_negative"] += 1
        print(
            "OTP regression metrics: "
            f"TP={metrics['true_positive']} TN={metrics['true_negative']} "
            f"FP={metrics['false_positive']} FN={metrics['false_negative']}"
        )
        self.assertEqual(metrics["false_positive"], 0)
        self.assertEqual(metrics["false_negative"], 0)


def _case_test(case):
    def test(self):
        result = classify(case["subject"], case["body"])
        self.assertEqual(
            result.type.value, case["expected_type"],
            f'{case["comment"]}; confidence={result.confidence}; '
            f'reason={result.reason}',
        )
        self.assertEqual(
            result.code, case["expected_code"],
            f'{case["comment"]}; classifier selected {result.code!r}',
        )
    return test


for _case in CASES:
    setattr(OtpRegression, f'test_case_{_case["id"]}', _case_test(_case))


if __name__ == "__main__":
    unittest.main()
