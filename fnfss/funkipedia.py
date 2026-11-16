"""Funkipedia (Fandom) importer.

Fetches a character wiki page, discovers GIF/image assets linked or embedded
in the page, and categorises them by filename keywords. Nothing is downloaded
until the user selects items - discovery only collects metadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urljoin, urlparse

import requests
from lxml import html as lxml_html

from . import gifproc


@dataclass
class DiscoveredAsset:
    url: str
    name: str
    kind: str = "gif"           # "gif" | "png" | "other"
    width: int = 0
    height: int = 0
    frames: int = 0
    duration_ms: int = 0
    category: str = "Miscellaneous"
    selected: bool = False
    thumb_url: str = ""
    error: str = ""
    thumb_png: bytes = b""      # first frame, PNG-encoded, for the gallery


@dataclass
class ImportResult:
    page_title: str = ""
    assets: list[DiscoveredAsset] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# Filename keyword -> category. Order matters: first match wins, so
# miss/death/hurt come BEFORE directions - "bf-leftMiss.gif" is a miss
# animation, not a sing-left one.
_CATEGORY_RULES = [
    ("idle", "Idle"),
    ("miss", "Miss"),
    ("death", "Death"), ("dead", "Death"), ("die", "Death"), ("gameover", "Death"),
    ("hurt", "Hurt"), ("hit", "Hurt"),
    ("singleft", "Sing LEFT"), ("sing-left", "Sing LEFT"), ("left", "Sing LEFT"),
    ("singdown", "Sing DOWN"), ("sing-down", "Sing DOWN"), ("down", "Sing DOWN"),
    ("singup", "Sing UP"), ("sing-up", "Sing UP"), ("up", "Sing UP"),
    ("singright", "Sing RIGHT"), ("sing-right", "Sing RIGHT"), ("right", "Sing RIGHT"),
    ("alt", "Alternate"), ("special", "Alternate"), ("bonus", "Alternate"),
    ("add", "Alternate"), ("extra", "Alternate"),
]


def categorise(name: str) -> str:
    """Best-effort category from the asset filename. Never assumes a
    character follows vanilla naming - unmatched assets land in Misc."""
    n = re.sub(r"[^a-z]", "", name.lower())
    for key, cat in _CATEGORY_RULES:
        k = key.replace("-", "")
        if k in n:
            return cat
    return "Miscellaneous"


_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FNF-Sprite-Studio/1.0"}


def _is_animation_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    if path.endswith((".gif", ".png", ".webp")):
        return True
    # Fandom thumbnail URLs look like
    #   .../images/X/XX/Name.ext/revision/latest/thumbnail/width/W/height/H?cb=..
    # - the extension sits BEFORE /revision/, not at the end of the path.
    stem = path.split("/revision/", 1)[0]
    return "/images/" in stem and stem.endswith((".gif", ".png", ".webp"))


def _canonical_media(url: str) -> str:
    """Fandom serves originals via static.wikia.nocookie.net/.../<file>.

    Thumbnail URLs (.../revision/latest/thumbnail/...) are rewritten to the
    original (.../revision/latest) so we download full-res frames.
    """
    path = urlparse(url).path
    if "/revision/" in path:
        tail = path.split("/revision/", 1)[1]
        # thumbnail/scale variants -> serve the original revision instead
        if tail != "latest" and not tail.startswith("latest?"):
            url = url.split("/revision/", 1)[0] + "/revision/latest"
    # ?format=original stops Fandom's content negotiation from serving
    # animated WebP in place of the GIF.
    if "format=original" not in url:
        url += ("&" if "?" in url else "?") + "format=original"
    return url


def _is_special_path(url: str) -> bool:
    p = urlparse(url).path.lower()
    return "/special:" in p or "special_file_path" in p or "file:" in p


def discover(page_url: str, session: requests.Session | None = None,
             head_probe: bool = True) -> ImportResult:
    """Fetches the wiki page and lists candidate animation assets.

    Finds: <img>/<video poster> sources, href links to files, and
    Special:FilePath references in the page markup. Deduplicates by URL.
    `head_probe` optionally HEAD-requests each candidate for dimensions -
    set False for speed (metadata then fills on import).
    """
    res = ImportResult()
    sess = session or requests.Session()
    sess.headers.update(_UA)

    # Fandom/Wikia blocks plain page fetches (403) but serves the same
    # parsed HTML through the MediaWiki API - use it when available.
    page_html = None
    base = urlparse(page_url)
    api = f"{base.scheme}://{base.netloc}/api.php"
    title = unquote(urlparse(page_url).path.rsplit("/wiki/", 1)[-1])
    try:
        r = sess.get(api, params={
            "action": "parse", "page": title, "prop": "text",
            "format": "json", "formatversion": "2",
            "redirects": "1",
        }, timeout=30)
        if r.ok:
            page_html = r.json()["parse"]["text"]
            res.page_title = r.json()["parse"].get("title", "")
    except Exception:  # noqa: BLE001 - fall through to direct fetch
        page_html = None

    if page_html is None:
        try:
            r = sess.get(page_url, timeout=30)
            r.raise_for_status()
            page_html = r.text
        except requests.RequestException as e:
            res.warnings.append(f"page fetch failed: {e}")
            return res

    tree = lxml_html.fromstring(page_html)
    if not res.page_title:
        title_el = tree.find(".//title")
        res.page_title = (title_el.text or "").split("|")[0].strip() if title_el is not None else ""

    found: dict[str, DiscoveredAsset] = {}

    def add(url: str, prefer_name: str = "") -> None:
        url = url.strip()
        if not url or _is_special_path(url):
            return
        absu = _canonical_media(urljoin(page_url, url))
        if not _is_animation_url(absu):
            return
        if absu in found:
            return
        # Name comes from the path stem before any /revision/ suffix, so
        # thumbnail URLs still yield "HMPFMikuIdle.gif" not "120".
        stem = urlparse(absu).path.split("/revision/", 1)[0]
        name = prefer_name or unquote(stem.rsplit("/", 1)[-1])
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else "png"
        kind = ext if ext in ("gif", "png", "webp") else "png"
        # Animations only - static PNGs are spritesheets/portraits, not
        # frame strips, and drown out the actual GIFs.
        if kind != "gif":
            return
        # Same filename uploaded twice (different paths) is the same asset.
        if any(a.name.lower() == name.lower() and a.kind == kind for a in found.values()):
            return
        # Skip obvious icons/UI sprites.
        if re.search(r"(icon|logo|button|wiki|edit|sandbox|\.svg$)", name, re.I):
            return
        found[absu] = DiscoveredAsset(url=absu, name=name, kind=kind,
                                      category=categorise(name))

    base = urlparse(page_url)
    wiki_base = f"{base.scheme}://{base.netloc}"

    for img in tree.iter("img"):
        for attr in ("src", "data-src", "data-original"):
            u = img.get(attr)
            if u:
                add(u)
        # Fandom lazy-loads via srcset too.
        srcset = img.get("srcset") or img.get("data-srcset")
        if srcset:
            for part in srcset.split(","):
                u = part.strip().split(" ")[0]
                if u:
                    add(u)

    for a in tree.iter("a"):
        href = a.get("href") or ""
        if "/wiki/File:" in href or "/wiki/Special:FilePath/" in href or href.lower().endswith((".gif", ".png")):
            # Special:FilePath/<name> -> real file URL
            if "/wiki/Special:FilePath/" in href:
                fname = unquote(href.split("Special:FilePath/", 1)[1].split("?")[0])
                add(f"{wiki_base}/wiki/Special:FilePath/{fname}")
            else:
                add(href)

    # Video posters sometimes carry the animation frame strip.
    for v in tree.iter("video"):
        poster = v.get("poster")
        if poster:
            add(poster)

    assets = list(found.values())

    # Probe dimensions/frame counts where cheap (GIF header only).
    if head_probe:
        for a in assets:
            try:
                _probe(a)
            except Exception as e:  # noqa: BLE001 - probe failures are non-fatal
                a.error = str(e)

    # Stable ordering: category order then name.
    cat_order = ["Idle", "Sing LEFT", "Sing DOWN", "Sing UP", "Sing RIGHT",
                 "Miss", "Death", "Hurt", "Alternate", "Miscellaneous"]
    assets.sort(key=lambda a: (cat_order.index(a.category) if a.category in cat_order else 99,
                               a.name.lower()))
    res.assets = assets
    return res


def _probe(asset: DiscoveredAsset) -> None:
    """Reads just enough of the file to get size/frame/duration metadata."""
    stem = urlparse(asset.url).path.split("/revision/", 1)[0].lower()
    if not stem.endswith((".gif", ".webp")):
        return
    from PIL import Image
    from io import BytesIO
    # Range-request the first chunk; GIF headers live at the front.
    try:
        r = requests.get(asset.url, timeout=20, stream=True,
                         headers={**_UA, "Range": "bytes=0-262143"})
        data = b"".join(r.iter_content(65536))
        img = Image.open(BytesIO(data))
        asset.width, asset.height = img.size
        n = 0
        dur = 0
        # A range-fetched GIF is truncated by definition - count frames
        # until PIL runs out, tolerating the truncation error at the end.
        while n < 10000:
            try:
                img.seek(n)
            except Exception:
                break
            n += 1
            dur += int(img.info.get("duration", 0) or 0)
        asset.frames = n
        asset.duration_ms = dur
        # First frame as a PNG thumbnail for the gallery.
        try:
            img.seek(0)
            fr = img.convert("RGBA")
            fr.thumbnail((96, 96))
            from io import BytesIO
            buf = BytesIO()
            fr.save(buf, "PNG")
            asset.thumb_png = buf.getvalue()
        except Exception:
            pass
    except Exception:
        pass  # metadata optional; import will surface real errors


def import_asset(asset: DiscoveredAsset, prefix: str = "") -> "gifproc.Animation":
    """Downloads and parses one selected asset into an Animation."""
    if asset.error:
        raise ValueError(asset.error)
    data = gifproc.fetch_bytes(asset.url)
    name = asset.name.rsplit(".", 1)[0]
    return gifproc.load_animation(name, asset.url, data, prefix=prefix)
