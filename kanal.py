"""
Kanal okuyucu (10 dakikada bir)
- Senin Telegram hesabinla (oturum anahtari) House kanalini ve Heathside grubunun
  Giveaways konusunu okur.
- Yeni mesajlardaki alphabot.app linklerini bulur (yazili linkler, kelimeye gizlenmis
  linkler ve butonlar dahil).
- 4 hesapla katilir (Firo + ikinci deneme), sonucu @AlphaKatilimBot'tan yazar.
- Sadece OKUR; senin adina mesaj atmaz, gruplara bir sey yazmaz.
"""
import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import InputPeerChannel

import firo
import katilim as kt

API_ID = int(os.environ["TG_API_ID"].strip())
API_HASH = os.environ["TG_API_HASH"].strip()
SESSION = os.environ["TG_SESSION"].strip()

# (gorunen ad, kullanici adi, konu numarasi ya da None)
KAYNAKLAR = [
    ("House", "houseweb3channel", None),
    ("Heathside", "Heathside", 31187),
]
DOSYA = "kanal_durum.json"
ILK_CALISMA_SAAT = 6  # ilk calismada son 6 saatin mesajlarina bakilir
TEKRAR_YOK = ("Çekiliş bitmiş", "Çekiliş bulunamadı", "API anahtarı geçersiz", "Çekiliş henüz başlamadı")


def durum_yukle():
    try:
        with open(DOSYA) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def durum_kaydet(durum):
    with open(DOSYA, "w") as f:
        json.dump(durum, f, indent=1, sort_keys=True)


def mesajdaki_linkler(msg):
    """Yazili linkler + kelimeye gizlenmis linkler + butonlar + onizleme."""
    metinler = [msg.message or ""]
    for ent in msg.entities or []:
        url = getattr(ent, "url", None)
        if url:
            metinler.append(url)
    markup = getattr(msg, "reply_markup", None)
    for satir in getattr(markup, "rows", None) or []:
        for b in satir.buttons:
            url = getattr(b, "url", None)
            if url:
                metinler.append(url)
    webpage = getattr(getattr(msg, "media", None), "webpage", None)
    if getattr(webpage, "url", None):
        metinler.append(webpage.url)
    sluglar = []
    for m in metinler:
        for s in kt.LINK_RE.findall(m):
            if s.lower() not in kt.SAYFA_ADLARI and s not in sluglar:
                sluglar.append(s)
    return sluglar


async def kaynak_oku(client, durum, ad, kullanici, konu):
    k = durum.setdefault(ad, {})
    # Kullanici adini her seferinde sormamak icin kimligi sakla (Telegram siniri)
    if k.get("id") and k.get("hash"):
        peer = InputPeerChannel(int(k["id"]), int(k["hash"]))
        forum = k.get("forum", False)
    else:
        ent = await client.get_entity(kullanici)
        peer = InputPeerChannel(ent.id, ent.access_hash)
        forum = bool(getattr(ent, "forum", False))
        k.update({"id": ent.id, "hash": ent.access_hash, "forum": forum})

    son_id = k.get("son_id", 0)
    kw = {"limit": 100 if son_id else 30}
    if son_id:
        kw["min_id"] = son_id
    if konu and forum:
        kw["reply_to"] = konu

    sinir = datetime.now(timezone.utc) - timedelta(hours=ILK_CALISMA_SAAT)
    bulunan, en_buyuk = [], son_id
    async for msg in client.iter_messages(peer, **kw):
        en_buyuk = max(en_buyuk, msg.id)
        if not son_id and msg.date and msg.date < sinir:
            continue
        for s in mesajdaki_linkler(msg):
            if s not in bulunan:
                bulunan.append(s)
    k["son_id"] = en_buyuk
    print(f"{ad}: {len(bulunan)} alphabot linki bulundu (son mesaj {en_buyuk})")
    return bulunan


async def kanallari_oku(durum):
    client = TelegramClient(StringSession(SESSION), API_ID, API_HASH,
                            device_model="Alphabot Kanal Okuyucu", app_version="1.0")
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise SystemExit("HATA: Telegram oturumu gecersiz. TG_SESSION'i yeniden olustur.")
    sonuc = {}
    try:
        for ad, kullanici, konu in KAYNAKLAR:
            try:
                sonuc[ad] = await kaynak_oku(client, durum, ad, kullanici, konu)
            except Exception as e:
                print(f"{ad} okunamadi: {e!r}")
                sonuc[ad] = []
    finally:
        await client.disconnect()
    return sonuc


