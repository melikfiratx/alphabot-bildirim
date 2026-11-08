"""
Alphabot kisa cekilis bildirimi
- Topluluklarindaki (scope=community), katilmadigin (filter=unregistered),
  aktif (status=active) cekilisleri ceker.
- Toplam suresi MAX_HOURS (varsayilan 8) saat veya daha az olanlari bulur.
- Her cekilis icin Telegram'a TEK bir bildirim atar (seen.json ile hatirlar).
"""
import html
import json
import firo
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

API_KEY = os.environ["ALPHABOT_API_KEY"]
TG_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TG_CHAT = os.environ["TELEGRAM_CHAT_ID"]
MAX_HOURS = float(os.environ.get("MAX_HOURS", "8"))
SEEN_FILE = "seen.json"

# --- Otomatik katilim ayarlari ---
AUTO_JOIN = os.environ.get("AUTO_JOIN", "1") == "1"
HARIC = [w.strip().lower() for w in os.environ.get("HARIC", "").split(",") if w.strip()]
HESAPLAR = [
    ("Chrome", os.environ.get("ALPHABOT_KEY_CHROME", "").strip()),
    ("Edge", API_KEY.strip()),
    ("Firefox", os.environ.get("ALPHABOT_KEY_FIREFOX", "").strip()),
    ("Brave", os.environ.get("ALPHABOT_KEY_BRAVE", "").strip()),
]
CEVIRI = [
    ("already entered", "zaten", "Zaten katılmışsın"),
    ("task", "hata", "Görev eksik"),
    ("requirement", "hata", "Şart eksik"),
    ("ended", "hata", "Çekiliş bitmiş"),
    ("not started", "hata", "Çekiliş henüz başlamadı"),
    ("not found", "hata", "Çekiliş bulunamadı"),
    ("wallet", "hata", "Cüzdan sorunu"),
    ("role", "hata", "Discord rolü yok"),
    ("discord", "hata", "Discord şartı eksik"),
    ("twitter", "hata", "X görevi eksik"),
]


def siniflandir(metin):
    kucuk = str(metin).lower()
    for anahtar, durum, tr in CEVIRI:
        if anahtar in kucuk:
            return durum, tr
    metin = str(metin).replace("\n", " ").strip()
    return "hata", metin[:120]


