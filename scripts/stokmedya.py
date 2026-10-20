#!/usr/bin/env python3
"""stokmedya — ücretsiz stok/arşiv görsel ve video arama, sahne eşleme, indirme.

Arama katmanı connerkward/web-media-getter-skill (MIT, (c) 2026 Conner K Ward)
webmedia.py dosyasından uyarlanmıştır. Eklenenler: kaynak katmanları, YouTube CC
araması, kara liste, sahne eşleme (sorgu + ilk sonuç), tekrar engeli, manifest.

Yalnızca stdlib. Anahtarsız kaynaklar her zaman çalışır; anahtarlı kaynaklar
(PEXELS_API_KEY, PIXABAY_API_KEY, YOUTUBE_API_KEY) env değişkeni varsa açılır.

Komutlar:
  stokmedya.py ara "1950s street scene" --tur image --adet 6
  stokmedya.py esle sahneler.json --out <klasör>
  stokmedya.py url-indir <url> --out <klasör> --sayfa <page_url> --lisans bilinmiyor
"""
import argparse, json, os, re, shutil, subprocess, sys, unicodedata
import urllib.parse, urllib.request, concurrent.futures as cf

UA = {"User-Agent": "stokmedya/1.0 (personal use)"}
TIMEOUT = 25
MAX_MB = 150  # tek dosya üst sınırı; arşiv filmleri GB'larca olabilir
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KARA_LISTE = os.path.join(SKILL_DIR, "kara-liste.txt")
VARSAYILAN_CIKTI = os.environ.get("STOKMEDYA_CIKTI", os.path.expanduser("~/Claude Personal Projects/stok-medya/cikti"))
ENV_DOSYA = os.environ.get("STOKMEDYA_ENV", os.path.expanduser("~/Claude Personal Projects/stok-medya/.env"))


def env_yukle():
    """ENV_DOSYA içindeki ANAHTAR=deger satırlarını env'e ekle (mevcut env'i ezmez)."""
    if not os.path.exists(ENV_DOSYA): return
    with open(ENV_DOSYA) as fh:
        for l in fh:
            l = l.strip()
            if not l or l.startswith("#") or "=" not in l: continue
            k, v = l.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if v: os.environ.setdefault(k.strip(), v)


