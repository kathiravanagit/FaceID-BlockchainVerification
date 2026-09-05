import os
import re
import sys
import json
import time
import hashlib
import requests
from pathlib import Path
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup


SOCIAL_DOMAINS = {
    "facebook.com", "fb.com", "fb.watch",
    "twitter.com", "x.com",
    "instagram.com",
    "tiktok.com",
    "linkedin.com",
    "snapchat.com",
    "pinterest.com",
    "reddit.com",
    "tumblr.com",
    "flickr.com",
    "youtube.com",
    "threads.net",
    "mastodon.social",
    "bsky.app",
}


def _is_post_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path = parsed.path or ""
        if "instagram.com" in host and ("/p/" in path or "/reel/" in path):
            return True
        if ("twitter.com" in host or host == "x.com" or host.endswith(".x.com")) and "/status/" in path:
            return True
        if "tiktok.com" in host and "/video/" in path:
            return True
        if "youtube.com" in host and ("/watch" in path or "/shorts/" in path):
            return True
        if "reddit.com" in host and "/comments/" in path:
            return True
        if "facebook.com" in host and any(k in path for k in ("/posts/", "/videos/", "/reel/", "/photo", "/watch")):
            return True
        if "pinterest." in host and "/pin/" in path:
            return True
        if "threads." in host and "/post/" in path:
            return True
        if "linkedin.com" in host and ("/posts/" in path or "/feed/" in path):
            return True
        return False
    except Exception:
        return False


def _is_reachable(url: str) -> bool:
    try:
        resp = requests.head(url, headers=HEADERS, timeout=10, allow_redirects=True)
        if resp.status_code in (403, 429):
            return True
        return 200 <= resp.status_code < 400
    except Exception:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10, stream=True)
            resp.close()
            if resp.status_code in (403, 429):
                return True
            return 200 <= resp.status_code < 400
        except Exception:
            return False


def pick_best_match(matches: list) -> dict | None:
    if not matches:
        return None
    post_urls = [m for m in matches if _is_post_url(m.get("url", ""))]
    candidates = post_urls if post_urls else matches
    for m in candidates:
        if _is_reachable(m.get("url", "")):
            return m
    return candidates[0]

YANDEX_INTERNAL = {"yandex.com", "yandex.net", "ya.ru", "yastatic.net", "passport.yandex.com"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _is_social_url(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
        if any(yd in host for yd in YANDEX_INTERNAL):
            return False
        return any(d in host for d in SOCIAL_DOMAINS)
    except Exception:
        return False


def _detect_platform(domain: str) -> str:
    domain = domain.lower()
    for key in ["facebook", "fb.com", "fb.watch"]:
        if key in domain:
            return "Facebook"
    if domain == "x.com" or domain.endswith(".x.com") or "twitter.com" in domain:
        return "Twitter/X"
    if "instagram" in domain:
        return "Instagram"
    if "tiktok" in domain:
        return "TikTok"
    if "linkedin" in domain:
        return "LinkedIn"
    if "reddit" in domain:
        return "Reddit"
    if "pinterest" in domain:
        return "Pinterest"
    if "youtube" in domain:
        return "YouTube"
    if "flickr" in domain:
        return "Flickr"
    if "tumblr" in domain:
        return "Tumblr"
    if "threads" in domain:
        return "Threads"
    if "mastodon" in domain:
        return "Mastodon"
    if "bsky" in domain:
        return "Bluesky"
    return "Web"


def search_yandex_playwright(image_path: str, max_results: int = 20) -> dict:
    """
    Upload image to Yandex Reverse Image Search using Playwright headless browser.
    Genuine browser-based reverse image search - no API key needed.
    """
    image_path = Path(image_path).resolve()
    if not image_path.is_file():
        return {"matches": [], "engine": "yandex", "error": f"File not found: {image_path}"}

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"matches": [], "engine": "yandex", "error": "Playwright not installed. Run: pip install playwright && playwright install chromium"}

    matches = []
    seen = set()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="en-US",
                viewport={"width": 1280, "height": 720},
            )
            page = context.new_page()

            page.goto("https://yandex.com/images/", timeout=30000)
            page.wait_for_load_state("networkidle", timeout=15000)

            try:
                camera_btn = page.locator("button.input__cbir-button, .input__cbir-button, [data-testid='cbir-button']")
                if camera_btn.count() > 0:
                    camera_btn.first.click()
                    page.wait_for_timeout(1000)
            except Exception:
                pass

            try:
                file_input = page.locator('input[type="file"]')
                if file_input.count() > 0:
                    file_input.first.set_input_files(str(image_path))
                    page.wait_for_timeout(5000)
                else:
                    browser.close()
                    return _yandex_upload_fallback(image_path, max_results)
            except Exception as e:
                browser.close()
                return {"matches": [], "engine": "yandex", "error": f"File upload failed: {e}"}

            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                page.wait_for_timeout(5000)

            page.wait_for_timeout(3000)

            current_url = page.url
            html_content = page.content()

            soup = BeautifulSoup(html_content, "html.parser")

            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                if href.startswith("//"):
                    href = "https:" + href
                elif href.startswith("/"):
                    href = "https://yandex.com" + href

                if "yandex" in href:
                    continue

                if href.startswith("http") and _is_social_url(href) and href not in seen:
                    seen.add(href)
                    domain = urlparse(href).hostname or ""
                    matches.append({
                        "url": href,
                        "platform": _detect_platform(domain),
                        "source": "yandex",
                    })

                if len(matches) >= max_results:
                    break

            for div in soup.find_all(attrs={"data-bem": True}):
                try:
                    bem = json.loads(div["data-bem"])
                    for key, val in bem.items():
                        if isinstance(val, dict):
                            for subkey, subval in val.items():
                                if isinstance(subval, str) and subval.startswith("http"):
                                    if _is_social_url(subval) and subval not in seen:
                                        seen.add(subval)
                                        domain = urlparse(subval).hostname or ""
                                        matches.append({
                                            "url": subval,
                                            "platform": _detect_platform(domain),
                                            "source": "yandex",
                                        })
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue

            for img in soup.find_all("img"):
                src = img.get("src", "") or img.get("data-src", "")
                parent = img.find_parent("a", href=True)
                if parent:
                    href = parent["href"]
                    if href.startswith("//"):
                        href = "https:" + href
                    if _is_social_url(href) and href not in seen:
                        seen.add(href)
                        domain = urlparse(href).hostname or ""
                        matches.append({
                            "url": href,
                            "platform": _detect_platform(domain),
                            "source": "yandex",
                        })

            browser.close()

        return {
            "matches": matches[:max_results],
            "engine": "yandex",
            "error": None,
        }

    except Exception as e:
        return {"matches": [], "engine": "yandex", "error": f"Yandex search failed: {e}"}


