"""
Gunluk otomatik katilim (her gun 00:00 ve 16:00)
- Edge hesabinin listesi: My communities + Unregistered + aktif, en yakinda biten once.
- 00:00 turu: ayni gun 16:00'ya kadar bitecekler. 16:00 turu: gece 00:00'a kadar bitecekler.
- 4 hesapla katilir (Firo: GTD'si olan hesap atlanir), hata alanlari 1 kez daha dener.
- Sonucu @AlphaKatilimBot'tan yazar. katilim.py ve firo.py'yi kullanir.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import firo
import katilim as kt

EDGE_KEY = os.environ["ALPHABOT_API_KEY"].strip()
MAX_WINNERS = int(os.environ.get("MAX_WINNERS", "0") or 0)  # 0 = sinir yok
HARIC = [w.strip().lower() for w in os.environ.get("HARIC", "").split(",") if w.strip()]
TR = timezone(timedelta(hours=3))
BEKLEME_SN = 0.7
TEKRAR_YOK = ("Çekiliş bitmiş", "Çekiliş bulunamadı", "API anahtarı geçersiz", "Çekiliş henüz başlamadı")


def to_ms(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v if v > 1e11 else v * 1000
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp() * 1000
    except ValueError:
        return None


def pencere_sonu(simdi):
    """Bir sonraki sinir: 16:00 ya da 00:00 (en az 30 dk sonrasi)."""
    gun = simdi.replace(hour=0, minute=0, second=0, microsecond=0)
    for aday in (gun + timedelta(hours=16), gun + timedelta(days=1), gun + timedelta(days=1, hours=16)):
        if aday > simdi + timedelta(minutes=30):
            return aday


def sayfa_getir(sayfa):
    params = {"scope": "community", "filter": "unregistered", "status": "active",
              "sort": "ending", "sortDir": 1, "pageSize": 50, "pageNum": sayfa}
    url = "https://api.alphabot.app/v1/raffles?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {EDGE_KEY}",
                                               "User-Agent": "alphabot-gunluk"})
    for deneme in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.load(r).get("data", {})
            return d.get("raffles", []), d.get("finalPage", True)
        except urllib.error.HTTPError as e:
            if e.code == 429 and deneme < 2:
                print("429 (limit) - 2 dk bekleniyor")
                time.sleep(120)
                continue
            raise
    return [], True


def cekilisleri_getir(sinir_ms):
    hepsi, eksik = [], False
    for sayfa in range(6):
        try:
            raffles, son = sayfa_getir(sayfa)
        except Exception as e:
            print(f"Sayfa {sayfa} alinamadi: {e}")
            eksik = True
            break
        hepsi += raffles
        bitisler = [to_ms(r.get("endDate")) for r in raffles]
        if son or not raffles or (bitisler[-1] and bitisler[-1] > sinir_ms):
            break
        time.sleep(3)
    return hepsi, eksik


def main():
    simdi = datetime.now(TR)
    sinir = pencere_sonu(simdi)
    simdi_ms, sinir_ms = simdi.timestamp() * 1000, sinir.timestamp() * 1000
    etiket = f"{simdi.strftime('%H:%M')} → {sinir.strftime('%d.%m %H:%M')}"

    raffles, eksik = cekilisleri_getir(sinir_ms)
    print(f"{len(raffles)} cekilis geldi, pencere: {etiket}")

    secilen, atlanan_cok, atlanan_haric = [], [], []
    for r in raffles:
        end, slug = to_ms(r.get("endDate")), r.get("slug")
        if not slug or end is None or not (simdi_ms < end <= sinir_ms):
            continue
        ad = str(r.get("name") or slug)
        wc = r.get("winnerCount")
        if MAX_WINNERS and isinstance(wc, (int, float)) and wc > MAX_WINNERS:
            atlanan_cok.append(ad)
        elif any(w in ad.lower() for w in HARIC):
            atlanan_haric.append(ad)
        elif slug not in [x["slug"] for x in secilen]:
            secilen.append(r)

    if not secilen:
        kt.mesaj_at(f"🌙 Günlük katılım ({etiket}): bu pencerede katılınacak çekiliş yok.")
        return

    aktif = [(ad, key) for ad, key in kt.HESAPLAR if key]
    kt.mesaj_at(f"🌙 Günlük katılım başladı ({etiket}): {len(secilen)} çekiliş, {len(aktif)} hesap...")

    firo_veri = firo.yukle()
    sonuclar = {r["slug"]: {} for r in secilen}
    for ad, key in aktif:
        for r in secilen:
            s = r["slug"]
            if firo.atla_mi(firo_veri, ad, r):
                sonuclar[s][ad] = ("atla", "")
                continue
            sonuclar[s][ad] = kt.kayit_ol(key, s)
            time.sleep(BEKLEME_SN)

    # Ikinci deneme
    tekrar = [(r["slug"], ad, key) for ad, key in aktif for r in secilen
              if sonuclar[r["slug"]][ad][0] == "hata" and not sonuclar[r["slug"]][ad][1].startswith(TEKRAR_YOK)]
    duzelen = 0
    if tekrar:
        print(f"{len(tekrar)} kayit ikinci kez denenecek")
        time.sleep(60)
        for s, ad, key in tekrar:
            d, a = kt.kayit_ol(key, s)
            if d in ("ok", "zaten"):
                d, a = "ok", ""
                duzelen += 1
            else:
                a += " (2 kez denendi)"
            sonuclar[s][ad] = (d, a)
            time.sleep(BEKLEME_SN)

    # Rapor (kisa): sadece sorunlu olanlar ayrintili
    IKON = {"ok": "✅", "zaten": "☑️", "hata": "⚠️", "atla": "⏭️"}
    sayac = {"ok": 0, "zaten": 0, "hata": 0, "atla": 0}
    sorunlar = []
    for r in secilen:
        s = r["slug"]
        gruplar = {}
        for ad, _ in aktif:
            d, a = sonuclar[s][ad]
            sayac[d] += 1
            if d == "hata":
                gruplar.setdefault(a, []).append(ad)
        if gruplar:
            ikonlar = " ".join(f"{ad[0]}{IKON[sonuclar[s][ad][0]]}" for ad, _ in aktif)
            for aciklama, hesaplar in gruplar.items():
                sorunlar.append(f"⚠️ {aciklama} ({', '.join(hesaplar)})  [{ikonlar}]\n   https://www.alphabot.app/{s}")

    mesaj = [f"🌙 Günlük katılım bitti ({etiket})",
             f"{len(secilen)} çekiliş · ✅ {sayac['ok']} katılım · ☑️ {sayac['zaten']} zaten · "
             f"⏭️ {sayac['atla']} GTD'n var · ⚠️ {sayac['hata']} sorun"]
    if duzelen:
        mesaj.append(f"🔁 {duzelen} kayıt ikinci denemede tamamlandı")
    if sorunlar:
        mesaj += ["", "Sorunlu olanlar (C=Chrome E=Edge F=Firefox B=Brave):"] + sorunlar
    if atlanan_cok:
        mesaj += ["", f"{MAX_WINNERS}+ kazanan olduğu için atlanan: {len(atlanan_cok)}"]
    if atlanan_haric:
        mesaj += ["", "Hariç listesinden atlanan: " + ", ".join(atlanan_haric)]
    if eksik:
        mesaj += ["", "ℹ️ Alphabot istek sınırı yüzünden liste tam alınamadı; bazı çekilişler eksik olabilir."]
    kt.mesaj_at("\n".join(mesaj))


if __name__ == "__main__":
    main()
