"""kontak + dogrula boru hattı: hareket testi ve referans görsel. Konudan bağımsız."""
import json, os, shutil, sys
import pytest
import stokmedya as sm


def _calistir(*argv):
    sys.argv = ["stokmedya.py", *argv]
    sm.main()


def _klasor(tmp_path, kayitlar):
    for r in kayitlar:
        if r.get("_kaynak"):
            shutil.copy(r.pop("_kaynak"), tmp_path / r["file"])
    json.dump({"sorgu": "deneme", "sonuclar": {"video": kayitlar}, "hatalar": {}},
              open(tmp_path / "sonuclar.json", "w"))
    return str(tmp_path)


def _video(ad, kaynak):
    return {"source": "web", "type": "video", "title": ad, "file": ad + ".mp4",
            "page_url": "https://ornek.test/" + ad, "_kaynak": kaynak}


def test_haiku_kabul_etse_de_gercek_olmayan_video_elenir(tmp_path, sentetik, gercek_ornek):
    k = _klasor(tmp_path, [_video("gercek", sentetik["gercek_kayan_kutu"]),
                           _video("efekt", gercek_ornek("foto_efekt_yakinlasma")),
                           _video("kayit", sentetik["ekran_kaydi_gri_cerceve"])])
    _calistir("kontak", k, "--dosya")
    adaylar = json.load(open(os.path.join(k, "_dogrulama", "adaylar.json")))
    assert {a["id"]: a["hareket"] for a in adaylar["adaylar"]} == {
        "v0": "gercek", "v1": "foto_efekt", "v2": "ekran_kaydi"}
    # Haiku üçünü de kabul etmiş olsun
    json.dump({"kabul": ["v0", "v1", "v2"]}, open(os.path.join(k, "_dogrulama", "karar_1.json"), "w"))
    _calistir("dogrula", k, "--hedef", "0")
    kalan = json.load(open(os.path.join(k, "sonuclar.json")))["sonuclar"]["video"]
    assert [r["title"] for r in kalan] == ["gercek"]
    elenen = json.load(open(os.path.join(k, "elenenler.json")))
    assert {r["title"]: r["elenme"] for r in elenen} == {"efekt": "hareket: foto_efekt", "kayit": "hareket: ekran_kaydi"}


def test_hareket_serbest_ile_hareket_testi_atlanir(tmp_path, sentetik):
    k = _klasor(tmp_path, [_video("efekt", sentetik["foto_efekt_zoompan"])])
    _calistir("kontak", k, "--dosya")
    json.dump({"kabul": ["v0"]}, open(os.path.join(k, "_dogrulama", "karar_1.json"), "w"))
    _calistir("dogrula", k, "--hedef", "0", "--hareket-serbest")
    kalan = json.load(open(os.path.join(k, "sonuclar.json")))["sonuclar"]["video"]
    assert [r["title"] for r in kalan] == ["efekt"]


def test_referans_gorsel_ayri_sayfaya_konur(tmp_path, sentetik):
    import subprocess
    ref = tmp_path / "ref.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1", "-i", sentetik["gercek_kayan_kutu"],
                    "-frames:v", "1", str(ref)], check=True)
    k = _klasor(tmp_path, [_video("gercek", sentetik["gercek_kayan_kutu"])])
    _calistir("kontak", k, "--dosya", "--referans", str(ref))
    dd = os.path.join(k, "_dogrulama")
    assert os.path.exists(os.path.join(dd, "referans.jpg"))
    assert json.load(open(os.path.join(dd, "adaylar.json")))["referans"] == "referans.jpg"