def _get(url, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def rec(**k):
    k.setdefault("type", "image"); k.setdefault("license", ""); k.setdefault("author", "")
    k.setdefault("w", None); k.setdefault("h", None); k.setdefault("dl", None)
    return k


# ---- PD / CC arşiv (anahtarsız) -----------------------------------------
def openverse(q, typ, n):
    if typ == "video": return []
    d = _get(f"https://api.openverse.org/v1/images/?q={urllib.parse.quote(q)}&page_size={n}")
    return [rec(source="openverse", title=it.get("title", ""), url=it.get("url"), dl=it.get("url"),
                thumb=it.get("thumbnail") or it.get("url"), page_url=it.get("foreign_landing_url"),
                author=it.get("creator", ""), license=f"{it.get('license','')} {it.get('license_version','')}".strip(),
                w=it.get("width"), h=it.get("height"), type="image") for it in d.get("results", [])]


def internetarchive(q, typ, n):
    mt = "movies" if typ == "video" else "image"
    qq = urllib.parse.quote(f'({q}) AND mediatype:({mt})')
    d = _get(f"https://archive.org/advancedsearch.php?q={qq}&rows={n}&output=json"
             "&fl[]=identifier&fl[]=title&fl[]=creator&fl[]=licenseurl&sort[]=downloads+desc")
    out = []
    for doc in d.get("response", {}).get("docs", []):
        ident = doc.get("identifier")
        out.append(rec(source="internetarchive", title=doc.get("title", ""),
                       url=f"https://archive.org/details/{ident}",
                       thumb=f"https://archive.org/services/img/{ident}", dl=None,
                       page_url=f"https://archive.org/details/{ident}", ident=ident,
                       author=(doc.get("creator") if isinstance(doc.get("creator"), str) else ""),
                       license=doc.get("licenseurl") or "öğeye bak (IA)", type=typ))
    return out


def _ia_dosya(ident, typ):
    """IA öğesini tek oynatılabilir mp4 ya da gerçek içerik görseline çöz."""
    try:
        files = _get(f"https://archive.org/metadata/{ident}").get("files", [])
        sz = lambda f: float(f.get("size", 0) or 0)
        if typ == "video":
            c = sorted([f for f in files if f.get("name", "").lower().endswith(".mp4")], key=sz)
            c = [f for f in c if sz(f) <= MAX_MB * 1e6]
            pick = c[0] if c else None
        else:
            c = [f for f in files if f.get("name", "").lower().endswith((".jpg", ".jpeg", ".png"))
                 and "thumb" not in f.get("name", "").lower() and f.get("source") != "thumbnail"]
            under = [f for f in c if sz(f) <= 15e6]
            pick = max(under, key=sz) if under else (min(c, key=sz) if c else None)
        if pick:
            return f"https://archive.org/download/{ident}/{urllib.parse.quote(pick['name'])}"
    except Exception:
        pass
    return None


def nasa(q, typ, n):
    mt = "video" if typ == "video" else "image"
    d = _get(f"https://images-api.nasa.gov/search?q={urllib.parse.quote(q)}&media_type={mt}")
    out = []
    for it in d.get("collection", {}).get("items", [])[:n]:
        data = (it.get("data") or [{}])[0]; links = it.get("links") or [{}]
        out.append(rec(source="nasa", title=data.get("title", ""), url=it.get("href"),
                       thumb=links[0].get("href"), dl=(links[0].get("href") if mt == "image" else None),
                       nasa_manifest=it.get("href"),
                       page_url=f"https://images.nasa.gov/details/{data.get('nasa_id','')}",
                       author=data.get("photographer") or data.get("center", ""),
                       license="public domain (NASA)", type=mt))
    return out


def _nasa_video(manifest_url):
    try:
        urls = _get(manifest_url)
        mp4 = [u for u in urls if u.endswith(".mp4")]
        pref = [u for u in mp4 if "~medium" in u or "~small" in u]
        return (pref or mp4 or [None])[0]
    except Exception:
        return None


def wikimedia(q, typ, n):
    if typ == "video": return []
    url = ("https://commons.wikimedia.org/w/api.php?action=query&generator=search"
           f"&gsrsearch={urllib.parse.quote(q)}&gsrnamespace=6&gsrlimit={min(50, n*2)}&prop=imageinfo"
           "&iiprop=url|size|mediatype|extmetadata&iiurlwidth=1920&format=json")
    d = _get(url); out = []
    for p in (d.get("query", {}).get("pages", {}) or {}).values():
        ii = (p.get("imageinfo") or [{}])[0]; em = ii.get("extmetadata", {}) or {}
        if ii.get("mediatype") not in ("BITMAP", "DRAWING"): continue
        if len(out) >= n: break
        out.append(rec(source="wikimedia", title=p.get("title", "").replace("File:", ""),
                       url=ii.get("url"), dl=ii.get("thumburl") or ii.get("url"),
                       thumb=ii.get("thumburl") or ii.get("url"), page_url=ii.get("descriptionurl"),
                       author=re.sub("<[^>]+>", "", (em.get("Artist", {}) or {}).get("value", ""))[:120],
                       license=(em.get("LicenseShortName", {}) or {}).get("value", ""),
                       w=ii.get("width"), h=ii.get("height"), type="image"))
    return out


def loc(q, typ, n):
    if typ == "video": return []
    d = _get(f"https://www.loc.gov/photos/?q={urllib.parse.quote(q)}&fo=json&c={n}")
    out = []
    for it in (d.get("results") or [])[:n]:
        imgs = [u for u in (it.get("image_url") or []) if re.search(r"\.(jpg|jpeg|png)", u)]
        if not imgs: continue
        out.append(rec(source="loc", title=(it.get("title") or "")[:120], url=imgs[-1], dl=imgs[-1],
                       thumb=imgs[0], page_url=it.get("id") or it.get("url"),
                       license="öğeye bak (LoC)", type="image"))
    return out


# ---- ücretsiz stok (ücretsiz anahtar) -----------------------------------
def pexels(q, typ, n):
    key = os.environ.get("PEXELS_API_KEY")
    if not key: return []
    if typ == "video":
        d = _get(f"https://api.pexels.com/videos/search?query={urllib.parse.quote(q)}&per_page={n}",
                 headers={"Authorization": key}); out = []
        for v in d.get("videos", []):
            files = [f for f in v.get("video_files", []) if (f.get("width") or 0) <= 1920]
            files.sort(key=lambda f: (f.get("width") or 0))
            best = files[-1] if files else {}
            out.append(rec(source="pexels", title=(v.get("url") or "").rstrip("/").split("/")[-1],
                           url=v.get("url"), dl=best.get("link"), thumb=v.get("image"), page_url=v.get("url"),
                           author=(v.get("user") or {}).get("name", ""), license="Pexels License",
                           w=v.get("width"), h=v.get("height"), duration=v.get("duration"), type="video"))
        return out
    d = _get(f"https://api.pexels.com/v1/search?query={urllib.parse.quote(q)}&per_page={n}",
             headers={"Authorization": key})
    return [rec(source="pexels", title=p.get("alt", ""), url=(p.get("src") or {}).get("large2x"),
                dl=(p.get("src") or {}).get("large2x"), thumb=(p.get("src") or {}).get("medium"),
                page_url=p.get("url"), author=p.get("photographer", ""), license="Pexels License",
                w=p.get("width"), h=p.get("height"), type="image") for p in d.get("photos", [])]


def pixabay(q, typ, n):
    key = os.environ.get("PIXABAY_API_KEY")
    if not key: return []
    base = "https://pixabay.com/api/videos/" if typ == "video" else "https://pixabay.com/api/"
    d = _get(f"{base}?key={key}&q={urllib.parse.quote(q)}&per_page={max(3, n)}"); out = []
    for h in d.get("hits", [])[:n]:
        if typ == "video":
            vs = h.get("videos") or {}
            v = vs.get("large") if (vs.get("large") or {}).get("url") else vs.get("medium", {})
            out.append(rec(source="pixabay", title=h.get("tags", ""), url=h.get("pageURL"), dl=v.get("url"),
                           thumb=v.get("thumbnail"), page_url=h.get("pageURL"), author=h.get("user", ""),
                           license="Pixabay Content License", duration=h.get("duration"), type="video"))
        else:
            out.append(rec(source="pixabay", title=h.get("tags", ""), url=h.get("largeImageURL"),
                           dl=h.get("largeImageURL"), thumb=h.get("previewURL"), page_url=h.get("pageURL"),
                           author=h.get("user", ""), license="Pixabay Content License",
                           w=h.get("imageWidth"), h=h.get("imageHeight"), type="image"))
    return out


# ---- web (YouTube yalnızca Creative Commons) -----------------------------
def youtube(q, typ, n):
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key or typ != "video": return []
    d = _get("https://www.googleapis.com/youtube/v3/search?part=snippet&type=video"
             f"&videoLicense=creativeCommon&maxResults={n}&q={urllib.parse.quote(q)}&key={key}")
    out = []
    for it in d.get("items", []):
        vid = (it.get("id") or {}).get("videoId"); sn = it.get("snippet") or {}
        if not vid: continue
        out.append(rec(source="youtube", title=sn.get("title", ""), url=f"https://www.youtube.com/watch?v={vid}",
                       dl=None, yt_id=vid, thumb=((sn.get("thumbnails") or {}).get("high") or {}).get("url"),
                       page_url=f"https://www.youtube.com/watch?v={vid}", author=sn.get("channelTitle", ""),
                       channel_id=sn.get("channelId"), license="CC BY 3.0 (YouTube)", type="video"))
    return out


# ---- sosyal (X API v2, kullandıkça öde: dönen gönderi başına ücret) -------
X_FIYAT = 0.005  # $ / dönen gönderi (2026 pay-per-use)
X_ADET = 20      # arama başına çekilecek gönderi; cmd_ara --x-adet ile değişir
X_SAYAC = {"gonderi": 0}
_x_cache = {}


def _x_cek(q, n):
    key = os.environ.get("X_BEARER_TOKEN")
    if not key or n <= 0: return []
    if (q, n) in _x_cache: return _x_cache[(q, n)]
    n = max(10, min(100, n))  # API sınırı 10-100
    qq = urllib.parse.quote(f"({q}) has:media -is:retweet")
    d = _get(f"https://api.x.com/2/tweets/search/recent?query={qq}&max_results={n}"
             "&expansions=attachments.media_keys,author_id&tweet.fields=created_at,public_metrics"
             "&media.fields=type,url,preview_image_url,variants,width,height&user.fields=username",
             headers={"Authorization": f"Bearer {key}"})
    X_SAYAC["gonderi"] += len(d.get("data") or [])
    medya = {m["media_key"]: m for m in (d.get("includes") or {}).get("media", [])}
    kisi = {u["id"]: u.get("username", "") for u in (d.get("includes") or {}).get("users", [])}
    out = []
    for tw in d.get("data") or []:
        u = kisi.get(tw.get("author_id"), "")
        link = f"https://x.com/{u or 'i'}/status/{tw['id']}"
        for mk in (tw.get("attachments") or {}).get("media_keys", []):
            m = medya.get(mk) or {}
            typ = "image" if m.get("type") == "photo" else "video"
            out.append(rec(source="x", title=re.sub(r"\s+", " ", tw.get("text", ""))[:120], url=link, dl=None,
                           thumb=m.get("url") or m.get("preview_image_url"), page_url=link,
                           author=f"@{u}" if u else "", license="X — telif paylaşanda (yalnız referans)",
                           w=m.get("width"), h=m.get("height"), type=typ,
                           begeni=(tw.get("public_metrics") or {}).get("like_count")))
    _x_cache[(q, n)] = out
    return out


def x(q, typ, n):
    return [r for r in _x_cek(q, X_ADET) if r["type"] == typ][:n]


KATMAN = {
    "stok": {"pexels": pexels, "pixabay": pixabay},
    "pd": {"wikimedia": wikimedia, "nasa": nasa, "loc": loc, "internetarchive": internetarchive, "openverse": openverse},
    "web": {"youtube": youtube},
    "sosyal": {"x": x},
}
# İlk-sonuç seçiminde öncelik: stok kısa klip > PD arşiv > web
SIRA = [s for k in ("stok", "pd", "web", "sosyal") for s in KATMAN[k]]
REG = {s: f for k in KATMAN.values() for s, f in k.items()}


# Kaynak başına API'nin tek istekte verdiği üst sınır
LIMIT = {"pixabay": 200, "pexels": 80, "openverse": 20, "wikimedia": 25, "internetarchive": 100,
         "nasa": 100, "loc": 100, "youtube": 50, "x": 100}
VARSAYILAN_HEDEF = {"image": 60, "video": 10}


def toplu_ara(q, typ, hedef, srcs):
    """Her kaynaktan geniş çek, kaynaklar arasında sırayla (round-robin) karıştır, hedefte kes.
    hedef=0: sınırsız (bulunan her şey)."""
    havuz = {}
    with cf.ThreadPoolExecutor(max_workers=max(1, len(srcs))) as ex:
        futs = {ex.submit(ara, q, typ, LIMIT.get(s, 50) if hedef == 0 else min(LIMIT.get(s, 50), hedef), [s]): s
                for s in srcs if s in REG}
        errs = {}
        for f in cf.as_completed(futs):
            res, e = f.result(); errs.update(e)
            if res: havuz[futs[f]] = res
    # Kaynak içi sıralama: sorgu kelimelerini başlık/etikette daha çok içeren öne (hiçbiri atılmaz)
    kelimeler = [w for w in re.findall(r"[a-z0-9]+", q.lower()) if len(w) > 2]
    puan = lambda r: sum(w in (r.get("title") or "").lower() for w in kelimeler)
    for s in havuz:
        havuz[s].sort(key=puan, reverse=True)
    sira = [s for s in SIRA if s in havuz]
    out, gorulen, i = [], set(), 0
    while any(i < len(havuz[s]) for s in sira):
        for s in sira:
            if i < len(havuz[s]):
                r = havuz[s][i]; k = r.get("page_url") or r.get("url")
                if k and k not in gorulen:
                    gorulen.add(k); out.append(r)
        i += 1
    return (out[:hedef] if hedef else out), errs


def esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def yaz_galeri(out, sorgu, sonuc):
    kartlar = []
    for typ, recs in sonuc.items():
        kartlar.append(f'<h2>{"Görsel" if typ == "image" else "Video"} ({len(recs)})</h2><div class="grid">')
        for i, r in enumerate(recs, 1):
            link = r.get("page_url") or r.get("url") or "#"
            img = f'<img loading="lazy" src="{esc(r.get("thumb"))}" alt="">' if r.get("thumb") else '<div class="yok">önizleme yok</div>'
            vid = '<span class="play">▶</span>' if typ == "video" else ""
            kartlar.append(f'<a class="kart" href="{esc(link)}" target="_blank" rel="noopener"><div class="thumb">{img}{vid}</div>'
                           f'<div class="meta"><b>{i}. {esc((r.get("title") or "")[:70])}</b>'
                           f'<span>{esc(r["source"])} · {esc((r.get("author") or "")[:30])}</span>'
                           f'<span class="lis">{esc((r.get("license") or "")[:40])}</span></div></a>')
        kartlar.append("</div>")
    html = f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(sorgu)} — stok medya</title><style>
