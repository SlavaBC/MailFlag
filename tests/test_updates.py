"""Regression tests for the focused Google Drive Updates document."""

from email.message import EmailMessage
from types import SimpleNamespace
import unittest

from mailflag.core.otp import classify_otp
from mailflag.core.sender import format_message_sender, format_sender


class SenderDisplayTests(unittest.TestCase):
    def assert_sender(self, raw, expected):
        self.assertEqual(format_sender(raw), expected)

    def test_email_only(self):
        self.assert_sender("shipment-tracking@amazon.ca",
                           "shipment-tracking@amazon.ca")

    def test_short_display_name_and_email(self):
        self.assert_sender("Amazon.ca <shipment-tracking@amazon.ca>",
                           "Amazon.ca <shipment-tracking@amazon.ca>")

    def test_long_display_name_preserves_email(self):
        raw = ("International Customer Service and Online Order Notification "
               "Department for Canada <customer@example.test>")
        result = format_sender(raw)
        self.assertIn("International Customer Service", result)
        self.assertTrue(result.endswith("<customer@example.test>"))

    def test_cyrillic_and_french_accents(self):
        self.assert_sender("Служба поддержки <help@example.test>",
                           "Служба поддержки <help@example.test>")
        self.assert_sender("Service à la clientèle <a@example.test>",
                           "Service à la clientèle <a@example.test>")

    def test_mime_encoded_display_name(self):
        self.assert_sender("=?UTF-8?B?0KHQu9GD0LbQsdCwINC/0L7QtNC00LXRgNC20LrQuA==?= <help@example.test>",
                           "Служба поддержки <help@example.test>")

    def test_quoted_display_name(self):
        self.assert_sender('"Orders, Canada" <orders@example.test>',
                           "Orders, Canada <orders@example.test>")

    def test_very_long_values_are_bounded_but_address_survives(self):
        email = "very-long-local-part-" + "x" * 120 + "@example.test"
        result = format_sender(f"{'Name ' * 100} <{email}>")
        self.assertLess(len(result), 340)
        self.assertTrue(result.endswith(f"<{email}>"))

    def test_message_uses_raw_from_header_instead_of_email_only_property(self):
        obj = EmailMessage()
        obj["From"] = "Amazon.ca <shipment-tracking@amazon.ca>"
        message = SimpleNamespace(obj=obj, from_="shipment-tracking@amazon.ca")
        self.assertEqual(format_message_sender(message),
                         "Amazon.ca <shipment-tracking@amazon.ca>")


class OtpYearAndNegationTests(unittest.TestCase):
    def assert_normal(self, subject, body):
        result = classify_otp(subject, body)
        self.assertEqual(result["type"], "NORMAL", result)
        self.assertIsNone(result["code"], result)

    def test_calendar_years_in_ordinary_messages(self):
        contexts = (
            "Your annual statement for {year} is ready.",
            "Invoice period: January {year}. Verification completed.",
            "Security report and account summary for tax year {year}.",
        )
        for year in range(2025, 2031):
            for template in contexts:
                with self.subTest(year=year, template=template):
                    self.assert_normal("Billing update", template.format(year=year))

    def test_negated_verification_language_is_normal(self):
        cases = (
            "This is not a verification code. Statement year 2026.",
            "This is not an OTP. The report covers 2027.",
            "No verification code is required for your 2028 invoice.",
            "You do not need a verification code for the 2029 renewal.",
        )
        for body in cases:
            with self.subTest(body=body):
                self.assert_normal("Account notice", body)

    def test_real_otp_with_year_shaped_value_requires_explicit_instruction(self):
        result = classify_otp("Sign in", "Use this verification code: 2026")
        self.assertEqual((result["type"], result["code"]), ("OTP", "2026"))

    def test_regular_strong_otp_still_works(self):
        for text, code in (
            ("Use this verification code: 482913", "482913"),
            ("Enter the following code: 8841", "8841"),
            ("Your one-time code is 193746", "193746"),
        ):
            with self.subTest(text=text):
                result = classify_otp("Sign in", text)
                self.assertEqual((result["type"], result["code"]), ("OTP", code))


if __name__ == "__main__":
    unittest.main()
