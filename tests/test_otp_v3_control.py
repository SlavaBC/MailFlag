"""Regression checks for the 200-case OTP v3 control corpus."""

import json
from pathlib import Path
import unittest

from mailflag.core.otp import classify_otp


CASES = json.loads(
    (Path(__file__).with_name("data") / "otp_v3_control.json").read_text(
        encoding="utf-8"
    )
)


class OtpV3Control(unittest.TestCase):
    def test_case_count(self):
        self.assertEqual(len(CASES), 200)


def _case_test(case):
    def test(self):
        result = classify_otp(case["subject"], case["body"])
        self.assertEqual(result["type"], case["expected_type"], case["comment"])
        self.assertEqual(result["code"], case["expected_code"], case["comment"])

    return test


for _case in CASES:
    setattr(OtpV3Control, f'test_case_{_case["id"]}', _case_test(_case))


if __name__ == "__main__":
    unittest.main()
