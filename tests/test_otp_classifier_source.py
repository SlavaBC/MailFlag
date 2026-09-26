#!/usr/bin/env python3

import unittest

from mailflag import classify_otp, extract_code


class OtpClassifierRegressionTests(unittest.TestCase):
    def test_fresh_positive_variations(self):
        cases = [
            ("Secure login", "Enter 701204 to continue. Session 998812.", "701204"),
            ("Код входа", "Код входа: 000042. Запрос № 781245.", "000042"),
            ("New authentication code", "Previous code 111222 expired. New code: 333444.", "333444"),
            ("Device approval", "Authorization code — 8571. Device model A2026.", "8571"),
            ("Two factor", "Use this 2FA code: 76543210. Attempt 1 of 3.", "76543210"),
            ("Account recovery", "Account recovery code\n540091\nValid for five minutes.", "540091"),
            ("HTML", "<p>Your security code is <strong>086204</strong>.</p>", "086204"),
            ("Подтверждение", "Введите 9150 для подтверждения входа. Заказ 661920 не является кодом.", "9150"),
            ("Replacement", "Do not use old code 120045; replacement code: 907311.", "907311"),
            ("Sign in", "440028 is your one-time code.", "440028"),
            ("Current code", "Earlier code 880011 is invalid. Current verification code 220099.", "220099"),
            ("Login", "Login code: (314159). IP 10.20.30.40.", "314159"),
            ("Retry succeeded", "The first request failed. New code: 271828.", "271828"),
        ]
        for subject, body, expected in cases:
            with self.subTest(subject=subject, body=body):
                self.assertEqual(extract_code(subject, body), expected)

    def test_fresh_negative_variations(self):
        cases = [
            ("Authentication outage", "Authentication failed with error code 620401."),
            ("Код просрочен", "Код входа 774411 истёк. Новый код не создавался."),
            ("Promotion", "Use promo code DEAL2027 for 25% off."),
            ("Shipping", "Order 410092, tracking 77120499, postal code 90210."),
            ("Release", "Security update version 5.12.2026 build 880044."),
            ("Support", "Verification support ticket 550091 is now closed."),
            ("Телефон", "Подтвердите номер профиля +7 916 555 0199."),
            ("Cancelled", "Do not enter 840091. The login request was cancelled."),
            ("Receipt", "Invoice 992014 totals $48.20 and is due at 18:30."),
            ("Security training", "In 2024, 72% of login attacks reused passwords."),
            ("Quoted old mail", "No new code has been requested.\n> Verification code: 630081\n> Expired."),
            ("Product", "Product code 440012 and serial 99182730 were registered."),
        ]
        for subject, body in cases:
            with self.subTest(subject=subject, body=body):
                result = classify_otp(subject, body)
                self.assertEqual(result["type"], "NORMAL", result)
                self.assertIsNone(result["code"], result)


if __name__ == "__main__":
    unittest.main()
