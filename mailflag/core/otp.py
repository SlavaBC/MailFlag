"""Local deterministic OTP classification, independent of GUI and providers."""

from dataclasses import dataclass
from enum import Enum
import html
import re


class MessageType(str, Enum):
    OTP = "OTP"
    NORMAL = "NORMAL"


@dataclass(frozen=True)
class ClassificationResult:
    type: MessageType
    code: str | None
    confidence: int
    reason: str


# Public compatibility threshold used by the current application and tests.
MIN_CONFIDENCE = 5


CODE_RE = re.compile(r"(?<!\d)(\d{4,8})(?!\d)")
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")

# OTP classification deliberately remains local and deterministic.  Positive
# phrases identify the purpose of a number; negative phrases prevent ordinary
# identifiers (tickets, versions, expired codes, and so on) from becoming OTPs.
OTP_POSITIVE_PHRASES = (
    "verification code", "security code", "sign-in code", "signin code",
    "login code", "authentication code", "authorization code", "2fa code",
    "one-time code", "one time code", "one-time passcode", "otp",
    "recovery code", "account recovery code",
    "код подтверждения", "проверочный код", "код безопасности",
    "код входа", "код авторизации", "код восстановления", "одноразовый код", "ваш код",
    "your code", "enter", "use code", "use this", "введите",
    "используйте код", "подтвердите аккаунт кодом",
)

OTP_CURRENT_PHRASES = (
    "new code", "latest code", "current code", "replacement code",
    "new service reply", "новый код", "последний код", "текущий код",
    "код обновлён", "используйте новый код",
)

OTP_INVALID_PHRASES = (
    "expired", "invalid", "no longer valid", "do not use", "don't use",
    "must not be entered", "cancelled", "canceled", "earlier code",
    "old code", "previous code", "not the code", "do not enter",
    "истёк", "истек", "недействител", "не действует", "не используйте",
    "не вводите", "отменён", "отменен", "старый код", "предыдущий код",
)

OTP_GLOBAL_NEGATIVE_PHRASES = (
    "no code was generated", "no code generated", "code was not generated",
    "no new code has been requested", "request failed",
    "код не был сгенерирован", "код не создан", "новый код ещё не запрошен",
    "новый код еще не запрошен", "ничего подтверждать не требуется",
    "no action or verification is required",
)

OTP_IDENTIFIER_LABELS = (
    "error code", "status code", "promo code", "promotional code",
    "referral code", "product code", "postal code", "support case",
    "support request", "ticket", "case", "order", "invoice", "tracking",
    "serial", "version", "build", "batch", "reference", "ref ",
    "transaction id", "operation number", "operation id", "номер обращения", "номер заявки",
    "код ошибки", "код статуса", "промокод", "реферальный код",
    "код продукта", "почтовый индекс", "индекс", "заказ", "счёт", "счет",
    "трек-номер", "серия документа", "версия", "сборка", "номер операции",
    "id операции", "locker", "ячейка", "zip",
)

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
PHONE_RE = re.compile(
    r"(?<!\w)(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)|\d{2,4})[\s.-]\d{3}[\s.-]\d{4}(?!\w)",
    re.IGNORECASE,
)
DATE_RE = re.compile(r"\b(?:19|20)\d{2}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])\b")
TIME_RE = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b")
DECIMAL_VERSION_RE = re.compile(r"\b\d+(?:\.\d+){2,}\b")
def _otp_plain_text(value):
    """Turn HTML-ish mail content into readable text without joining words."""
    value = html.unescape(value or "").replace("\xa0", " ")
    value = re.sub(r"(?i)<(?:br|/p|/div|/tr|/li|/h[1-6])\b[^>]*>", "\n", value)
    value = TAG_RE.sub(" ", value)
    return "\n".join(SPACE_RE.sub(" ", line).strip() for line in value.splitlines())


def _visible_unquoted_text(value):
    """Compatibility helper retained for callers from MailFlag 0.12.1."""
    return _otp_plain_text(value)


def _phrase_positions(text, phrases):
    positions = []
    for phrase in phrases:
        start = 0
        while True:
            pos = text.find(phrase, start)
            if pos < 0:
                break
            positions.append((pos, phrase))
            start = pos + len(phrase)
    return positions


def _inside_any_span(start, end, spans):
    return any(start < span_end and end > span_start for span_start, span_end in spans)


def _distance_to_phrase(start, end, phrase_start, phrase):
    phrase_end = phrase_start + len(phrase)
    if start < phrase_end and end > phrase_start:
        return 0
    return min(abs(start - phrase_end), abs(end - phrase_start))


