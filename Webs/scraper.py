import requests
from cloudscraper import create_scraper
from asyncio import to_thread
from loguru import logger

# Optional: curl_cffi impersonates a real Chrome TLS/HTTP2 fingerprint, which gets
# through bot-protection that rejects plain `requests`/cloudscraper. It's only used
# as a fallback when the normal path is blocked, and only if it's installed.
try:
  from curl_cffi import requests as _curl
except Exception:  # pragma: no cover - optional dependency
  _curl = None

# Without a timeout, a slow/dead site leaves the underlying request hanging
# forever, which blocks whichever thread picked it up from asyncio's shared
# default thread-pool (the same pool Tools/img2pdf.py's image downloads use
# via to_thread) - enough of those and the whole bot silently stops being
# able to download anything, with no error, no crash, just a growing queue.
DEFAULT_TIMEOUT = 20  # seconds

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

_BLOCKED = (403, 429, 503)


def looks_blocked(status: int, text: str = "") -> bool:
  """True for a bot-protection / Cloudflare challenge page (as opposed to a real 404 etc.)."""
  if status in _BLOCKED:
    return True
  head = (text or "")[:3000].lower()
  return "just a moment" in head or "cf-chl" in head or "challenge-platform" in head


class Scraper:
  def __init__(self):
    self.scraper = create_scraper()
    # Persistent session for the non-Cloudflare path too, so repeated
    # requests to the same site (very common - a chapter list fetch is
    # followed by dozens of image requests) reuse the TCP/TLS connection
    # instead of paying a fresh handshake every single call.
    self.session = requests.Session()
    # Image downloads (Tools/cworker.py) read `webs.cs`; sites that need the
    # Cloudflare-aware client for their images set this to True.
    self.cs = False
    # Set to "chrome" by sources behind Cloudflare Turnstile: every request (and, via
    # `cs`, every image download) then goes through curl_cffi with a real Chrome fingerprint.
    self.impersonate = None

  # ----------------------------------------------------------------------- #
  def _curl_request(self, method, url, **kwargs):
    kwargs.pop("allow_redirects", None)
    return _curl.request(method, url, impersonate="chrome", allow_redirects=True, **kwargs)

  async def _request(self, method, url, rjson=None, cs=None, *args, **kwargs):
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    if self.impersonate and _curl is None:
      logger.error("This source needs curl_cffi (Cloudflare Turnstile) but it is not installed: "
                   "run `pip install curl_cffi` (it is in requirements.txt)")
    if self.impersonate and _curl is not None:
      response = await to_thread(self._curl_request, method, url, **kwargs)
    elif cs:
      response = await to_thread(getattr(self.scraper, method), url, *args, **kwargs)
      # cloudscraper can't beat every protection level. If it got blocked, retry once
      # with a real-Chrome fingerprint (when curl_cffi is installed).
      if _curl is not None and looks_blocked(response.status_code, getattr(response, "text", "")):
        logger.info(f"{method.upper()} {url}: blocked ({response.status_code}), retrying with curl_cffi")
        try:
          alt = await to_thread(self._curl_request, method, url, **kwargs)
          if alt.status_code == 200:
            response = alt
        except Exception as e:
          logger.warning(f"curl_cffi fallback failed for {url}: {type(e).__name__}: {e}")
    else:
      response = await to_thread(getattr(self.session, method), url, *args, **kwargs)
      response.raise_for_status()

    if response.status_code == 200:
      if rjson:
        try:
          return response.json()
        except ValueError:
          logger.warning(f"{method.upper()} {url}: 200 but body is not JSON (first 120 chars: {response.text[:120]!r})")
          return None
      return response.text

    logger.warning(f"{method.upper()} {url}: HTTP {response.status_code}")
    return None

  async def get(self, url, rjson=None, cs=None, *args, **kwargs):
    return await self._request("get", url, rjson, cs, *args, **kwargs)

  async def post(self, url, rjson=None, cs=None, *args, **kwargs):
    return await self._request("post", url, rjson, cs, *args, **kwargs)
