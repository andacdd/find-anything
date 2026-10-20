"""Hareket testi: bir video klibin gerçek hareketli çekim mi, yoksa ekran kaydı,
fotoğraf üstüne efekt ya da sabit kare mi olduğunu konudan bağımsız söyler."""
import pytest
import stokmedya as sm


@pytest.mark.parametrize("ad,beklenen", [
    ("gercek_kayan_kutu", {"gercek"}),
    # ffmpeg zoompan tam piksel adımla titrer; kalan fark gerçek Ken Burns'ten yüksek olabilir
    ("foto_efekt_zoompan", {"foto_efekt", "supheli"}),
    ("sabit_kare", {"sabit"}),
    ("ekran_kaydi_gri_cerceve", {"ekran_kaydi"}),
])
def test_sentetik_videolar_dogru_siniflanir(sentetik, ad, beklenen):
    assert sm.hareket_analiz(sentetik[ad])["karar"] in beklenen


# Sözleşme: sahte klip asla "gercek" çıkmaz; gerçek klip asla otomatik elenmez
# ("supheli" elenmez, karelerine bakılır).
OTOMATIK_ELENEN = {"foto_efekt", "ekran_kaydi", "sabit"}


@pytest.mark.parametrize("ad,beklenen", [
    # Ensar'ın şikâyet ettiği klipler (stok-medya, Tesla Roadster aramasında)
    ("ekran_kaydi_imlecli", "ekran_kaydi"),
    ("foto_efekt_yakinlasma", "foto_efekt"),
])
def test_bilinen_sahteler_elenir(gercek_ornek, ad, beklenen):
    assert sm.hareket_analiz(gercek_ornek(ad))["karar"] == beklenen


def test_paralaks_animasyonu_gercek_gecmez(gercek_ornek):
    # fotoğraf katmanlara ayrılıp farklı hızda kaydırılmış (2,5D); tek parça hizalama tam açıklayamaz
    assert sm.hareket_analiz(gercek_ornek("foto_efekt_paralaks"))["karar"] != "gercek"


@pytest.mark.parametrize("ad", ["gercek_ustten_ucus", "gercek_az_hareketli_sahne"])
def test_gercek_cekim_otomatik_elenmez(gercek_ornek, ad):
    assert sm.hareket_analiz(gercek_ornek(ad))["karar"] not in OTOMATIK_ELENEN


def test_cli_hareket_json_dondurur(sentetik, capsys):
    import json, sys
    sys.argv = ["stokmedya.py", "hareket", sentetik["sabit_kare"]]
    sm.main()
    cikti = json.loads(capsys.readouterr().out)
    assert cikti[0]["karar"] == "sabit"
