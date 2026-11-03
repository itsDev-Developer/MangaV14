# Session 9 — TempleToons fix, HentaiFox source

## Shared HTTP layer (`Webs/scraper.py`)
* Every non-200 / non-JSON response is now logged (before, failures were silent -> "nothing found").
* If a Cloudflare-style block (403/429/503/challenge page) is detected, the request is retried once with
  `curl_cffi` (real Chrome fingerprint). Optional: added to requirements.txt; skipped if not installed.
* `Scraper.cs` attribute (image downloads use the Cloudflare-aware client when True).

## TempleToons (`Webs/templetoons.py`)
* Page data is now decoded from each `self.__next_f.push([1,"..."])` as real JSON strings (values split across
  pushes no longer break), plus `__NEXT_DATA__`.
* If the JSON API fails/changes, the comic list is rebuilt from the site's own pages (/, /comics, /series) by link shape.
* `/_next/image?url=...` image tags are decoded; more image-array key names; retries; paid/locked chapters are logged.

## HentaiFox (`Webs/hentaifox.py`, source id `hf`)
* Search (also accepts a gallery id or link), gallery info card, one "Chapter 1" per gallery, full page list.
* Pages come from thumbnails (`1t.jpg` -> `1.jpg`), falling back to load_dir/load_id/load_pages + the reader's `g_th`.
* Registered in `Webs/__init__.py` and `TG/storage.py`; works with search, subscribe, post and download flows.

## Testing
* Offline against synthetic pages only (no network here). On the server run:
  `python -m Webs.diagnose templetoons "solo"` and `python -m Webs.diagnose hentaifox "query"`.

# Session 10
* **Settings persistence (MongoDB)** - root cause of "settings don't survive a deploy": the background DB flusher
  (`Tools/db.flusher`) was never started and nothing flushed on shutdown, so changes stayed in memory and reached
  MongoDB only on /restart. Now: flusher is a startup hook, config changes are written immediately,
  `Bot.stop()` + `atexit` do a final flush, startup logs what was loaded, warns (log + admin DM) when `DB_URL` is
  empty, and `/dbstatus` shows where data lives. Needs `DB_URL` set to a MongoDB string.
* **TempleToons** - site is behind Cloudflare Turnstile; cloudscraper can't pass it. Requests and image downloads
  now use curl_cffi (Chrome fingerprint) (`Scraper.impersonate`, `webs.cs == "chrome"`); catalog falls back to
  sitemap.xml (API -> sitemap -> HTML pages).
* **AllPornComics** (`Webs/allporncomics.py`, sf `apc`) - class-name independent; Madara AJAX + `?style=list` fallbacks.
* `python -m Webs.diagnose allporncomics`.

# Session 11
* **Added admins couldn't use commands** - ~80 handlers used `filters.user(Vars.ADMINS)`, which Pyrogram copies into a
  fixed set when the module loads, so admins added later (via /settings -> Admins) were never in it. All now use the
  live `admin_only` filter. Also: `/search` used a non-existent `client.ADMINS`/`client.SHORTENER`, `/settings`-style
  checks use `is_admin()`, and a newly added admin gets the admin command menu immediately (`Bot.set_admin_menu`).
  (Added admins were also being lost on restart before - fixed by the Session 10 DB flush fix.)
* **/read - online PDF reader** - reply to a PDF with /read (or send one with /read as the caption) -> a link
  `<PUBLIC_URL>/read/<token>` opening a mobile-friendly vertical reader (PDF.js, lazy pages, zoom, remembers your page).
  `Tools/webreader.py` (storage, HTTP, page) + `TG/readcmd.py`; served by the existing web server (`Tools/api.py` routes
  `/read/*`). Streams from disk with Range support, 192-bit tokens, expiry cleanup, brute-force throttle, size/per-user limits.
  Settings: /settings -> 🌐 Web Reader (on/off, Public URL, lifetime, max MB, links per user). Render/Koyeb/Heroku URLs
  are auto-detected; otherwise set `PUBLIC_URL`. Files live in `./webreader/` (ephemeral on most hosts - links die on redeploy).

