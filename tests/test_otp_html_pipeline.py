"""OTP regression tests for the cleaned human-readable message pipeline."""

from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
import unittest

from mailflag.core.otp import classify_otp
from mailflag.core.preview import extract_human_text, extract_message_text


DATA = Path(__file__).with_name("data")


def classify_parts(subject, plain="", html=""):
    body = extract_human_text(plain, html)
    return body, classify_otp(subject, body)


class HtmlSafeOtpPipeline(unittest.TestCase):
    def assert_normal_without(self, html, forbidden="278509"):
        body, result = classify_parts("Ordinary notification", html=html)
        self.assertNotIn(forbidden, body)
        self.assertEqual(result["type"], "NORMAL")
        self.assertIsNone(result["code"])

    def test_number_only_in_class_name(self):
        self.assert_normal_without('<div class="verification-code-278509">Package delivered.</div>')

    def test_number_only_in_css_selector(self):
        self.assert_normal_without(
            "<style>.verification-code-278509{display:block}</style><p>Package delivered.</p>"
        )

    def test_number_only_in_url(self):
        self.assert_normal_without(
            '<p>Package delivered.</p><a href="https://example.test/verification/278509">Track</a>'
        )

    def test_number_only_in_tracking_parameter(self):
        self.assert_normal_without(
            '<p>Package delivered.</p><img src="https://t.test/p.gif?code=278509">'
        )

    def test_number_only_in_html_comment(self):
        self.assert_normal_without("<!-- verification code 278509 --><p>Package delivered.</p>")

    def test_number_only_in_image_filename(self):
        self.assert_normal_without('<img alt="" src="verification-code-278509.png"><p>Delivered.</p>')

    def test_number_only_in_hidden_technical_block(self):
        self.assert_normal_without(
            '<div style="display:none">template verification code 278509</div>'
            "<p>Your parcel was delivered.</p>"
        )

    def test_real_otp_in_visible_html(self):
        body, result = classify_parts(
            "Sign-in request",
            html="<style>.code-778899{color:red}</style><p>Your verification code is <b>482913</b>.</p>",
        )
        self.assertIn("482913", body)
        self.assertEqual((result["type"], result["code"]), ("OTP", "482913"))

    def test_real_otp_in_plain_text(self):
        body, result = classify_parts(
            "Security code",
            plain="Use this code to sign in: 8841",
            html='<p class="code-278509">Ignore HTML alternative.</p>',
        )
        self.assertNotIn("278509", body)
        self.assertEqual((result["type"], result["code"]), ("OTP", "8841"))

    def test_order_reference_in_visible_text_is_normal(self):
        body, result = classify_parts(
            "Order delivered",
            html="<p>Your order reference 482913 has been delivered.</p>",
        )
        self.assertIn("482913", body)
        self.assertEqual(result["type"], "NORMAL")

    def test_only_nearby_strong_context_selects_otp(self):
        body, result = classify_parts(
            "Account activity",
            html=(
                "<p>Order 111222 was placed on 2026-09-25.</p>"
                "<p>Your verification code is 482913.</p>"
            ),
        )
        self.assertIn("111222", body)
        self.assertEqual((result["type"], result["code"]), ("OTP", "482913"))

    def test_real_walmart_delivered_message_is_normal(self):
        path = DATA / "walmart_delivered_real.eml"
        message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        body = extract_message_text(message)
        result = classify_otp(str(message["Subject"]), body)
        self.assertEqual(str(message["Subject"]), "Your order was delivered")
        self.assertNotIn("278509", body)
        self.assertEqual(result["type"], "NORMAL")
        self.assertIsNone(result["code"])

    def test_text_attachment_is_not_scanned(self):
        message = EmailMessage()
        message.set_content("Your parcel has been delivered.")
        message.add_attachment(
            "Your verification code is 278509.",
            subtype="plain",
            filename="technical.txt",
        )
        body = extract_message_text(message)
        result = classify_otp("Delivery notice", body)
        self.assertNotIn("278509", body)
        self.assertEqual(result["type"], "NORMAL")

    def test_real_roku_signin_message_is_otp(self):
        message = BytesParser(policy=policy.default).parsebytes(
            (DATA / "roku_signin_real.eml").read_bytes()
        )
        body = extract_message_text(message)
        result = classify_otp(str(message["Subject"]), body)
        self.assertEqual((result["type"], result["code"]), ("OTP", "482913"))


if __name__ == "__main__":
    unittest.main()
