"""
Alphabot kazanc takibi
- Saatte bir 4 hesabin kazandigi cekilisleri (filter=winners) kontrol eder.
- Yeni bir kazanc varsa e-posta atar (hangi hesap, hangi cekilis, link).
- Ilk calismada mevcut kazanclari sadece kaydeder, mail atmaz.
- Bildirilenler kazanilanlar.json dosyasinda tutulur.
"""
import json
import os
import smtplib
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

HESAPLAR = [
    ("Chrome", os.environ.get("ALPHABOT_KEY_CHROME", "").strip()),
    ("Edge", os.environ.get("ALPHABOT_API_KEY", "").strip()),
    ("Firefox", os.environ.get("ALPHABOT_KEY_FIREFOX", "").strip()),
    ("Brave", os.environ.get("ALPHABOT_KEY_BRAVE", "").strip()),
]
MAIL_ADRES = os.environ["MAIL_ADRES"].strip()
MAIL_SIFRE = os.environ["MAIL_SIFRE"].replace(" ", "").strip()
MAIL_ALICI = (os.environ.get("MAIL_ALICI") or MAIL_ADRES).strip()
DOSYA = "kazanilanlar.json"
NOT_DOSYASI = "kazanclar.txt"
HESAP_NO = {"Chrome": "1. hesap", "Edge": "2. hesap", "Firefox": "3. hesap", "Brave": "4. hesap"}

if "@" not in MAIL_ADRES or len(MAIL_SIFRE) != 16 or not MAIL_SIFRE.isascii():
    print(f"UYARI: MAIL_ADRES '@' iceriyor mu: {'@' in MAIL_ADRES}, MAIL_SIFRE uzunlugu: {len(MAIL_SIFRE)} (16 olmali), sadece Ingilizce harf: {MAIL_SIFRE.isascii()}")


def kazananlari_getir(key):
    params = {"filter": "winners", "scope": "all", "sort": "newest", "pageSize": 50}
    url = "https://api.alphabot.app/v1/raffles?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}",
                                               "User-Agent": "alphabot-kazanan"})
    with urllib.request.urlopen(req, timeout=20) as r:
        cevap = json.load(r)
    return (cevap.get("data") or {}).get("raffles", [])


def mail_at(konu, govde):
    msg = MIMEText(govde, "plain", "utf-8")
    msg["Subject"] = konu
    msg["From"] = MAIL_ADRES
    msg["To"] = MAIL_ALICI
    son_hata = None
    for deneme in range(2):
        # once SSL (465), olmazsa STARTTLS (587)
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
                s.login(MAIL_ADRES, MAIL_SIFRE)
                s.send_message(msg)
            return
        except smtplib.SMTPAuthenticationError:
            raise SystemExit("HATA: Gmail giris reddedildi. MAIL_ADRES veya MAIL_SIFRE yanlis.")
        except Exception as e:
            son_hata = e
            print("465 olmadi:", repr(e))
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
                s.ehlo()
                s.starttls()
                s.ehlo()
                s.login(MAIL_ADRES, MAIL_SIFRE)
                s.send_message(msg)
            return
        except smtplib.SMTPAuthenticationError:
            raise SystemExit("HATA: Gmail giris reddedildi. MAIL_ADRES veya MAIL_SIFRE yanlis.")
        except Exception as e:
            son_hata = e
            print("587 olmadi:", repr(e))
        time.sleep(10)
    raise SystemExit(f"HATA: Mail gonderilemedi: {son_hata!r}")


def main():
    try:
        with open(DOSYA) as f:
            kayit = json.load(f)
        ilk_calisma = False
    except (FileNotFoundError, json.JSONDecodeError):
        kayit, ilk_calisma = {}, True

    yeniler, hatalar = [], []
    for ad, key in HESAPLAR:
        if not key:
            continue
        try:
            raffles = kazananlari_getir(key)
        except urllib.error.HTTPError as e:
            hatalar.append(f"{ad}: HTTP {e.code}")
            continue
        except Exception as e:
            hatalar.append(f"{ad}: {e}")
            continue
        print(f"{ad}: {len(raffles)} kazanc listede")
        bilinen = set(kayit.get(ad, []))
        for r in raffles:
            rid = str(r.get("_id") or r.get("id") or r.get("slug"))
            if rid in bilinen:
                continue
            bilinen.add(rid)
            if not ilk_calisma:
                yeniler.append((ad, r))
        kayit[ad] = sorted(bilinen)
        time.sleep(1)

    if hatalar:
        print("Hatalar:", hatalar)

    if ilk_calisma:
        toplam = sum(len(v) for v in kayit.values())
        mail_at("✅ Alphabot kazanç takibi başladı",
                f"Kazanç takibi kuruldu. Şu ana kadarki {toplam} kazanç kaydedildi.\n"
                "Bundan sonra yeni bir çekiliş kazandığında bu adrese mail gelecek.")
    elif yeniler:
        satirlar = []
        for ad, r in yeniler:
            isim = r.get("name") or r.get("slug") or "İsimsiz çekiliş"
            link = f"https://www.alphabot.app/{r.get('slug')}" if r.get("slug") else ""
            satirlar.append(f"🏆 {dict(Chrome='1. hesap', Edge='2. hesap', Firefox='3. hesap', Brave='4. hesap').get(ad, ad)} kazandı: {isim}\n   {link}")
        konu = f"🏆 Alphabot: {len(yeniler)} yeni kazanç!"
        mail_at(konu, "Tebrikler! Yeni kazançların:\n\n" + "\n\n".join(satirlar))
        print(f"{len(yeniler)} yeni kazanc mail ile bildirildi.")
        # Not defteri dosyasina ekle
        zaman = datetime.now(timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M")
        with open(NOT_DOSYASI, "a", encoding="utf-8") as f:
            for ad, r in yeniler:
                isim = r.get("name") or r.get("slug") or "İsimsiz çekiliş"
                link = f"https://www.alphabot.app/{r.get('slug')}" if r.get("slug") else ""
                f.write(f"{HESAP_NO.get(ad, ad)} kazandı | {isim}\n")
    else:
        print("Yeni kazanc yok.")

    with open(DOSYA, "w") as f:
        json.dump(kayit, f, indent=1, sort_keys=True)
    if not os.path.exists(NOT_DOSYASI):
        with open(NOT_DOSYASI, "w", encoding="utf-8") as f:
            f.write("ALPHABOT KAZANÇLARIM\n\n")


if __name__ == "__main__":
    main()
