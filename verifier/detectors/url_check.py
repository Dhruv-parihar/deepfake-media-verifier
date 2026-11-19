import ipaddress
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from verifier.models import DetectorResult

NAME = "Source and URL checks"
SHORTENERS = {
    "bit.ly",
    "t.co",
    "tinyurl.com",
    "goo.gl",
    "ow.ly",
    "is.gd",
    "buff.ly",
    "cutt.ly",
    "rebrand.ly",
    "shorturl.at",
    "tiny.cc",
    "lnkd.in",
}
RISKY_TLDS = {"tk", "ml", "ga", "cf", "gq", "top", "click", "zip", "mov"}
USER_AGENT = "deepfake-media-verifier/1.0 (educational project)"
MAX_BYTES = 2_000_000


def inspect_host(result, parsed, host):
    if parsed.scheme == "http":
        result.add("medium", "Connection is not encrypted", "The link uses http, so content can be altered in transit.")
    if "@" in parsed.netloc:
        result.add("high", "Credentials before the hostname", "Text before '@' can disguise the real destination of a link.")
    try:
        ipaddress.ip_address(host)
        result.add("medium", "Link points to a raw IP address", "Reputable outlets use domain names, not bare IP addresses.")
    except ValueError:
        pass
    if "xn--" in host:
        result.add("medium", "Internationalized (punycode) domain", "Look-alike characters can imitate a trusted site.")
    if host in SHORTENERS:
        result.add("low", "URL shortener", "The final destination is hidden. Expand the link before trusting it.")
    labels = host.split(".")
    if len(labels) > 4:
        result.add("low", "Many subdomains", f"'{host}' has {len(labels)} labels, a pattern used to imitate other sites.")
    if labels[-1] in RISKY_TLDS:
        result.add("low", f"Domain ends in .{labels[-1]}", "This top-level domain is frequently abused for throwaway sites.")
    if len(parsed.geturl()) > 200:
        result.add("low", "Very long URL", "Long links can hide tracking or redirect parameters.")


def first_meta(soup, *selectors):
    for attribute, value in selectors:
        tag = soup.find("meta", attrs={attribute: value})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


def inspect_page(result, url, host):
    session = requests.Session()
    session.max_redirects = 5
    try:
        response = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=15, stream=True)
    except requests.exceptions.SSLError:
        result.add("high", "TLS certificate could not be verified", "The site's HTTPS certificate failed validation.")
        return
    except requests.exceptions.RequestException as exc:
        result.add("low", "Page could not be fetched", str(exc)[:200])
        return

    try:
        final_host = (urlparse(response.url).hostname or "").lower()
        result.data["final_url"] = response.url
        result.data["status_code"] = response.status_code
        result.data["redirects"] = len(response.history)

        if final_host and final_host != host:
            result.add("medium", "Redirects to a different domain", f"{host} sends visitors to {final_host}.")
        if len(response.history) >= 3:
            result.add("low", "Long redirect chain", f"{len(response.history)} redirects before the final page.")
        if response.status_code >= 400:
            result.add("low", f"Server returned HTTP {response.status_code}", "The page may be removed or blocking automated checks.")

        content_type = response.headers.get("Content-Type", "")
        result.data["content_type"] = content_type
        if "html" not in content_type.lower():
            result.add("info", "Not an HTML page", f"Content type is '{content_type or 'unknown'}', so page details were not parsed.")
            return

        raw = response.raw.read(MAX_BYTES, decode_content=True)
    finally:
        response.close()

    soup = BeautifulSoup(raw, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else None
    author = first_meta(soup, ("name", "author"), ("property", "article:author"))
    published = first_meta(
        soup,
        ("property", "article:published_time"),
        ("name", "date"),
        ("itemprop", "datePublished"),
    )
    if not published:
        time_tag = soup.find("time", attrs={"datetime": True})
        published = time_tag["datetime"] if time_tag else None
    canonical_tag = soup.find("link", rel="canonical")
    canonical = canonical_tag.get("href") if canonical_tag else None

    media_links = []
    for tag in soup.find_all(["video", "source", "iframe"]):
        source = tag.get("src")
        if source:
            media_links.append(source)
    og_video = first_meta(soup, ("property", "og:video"))
    if og_video:
        media_links.append(og_video)

    result.data.update(
        {
            "title": title,
            "description": first_meta(soup, ("name", "description"), ("property", "og:description")),
            "site_name": first_meta(soup, ("property", "og:site_name")),
            "author": author,
            "published": published,
            "canonical": canonical,
            "image_count": len(soup.find_all("img")),
            "embedded_media": media_links[:10],
        }
    )

    if not author:
        result.add("low", "No named author", "Credible reporting normally names who wrote it.")
    if not published:
        result.add("low", "No publication date found", "Without a date, old material can be passed off as new.")
    if canonical:
        canonical_host = (urlparse(canonical).hostname or "").lower()
        if canonical_host and canonical_host != final_host:
            result.add(
                "medium",
                "Canonical link points to another site",
                f"The page says the original lives on {canonical_host}, so this may be copied content.",
            )


def analyze(url, fetch=True):
    result = DetectorResult(NAME)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host:
        result.status = "error"
        result.note = "Provide a full http(s) URL such as https://example.com/article"
        return result
    result.data["host"] = host
    inspect_host(result, parsed, host)
    if fetch:
        inspect_page(result, url, host)
    return result
