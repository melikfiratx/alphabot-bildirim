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


# ---------------- 2) Alphabot takvimi (gunluk) ----------------
def kitap_adlari():
    """kazanclar.txt: @kullanici -> o kullanici adinin gectigi satirlar"""
    adlar = {}
    try:
        with open("kazanclar.txt", encoding="utf-8") as f:
            for satir in f:
                satir = satir.strip()
                for k in KULLANICI_RE.findall(satir):
                    adlar.setdefault(k.lower(), []).append(satir)
    except FileNotFoundError:
        pass
    return adlar


def takvim_getir(api_key, sayfa, durum=None):
    params = {"scope": "all", "sort": "minting", "sortDir": 1, "pageSize": 50, "pageNum": sayfa}
    if durum:
        params["status"] = durum
    url = "https://api.alphabot.app/v1/raffles?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}",
                                               "User-Agent": "alphabot-mint"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r).get("data", {})
    return data.get("raffles", []), data.get("finalPage", True)


def x_adi(url):
    url = str(url or "").strip()
    return url.rstrip("/").split("?")[0].split("/")[-1].lstrip("@").lower() if url else ""


def gunluk():
    api_key = os.environ["ALPHABOT_API_KEY"].strip()
    bugun = datetime.now(TR).date()
    kitap = kitap_adlari()
    bugunku, gorulen = {}, 0
    for durum in (None, "ended", "finalized"):
        sayfa, sayi, bugun_sayi, ornek_tarihler = 0, 0, 0, []
        while sayfa < 6:
            try:
                raffles, son = takvim_getir(api_key, sayfa, durum)
            except Exception as e:
                print(f"[{durum}] takvim alinamadi:", e)
                break
            sayi += len(raffles)
            gecti = False
            for r in raffles:
                md = r.get("mintDate")
                if not md:
                    continue
                zaman = datetime.fromtimestamp(md / 1000 if md > 1e11 else md, TR)
                if len(ornek_tarihler) < 3:
                    ornek_tarihler.append(zaman.strftime("%d.%m"))
                if zaman.date() > bugun:
                    gecti = True
                    continue
                if zaman.date() == bugun:
                    x = x_adi(r.get("twitterUrl"))
                    if x and x not in bugunku:
                        bugun_sayi += 1
                        bugunku[x] = zaman.strftime("%H:%M") if r.get("mintDateHasTime") else ""
            if son or gecti:
                break
            sayfa += 1
            time.sleep(2)
        gorulen += sayi
        print(f"[durum={durum or 'hepsi'}] {sayi} cekilis, bugun mint: {bugun_sayi}, ilk mint tarihleri: {ornek_tarihler}")
        time.sleep(2)
    print(f"Takvimde {gorulen} cekilis tarandi, bugun mint olan {len(bugunku)} proje bulundu: {sorted(bugunku)}")

    # Yedek: 4 hesabin kendi kazanclarindaki mint tarihleri (takvimde cikmazsa diye)
    try:
        import kazanan as kz
        for ad, key in kz.HESAPLAR:
            if not key:
                continue
            for sayfa_no in range(10):
                raffles = kz.kazananlari_getir(key, sayfa_no)
                for r in raffles:
                    md = r.get("mintDate")
                    if not md:
                        continue
                    zaman = datetime.fromtimestamp(md / 1000 if md > 1e11 else md, TR)
                    x = x_adi(r.get("twitterUrl"))
                    if zaman.date() == bugun and x and x not in bugunku:
                        bugunku[x] = zaman.strftime("%H:%M") if r.get("mintDateHasTime") else ""
                        kitap.setdefault(x, []).append(kz.bicimle(ad, r))
                if getattr(kz.kazananlari_getir, "son_sayfa", True):
                    break
                time.sleep(2)
            time.sleep(1)
    except Exception as e:
        print("Kazanc kontrolu yapilamadi:", e)

    tarih = bugun.strftime("%d.%m.%Y")
    eslesen = {x: kitap[x] for x in bugunku if x in kitap}
    if eslesen:
        satirlar = [f"🗓️ Alphabot takvimine göre BUGÜN ({tarih}) mintin var! ({len(eslesen)} proje)", ""]
        for x, ilgili in eslesen.items():
            saat = bugunku[x]
            satirlar.append(f"• @{x}" + (f"  ⏰ {saat}" if saat else ""))
            for satir in ilgili:
                satirlar.append(f"   {satir}")
        satirlar += ["", "Not: Tarihler Alphabot'tan geliyor, X'ten teyit etmeyi unutma."]
    else:
        satirlar = [f"🗓️ Alphabot takvimine göre bugün ({tarih}) mintin yok.",
                    f"(Takvimde bugün {len(bugunku)} proje var, hiçbiri kazanclar.txt ile eşleşmedi.)"]
    print("\n".join(satirlar))
    mesaj_at("\n".join(satirlar))


if __name__ == "__main__":
    mod = sys.argv[1] if len(sys.argv) > 1 else "dinle"
    gunluk() if mod == "gunluk" else dinle()
