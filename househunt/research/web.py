"""Read public pages with bounded downloads, redirects and DNS-pinned connections."""
from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup


def canonical_url(raw: str) -> str:
    try:
        p = urlsplit(raw.strip())
        host = (p.hostname or "").lower().rstrip(".")
        if (p.scheme not in ("http", "https") or not host or "." not in host
                or p.username or p.password or p.port not in (None, 80, 443)
                or host.endswith((".local", ".internal", ".localhost"))
                or any(ord(c) < 33 for c in raw)):
            return ""
        try:
            if not ipaddress.ip_address(host).is_global:
                return ""
        except ValueError:
            pass
        query = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith("utm_")
                 and k.lower() not in ("gclid", "fbclid")]
        return urlunsplit((p.scheme, p.netloc.lower(), p.path or "/", urlencode(query), ""))
    except ValueError:
        return ""


def host(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.")


@dataclass
class Page:
    url: str
    title: str
    text: str
    links: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)


def fetch_page(url: str) -> Page | None:
    """No cookies, auth, JS or CAPTCHA bypass. Private/reserved addresses are refused."""
    try:
        for _ in range(4):
            url = canonical_url(url)
            if not url:
                return None
            p = urlsplit(url)
            port = p.port or (443 if p.scheme == "https" else 80)
            ips = {x[4][0] for x in socket.getaddrinfo(p.hostname, port, type=socket.SOCK_STREAM)}
            if not ips or not all(ipaddress.ip_address(ip).is_global for ip in ips):
                return None
            # Connect to a checked IP, preserving hostname for TLS and HTTP Host.
            # This avoids a second DNS lookup/rebinding between validation and connect.
            sock = socket.create_connection((sorted(ips)[0], port), timeout=12)
            try:
                if p.scheme == "https":
                    sock = ssl.create_default_context().wrap_socket(sock, server_hostname=p.hostname)
                connection = http.client.HTTPConnection(p.hostname, port, timeout=12)
                connection.sock = sock
                connection.request("GET", urlunsplit(("", "", p.path, p.query, "")), headers={
                    "User-Agent": "KeyHunt/0.1 (public rental research)", "Accept": "text/html", "Accept-Encoding": "identity"})
                response = connection.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.getheader("Location", ""))
                    continue
                if response.status != 200 or "html" not in response.getheader("Content-Type", ""):
                    return None
                data = response.read(2_000_001)
                if len(data) > 2_000_000:
                    return None
                soup = BeautifulSoup(data, "html.parser")
                title = soup.title.get_text(" ", strip=True) if soup.title else host(url)
                links = list(dict.fromkeys(canonical_url(urljoin(url, a['href'])) for a in soup.select('a[href]')))
                links = [u for u in links if u and re.search(r'property|properties|listing|apartment|rental|homedetails|/view/d|/b/', u, re.I)][:60]
                images = [canonical_url(urljoin(url, m.get('content', ''))) for m in soup.select('meta[property="og:image"]')]
                for el in soup(["script", "style", "noscript", "nav", "footer", "header"]):
                    el.decompose()
                text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:60000]
                if len(text) < 100 or re.search(r"^(Access denied|Just a moment|Verify you are human)", title, re.I):
                    return None
                return Page(url=url, title=title[:250], text=text, links=links, images=[u for u in images if u][:5])
            finally:
                sock.close()
    except (OSError, ValueError, http.client.HTTPException):
        return None
    return None


def exact_quote(quote: str, page: Page) -> bool:
    return len(quote.strip()) >= 3 and re.sub(r"\s+", " ", quote).strip().casefold() in page.text.casefold()
