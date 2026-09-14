"""Bounded public HTTPS retrieval and deterministic text selection for Skill Watch."""

from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
import time
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlsplit

MAX_BYTES = 1_000_000
MAX_TEXT = 60_000
TIMEOUT = 15


class WatchError(Exception):
    """An input, retrieval, or baseline error that must not look like no change."""


def validate_url(url):
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.port in (None, 443)
            and not parsed.username
            and not parsed.password
            and not any(ord(char) < 33 or ord(char) > 126 for char in url)
            and "\\" not in url
        )
    except ValueError as error:
        raise WatchError("Invalid source URL") from error
    if not valid:
        raise WatchError("Sources require an ASCII HTTPS URL on port 443 without credentials")
    return parsed


class PublicHTTPS(http.client.HTTPSConnection):
    def connect(self):
        addresses = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
        if not addresses or any(
            not ipaddress.ip_address(address[4][0]).is_global for address in addresses
        ):
            raise WatchError("Source resolves to a non-public address")
        # Connect to a checked address, not a second DNS lookup of the hostname.
        # A dual-stack host can return an unreachable address first, so try each
        # public result while retaining the original hostname for TLS SNI.
        last_error = None
        for address in addresses:
            raw = None
            try:
                raw = socket.create_connection((address[4][0], self.port), timeout=self.timeout)
                self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
                return
            except OSError as error:
                last_error = error
                if raw is not None:
                    raw.close()
        if last_error is not None:
            raise last_error


class RefreshTarget(HTMLParser):
    def __init__(self):
        super().__init__()
        self.target = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "meta" and (attributes.get("http-equiv") or "").lower() == "refresh":
            match = re.fullmatch(
                r"\s*\d+\s*;\s*url\s*=\s*(.+)", attributes.get("content") or "", re.I
            )
            if match:
                if self.target is not None:
                    raise WatchError("Ambiguous HTML refresh destinations")
                self.target = match[1].strip(" \"'")


def fetch(url):
    current = urldefrag(url)[0]
    deadline = time.monotonic() + TIMEOUT
    for _ in range(4):
        parsed = validate_url(current)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise WatchError("Source request timed out")
        connection = PublicHTTPS(
            parsed.hostname, port=443, timeout=remaining, context=ssl.create_default_context()
        )
        try:
            target = parsed.path or "/"
            if parsed.query:
                target += "?" + parsed.query
            connection.request(
                "GET", target, headers={"User-Agent": "Maintainer-Skills-Lab-Skill-Watch/0.1"}
            )
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location:
                    raise WatchError("Redirect has no destination")
                current = urldefrag(urljoin(current, location))[0]
                continue
            if response.status != 200:
                raise WatchError(f"Source returned HTTP {response.status}")
            media_type = response.getheader("Content-Type", "").split(";", 1)[0].strip()
            if media_type not in ("text/html", "text/plain", "text/markdown"):
                raise WatchError(f"Unsupported content type: {media_type or 'missing'}")
            if response.getheader("Content-Encoding", "identity") != "identity":
                raise WatchError("Compressed responses are unsupported")
            chunks, size = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise WatchError("Source response timed out")
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(16_384, MAX_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_BYTES:
                    raise WatchError("Source exceeds the 1 MB response limit")
            # read1() can return EOF without raising for an unsatisfied Content-Length.
            if response.length is not None and response.length > 0:
                raise WatchError("Source response ended before Content-Length was satisfied")
            encoding = response.headers.get_content_charset() or "utf-8"
            content = b"".join(chunks).decode(encoding)
            if media_type == "text/html":
                refresh = RefreshTarget()
                refresh.feed(content)
                if refresh.target is not None:
                    current = urldefrag(urljoin(current, refresh.target))[0]
                    continue
            return content, media_type, current
        except (OSError, http.client.HTTPException, UnicodeError, LookupError) as error:
            raise WatchError(f"Source retrieval failed ({type(error).__name__})") from error
        finally:
            connection.close()
    raise WatchError("Source exceeded the redirect limit")


class PageText(HTMLParser):
    OMIT = {"script", "style", "template", "head", "nav", "header", "footer"}
    BLOCK = {"p", "div", "section", "article", "li", "tr", "br", "pre", "h1", "h2", "h3", "h4"}
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.pieces = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        omit = (
            tag in self.OMIT
            or "hidden" in attributes
            or attributes.get("aria-hidden") == "true"
            or any(item[1] for item in self.stack)
        )
        if not omit and tag in self.BLOCK:
            self.pieces.append("\n")
        if tag not in self.VOID:
            if len(self.stack) >= 256:
                raise WatchError("HTML nesting limit exceeded")
            self.stack.append((tag, omit))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in self.BLOCK and not any(item[1] for item in self.stack):
            self.pieces.append("\n")
        for position in range(len(self.stack) - 1, -1, -1):
            if self.stack[position][0] == tag:
                del self.stack[position:]
                break

    def handle_data(self, data):
        if not any(item[1] for item in self.stack):
            if not any(item[0] == "pre" for item in self.stack):
                data = re.sub(r"\s+", " ", data)
            self.pieces.append(data)


def select_text(content, media_type, start="", end=""):
    if media_type == "text/html":
        parser = PageText()
        parser.feed(content)
        parser.close()
        content = "".join(parser.pieces)
    text = "\n".join(line.rstrip() for line in content.replace("\r\n", "\n").splitlines())
    text = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", text).strip()
    if start:
        if text.count(start) != 1:
            raise WatchError("Start marker must occur exactly once in extracted text")
        text = text[text.index(start) :]
    if end:
        if text.count(end) != 1:
            raise WatchError("End marker must occur exactly once after the start marker")
        text = text[: text.index(end)]
    text = text.strip()
    if not text:
        raise WatchError("Selected source text is empty")
    if len(text) > MAX_TEXT:
        raise WatchError("Selected text exceeds 60,000 characters; narrow it with markers")
    return text