def katil_ve_raporla(kaynak_sluglari):
    sluglar, nereden = [], {}
    for ad, liste in kaynak_sluglari.items():
        for s in liste:
            if s not in sluglar:
                sluglar.append(s)
                nereden[s] = ad
    aktif = [(ad, key) for ad, key in kt.HESAPLAR if key]
    ozet = ", ".join(f"{ad}: {len(l)}" for ad, l in kaynak_sluglari.items() if l)
    kt.mesaj_at(f"📡 Kanallarda {len(sluglar)} yeni çekiliş bulundu ({ozet}), {len(aktif)} hesapla katılıyorum...")

    # Firo icin cekilis bilgisi
    firo_veri = firo.yukle()
    bilgi = {}
    if firo_veri:
        for i, s in enumerate(sluglar):
            bilgi[s] = kt.tek_cekilis(s, aktif[i % len(aktif)][1])
            time.sleep(0.5)

    sonuclar = {s: {} for s in sluglar}
    for ad, key in aktif:
        for s in sluglar:
            if firo.atla_mi(firo_veri, ad, bilgi.get(s)):
                sonuclar[s][ad] = ("atla", "")
                continue
            sonuclar[s][ad] = kt.kayit_ol(key, s)
            time.sleep(kt.BEKLEME_SN)

    # Ikinci deneme
    tekrar = [(s, ad, key) for ad, key in aktif for s in sluglar
              if sonuclar[s][ad][0] == "hata" and not sonuclar[s][ad][1].startswith(TEKRAR_YOK)]
    duzelen = 0
    if tekrar:
        time.sleep(60)
        for s, ad, key in tekrar:
            d, a = kt.kayit_ol(key, s)
            if d in ("ok", "zaten"):
                d, a = "ok", ""
                duzelen += 1
            else:
                a += " (2 kez denendi)"
            sonuclar[s][ad] = (d, a)
            time.sleep(kt.BEKLEME_SN)

    IKON = {"ok": "✅", "zaten": "☑️", "hata": "⚠️", "atla": "⏭️"}
    sayac = {"ok": 0, "zaten": 0, "hata": 0, "atla": 0}
    satirlar, sorunlar = [], []
    for s in sluglar:
        for ad, _ in aktif:
            sayac[sonuclar[s][ad][0]] += 1
        satirlar.append(f"• {s}  ({nereden[s]})\n   " +
                        "  ".join(f"{ad} {IKON[sonuclar[s][ad][0]]}" for ad, _ in aktif))
        gruplar = {}
        for ad, _ in aktif:
            d, a = sonuclar[s][ad]
            if d == "hata":
                gruplar.setdefault(a, []).append(ad)
        for aciklama, hesaplar in gruplar.items():
            sorunlar.append(f"⚠️ {aciklama} ({', '.join(hesaplar)})\n   https://www.alphabot.app/{s}")

    ust = (f"📡 Kanal katılımı bitti\n✅ {sayac['ok']} yeni   ☑️ {sayac['zaten']} zaten   "
           f"⚠️ {sayac['hata']} sorun   ⏭️ {sayac['atla']} GTD'n var")
    if duzelen:
        ust += f"\n🔁 {duzelen} kayıt ikinci denemede tamamlandı"
    mesaj = [ust, ""] + satirlar
    if sorunlar:
        mesaj += ["", "Sorunlu olanlar:"] + sorunlar
    kt.mesaj_at("\n".join(mesaj))


def main():
    durum = durum_yukle()
    kaynak_sluglari = asyncio.run(kanallari_oku(durum))

    # Daha once islenen linkleri tekrar isleme
    gorulen = durum.setdefault("_gorulen", [])
    for ad in kaynak_sluglari:
        kaynak_sluglari[ad] = [s for s in kaynak_sluglari[ad] if s not in gorulen]
    yeni = sorted({s for l in kaynak_sluglari.values() for s in l})
    gorulen.extend(yeni)
    durum["_gorulen"] = gorulen[-1000:]
    durum_kaydet(durum)  # once kaydet: katilim yarida kalsa bile ayni linkler tekrar islenmez

    if not yeni:
        print("Yeni alphabot linki yok.")
        return
    katil_ve_raporla(kaynak_sluglari)


if __name__ == "__main__":
    main()
