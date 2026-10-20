"""Test ortamı: stokmedya modülünü içe aktarır, sentetik videoları ffmpeg ile üretir.

Sentetik videolar konudan bağımsızdır (desen + hareketli kutu); gerçek örnekler
tests/fixtures/ altındadır ve bilinen bir şikâyetten (ekran kaydı, fotoğraf efekti) gelir.
"""
import os, subprocess, sys
import pytest

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KOK, "scripts"))
FIXTURES = os.path.join(KOK, "tests", "fixtures")
URETILEN = os.path.join(KOK, "tests", "_uretilen")

# Ortak kaynak: hareketsiz, dokulu bir arka plan (testsrc'nin ilk karesi)
_ZEMIN = "testsrc=size=640x360:rate=1,trim=end_frame=1"

SENTETIK = {
    # nesne hareket ediyor, arka plan sabit: gerçek çekime benzer
    "gercek_kayan_kutu": (
        f"{_ZEMIN},loop=-1:1,fps=10,trim=duration=4[z];"
        "color=c=orange:size=80x80:rate=10:duration=4[k];"
        "[z][k]overlay=x='40+t*100':y='140+20*sin(t*3)'"
    ),
    # tek fotoğraf üstüne yakınlaştırma + kaydırma (Ken Burns)
    "foto_efekt_zoompan": (
        f"{_ZEMIN},scale=1280:720,zoompan=z='1+0.004*on':x='iw/2-(iw/zoom/2)+on*0.8':"
        "y='ih/2-(ih/zoom/2)':d=40:s=640x360:fps=10"
    ),
    # hiç değişmeyen kare
    "sabit_kare": f"{_ZEMIN},loop=-1:1,fps=10,trim=duration=4",
    # gri çerçeve içinde oynayan içerik: ekran kaydı
    "ekran_kaydi_gri_cerceve": (
        f"{_ZEMIN},loop=-1:1,fps=10,trim=duration=4,scale=400:226[z];"
        "color=c=orange:size=40x40:rate=10:duration=4[k];"
        "[z][k]overlay=x='20+t*60':y=90[ic];"
        "color=c=0x262626:size=640x360:rate=10:duration=4[bg];"
        "[bg][ic]overlay=x=120:y=67"
    ),
}


def _uret(ad, filtre):
    os.makedirs(URETILEN, exist_ok=True)
    yol = os.path.join(URETILEN, ad + ".mp4")
    if not os.path.exists(yol):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "nullsrc=s=16x16:d=4",
                        "-filter_complex", filtre, "-t", "4", "-an", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", yol], check=True)
    return yol


@pytest.fixture(scope="session")
def sentetik():
    return {ad: _uret(ad, f) for ad, f in SENTETIK.items()}


@pytest.fixture(scope="session")
def gercek_ornek():
    return lambda ad: os.path.join(FIXTURES, ad + ".mp4")
