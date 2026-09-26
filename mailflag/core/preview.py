"""Provider-, IMAP-, and GUI-independent email preview extraction."""

from __future__ import annotations

from email.message import Message
from html.parser import HTMLParser
import re


ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
SPACE_RE = re.compile(r"[ \t\f\v]+")
CSS_TOKEN_RE = re.compile(
    r"(?:padding\s*:|margin\s*:|font-size\s*:|!important|@media\b|"
    r"border(?:-[a-z]+)?\s*:|display\s*:|<\s*(?:div|table)\b)", re.I,
)
BOILERPLATE_RE = re.compile(
    r"^(?:view (?:this (?:email|message)|email) in (?:your )?browser|"
    r"view in browser|having trouble viewing (?:this|the) email\??|"
    r"trouble viewing\??|unsubscribe|manage (?:your )?preferences|"
    r"privacy policy|email preferences)(?:\s*[|·•-].*)?$", re.I,
)
QUOTE_BOUNDARY_RE = re.compile(
    r"^(?:-{2,}\s*(?:original|forwarded) message\s*-{2,}|"
    r"begin forwarded message:|on .+ wrote:|from:\s+.+)$", re.I,
)
BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "div", "footer",
    "h1", "h2", "h3", "h4", "h5", "h6", "header", "li", "main", "p",
    "section", "table", "td", "th", "tr",
}
IGNORED_TAGS = {"head", "style", "script", "noscript", "template", "svg"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}


def _normalize(value: str | None) -> str:
    value = ZERO_WIDTH_RE.sub("", value or "").replace("\xa0", " ")
    lines = []
    for raw_line in value.replace("\r", "\n").split("\n"):
        line = SPACE_RE.sub(" ", raw_line).strip()
        if not line:
            continue
        if line.startswith(">") or QUOTE_BOUNDARY_RE.match(line):
            break
        lines.append(line)
    return "\n".join(lines)


def _useful_lines(value: str) -> list[str]:
    lines = []
    for line in value.splitlines():
        pieces = [piece.strip() for piece in re.split(r"\s*[|•·]\s*", line)]
        useful = [piece for piece in pieces if piece and not BOILERPLATE_RE.match(piece)]
        lines.extend(useful)
    return lines


def _technical_density(value: str) -> float:
    if not value:
        return 1.0
    tokens = CSS_TOKEN_RE.findall(value)
    return len(tokens) / max(1, len(value.split()))


def _acceptable(value: str) -> bool:
    if len(value) < 8 or sum(ch.isalpha() for ch in value) < 5:
        return False
    if _technical_density(value) >= 0.08:
        return False
    if re.search(r"(?:\{\s*[a-z-]+\s*:|</?[a-z][^>]*>)", value, re.I):
        return False
    return True


def _finish(value: str, limit: int) -> str:
    value = SPACE_RE.sub(" ", value.replace("\n", " ")).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


class _EmailHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._hidden_stack: list[tuple[str, bool, bool]] = []
        self.visible: list[str] = []
        self.preheaders: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attributes = {str(k).lower(): str(v or "") for k, v in attrs}
        if tag in IGNORED_TAGS:
            self._ignored_depth += 1
        marker = " ".join((attributes.get("id", ""), attributes.get("class", ""))).lower()
        style = attributes.get("style", "").replace(" ", "").lower()
        hidden = (
            "hidden" in attributes
            or "display:none" in style
            or "visibility:hidden" in style
            or "max-height:0" in style
            or "opacity:0" in style
            or attributes.get("aria-hidden", "").lower() == "true"
        )
        preheader = "preheader" in marker or "preview" in marker
        parent_hidden = self._hidden_stack[-1][1] if self._hidden_stack else False
        parent_preheader = self._hidden_stack[-1][2] if self._hidden_stack else False
        if tag not in VOID_TAGS:
            self._hidden_stack.append((tag, hidden or parent_hidden, preheader or parent_preheader))
        if tag in BLOCK_TAGS and not hidden and not parent_hidden:
            self.visible.append("\n")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in BLOCK_TAGS and self._ignored_depth == 0:
            self.visible.append("\n")
        for index in range(len(self._hidden_stack) - 1, -1, -1):
            if self._hidden_stack[index][0] == tag:
                del self._hidden_stack[index:]
                break
        if tag in IGNORED_TAGS and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data):
        if self._ignored_depth or not data:
            return
        _tag, hidden, preheader = self._hidden_stack[-1] if self._hidden_stack else ("", False, False)
        if hidden:
            if preheader or _acceptable(_normalize(data)):
                self.preheaders.append(data)
            return
        self.visible.append(data)


def _html_candidates(html_body: str | None) -> tuple[list[str], str]:
    if not html_body:
        return [], ""
    parser = _EmailHTMLParser()
    try:
        parser.feed(html_body)
        parser.close()
    except (ValueError, AssertionError):
        return [], ""
    preheaders = []
    for value in parser.preheaders:
        candidate = " ".join(_useful_lines(_normalize(value)))
        if _acceptable(candidate):
            preheaders.append(candidate)
    visible = "\n".join(_useful_lines(_normalize("".join(parser.visible))))
    return preheaders, visible


def extract_preview(
    plain_body: str | None = None,
    html_body: str | None = None,
    limit: int = 260,
) -> str:
    """Return the best human-readable preview, or an empty string."""
    plain = "\n".join(_useful_lines(_normalize(plain_body)))
    if _acceptable(plain):
        return _finish(plain, limit)

    preheaders, visible = _html_candidates(html_body)
    for candidate in preheaders:
        if _acceptable(candidate):
            return _finish(candidate, limit)
    if _acceptable(visible):
        return _finish(visible, limit)
    return ""


def extract_message_preview(message: Message, limit: int = 260) -> str:
    """Extract preview from a stdlib parsed MIME message."""
    plain_parts: list[str] = []
    html_parts: list[str] = []
    parts = message.walk() if message.is_multipart() else (message,)
    for part in parts:
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        try:
            value = part.get_content()
        except (LookupError, UnicodeError):
            payload = part.get_payload(decode=True) or b""
            value = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        (plain_parts if content_type == "text/plain" else html_parts).append(str(value))
    return extract_preview("\n".join(plain_parts), "\n".join(html_parts), limit)