def kayit_ol(api_key, slug):
    """('ok'|'zaten'|'hata', aciklama)"""
    req = urllib.request.Request(
        "https://api.alphabot.app/v1/register",
        data=json.dumps({"slug": slug}).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                 "User-Agent": "alphabot-bildirim"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            cevap = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            hata = json.load(e)
        except Exception:
            hata = {}
        if e.code == 401:
            return "hata", "API anahtarı geçersiz"
        if e.code == 429:
            return "hata", "Limit aşıldı"
        return siniflandir(hata.get("message") or json.dumps(hata) or f"HTTP {e.code}")
    except Exception as e:
        return "hata", "Bağlantı hatası"
    print(f"[katilim {slug}]", json.dumps(cevap)[:400])
    data = cevap.get("data") or {}
    val = data.get("validation")
    gecersiz = isinstance(val, dict) and (val.get("valid") is False or val.get("success") is False)
    if cevap.get("success") and not gecersiz:
        return "ok", ""
    return siniflandir(data.get("resultMd") or cevap.get("message") or "Bilinmeyen hata")


FIRO = firo.yukle()


def otomatik_katil(slug, r=None):
    """Bildirim mesajina eklenecek satirlari dondurur."""
    ikon = {"ok": "✅", "zaten": "☑️", "hata": "⚠️", "atla": "⏭️"}
    sonuc, gruplar, atlanan = [], {}, []
    for ad, key in HESAPLAR:
        if not key:
            continue
        if firo.atla_mi(FIRO, ad, r):
            sonuc.append(f"{ad} {ikon['atla']}")
            atlanan.append(ad)
            continue
        durum, aciklama = kayit_ol(key, slug)
        sonuc.append(f"{ad} {ikon[durum]}")
        if durum == "hata":
            gruplar.setdefault(aciklama, []).append(ad)
        time.sleep(0.5)
    satirlar = ["🤖 Otomatik katılım: " + "  ".join(sonuc)]
    for aciklama, hesaplar in gruplar.items():
        satirlar.append(f"⚠️ {html.escape(aciklama)} ({', '.join(hesaplar)})")
    if atlanan:
        satirlar.append(f"⏭️ Bu projeden zaten GTD'n var ({', '.join(atlanan)})")
    return satirlar


def to_ms(value):
    """Tarih alanini milisaniyeye cevirir (sayi ya da ISO metin olabilir)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value if value > 1e11 else value * 1000
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000
    except ValueError:
        return None


def sure_yazi(ms):
    dakika = max(0, int(ms // 60000))
    saat, dk = divmod(dakika, 60)
    return f"{saat} sa {dk} dk" if saat else f"{dk} dk"


def get_raffles():
    params = {
        "scope": "community",
        "filter": "unregistered",
        "status": "active",
        "sort": "ending", "sortDir": 1,
        "pageSize": 50,
    }
    url = "https://api.alphabot.app/v1/raffles?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {API_KEY}", "User-Agent": "alphabot-bildirim"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    if not data.get("success"):
        raise RuntimeError(f"Alphabot hata dondu: {data}")
    return data.get("data", {}).get("raffles", [])


def telegram_gonder(metin):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    body = urllib.parse.urlencode(
        {"chat_id": TG_CHAT, "text": metin, "parse_mode": "HTML", "disable_web_page_preview": "true"}
    ).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=30) as resp:
        resp.read()


def main():
    try:
        with open(SEEN_FILE) as f:
            seen = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        seen = {}

    try:
        raffles = get_raffles()
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print("Rate limit (429) - bu tur atlaniyor.")
            return
        print(f"Alphabot HTTP hatasi: {e.code} {e.read()[:300]!r}")
        sys.exit(1)

    print(f"{len(raffles)} cekilis geldi.")
    if raffles:
        print("Ornek alan adlari:", sorted(raffles[0].keys()))

    now = time.time() * 1000
    yeni = 0
    for r in raffles:
        rid = str(r.get("_id") or r.get("id") or r.get("slug"))
        start, end = to_ms(r.get("startDate")), to_ms(r.get("endDate"))
        if not rid or start is None or end is None or rid in seen:
            continue
        toplam = end - start
        if toplam > MAX_HOURS * 3600 * 1000 or end <= now:
            continue

        ad = html.escape(str(r.get("name") or "Isimsiz cekilis"))
        link = f"https://www.alphabot.app/{r.get('slug')}" if r.get("slug") else "https://www.alphabot.app/raffles"
        satirlar = [
            f"⏰ <b>Kısa çekiliş: {ad}</b>",
            f"Toplam süre: {sure_yazi(toplam)}",
            f"Kalan süre: {sure_yazi(end - now)}",
        ]
        if r.get("winnerCount") is not None:
            satirlar.append(f"Kazanan sayısı: {r.get('winnerCount')}")
        satirlar.append(link)

        if AUTO_JOIN and r.get("slug"):
            ad_kucuk = str(r.get("name") or "").lower()
            if any(w in ad_kucuk for w in HARIC):
                satirlar.append("🚫 Hariç listesinde, otomatik katılım yapılmadı")
            else:
                satirlar += otomatik_katil(r["slug"], r)

        telegram_gonder("\n".join(satirlar))
        seen[rid] = end
        yeni += 1
        time.sleep(1)

    # 2 gunden eski kayitlari temizle
    seen = {k: v for k, v in seen.items() if v > now - 2 * 86400 * 1000}
    with open(SEEN_FILE, "w") as f:
        json.dump(seen, f, indent=1, sort_keys=True)
    print(f"{yeni} yeni bildirim gonderildi.")


if __name__ == "__main__":
    main()
