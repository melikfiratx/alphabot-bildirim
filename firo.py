"""
Firo islemi: bir hesap bir projeyi GARANTI (gtd/guaranteed, fcfs olmadan) kazandiysa,
o projenin yeni cekilislerinde o hesap atlanir.
Proje; Alphabot projectId'si VEYA X (Twitter) kullanici adiyla taninir.
Veriyi kazanan.py, kazanilan_projeler.json dosyasina yazar.
"""
import json

DOSYA = "kazanilan_projeler.json"


def x_kullanici(url):
    url = str(url or "").strip()
    if not url:
        return ""
    return url.rstrip("/").split("?")[0].split("/")[-1].lstrip("@").lower()


def garanti_mi(isim):
    n = str(isim or "").lower()
    return ("gtd" in n or "guaranteed" in n) and "fcfs" not in n


def yukle():
    try:
        with open(DOSYA) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def atla_mi(veri, hesap, r):
    """r: cekilis verisi (projectId, twitterUrl). Atlanmali mi?"""
    if not r:
        return False
    d = veri.get(hesap) or {}
    pid = str(r.get("projectId") or "")
    x = x_kullanici(r.get("twitterUrl"))
    return bool((pid and pid in d.get("ids", [])) or (x and x in d.get("x", [])))