def _yandex_upload_fallback(image_path: Path, max_results: int = 20) -> dict:
    """Fallback: upload via requests and parse the HTML response."""
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        session.get("https://yandex.com/images/", timeout=15)
        image_bytes = image_path.read_bytes()
        files = {"upfile": (image_path.name, image_bytes, "image/jpeg")}
        params = {"rpt": "imageview"}

        resp = session.post(
            "https://yandex.com/images/search",
            files=files,
            params=params,
            timeout=30,
            allow_redirects=True,
        )

        soup = BeautifulSoup(resp.text, "html.parser")
        matches = []
        seen = set()

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                href = "https://yandex.com" + href
            if "yandex" not in href and href.startswith("http") and _is_social_url(href) and href not in seen:
                seen.add(href)
                domain = urlparse(href).hostname or ""
                matches.append({"url": href, "platform": _detect_platform(domain), "source": "yandex"})

        return {"matches": matches[:max_results], "engine": "yandex", "error": None}

    except Exception as e:
        return {"matches": [], "engine": "yandex", "error": f"Yandex fallback failed: {e}"}


def _upload_to_free_host(image_path: Path) -> str:
    """Upload image to free hosting service and return public URL."""
    try:
        with open(image_path, "rb") as f:
            resp = requests.post(
                "https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload"},
                files={"fileToUpload": f},
                timeout=30,
            )
        if resp.status_code == 200 and resp.text.startswith("http"):
            return resp.text.strip()
    except Exception:
        pass

    try:
        with open(image_path, "rb") as f:
            resp = requests.post(
                "https://telegra.ph/upload",
                files={"file": ("image.jpg", f, "image/jpeg")},
                timeout=15,
            )
        if resp.status_code == 200:
            data = resp.json()
            if data and len(data) > 0:
                return "https://telegra.ph" + data[0].get("src", "")
    except Exception:
        pass

    return ""


def search_serpapi(image_path: str, api_key: str, max_results: int = 10) -> dict:
    if not api_key:
        return {"matches": [], "engine": "serpapi", "error": "No SerpAPI key provided"}

    image_path = Path(image_path).resolve()
    if not image_path.is_file():
        return {"matches": [], "engine": "serpapi", "error": f"File not found: {image_path}"}

    try:
        image_url = _upload_to_free_host(image_path)
        if not image_url:
            return {"matches": [], "engine": "serpapi", "error": "Failed to upload image to hosting service"}

        params = {
            "engine": "google_lens",
            "api_key": api_key,
            "url": image_url,
        }

        resp = requests.get("https://serpapi.com/search.json", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        matches = []
        seen = set()

        for match in data.get("visual_matches", []):
            url = match.get("link", "")
            if url and url not in seen:
                seen.add(url)
                domain = urlparse(url).hostname or ""
                matches.append({
                    "url": url,
                    "platform": _detect_platform(domain),
                    "title": match.get("title", ""),
                    "source": "serpapi",
                })

        for result in data.get("text_results", []):
            url = result.get("link", "")
            if url and url not in seen:
                seen.add(url)
                domain = urlparse(url).hostname or ""
                matches.append({
                    "url": url,
                    "platform": _detect_platform(domain),
                    "title": result.get("title", ""),
                    "source": "serpapi",
                })

        return {"matches": matches[:max_results], "engine": "serpapi", "error": None}

    except Exception as e:
        return {"matches": [], "engine": "serpapi", "error": f"SerpAPI search failed: {e}"}


def reverse_image_search(image_path: str, serpapi_key: str = None, max_results: int = 20) -> dict:
    all_matches = []
    engines_tried = []

    yandex_result = search_yandex_playwright(image_path, max_results)
    engines_tried.append("yandex")
    if yandex_result["error"]:
        print(f"  [!] Yandex: {yandex_result['error']}")
    all_matches.extend(yandex_result["matches"])

    if serpapi_key:
        serp_result = search_serpapi(image_path, serpapi_key, max_results)
        engines_tried.append("serpapi")
        if serp_result["error"]:
            print(f"  [!] SerpAPI: {serp_result['error']}")
        all_matches.extend(serp_result["matches"])

    seen = set()
    unique = []
    for m in all_matches:
        if m["url"] not in seen:
            seen.add(m["url"])
            unique.append(m)

    return {
        "matches": unique,
        "engines": engines_tried,
        "total_raw": len(all_matches),
        "total_unique": len(unique),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python reverse_search.py <image_path> [serpapi_key]")
        sys.exit(1)
    key = sys.argv[2] if len(sys.argv) > 2 else os.getenv("SERPAPI_KEY")
    result = reverse_image_search(sys.argv[1], serpapi_key=key)
    print(json.dumps(result, indent=2))