:root{{--bg:#fafaf9;--fg:#1c1917;--mut:#78716c;--kart:#fff;--cizgi:#e7e5e4}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1c1917;--fg:#fafaf9;--mut:#a8a29e;--kart:#292524;--cizgi:#44403c}}}}
body{{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif}}
h1{{font-size:20px}}h2{{font-size:16px;margin-top:28px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}}
.kart{{background:var(--kart);border:1px solid var(--cizgi);border-radius:8px;overflow:hidden;color:inherit;text-decoration:none}}
.thumb{{position:relative;aspect-ratio:16/10;background:var(--cizgi)}}.thumb img{{width:100%;height:100%;object-fit:cover;display:block}}
.yok{{display:grid;place-items:center;height:100%;color:var(--mut)}}
.play{{position:absolute;right:8px;bottom:6px;background:#000a;color:#fff;border-radius:4px;padding:0 6px}}
.meta{{padding:8px;display:flex;flex-direction:column;gap:2px}}.meta span{{color:var(--mut);font-size:12px}}.lis{{font-family:ui-monospace,monospace}}
</style></head><body><h1>“{esc(sorgu)}”</h1>{''.join(kartlar)}</body></html>"""
    yol = os.path.join(out, "galeri.html")
    open(yol, "w").write(html)
    return yol


def kaynaklar(katmanlar):
    return [s for k in katmanlar for s in KATMAN.get(k, {})]


def kara_liste():
    if not os.path.exists(KARA_LISTE): return []
    with open(KARA_LISTE) as fh:
        return [l.strip().lower() for l in fh if l.strip() and not l.startswith("#")]


def engelli(r, kl):
    alanlar = " ".join(str(r.get(k) or "") for k in ("source", "page_url", "url", "author", "channel_id")).lower()
    return any(x in alanlar for x in kl)


def ara(q, typ, n, srcs):
    res, errs = [], {}
    with cf.ThreadPoolExecutor(max_workers=max(1, len(srcs))) as ex:
        futs = {ex.submit(REG[s], q, typ, n): s for s in srcs if s in REG}
        for f in cf.as_completed(futs):
            s = futs[f]
            try: res.extend(f.result())
            except Exception as e: errs[s] = str(e)[:80]
    kl = kara_liste()
    res = [r for r in res if not engelli(r, kl)]
    res.sort(key=lambda r: SIRA.index(r["source"]))
    return res, errs


# ---- indirme -------------------------------------------------------------
def _ext(url, typ):
    m = re.search(r"\.(jpg|jpeg|png|gif|webp|mp4|webm|mov|ogv)(?:\?|$)", (url or "").lower())
    return "." + m.group(1) if m else (".mp4" if typ == "video" else ".jpg")


def slug(s, n=50):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:n] or "medya"


def cozumle(r):
    """Kaydın doğrudan indirilebilir URL'sini bul (gerekirse tembel çözüm)."""
    if r.get("dl"): return r["dl"]
    if r["source"] == "internetarchive" and r.get("ident"):
        r["dl"] = _ia_dosya(r["ident"], r["type"])
    elif r["source"] == "nasa" and r["type"] == "video" and r.get("nasa_manifest"):
        r["dl"] = _nasa_video(r["nasa_manifest"])
    return r.get("dl")


def indir_url(dl, path):
    if urllib.parse.urlparse(dl).scheme not in ("http", "https"):
        raise ValueError("http(s) olmayan URL")
    req = urllib.request.Request(dl, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp:
        cl = int(resp.headers.get("Content-Length") or 0)
        if cl > MAX_MB * 1e6: raise ValueError(f"{cl/1e6:.0f} MB > {MAX_MB} MB")
        toplam = 0
        with open(path, "wb") as fh:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk: break
                toplam += len(chunk)
                if toplam > MAX_MB * 1e6:
                    fh.close(); os.remove(path); raise ValueError(f"> {MAX_MB} MB")
                fh.write(chunk)


def indir_youtube(r, path_base, sure):
    if not shutil.which("yt-dlp"):
        raise RuntimeError("yt-dlp kurulu değil")
    cmd = ["yt-dlp", "-q", "--no-playlist", "-f", "mp4[height<=1080]/best[height<=1080]",
           "--download-sections", f"*0-{int(sure)}", "-o", path_base + ".%(ext)s", r["url"]]
    subprocess.run(cmd, check=True, timeout=300)
    for f in os.listdir(os.path.dirname(path_base)):
        if f.startswith(os.path.basename(path_base) + "."):
            return os.path.join(os.path.dirname(path_base), f)
    raise RuntimeError("yt-dlp dosya üretmedi")


def indir(r, out, ad, sure=15):
    """Kaydı indir, dosya adını döndür. Hata olursa istisna fırlatır."""
    os.makedirs(out, exist_ok=True)
    if r["source"] == "x":
        raise ValueError("X medyası indirilmez (telif paylaşanda); yalnız link")
    if r["source"] == "youtube":
        return os.path.basename(indir_youtube(r, os.path.join(out, ad), sure))
    dl = cozumle(r)
    if not dl: raise ValueError("indirilebilir dosya yok")
    fn = ad + _ext(dl, r["type"])
    indir_url(dl, os.path.join(out, fn))
    return fn


ATIF_GEREKEN = ("openverse", "wikimedia", "internetarchive", "loc", "youtube", "web")


def atif_satiri(r):
    r = {k: (" ".join(v.split()) if isinstance(v, str) else v) for k, v in r.items()}
    return f"- {r.get('title') or r['source']} — {r.get('author') or 'bilinmiyor'} — {r.get('license') or 'lisans bilinmiyor'} — {r.get('page_url') or r.get('url')}"


def yaz_atif(out, kayitlar):
    gerek = [r for r in kayitlar if r.get("source") in ATIF_GEREKEN]
    with open(os.path.join(out, "atif.txt"), "w") as fh:
        fh.write("Kaynaklar (video açıklamasına eklenecek):\n")
        for r in gerek: fh.write(atif_satiri(r) + "\n")
        bilinmeyen = [r for r in kayitlar if "bilinmiyor" in (r.get("license") or "")]
        if bilinmeyen:
            fh.write("\nLİSANSI BİLİNMEYENLER (yayından önce kontrol et):\n")
            for r in bilinmeyen: fh.write(atif_satiri(r) + "\n")


def indir_hepsi(out, sonuc, sure):
    """sonuc içindeki her kaydı indir (X hariç, zaten inmişse atla), atif.txt yaz."""
    for typ, recs in sonuc.items():
        for i, r in enumerate(recs):
            if r.get("file") and os.path.exists(os.path.join(out, r["file"])): continue
            r.pop("download_error", None)
            try: r["file"] = indir(r, out, f"{typ}_{i:03d}_{r['source']}", sure)
            except Exception as ex: r["download_error"] = str(ex)[:80]
    yaz_atif(out, [r for recs in sonuc.values() for r in recs if r.get("file")])


# ---- hareket testi -------------------------------------------------------
# Bir klibin gerçek hareketli çekim mi olduğunu konudan bağımsız ölçer. Haiku tek karede
# "konu var mı" diye bakar; ekran kaydını ve fotoğraf üstüne yakınlaştırmayı göremez.
# Kararlar: gercek | foto_efekt (tek fotoğrafa zoom/kaydırma/döndürme) | supheli (fotoğraf
# animasyonu olabilir, ör. 2,5D paralaks; karelerine bakılmalı) | ekran_kaydi (sabit çerçeve
# içinde oynatılan görüntü) | sabit (kare değişmiyor). numpy + ffmpeg gerekir.
HAREKET_KARE = 10          # klip boyunca örneklenen nokta sayısı (her noktada bir kare çifti)
HAREKET_ARALIK = 0.4       # çiftteki iki kare arası (sn); klip uzunluğundan bağımsız
HAREKET_GENISLIK = 112     # analiz çözünürlüğü (px)
HAREKET_BELIRGIN = 1.2     # karara yalnız bu kadar değişen kare çiftleri katılır
# Eşikler 40 gerçek çekim ve 17 fotoğraf animasyonu (Ken Burns, döndürme, 2,5D paralaks) üzerinde
# ölçüldü. Tek ölçek+döndürme+kaydırma hizalamasından sonra kalan fark (medyan):
HAREKET_FOTO_KALINTI = 0.85    # altı: fotoğraf efekti (sahtelerin 12/17'si; gerçeklerin 1/40'ı)
HAREKET_SUPHELI_KALINTI = 1.6  # 0.85-1.6: şüpheli, karelerine bakılmalı (sahte 5, gerçek 2 burada)
HAREKET_SUPHELI_ORAN = 0.8     # şüpheli için ayrıca: kalan fark / ham fark bunun altında
HAREKET_ELENEN = {"foto_efekt", "ekran_kaydi", "sabit"}  # dogrula bunları Haiku kabul etse de eler
HAREKET_BLOK_SABIT = 0.3       # blok medyanı bunun altında: kamera sabit, sahnede nesne hareket ediyor
HAREKET_FOTO_TABAN = 0.75      # ...ama kalan fark bunun altındaysa yine fotoğraf (çok yavaş zoom)


def _gri_kareler(yol, n=HAREKET_KARE, w=HAREKET_GENISLIK, aralik=HAREKET_ARALIK):
    """Klip boyunca n noktada, aralarında `aralik` sn olan kare çiftleri: [(a, b), ...] (gri, w px)."""
    import numpy as np
    bilgi = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height:format=duration", "-of", "json", yol],
                           capture_output=True, text=True, timeout=60).stdout
    b = json.loads(bilgi); st = b["streams"][0]
    sure = float(b["format"]["duration"]); h = max(2, round(w * st["height"] / st["width"] / 2) * 2)
    aralik = min(aralik, sure / 3)
    bas, son = sure * 0.05, max(sure * 0.05, sure * 0.95 - aralik)
    def kare(t):
        ham = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", yol, "-frames:v", "1",
                              "-vf", f"scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
                             capture_output=True, timeout=120).stdout
        return np.frombuffer(ham, dtype=np.uint8).reshape(h, w).astype(float) if len(ham) == w * h else None
    ciftler = []
    for i in range(n):
        t = bas + (son - bas) * i / max(1, n - 1)
        a, b = kare(t), kare(t + aralik)
        if a is not None and b is not None: ciftler.append((a, b))
    return ciftler


def _duz_cerceve(kare):
    """Kenarlardaki tek renkli bant kalınlıkları (üst, alt, sol, sağ) ve bant parlaklığı."""
    import numpy as np
    H, W = kare.shape
    def kalinlik(dilimler):
        n = 0
        for d in dilimler:
            if d.std() > 5: break       # hafif renk geçişine (vinyet) izin ver
            n += 1
        return n
    ust = kalinlik(kare[i] for i in range(H // 3))
    alt = kalinlik(kare[H - 1 - i] for i in range(H // 3))
    sol = kalinlik(kare[:, i] for i in range(W // 3))
    sag = kalinlik(kare[:, W - 1 - i] for i in range(W // 3))
    bant = [kare[:ust].mean() if ust else None, kare[H - alt:].mean() if alt else None,
            kare[:, :sol].mean() if sol else None, kare[:, W - sag:].mean() if sag else None]
    return (ust, alt, sol, sag), bant


def _bulanik(a):
    from PIL import Image, ImageFilter
    import numpy as np
    return np.asarray(Image.fromarray(a.astype("uint8")).filter(ImageFilter.GaussianBlur(1.2)), dtype=float)


def _global_kalinti(a, b):
    """b'yi a'dan tek bir ölçek + döndürme + kaydırmayla açıklamaya çalış; en iyi ortalama farkı döndür.
    Fotoğraf animasyonunda (Ken Burns) kalan fark sıkıştırma gürültüsü kadardır."""
    import numpy as np
    from PIL import Image
    h, w = a.shape; m = max(4, w // 10); cx, cy = w / 2, h / 2
    A = Image.fromarray(np.clip(a, 0, 255).astype("uint8")); hedef = b[m:h - m, m:w - m]
    def hata(s, r, dx, dy):
        c, si = np.cos(np.radians(r)) / s, np.sin(np.radians(r)) / s
        T = (c, si, cx - c * (cx + dx) - si * (cy + dy), -si, c, cy + si * (cx + dx) - c * (cy + dy))
        t = A.transform((w, h), Image.AFFINE, T, resample=Image.BILINEAR)
        return float(np.abs(np.asarray(t, dtype=float)[m:h - m, m:w - m] - hedef).mean())
    f, s, r, dx, dy = min((hata(s, 0, dx, dy), s, 0, dx, dy) for s in np.arange(0.92, 1.081, 0.04)
                          for dx in range(-8, 9, 4) for dy in range(-8, 9, 4))
    ad = [0.02, 1.0, 2.0]                         # ölçek, derece, piksel adımları
    while ad[2] >= 0.25:                          # desen araması ile incelt
        iyi = False
        for d in ((ad[0], 0, 0, 0), (-ad[0], 0, 0, 0), (0, ad[1], 0, 0), (0, -ad[1], 0, 0),
                  (0, 0, ad[2], 0), (0, 0, -ad[2], 0), (0, 0, 0, ad[2]), (0, 0, 0, -ad[2])):
            y = hata(s + d[0], r + d[1], dx + d[2], dy + d[3])
            if y < f: f, s, r, dx, dy, iyi = y, s + d[0], r + d[1], dx + d[2], dy + d[3], True
        if not iyi: ad = [x / 2 for x in ad]
    return f


def _blok_kalinti(a, b, n=4, R=5):
    """Kareyi n x n bloğa böl, her bloğu ayrı kaydırarak eşle; blok farklarının medyanı.
    Kamera sabit ve sahnede yalnız bir nesne hareket ediyorsa çoğu blok ~0 çıkar."""
    import numpy as np
    h, w = a.shape; bh, bw = h // n, w // n; fs = []
    for i in range(n):
        for j in range(n):
            y0, x0 = i * bh, j * bw
            if bh <= 2 * R + 2 or bw <= 2 * R + 2: continue
            hedef = b[y0 + R:y0 + bh - R, x0 + R:x0 + bw - R]
            fs.append(min(float(np.abs(a[y0 + R + dy:y0 + bh - R + dy, x0 + R + dx:x0 + bw - R + dx] - hedef).mean())
                          for dy in range(-R, R + 1) for dx in range(-R, R + 1)))
    return float(np.median(fs)) if fs else 0.0


def hareket_analiz(yol):
    import numpy as np
    cf_ = _gri_kareler(yol)
    if not cf_:
        return {"karar": "sabit", "cift": 0}
    k = np.array([a for a, _ in cf_] + [b for _, b in cf_])
    H, W = k.shape[1:]
    (ust, alt, sol, sag), bant = _duz_cerceve(np.median(k, axis=0))
    olcum = {"nokta": len(cf_), "cerceve": [ust, alt, sol, sag]}
    dort_kenar = min(ust, alt) >= H * 0.03 and min(sol, sag) >= W * 0.03
    renkli = [x for x in bant if x is not None]
    if dort_kenar and min(renkli) > 8 and max(renkli) - min(renkli) < 12:
        return {"karar": "ekran_kaydi", **olcum}  # dört kenarda aynı renk, siyah olmayan çerçeve
    degisim = [float(np.percentile(np.abs(b - a), 99)) for a, b in cf_]
    olcum["degisim_p99"] = round(max(degisim), 1)
    if max(degisim) < 6:                          # hiçbir piksel belirgin değişmiyor
        return {"karar": "sabit", **olcum}
    kirp = (slice(ust, H - alt or H), slice(sol, W - sag or W))   # siyah bant (letterbox) varsa içeriğe kırp
    ciftler, hizli = [], 0
    for a0, b0 in cf_:
        a, b = _bulanik(a0[kirp]), _bulanik(b0[kirp])
        kimlik = float(np.abs(b - a).mean())
        if kimlik < 0.5: continue                 # bu aralıkta değişim yok
        glob = _global_kalinti(a, b)
        if glob > 15:                             # sahne geçişi ya da çok hızlı hareket
            hizli += 1; continue
        ciftler.append((kimlik, glob, _blok_kalinti(a, b)))
    if not ciftler:                               # hepsi atlandı: ya hiç değişim yok ya da her çift çok hızlı
        return {"karar": "gercek" if hizli else "sabit", **olcum}
    belirgin = [c for c in ciftler if c[0] >= HAREKET_BELIRGIN] or ciftler
    g = float(np.median([c[1] for c in belirgin]))
    blok = float(np.median([c[2] for c in belirgin]))
    oran = float(np.median([c[1] / c[0] for c in belirgin]))
    olcum.update(cift=len(belirgin), kalinti=round(g, 2), blok=round(blok, 2), oran=round(oran, 2))
    if blok < HAREKET_BLOK_SABIT and g >= HAREKET_FOTO_TABAN:
        karar = "gercek"                          # sabit kamera, hareket eden nesne
    elif g < HAREKET_FOTO_KALINTI:
        karar = "foto_efekt"
    elif g < HAREKET_SUPHELI_KALINTI and oran < HAREKET_SUPHELI_ORAN:
        karar = "supheli"
    else:
        karar = "gercek"
    return {"karar": karar, **olcum}


def cmd_hareket(a):
    print(json.dumps([{"dosya": y, **hareket_analiz(y)} for y in a.dosyalar], ensure_ascii=False, indent=1))


# ---- Haiku doğrulaması ---------------------------------------------------
# Akış: ara --hedef 0 (geniş havuz) -> kontak (numaralı önizleme sayfaları) -> Haiku alt ajanları
# sayfalara bakıp _dogrulama/karar_*.json yazar -> dogrula (yalnız kabul edilenler kalır).
# Videolar için ikinci tur: dogrula --indir -> kontak --dosya (indirilen klipten 4 kare) -> Haiku -> dogrula --sil.
HUCRE_W, HUCRE_H, SUTUN, SATIR = 400, 300, 4, 3


def _onizleme(r, typ, out, dd, dosyadan):
    """Kaydın önizleme resmini PIL Image olarak döndür; yoksa None."""
    from PIL import Image
    yerel = os.path.join(out, r["file"]) if r.get("file") else None
    if dosyadan and yerel and os.path.exists(yerel):
        if typ == "image":
            return Image.open(yerel).convert("RGB")
        try:  # videodan %10/%35/%60/%85 noktalarında 4 kare, 2x2
            sure = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", yerel],
                                        capture_output=True, text=True, timeout=60).stdout.strip() or 0)
            kareler = []
            for j, oran in enumerate((0.10, 0.35, 0.60, 0.85)):
                kp = os.path.join(dd, f"_kare_{slug(r.get('file') or 'x')}_{j}.jpg")  # iş parçacığı başına ayrı ad
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{sure * oran:.2f}", "-i", yerel, "-frames:v", "1", kp],
                               timeout=120, check=True)
                kareler.append(Image.open(kp).convert("RGB")); os.remove(kp)
            tuval = Image.new("RGB", (HUCRE_W * 2, HUCRE_H * 2))
            for j, k in enumerate(kareler):
                k.thumbnail((HUCRE_W, HUCRE_H)); tuval.paste(k, ((j % 2) * HUCRE_W, (j // 2) * HUCRE_H))
            return tuval
        except Exception:
            return None
    if not r.get("thumb"): return None
    try:
        import io
        req = urllib.request.Request(r["thumb"], headers=UA)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return Image.open(io.BytesIO(resp.read(8_000_000))).convert("RGB")
    except Exception:
        return None


def _referans_sayfasi(kaynaklar, dd):
    """Konunun güncel görünümünü gösteren referans görselleri (yerel yol ya da URL) tek sayfada topla.
    Haiku önce bu sayfaya bakar; ölçüt tarif yerine örnekle verilir."""
    import io
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    resimler = []
    for k in kaynaklar:
        try:
            if k.startswith(("http://", "https://")):
                with urllib.request.urlopen(urllib.request.Request(k, headers=UA), timeout=TIMEOUT) as r:
                    resimler.append(Image.open(io.BytesIO(r.read(15_000_000))).convert("RGB"))
            else:
                resimler.append(Image.open(k).convert("RGB"))
        except Exception as e:
            print(f"referans okunamadı: {k} ({e})", file=sys.stderr)
    if not resimler: return None
    sayfa = Image.new("RGB", (HUCRE_W * min(SUTUN, len(resimler)), (HUCRE_H + 44) * ((len(resimler) + SUTUN - 1) // SUTUN)), "white")
    font = ImageFont.load_default(size=34)
    for n, im in enumerate(resimler):
        x, y = (n % SUTUN) * HUCRE_W, (n // SUTUN) * (HUCRE_H + 44)
        im = ImageOps.contain(im, (HUCRE_W - 8, HUCRE_H - 8))
        sayfa.paste(im, (x + (HUCRE_W - im.width) // 2, y + 44 + (HUCRE_H - im.height) // 2))
        ImageDraw.Draw(sayfa).text((x + 8, y + 4), f"REF{n + 1}", fill="blue", font=font)
    sayfa.save(os.path.join(dd, "referans.jpg"), quality=90)
    return "referans.jpg"


def cmd_kontak(a):
    """sonuclar.json kayıtlarını numaralı kontak sayfalarına diz (_dogrulama/sayfa_NNN.jpg + adaylar.json)."""
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    out = a.klasor
    d = json.load(open(os.path.join(out, "sonuclar.json")))
    dd = os.path.join(out, "_dogrulama")
    if os.path.isdir(dd): shutil.rmtree(dd)
    os.makedirs(dd)
    isler = [(typ, i, r) for typ, recs in d["sonuclar"].items() for i, r in enumerate(recs)
             if r["source"] != "x" and (not a.dosya or r.get("file"))]
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        resimler = list(ex.map(lambda t: _onizleme(t[2], t[0], out, dd, a.dosya), isler))
    hareket = {}
    if a.dosya:                                   # indirilmiş videolara hareket testi
        vid = [(f"{typ[0]}{i}", os.path.join(out, r["file"])) for typ, i, r in isler if typ == "video"]
        with cf.ThreadPoolExecutor(max_workers=4) as ex:
            for (rid, _), h in zip(vid, ex.map(lambda v: hareket_analiz(v[1])["karar"], vid)):
                hareket[rid] = h
    font = ImageFont.load_default(size=34)
    adaylar, onizlemesiz, sayfa, hucre, n_sayfa = [], [], None, 0, 0
    def kaydet():
        nonlocal sayfa
        if sayfa: sayfa.save(os.path.join(dd, f"sayfa_{n_sayfa:03d}.jpg"), quality=85); sayfa = None
    for (typ, i, r), im in zip(isler, resimler):
        rid = f"{typ[0]}{i}"
        if im is None:
            onizlemesiz.append(rid); continue
        if sayfa is None:
            n_sayfa += 1; hucre = 0
            sayfa = Image.new("RGB", (HUCRE_W * SUTUN, (HUCRE_H + 44) * SATIR), "white")
        x, y = (hucre % SUTUN) * HUCRE_W, (hucre // SUTUN) * (HUCRE_H + 44)
        im = ImageOps.contain(im, (HUCRE_W - 8, HUCRE_H - 8))  # küçük önizlemeleri de hücreye büyüt
        sayfa.paste(im, (x + (HUCRE_W - im.width) // 2, y + 44 + (HUCRE_H - im.height) // 2))
        etiket = rid + (f" {hareket[rid].upper()}" if hareket.get(rid, "gercek") != "gercek" else "")
        ImageDraw.Draw(sayfa).text((x + 8, y + 4), etiket, fill="red", font=font)
        adaylar.append({"id": rid, "tur": typ, "kaynak": r["source"], "baslik": (r.get("title") or "")[:120],
                        "sayfa": f"sayfa_{n_sayfa:03d}.jpg", **({"hareket": hareket[rid]} if rid in hareket else {})})
        hucre += 1
        if hucre == SUTUN * SATIR: kaydet()
    kaydet()
    referans = _referans_sayfasi(a.referans, dd) if a.referans else None
    json.dump({"sorgu": d["sorgu"], "adaylar": adaylar, "onizlemesiz": onizlemesiz,
               **({"referans": referans} if referans else {})},
              open(os.path.join(dd, "adaylar.json"), "w"), indent=1, ensure_ascii=False)
    print(json.dumps({"klasor": dd, "sayfa": n_sayfa, "aday": len(adaylar), "onizlemesiz": len(onizlemesiz)}, ensure_ascii=False))


def cmd_dogrula(a):
    """_dogrulama/karar_*.json içindeki kabul listesini uygula: kalanlar sonuclar.json + galeri, elenenler elenenler.json.
    Önizlemesi olmayan ya da hiçbir kararda geçmeyen kayıt elenir (şüphede ele). X kayıtları dokunulmadan kalır."""
    out = a.klasor
    dd = os.path.join(out, "_dogrulama")
    d = json.load(open(os.path.join(out, "sonuclar.json")))
    kararlar = [f for f in os.listdir(dd) if f.startswith("karar") and f.endswith(".json")]
    if not kararlar: sys.exit("karar_*.json yok: önce Haiku doğrulaması çalışmalı")
    kabul = set()
    for f in kararlar: kabul |= set(json.load(open(os.path.join(dd, f))).get("kabul", []))
    yol_el = os.path.join(out, "elenenler.json")
    elenen = json.load(open(yol_el)) if os.path.exists(yol_el) else []
    ay = os.path.join(dd, "adaylar.json")
    hareket = {x["id"]: x["hareket"] for x in json.load(open(ay))["adaylar"] if "hareket" in x} if os.path.exists(ay) else {}
    yeni, ozet = {}, {}
    for typ, recs in d["sonuclar"].items():
        kal, el = [], []
        for i, r in enumerate(recs):
            rid = f"{typ[0]}{i}"; h = hareket.get(rid)
            if h: r["hareket"] = h
            if r["source"] == "x":
                kal.append(r)
            elif rid not in kabul:
                r["elenme"] = "haiku"; el.append(r)
            elif h in HAREKET_ELENEN and not a.hareket_serbest:
                r["elenme"] = f"hareket: {h}"; el.append(r)
            else:
                kal.append(r)
        hedef = VARSAYILAN_HEDEF.get(typ, 0) if a.hedef is None else a.hedef
        if hedef:
            x_kayit = [r for r in kal if r["source"] == "x"]
            kal = [r for r in kal if r["source"] != "x"][:hedef] + x_kayit
        if a.sil:
            for r in el:
                if r.get("file") and os.path.exists(os.path.join(out, r["file"])):
                    os.remove(os.path.join(out, r["file"])); r["silindi"] = r.pop("file")
        elenen.extend(el); yeni[typ] = kal
        ozet[typ] = {"kalan": len(kal), "elenen": len(el)}
    d["sonuclar"] = yeni; d["dogrulandi"] = True
    if a.indir: indir_hepsi(out, yeni, a.sure)
    elif a.sil: yaz_atif(out, [r for recs in yeni.values() for r in recs if r.get("file")])
    json.dump(d, open(os.path.join(out, "sonuclar.json"), "w"), indent=1, ensure_ascii=False)
    json.dump(elenen, open(yol_el, "w"), indent=1, ensure_ascii=False)
    for typ, recs in yeni.items():
        ozet[typ]["kaynaklar"] = {}
        for r in recs: ozet[typ]["kaynaklar"][r["source"]] = ozet[typ]["kaynaklar"].get(r["source"], 0) + 1
        if a.indir: ozet[typ]["indirilen"] = sum(1 for r in recs if r.get("file"))
    print(json.dumps({"galeri": yaz_galeri(out, d["sorgu"], yeni), **ozet}, ensure_ascii=False))


# ---- komutlar ------------------------------------------------------------
def cmd_ara(a):
    global X_ADET
    X_ADET = a.x_adet
    srcs = kaynaklar(a.katman.split(",")) if not a.kaynak else a.kaynak.split(",")
    turler = ["image", "video"] if a.tur == "hepsi" else [a.tur]
    out = a.out or os.path.join(VARSAYILAN_CIKTI, slug(a.sorgu))
    os.makedirs(out, exist_ok=True)
    sonuc, hatalar = {}, {}
    for typ in turler:
        hedef = VARSAYILAN_HEDEF[typ] if a.hedef is None else a.hedef
        res, errs = toplu_ara(a.sorgu, typ, hedef, srcs)
        sonuc[typ] = res
        if errs: hatalar[typ] = errs
    if a.indir:
        indir_hepsi(out, sonuc, a.sure)
    json.dump({"sorgu": a.sorgu, "sonuclar": sonuc, "hatalar": hatalar},
              open(os.path.join(out, "sonuclar.json"), "w"), indent=1, ensure_ascii=False)
    galeri = yaz_galeri(out, a.sorgu, sonuc)
    ozet = {"sorgu": a.sorgu, "klasor": out, "galeri": galeri, "hatalar": hatalar,
            "x": ({"gonderi": X_SAYAC["gonderi"], "maliyet_usd": round(X_SAYAC["gonderi"] * X_FIYAT, 3)}
                  if os.environ.get("X_BEARER_TOKEN") and "x" in srcs else "kapalı (X_BEARER_TOKEN yok ya da katman dışı)")}
    for typ, recs in sonuc.items():
        dag = {}
        for r in recs: dag[r["source"]] = dag.get(r["source"], 0) + 1
        ozet[typ] = {"adet": len(recs), "kaynaklar": dag,
                     "indirilen": sum(1 for r in recs if r.get("file")) if a.indir else None,
                     "ilk": [f"{r['source']} | {(r.get('title') or '')[:50]} | {(r.get('license') or '')[:25]} | {r.get('page_url') or r.get('url')}"
                             for r in recs[:a.goster]]}
    print(json.dumps(ozet, indent=1, ensure_ascii=False))


def cmd_esle(a):
    """sahneler.json: [{"id":1,"metin":"...","sorgular":["q1","q2"],"tur":"video","sure":5}]"""
    sahneler = json.load(open(a.sahneler))
    out = a.out or os.path.join(VARSAYILAN_CIKTI, slug(os.path.splitext(os.path.basename(a.sahneler))[0]))
    os.makedirs(out, exist_ok=True)
    srcs = kaynaklar(a.katman.split(","))
    kullanilan, manifest, hatalar = set(), [], {}
    for s in sahneler:
        sec, kullanilan_sorgu = None, None
        turler = [s.get("tur", "video")] + (["image"] if s.get("tur", "video") == "video" and a.gorsele_dus else [])
        for tur in turler:
            for q in s.get("sorgular", []):
                res, errs = ara(q, tur, a.adet, srcs)
                if errs: hatalar[q] = errs
                for r in res:  # sorgu + ilk sonuç: sıradaki ilk kullanılmamış, indirilebilen kayıt
                    anahtar = r.get("page_url") or r.get("url")
                    if anahtar in kullanilan: continue
                    try:
                        r["file"] = indir(r, out, f"sahne{int(s['id']):03d}_{r['source']}", s.get("sure", 15))
                    except Exception as e:
                        continue
                    kullanilan.add(anahtar); sec, kullanilan_sorgu = r, q
                    break
                if sec: break
            if sec: break
        satir = {"id": s["id"], "metin": s.get("metin", ""), "sure": s.get("sure"), "istenen_tur": s.get("tur", "video")}
        if sec:
            satir.update({"durum": "bulundu", "sorgu": kullanilan_sorgu, "dosya": sec["file"], "tur": sec["type"],
                          "kaynak": sec["source"], "lisans": sec.get("license"), "yazar": sec.get("author"),
                          "sayfa": sec.get("page_url"), "url": sec.get("dl") or sec.get("url")})
        else:
            satir.update({"durum": "bulunamadi", "denenen": s.get("sorgular", [])})
        manifest.append(satir)
        print(f"  sahne {s['id']}: {satir['durum']} {satir.get('kaynak','')} {satir.get('dosya','')}", file=sys.stderr)
    json.dump({"katmanlar": a.katman, "sahneler": manifest, "kaynak_hatalari": hatalar},
              open(os.path.join(out, "manifest.json"), "w"), indent=1, ensure_ascii=False)
    yaz_atif(out, [{"source": m["kaynak"], "title": m.get("dosya"), "author": m.get("yazar"),
                    "license": m.get("lisans"), "page_url": m.get("sayfa")} for m in manifest if m["durum"] == "bulundu"])
    bulunan = sum(m["durum"] == "bulundu" for m in manifest)
    print(json.dumps({"out": out, "bulunan": bulunan, "toplam": len(manifest),
                      "bulunamayan": [m["id"] for m in manifest if m["durum"] != "bulundu"]}, ensure_ascii=False))


def cmd_url_indir(a):
    out = a.out
    r = rec(source="web", title=a.baslik or "", url=a.url, dl=a.url, page_url=a.sayfa or a.url,
            author=a.yazar or "", license=a.lisans, type=a.tur)
    if engelli(r, kara_liste()):
        sys.exit("kara listede: indirilmedi")
    fn = a.ad or slug(a.baslik or os.path.basename(urllib.parse.urlparse(a.url).path) or "web")
    r["file"] = indir(r, out, fn)
    yol = os.path.join(out, "attribution.json")
    kayitlar = json.load(open(yol)) if os.path.exists(yol) else []
    kayitlar.append(r)
    json.dump(kayitlar, open(yol, "w"), indent=1, ensure_ascii=False)
    yaz_atif(out, [k for k in kayitlar if k.get("file")])
    print(json.dumps({"dosya": os.path.join(out, r["file"]), "lisans": r["license"]}, ensure_ascii=False))


def cmd_ekle(a):
    """Claude'un WebSearch ile bulduğu kayıtları (ör. site:x.com) mevcut aramaya ekle, galeriyi yenile.
    Girdi: [{"source":"x","type":"image|video","title":"...","page_url":"...","author":"@...","thumb":null}]"""
    yol = os.path.join(a.klasor, "sonuclar.json")
    d = json.load(open(yol))
    yeni = json.load(open(a.kayitlar))
    gorulen = {r.get("page_url") for recs in d["sonuclar"].values() for r in recs}
    eklenen = 0
    for r in yeni:
        if r.get("page_url") in gorulen: continue
        r = rec(**{k: v for k, v in r.items() if v is not None})
        r.setdefault("license", "X — telif paylaşanda (yalnız referans)")
        if r["source"] == "x" and not r.get("license"): r["license"] = "X — telif paylaşanda (yalnız referans)"
        d["sonuclar"].setdefault(r["type"], []).append(r); gorulen.add(r.get("page_url")); eklenen += 1
    json.dump(d, open(yol, "w"), indent=1, ensure_ascii=False)
    print(json.dumps({"eklenen": eklenen, "galeri": yaz_galeri(a.klasor, d["sorgu"], d["sonuclar"])}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="komut", required=True)

    p = sp.add_parser("ara"); p.add_argument("sorgu")
    p.add_argument("--tur", default="hepsi", choices=["hepsi", "image", "video"])
    p.add_argument("--hedef", type=int, default=None, help="tür başına sonuç; varsayılan görsel 60, video 10; 0 = sınırsız")
    p.add_argument("--goster", type=int, default=10, help="özette tür başına gösterilecek ilk N kayıt")
    p.add_argument("--katman", default="stok,pd,web,sosyal", help="stok,pd,web,sosyal")
    p.add_argument("--x-adet", type=int, default=20, help="X'ten çekilecek gönderi (ücretli, $0.005/gönderi); 0 = kapalı")
    p.add_argument("--kaynak", help="virgüllü kaynak listesi (katmanı ezer)")
    p.add_argument("--indir", action="store_true"); p.add_argument("--out")
    p.add_argument("--sure", type=int, default=15, help="YouTube için indirilecek saniye")
    p.set_defaults(f=cmd_ara)

    p = sp.add_parser("esle"); p.add_argument("sahneler")
    p.add_argument("--out"); p.add_argument("--katman", default="stok,pd,web")
    p.add_argument("--adet", type=int, default=5)
    p.add_argument("--gorsele-dus", action="store_true", help="video bulunamazsa görsel dene")
    p.set_defaults(f=cmd_esle)

    p = sp.add_parser("url-indir"); p.add_argument("url")
    p.add_argument("--out", required=True); p.add_argument("--sayfa"); p.add_argument("--baslik")
    p.add_argument("--yazar"); p.add_argument("--ad")
    p.add_argument("--lisans", default="bilinmiyor")
    p.add_argument("--tur", default="image", choices=["image", "video"])
    p.set_defaults(f=cmd_url_indir)

    env_yukle()
    p = sp.add_parser("ekle"); p.add_argument("klasor"); p.add_argument("kayitlar")
    p.set_defaults(f=cmd_ekle)

    p = sp.add_parser("kontak", help="Haiku doğrulaması için numaralı önizleme sayfaları (Pillow gerekir)")
    p.add_argument("klasor"); p.add_argument("--dosya", action="store_true", help="indirilen dosyalardan (videoda 4 kare + hareket testi)")
    p.add_argument("--referans", nargs="+", help="konunun güncel görünümü: yerel görsel yolu ya da URL (referans.jpg olur)")
    p.set_defaults(f=cmd_kontak)

    p = sp.add_parser("hareket", help="video gerçek çekim mi, ekran kaydı mı, fotoğraf efekti mi (numpy gerekir)")
    p.add_argument("dosyalar", nargs="+")
    p.set_defaults(f=cmd_hareket)

    p = sp.add_parser("dogrula", help="Haiku kararlarını uygula")
    p.add_argument("klasor"); p.add_argument("--hedef", type=int, default=None, help="tür başına üst sınır; 0 = sınırsız")
    p.add_argument("--indir", action="store_true"); p.add_argument("--sil", action="store_true", help="elenen indirilmiş dosyaları sil")
    p.add_argument("--hareket-serbest", action="store_true", help="hareket testi sonucunu yok say (yalnız Haiku kararı)")
    p.add_argument("--sure", type=int, default=15)
    p.set_defaults(f=cmd_dogrula)

    a = ap.parse_args(); a.f(a)


if __name__ == "__main__":
    main()
