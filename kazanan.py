"""
Alphabot kazanc takibi
- Saatte bir 4 hesabin kazandigi cekilisleri (filter=winners) kontrol eder.
- Yeni bir kazanc varsa e-posta atar (hangi hesap, hangi cekilis, link).
- Ilk calismada mevcut kazanclari sadece kaydeder, mail atmaz.
- Bildirilenler kazanilanlar.json dosyasinda tutulur.
"""
import json
import firo
import re
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


TIP_RE = re.compile(r"(\d+\s*x?\s*)?\b(GTD|FCFS|WL|FREE|OG|PUBLIC|GUARANTEED|ALLOWLIST|PRESALE)\b", re.IGNORECASE)
AYRAC_RE = re.compile(r"\s+(?:x|×|<>|&)\s+", re.IGNORECASE)


def _sade(t):
    return re.sub(r"[^a-z0-9]", "", str(t).lower())


def bicimle(ad, r):
    """Ornek: 'BLURB 1.hesap @Blurb_xyz 7 GTD + 18 FCFS'"""
    isim = str(r.get("name") or r.get("slug") or "")
    url = str(r.get("twitterUrl") or "")
    kullanici = url.rstrip("/").split("?")[0].split("/")[-1] if url else ""
    # tur kismi: ilk ve son tur kelimesi arasini al, varsa parantezleri koru
    eslesmeler = list(TIP_RE.finditer(isim))
    tip = ""
    if eslesmeler:
        bas, son = eslesmeler[0].start(), eslesmeler[-1].end()
        if bas > 0 and isim[bas - 1] == "(" and son < len(isim) and isim[son] == ")":
            bas, son = bas - 1, son + 1
        tip = isim[bas:son].strip()
    # proje adi: cekilis adindaki parcalardan X kullanici adina en cok benzeyeni
    proje = ""
    k = _sade(kullanici)
    for kok in ("official", "nft", "nfts", "xyz", "io", "eth", "app", "labs", "hq"):
        if k.endswith(kok) and len(k) > len(kok) + 2:
            k = k[: -len(kok)]
    en_iyi = 0
    for parca in AYRAC_RE.split(isim):
        temiz = TIP_RE.sub("", parca)
        temiz = re.sub(r"[()\[\]+\-–|]", " ", temiz)
        temiz = re.sub(r"\s+", " ", temiz).strip()
        p_sade = _sade(temiz)
        if not p_sade or not k:
            continue
        if p_sade in k or k in p_sade:
            puan = min(len(p_sade), len(k))
            if puan > en_iyi:
                en_iyi, proje = puan, temiz
    if not proje:
        proje = kullanici or isim
    hesap = HESAP_NO.get(ad, ad).replace(". hesap", ".hesap")
    parcalar = [proje, hesap]
    if kullanici:
        parcalar.append("@" + kullanici)
    if tip:
        parcalar.append(tip)
    return " ".join(parcalar)


def kazananlari_getir(key, sayfa=0):
    params = {"filter": "winners", "scope": "all", "sort": "newest", "pageSize": 50, "pageNum": sayfa}
    url = "https://api.alphabot.app/v1/raffles?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}",
                                               "User-Agent": "alphabot-kazanan"})
    with urllib.request.urlopen(req, timeout=20) as r:
        cevap = json.load(r)
    data = cevap.get("data") or {}
    kazananlari_getir.son_sayfa = data.get("finalPage", True)
    return data.get("raffles", [])


def proje_kaydet(projeler, ad, raffles):
    """Garanti kazanilan projeleri (Firo islemi icin) kaydeder."""
    d = projeler.setdefault(ad, {"ids": [], "x": []})
    ids, xs = set(d.get("ids", [])), set(d.get("x", []))
    for r in raffles:
        if not firo.garanti_mi(r.get("name")):
            continue
        if r.get("projectId"):
            ids.add(str(r["projectId"]))
        x = firo.x_kullanici(r.get("twitterUrl"))
        if x:
            xs.add(x)
    d["ids"], d["x"] = sorted(ids), sorted(xs)


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

    projeler = firo.yukle()
    saat = datetime.now(timezone(timedelta(hours=3))).hour
    tam_tarama = (not projeler) or saat == 4  # ilk seferde ve her gece 04'te tum sayfalar
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
        proje_kaydet(projeler, ad, raffles)
        if tam_tarama:
            sayfa = 1
            while not getattr(kazananlari_getir, "son_sayfa", True) and sayfa < 10:
                time.sleep(2)
                try:
                    ek = kazananlari_getir(key, sayfa)
                except Exception as e:
                    print(f"{ad}: sayfa {sayfa} alinamadi: {e}")
                    break
                proje_kaydet(projeler, ad, ek)
                sayfa += 1
            print(f"{ad}: tam tarama {sayfa} sayfa")
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
            satirlar.append(f"🏆 {bicimle(ad, r)}\n   {link}")
        konu = f"🏆 Alphabot: {len(yeniler)} yeni kazanç!"
        mail_at(konu, "Tebrikler! Yeni kazançların:\n\n" + "\n\n".join(satirlar))
        print(f"{len(yeniler)} yeni kazanc mail ile bildirildi.")
        # Not defteri dosyasina ekle
        zaman = datetime.now(timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M")
        with open(NOT_DOSYASI, "a", encoding="utf-8") as f:
            for ad, r in yeniler:
                isim = r.get("name") or r.get("slug") or "İsimsiz çekiliş"
                link = f"https://www.alphabot.app/{r.get('slug')}" if r.get("slug") else ""
                f.write(f"{bicimle(ad, r)}\n")
    else:
        print("Yeni kazanc yok.")

    with open(DOSYA, "w") as f:
        json.dump(kayit, f, indent=1, sort_keys=True)
    with open(firo.DOSYA, "w") as f:
        json.dump(projeler, f, indent=1, sort_keys=True)
    print("Firo: " + ", ".join(f"{a} {len(v.get('ids', []))} proje" for a, v in projeler.items()))
    if not os.path.exists(NOT_DOSYASI):
        with open(NOT_DOSYASI, "w", encoding="utf-8") as f:
            f.write("ALPHABOT KAZANÇLARIM\n\n")


if __name__ == "__main__":
    main()
