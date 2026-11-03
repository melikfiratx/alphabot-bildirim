"""
Alphabot otomatik katilim
- JOIN botuna (Telegram) senin attigin mesajlardaki alphabot.app linklerini okur.
- Her linke 4 hesapla (Chrome, Edge, Firefox, Brave) Alphabot API uzerinden katilir.
- X / Twitter linklerini ve diger linkleri atlar; hicbir gorev yapmaz.
- Sonucu ayni bota mesaj olarak yazar.
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

BOT_TOKEN = os.environ["JOIN_BOT_TOKEN"].strip()
OWNER_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"].strip()

HESAPLAR = [
    ("Chrome", os.environ.get("ALPHABOT_KEY_CHROME", "").strip()),
    ("Edge", os.environ.get("ALPHABOT_API_KEY", "").strip()),
    ("Firefox", os.environ.get("ALPHABOT_KEY_FIREFOX", "").strip()),
    ("Brave", os.environ.get("ALPHABOT_KEY_BRAVE", "").strip()),
]

BEKLEME_SN = 1.5  # her kayit arasi (limit: dakikada 100)
SAYFA_ADLARI = {
    "raffles", "projects", "calendar", "dashboard", "settings", "premium",
    "raids", "collabs", "create", "team", "news", "docs", "login",
}
LINK_RE = re.compile(r"alphabot\.app/([A-Za-z0-9][A-Za-z0-9_-]*)", re.IGNORECASE)


# ---------------- Telegram ----------------
def tg(method, params):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    body = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=40) as r:
        return json.load(r)


def mesaj_at(metin):
    # Telegram mesaj siniri 4096 karakter; uzunsa bol
    while metin:
        parca, metin = metin[:4000], metin[4000:]
        tg("sendMessage", {"chat_id": OWNER_CHAT_ID, "text": parca, "disable_web_page_preview": "true"})


# ---------------- Alphabot ----------------
def kayit_ol(api_key, slug):
    """(basarili_mi, kisa_aciklama) dondurur."""
    req = urllib.request.Request(
        "https://api.alphabot.app/v1/register",
        data=json.dumps({"slug": slug}).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "alphabot-katilim",
        },
        method="POST",
    )
    for deneme in range(2):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                cevap = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and deneme == 0:
                print("429 - 60 sn bekleniyor")
                time.sleep(60)
                continue
            try:
                hata = json.load(e)
            except Exception:
                hata = {}
            return False, kisalt(hata_metni(hata) or f"HTTP {e.code}")
        except Exception as e:  # ag hatasi vs.
            return False, kisalt(str(e))
    else:
        return False, "Rate limit (429)"

    print(f"[{slug}] cevap:", json.dumps(cevap)[:600])
    data = cevap.get("data") or {}
    sonuc = data.get("resultMd") or ""
    val = data.get("validation")
    gecersiz = isinstance(val, dict) and (val.get("valid") is False or val.get("success") is False)
    if cevap.get("success") and not gecersiz:
        return True, kisalt(sonuc)
    return False, kisalt(sonuc or hata_metni(cevap) or "Bilinmeyen hata")


def hata_metni(obj):
    if not isinstance(obj, dict):
        return ""
    for k in ("message", "error", "errors"):
        v = obj.get(k)
        if v:
            return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    d = obj.get("data")
    return hata_metni(d) if isinstance(d, dict) else ""


def kisalt(metin, n=160):
    metin = re.sub(r"[*_`#>\[\]]", "", str(metin)).replace("\n", " ").strip()
    return metin if len(metin) <= n else metin[: n - 1] + "…"


# ---------------- Ana akis ----------------
def main():
    guncellemeler = tg("getUpdates", {"timeout": 0}).get("result", [])
    if not guncellemeler:
        print("Yeni mesaj yok.")
        return
    son_id = max(u["update_id"] for u in guncellemeler)

    sluglar, link_yok = [], False
    for u in guncellemeler:
        msg = u.get("message") or u.get("edited_message") or {}
        if str(msg.get("chat", {}).get("id")) != OWNER_CHAT_ID:
            continue  # sadece senden gelen mesajlar
        metin = msg.get("text") or msg.get("caption") or ""
        bulunan = [s for s in LINK_RE.findall(metin) if s.lower() not in SAYFA_ADLARI]
        if not bulunan and not metin.startswith("/start"):
            link_yok = True
        for s in bulunan:
            if s not in sluglar:
                sluglar.append(s)

    if not sluglar:
        if link_yok:
            mesaj_at("Mesajında alphabot.app linki bulamadım. Linkleri alt alta yapıştırıp gönder.")
        tg("getUpdates", {"offset": son_id + 1, "timeout": 0})
        return

    aktif = [(ad, k) for ad, k in HESAPLAR if k]
    eksik = [ad for ad, k in HESAPLAR if not k]
    mesaj_at(f"⏳ {len(sluglar)} çekiliş alındı, {len(aktif)} hesapla katılıyorum...")

    sonuclar = {s: {} for s in sluglar}
    for ad, key in aktif:
        for s in sluglar:
            sonuclar[s][ad] = kayit_ol(key, s)
            time.sleep(BEKLEME_SN)

    # Rapor
    toplam = sum(1 for s in sluglar for ad, _ in aktif if sonuclar[s][ad][0])
    satirlar = [f"✅ Bitti: {toplam}/{len(sluglar) * len(aktif)} katılım başarılı", ""]
    notlar = []
    for s in sluglar:
        ikonlar = "  ".join(f"{ad} {'✅' if sonuclar[s][ad][0] else '⚠️'}" for ad, _ in aktif)
        satirlar.append(f"• {s}\n   {ikonlar}")
        for ad, _ in aktif:
            ok, aciklama = sonuclar[s][ad]
            if not ok:
                notlar.append(f"⚠️ {ad} – {s}: {aciklama}")
    if notlar:
        satirlar += ["", "Atlananlar / hatalar:"] + notlar
    if eksik:
        satirlar += ["", "Anahtarı olmadığı için atlanan hesaplar: " + ", ".join(eksik)]
    mesaj_at("\n".join(satirlar))

    # Mesajlari islenmis olarak isaretle (tekrar islenmesin)
    tg("getUpdates", {"offset": son_id + 1, "timeout": 0})


if __name__ == "__main__":
    main()