# Session 12
* **TempleToons images (root cause)** - `media.templetoons.com` answers 403 to any request carrying `Sec-Fetch-*` /
  `Priority` headers (reported and fixed upstream in keiyoushi/extensions-source #20356, Oct 24 2026). curl_cffi's
  Chrome impersonation adds exactly those headers, so the Session-10 fix made page loads work but broke every image.
  Pages still use Chrome impersonation; images now go out with plain headers (UA, Referer, `Accept: image/*`, no Origin).
* **Image downloader client ladder** (`Tools/img2pdf.py`): client kinds `False` (requests), `True` (cloudscraper),
  `"chrome"` (curl_cffi + Chrome headers), `"plain"` (curl_cffi Chrome TLS, no browser metadata). Attempt 1 uses the
  source's choice; a 403 rotates to the other kinds instead of repeating the same failing request. For "chrome" the
  hard-coded User-Agent/Sec-* are no longer sent (a UA that doesn't match the TLS fingerprint is a bot signal). Failure
  messages now say which client was used.
* **AllPornComics** - images/PDF: same client fix (plain headers first, automatic fallbacks) + smarter picture
  detection: trust the reader container; otherwise keep only the biggest same-folder group of images (related-comic
  thumbnails, logos and ads can't leak in), also reads image URLs from scripts; ignores `-300x200` thumbnails.
* TempleToons: real series title from the page (JSON-LD / h1 / og:title) when the catalog came from the sitemap;
  API call times out after 8 s so a dead API doesn't slow searches.
* `python -m Webs.diagnose ...` step 4 now downloads the first image through the bot's own download path.

# Session 12 (continued)
* **TempleToons now reads the site first**: sitemap.xml -> the site's own pages -> JSON API (last). If a series page can't be
  loaded or parsed, its chapters come from the sitemap's chapter URLs. Chapter titles from slugs: `chapter-8-5` -> "Chapter 8.5".
* **AllPornComics**: pictures that exist only in a script array are merged into the chapter's folder (natural order).
* Verified offline: image client ladder (plain headers first, rotation on 403, Origin stripped), picture detection on a noisy page,
  TempleToons with the series page blocked.

# Session 13
* **ComicsValley** (`Webs/comicsvalley.py`, sf `cv`) - same Madara engine as AllPornComics, so it shares its code
  (`Webs/allporncomics.py` is now site-parametric: `Site(base, hosts, prefixes, loose)`). `loose=True` because the comics
  section name isn't assumed: any two-segment link inside a listing card counts, taxonomy/utility pages
  (`/comic-genre/..`, `/comics-new/`, `/home-3/`) are skipped. AllPornComics output verified byte-identical after the refactor.
* **Fixed (affects every Madara listing)**: a card without its own picture could borrow the *next* card's title/poster;
  card search now never climbs into a container that holds more than one comic.
* **NHentai** (`Webs/nhentai.py`, sf `nh`) - JSON API (`/api/gallery/<id>`, `/api/galleries/search`) with HTML fallbacks
  (embedded `_gallery` JSON, thumbnails, `/search/?q=`); accepts a gallery number or link as the query; one gallery = one
  "Chapter 1"; Chrome-fingerprint client for the site, plain headers first for images.
* **Post button colours** - Read / Premium / Back-up buttons under channel posts now have an explicit colour
  (🔵 blue, 🟢 green, 🔴 red, ⚪ none, ✨ auto). Global defaults: /settings -> Post Design; per channel: /channels -> channel ->
  🎨 Button colours (tap to cycle; each button shows its own colour). Custom labels (e.g. "Premium Access") are no longer
  left uncoloured. Needs a Telegram library that supports button styles - the colour screen tells you if it doesn't
  (`pip install -U pyrofork`). `/diagnose` entries: comicsvalley, nhentai.

# Session 14
* **ComicsValley fix** - search now has three independent routes (site search page -> WordPress REST API -> Yoast sitemap),
  so a changed/blocked search page no longer means "nothing found"; chapter lists gained Madara's second AJAX route
  (`admin-ajax.php?action=manga_get_chapters`, post id auto-detected) - shared with AllPornComics. Every failing stage is logged.
* **TempleToons removed** - module, registry entry, diagnose option; id `tt1` added to `remove_site_sf` so users' leftover
  subscriptions to it are deleted automatically.
* **Templates redesign** (`Tools/templates.py`) - Editorial / Noir / Zen upgraded with ornamental rules and a framed facts
  panel in Noir; three new designs: Royal, Neon, Card. New premium-emoji slots: crown, bolt, book. Template buttons in the
  post preview wrap three per row. Verified: valid HTML for every design, <=1000 visible chars even with huge titles/synopses,
  missing fields, HTML in titles.
