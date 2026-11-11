"""
Alpha Mint botu (ayri Telegram botu)
Kullanim:
  python3 mint_bot.py dinle   -> Bota yapistirilan @kullanici adlarini kazanclar.txt ile eslestirir
  python3 mint_bot.py gunluk  -> Alphabot'taki kazanclardan mint tarihi BUGUN olanlari bildirir
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BOT_TOKEN = os.environ["MINT_BOT_TOKEN"].strip()
OWNER_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"].strip()
TR = timezone(timedelta(hours=3))
KULLANICI_RE = re.compile(r"@([A-Za-z0-9_]{2,15})")


# ---------------- Telegram ----------------
def tg(method, params):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    body = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=40) as r:
        return json.load(r)


def mesaj_at(metin):
    while metin:
        parca, metin = metin[:4000], metin[4000:]
        tg("sendMessage", {"chat_id": OWNER_CHAT_ID, "text": parca, "disable_web_page_preview": "true"})


# ---------------- 1) Yapistirilan listeyi eslestir ----------------
def eslestir(metinler):
    aranan = []
    for m in metinler:
        for k in KULLANICI_RE.findall(m):
            if k.lower() not in [a.lower() for a in aranan]:
                aranan.append(k)
    if not aranan:
        return "Mesajında @kullanıcı adı bulamadım. X'ten bulduğun @adları yapıştırıp gönder."
    try:
        with open("kazanclar.txt", encoding="utf-8") as f:
            satirlar = [l.strip() for l in f if l.strip()]
    except FileNotFoundError:
        satirlar = []
    eslesen = {}
    for satir in satirlar:
        satir_adlari = {k.lower() for k in KULLANICI_RE.findall(satir)}
        for k in aranan:
            if k.lower() in satir_adlari:
                eslesen.setdefault("@" + k, []).append(satir)
    if not eslesen:
        return (f"🔍 {len(aranan)} kullanıcı adını kontrol ettim.\n"
                "Bu listede senin kazandığın bir proje yok. ✅")
    mesaj = [f"🔔 BUGÜN MİNTİN VAR! ({len(eslesen)} proje)", ""]
    for k, ilgili in eslesen.items():
        mesaj.append(f"• {k}")
        for satir in ilgili:
            mesaj.append(f"   {satir}")
    mesaj += ["", f"(Toplam {len(aranan)} kullanıcı adı kontrol edildi.)"]
    return "\n".join(mesaj)


def dinle():
    try:
        guncellemeler = tg("getUpdates", {"timeout": 0}).get("result", [])
    except Exception as e:
        print("Telegram'a ulasilamadi, sonraki turda denenecek:", e)
        return
    if not guncellemeler:
        print("Yeni mesaj yok.")
        return
    son_id = max(u["update_id"] for u in guncellemeler)
    tg("getUpdates", {"offset": son_id + 1, "timeout": 0})  # okundu say
    metinler = []
    for u in guncellemeler:
        msg = u.get("message") or u.get("edited_message") or {}
        if str(msg.get("chat", {}).get("id")) != OWNER_CHAT_ID:
            continue
        metin = msg.get("text") or msg.get("caption") or ""
        if metin.startswith("/start"):
            continue
        metinler.append(metin)
    if metinler:
        mesaj_at(eslestir(metinler))


# ---------------- 2) Alphabot gunluk kontrol ----------------
def gunluk():
    import kazanan as kz  # kazanc takibinin fonksiyonlarini kullanir
    bugun = datetime.now(TR).date()
    bulunan, hatalar = [], []
    for ad, key in kz.HESAPLAR:
        if not key:
            continue
        sayfa = 0
        while True:
            try:
                raffles = kz.kazananlari_getir(key, sayfa)
            except Exception as e:
                hatalar.append(f"{ad}: {e}")
                break
            for r in raffles:
                md = r.get("mintDate")
                if not md:
                    continue
                zaman = datetime.fromtimestamp(md / 1000 if md > 1e11 else md, TR)
                if zaman.date() == bugun:
                    saat = zaman.strftime("%H:%M") if r.get("mintDateHasTime") else ""
                    bulunan.append((zaman, kz.bicimle(ad, r), saat))
            sayfa += 1
            if getattr(kz.kazananlari_getir, "son_sayfa", True) or sayfa >= 10:
                break
            time.sleep(2)
        time.sleep(1)

    tarih = bugun.strftime("%d.%m.%Y")
    if bulunan:
        bulunan.sort(key=lambda x: x[0])
        satirlar = [f"🗓️ Alphabot'a göre BUGÜN ({tarih}) mintin var! ({len(bulunan)})", ""]
        for _, bicim, saat in bulunan:
            satirlar.append(f"• {bicim}" + (f"  ⏰ {saat}" if saat else ""))
        satirlar += ["", "Not: Tarihler Alphabot'tan geliyor, X'ten teyit etmeyi unutma."]
    else:
        satirlar = [f"🗓️ Alphabot'a göre bugün ({tarih}) mintin yok."]
    if hatalar:
        satirlar += ["", "Kontrol edilemeyen hesaplar: " + "; ".join(hatalar)]
    print("\n".join(satirlar))
    mesaj_at("\n".join(satirlar))


if __name__ == "__main__":
    mod = sys.argv[1] if len(sys.argv) > 1 else "dinle"
    gunluk() if mod == "gunluk" else dinle()
