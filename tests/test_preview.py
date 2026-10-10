"""Unit and real-message regression tests for email preview extraction."""

from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
import unittest

from mailflag.core.preview import extract_message_preview, extract_preview


DATA = Path(__file__).with_name("data")


class PreviewExtractorTests(unittest.TestCase):
    def test_good_plain_text_is_preferred(self):
        result = extract_preview(
            "Your parcel will arrive tomorrow.",
            "<p>This HTML text must not win.</p>",
        )
        self.assertEqual(result, "Your parcel will arrive tomorrow.")

    def test_multipart_alternative_prefers_plain(self):
        message = EmailMessage()
        message.set_content("A useful plain-text account update.")
        message.add_alternative("<p>A different HTML update.</p>", subtype="html")
        self.assertEqual(
            extract_message_preview(message),
            "A useful plain-text account update.",
        )

    def test_html_only_preheader(self):
        html = (
            '<html><body><div class="preheader" style="display:none">'
            "Your order has shipped and will arrive soon.</div>"
            "<h1>Track your shipment</h1></body></html>"
        )
        self.assertEqual(
            extract_preview(html_body=html),
            "Your order has shipped and will arrive soon.",
        )

    def test_html_only_visible_text(self):
        html = "<html><body><h1>Welcome back</h1><p>Your weekly report is ready.</p></body></html>"
        self.assertEqual(
            extract_preview(html_body=html),
            "Your weekly report is ready.",
        )

    def test_css_heavy_email_discards_head(self):
        html = (
            "<html><head><style>#outlook a { padding: 0; margin: 0; } "
            "@media screen { table { border: 0 !important; }}</style></head>"
            "<body><p>Your delivery is scheduled for Friday.</p></body></html>"
        )
        result = extract_preview(html_body=html)
        self.assertEqual(result, "Your delivery is scheduled for Friday.")
        self.assertNotIn("padding", result)

    def test_hidden_junk_is_not_a_preheader(self):
        html = (
            '<div class="preheader" style="display:none">&nbsp;&zwnj;' * 20
            + "</div>" * 20
            + "<p>Your statement is available.</p>"
        )
        self.assertEqual(extract_preview(html_body=html), "Your statement is available.")

    def test_boilerplate_first_is_skipped(self):
        html = (
            "<p>View in browser</p><p>Having trouble viewing this email?</p>"
            "<p>Your reservation is confirmed for Saturday.</p>"
        )
        self.assertEqual(
            extract_preview(html_body=html),
            "Your reservation is confirmed for Saturday.",
        )

    def test_empty_or_garbled_html_returns_empty(self):
        self.assertEqual(
            extract_preview(html_body="<style>div{padding:0!important}</style><div>&nbsp;</div>"),
            "",
        )

    def test_quoted_or_forwarded_tail_is_ignored(self):
        plain = (
            "The meeting starts at ten.\n\n--- Original Message ---\n"
            "Your old verification code is 482913."
        )
        self.assertEqual(extract_preview(plain), "The meeting starts at ten.")

    def test_entities_and_zero_width_characters(self):
        html = "<p>Tom &amp; Jerry\u200b confirmed&nbsp;delivery.</p>"
        self.assertEqual(
            extract_preview(html_body=html),
            "Tom & Jerry confirmed delivery.",
        )

    def test_regression_walmart_html_only_message(self):
        path = DATA / "walmart_shipping_regression.eml"
        message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        preview = extract_message_preview(message)
        self.assertEqual(
            str(message["Subject"]),
            "Your order is on the move",
        )
        self.assertEqual(
            str(message["From"]),
            "Example Store <notices@example.test>",
        )
        self.assertEqual(
            preview,
            "Good news! Items from your order have been processed and will be on their way soon.",
        )
        self.assertNotRegex(preview, r"padding:|margin:|@media|!important")

    def test_regression_capital_one_skips_language_boilerplate(self):
        message = BytesParser(policy=policy.default).parsebytes(
            (DATA / "capital_one_payment_regression.eml").read_bytes()
        )
        preview = extract_message_preview(message)
        self.assertTrue(preview.startswith("Thanks for your payment of $100.00."), preview)
        self.assertNotIn("Défilez vers le bas", preview)

    def test_regression_amazon_skips_navigation_and_urls(self):
        message = BytesParser(policy=policy.default).parsebytes(
            (DATA / "amazon_shipped_regression.eml").read_bytes()
        )
        preview = extract_message_preview(message)
        self.assertTrue(preview.startswith("Your package was shipped!"), preview)
        self.assertNotIn("https://", preview)
        self.assertNotIn("Your Orders", preview)

    def test_regression_roku_does_not_use_shop_now_preheader(self):
        message = BytesParser(policy=policy.default).parsebytes(
            (DATA / "roku_signin_regression.eml").read_bytes()
        )
        preview = extract_message_preview(message)
        self.assertTrue(preview.startswith("Signing in? Are you trying to sign in"), preview)
        self.assertNotEqual(preview, "Shop Now")


if __name__ == "__main__":
    unittest.main()
