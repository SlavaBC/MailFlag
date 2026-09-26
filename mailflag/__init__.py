"""MailFlag package public interfaces."""

from .core.otp import classify_otp, extract_code

__all__ = ["classify_otp", "extract_code"]