def classify_otp(subject, body):
    """Classify an email and explain which numeric candidate, if any, won."""
    clean_subject = _otp_plain_text(subject)
    clean_body = _otp_plain_text(body)
    combined = f"{clean_subject}\n{clean_body}"
    lowered = combined.lower()

    current_positions = _phrase_positions(lowered, OTP_CURRENT_PHRASES)
    global_negative_positions = _phrase_positions(lowered, OTP_GLOBAL_NEGATIVE_PHRASES)
    has_later_current_code = any(
        current_pos > negative_pos + len(negative_phrase)
        for negative_pos, negative_phrase in global_negative_positions
        for current_pos, _current_phrase in current_positions
    )
    if global_negative_positions and not has_later_current_code:
        return {
            "type": "NORMAL", "code": None, "confidence": 0,
            "reason": "global_negative_context",
        }

    positive_positions = _phrase_positions(lowered, OTP_POSITIVE_PHRASES)
    if not positive_positions and not current_positions:
        return {
            "type": "NORMAL", "code": None, "confidence": 0,
            "reason": "no_otp_language",
        }

    excluded_spans = [m.span() for pattern in (URL_RE, PHONE_RE, DATE_RE, TIME_RE, DECIMAL_VERSION_RE) for m in pattern.finditer(combined)]
    subject_end = len(clean_subject)
    scored = []

    for match in CODE_RE.finditer(combined):
        start, end = match.span()
        code = match.group(1)
        reasons = []
        score = 0

        # Embedded alphanumeric fragments such as FRIEND2026 are identifiers.
        before = combined[start - 1] if start else ""
        after = combined[end] if end < len(combined) else ""
        if ((before and (before.isalnum() or before == "_"))
                or (after and (after.isalnum() or after == "_"))
                or _inside_any_span(start, end, excluded_spans)):
            scored.append((score - 20, start, code, ["structured_identifier"]))
            continue

        left = lowered[max(0, start - 90):start]
        right = lowered[end:min(len(lowered), end + 90)]
        local = lowered[max(0, start - 90):min(len(lowered), end + 90)]
        clause_start = max(
            lowered.rfind(mark, 0, start) for mark in (".", "!", "?", ";", "\n")
        ) + 1
        following_boundaries = [
            pos for mark in (".", "!", "?", ";", "\n")
            if (pos := lowered.find(mark, end)) >= 0
        ]
        clause_end = min(following_boundaries) if following_boundaries else len(lowered)
        clause = lowered[clause_start:clause_end]
        clause_left = lowered[clause_start:start]
        line_start = combined.rfind("\n", 0, start) + 1
        line = combined[line_start:combined.find("\n", end) if combined.find("\n", end) >= 0 else len(combined)]

        nearest_positive = min(
            (_distance_to_phrase(start, end, pos, phrase), phrase)
            for pos, phrase in positive_positions
        ) if positive_positions else (10**9, "")
        if nearest_positive[0] <= 25:
            score += 7
            reasons.append(f"near:{nearest_positive[1]}")
        elif nearest_positive[0] <= 90:
            score += 3
            reasons.append(f"context:{nearest_positive[1]}")

        nearest_current = min(
            (_distance_to_phrase(start, end, pos, phrase), phrase)
            for pos, phrase in current_positions
        ) if current_positions else (10**9, "")
        if nearest_current[0] <= 90:
            score += 8
            reasons.append(f"current:{nearest_current[1]}")

        if re.search(r"(?:enter|use|введите|используйте)[^\n;.!?]{0,40}$", clause_left):
            score += 5
            reasons.append("action_before_code")
        if re.search(r"^(?:\s|[:—–-]){0,8}(?:is\s+)?(?:your\s+)?(?:one-time\s+)?code\b", right):
            score += 3
            reasons.append("code_before_label")

        invalid_hits = [phrase for phrase in OTP_INVALID_PHRASES if phrase in clause]
        if invalid_hits:
            score -= 14
            reasons.append(f"invalid:{invalid_hits[0]}")

        # Identifier labels normally occur shortly before their value.  Keep
        # the range tight so an order number elsewhere cannot suppress an OTP.
        identifier_left = lowered[max(0, start - 35):start]
        identifier_hits = [label for label in OTP_IDENTIFIER_LABELS if label in identifier_left]
        if identifier_hits:
            score -= 12
            reasons.append(f"identifier:{identifier_hits[-1]}")

        if line.lstrip().startswith(">"):
            score -= 5
            reasons.append("quoted_history")
        if start <= subject_end:
            score += 1
            reasons.append("subject")

        scored.append((score, start, code, reasons))

    if not scored:
        return {
            "type": "NORMAL", "code": None, "confidence": 0,
            "reason": "no_numeric_candidate",
        }

    scored.sort(key=lambda item: (-item[0], item[1]))
    best = scored[0]
    if best[0] < 5:
        return {
            "type": "NORMAL", "code": None, "confidence": best[0],
            "reason": "no_confident_candidate", "candidates": scored,
        }

    return {
        "type": "OTP", "code": best[2], "confidence": best[0],
        "reason": ",".join(best[3]) or "otp_context", "candidates": scored,
    }


def extract_code(subject, body):
    """Backward-compatible API used by the existing popup code."""
    result = classify_otp(subject, body)
    return result["code"] if result["type"] == "OTP" else None

# Compatibility API retained for MailFlag 0.12.1 callers.
def confidence(subject, body):
    result = classify_otp(subject, body)
    if result["type"] == "OTP":
        return result["confidence"], result["code"]
    candidates = result.get("candidates", ())
    if candidates:
        best = candidates[0]
        return best[0], best[2]
    return result["confidence"], None


def classify(subject, body):
    result = classify_otp(subject, body)
    return ClassificationResult(
        type=MessageType(result["type"]),
        code=result["code"],
        confidence=result["confidence"],
        reason=result["reason"],
    )
