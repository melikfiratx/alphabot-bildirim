"""
Alphabot otomatik katilim
- JOIN botuna (Telegram) senin attigin mesajlardaki alphabot.app linklerini okur.
- Her linke 4 hesapla (Chrome, Edge, Firefox, Brave) Alphabot API uzerinden katilir.
- X / Twitter linklerini ve diger linkleri atlar; hicbir gorev yapmaz.
- Sonucu ayni bota mesaj olarak yazar.
"""
import json
import firo
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
LINK_RE = re.compile(r"alphabot\.app/([A-Za-z0-9_-]+)", re.IGNORECASE)


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
    """(durum, aciklama) dondurur. durum: 'ok' | 'zaten' | 'hata'"""
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
            print(f"[{slug}] HTTP {e.code}:", json.dumps(hata)[:600])
            if e.code == 401:
                return "hata", "API anahtarı geçersiz"
            return siniflandir(hata_metni(hata) or f"HTTP {e.code}")
        except Exception as e:  # ag hatasi vs.
            return "hata", "Bağlantı hatası: " + kisalt(str(e), 80)
    else:
        return "hata", "Limit aşıldı, sonra tekrar dene"

    print(f"[{slug}] cevap:", json.dumps(cevap)[:600])
    data = cevap.get("data") or {}
    sonuc = data.get("resultMd") or ""
    val = data.get("validation")
    gecersiz = isinstance(val, dict) and (val.get("valid") is False or val.get("success") is False)
    if cevap.get("success") and not gecersiz:
        return "ok", ""
    return siniflandir(sonuc or hata_metni(cevap) or "Bilinmeyen hata")


CEVIRI = [
    ("already entered", "zaten", "Zaten katılmışsın"),
    ("task", "hata", "Görev eksik"),
    ("requirement", "hata", "Şart eksik"),
    ("has ended", "hata", "Çekiliş bitmiş"),
    ("ended", "hata", "Çekiliş bitmiş"),
    ("not started", "hata", "Çekiliş henüz başlamadı"),
    ("not found", "hata", "Çekiliş bulunamadı (link hatalı olabilir)"),
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
    return "hata", kisalt(metin)


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


# ---------------- Firo islemi ----------------
def tek_cekilis(slug, api_key):
    """Cekilisin projectId / twitterUrl bilgisini getirir. Olmazsa None."""
    url = "https://api.alphabot.app/v1/raffles/" + urllib.parse.quote(slug)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}",
                                               "User-Agent": "alphabot-katilim"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            cevap = json.load(r)
    except urllib.error.HTTPError as e:
        print(f"[firo {slug}] HTTP {e.code}")
        return None
    except Exception as e:
        print(f"[firo {slug}] {e}")
        return None
    data = cevap.get("data") or {}
    if isinstance(data, dict) and isinstance(data.get("raffle"), dict):
        data = data["raffle"]
    return data if isinstance(data, dict) else None


# ---------------- Ana akis ----------------
def main():
    try:
        guncellemeler = tg("getUpdates", {"timeout": 0}).get("result", [])
    except Exception as e:
        print("Telegram'a ulasilamadi, sonraki turda denenecek:", e)
        return
    if not guncellemeler:
        print("Yeni mesaj yok.")
        return
    son_id = max(u["update_id"] for u in guncellemeler)
    tg("getUpdates", {"offset": son_id + 1, "timeout": 0})

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

    # Firo: her cekilisin projesini ogren (anahtarlar sirayla kullanilir)
    firo_veri = firo.yukle()
    bilgi, basarisiz = {}, 0
    for i, s in enumerate(sluglar):
        if not firo_veri or basarisiz >= 3 and not any(bilgi.values()):
            break
        bilgi[s] = tek_cekilis(s, aktif[i % len(aktif)][1])
        if bilgi[s] is None:
            basarisiz += 1
        time.sleep(0.5)
    firo_calisti = any(bilgi.values())

    sonuclar = {s: {} for s in sluglar}
    for ad, key in aktif:
        for s in sluglar:
            if firo.atla_mi(firo_veri, ad, bilgi.get(s)):
                sonuclar[s][ad] = ("atla", "")
                continue
            sonuclar[s][ad] = kayit_ol(key, s)
            time.sleep(BEKLEME_SN)

    # Ikinci deneme: hata alanlari bir kez daha dene
    TEKRAR_YOK = ("Çekiliş bitmiş", "Çekiliş bulunamadı", "API anahtarı geçersiz", "Çekiliş henüz başlamadı")
    tekrar = [(s, ad, key) for ad, key in aktif for s in sluglar
              if sonuclar[s][ad][0] == "hata" and not sonuclar[s][ad][1].startswith(TEKRAR_YOK)]
    duzelen = 0
    if tekrar:
        print(f"{len(tekrar)} kayit ikinci kez denenecek")
        time.sleep(60)
        for s, ad, key in tekrar:
            d, a = kayit_ol(key, s)
            if d in ("ok", "zaten"):
                d, a = "ok", ""
                duzelen += 1
            else:
                a = a + " (2 kez denendi)"
            sonuclar[s][ad] = (d, a)
            time.sleep(BEKLEME_SN)

    # Rapor
    IKON = {"ok": "✅", "zaten": "☑️", "hata": "⚠️", "atla": "⏭️"}
    sayac = {"ok": 0, "zaten": 0, "hata": 0, "atla": 0}
    satirlar, sorunlar = [], []
    for s in sluglar:
        for ad, _ in aktif:
            sayac[sonuclar[s][ad][0]] += 1
        satirlar.append(f"• {s}\n   " + "  ".join(f"{ad} {IKON[sonuclar[s][ad][0]]}" for ad, _ in aktif))
        # ayni sebebi tek satirda topla
        gruplar = {}
        for ad, _ in aktif:
            durum, aciklama = sonuclar[s][ad]
            if durum == "hata":
                gruplar.setdefault(aciklama, []).append(ad)
        for aciklama, hesaplar in gruplar.items():
            sorunlar.append(f"⚠️ {aciklama} ({', '.join(hesaplar)})\n   https://www.alphabot.app/{s}")

    ust = f"✅ {sayac['ok']} yeni katılım   ☑️ {sayac['zaten']} zaten katılmış   ⚠️ {sayac['hata']} sorun"
    if sayac["atla"]:
        ust += f"   ⏭️ {sayac['atla']} atlandı (GTD'n var)"
    if duzelen:
        ust += f"\n🔁 {duzelen} kayıt ikinci denemede tamamlandı"
    mesaj = [ust, ""] + satirlar
    if sorunlar:
        mesaj += ["", "Sorunlu olanlar:"] + sorunlar
    if eksik:
        mesaj += ["", "Anahtarı olmadığı için atlanan hesaplar: " + ", ".join(eksik)]
    if firo_veri and not firo_calisti:
        mesaj += ["", "ℹ️ Firo kontrolü yapılamadı (çekiliş bilgisi alınamadı), tüm hesaplarla denendi."]
    mesaj += ["", "✅ katıldı · ☑️ zaten katılmıştın · ⚠️ sorun var · ⏭️ projeden GTD'n var, atlandı"]
    mesaj_at("\n".join(mesaj))

    # Mesajlari islenmis olarak isaretle (tekrar islenmesin)
    tg("getUpdates", {"offset": son_id + 1, "timeout": 0})


if __name__ == "__main__":
    main()
