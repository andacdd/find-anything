---
name: stok-medya
description: Ücretsiz stok ve arşiv kaynaklarından (Pexels, Pixabay, Wikimedia, Internet Archive, NASA, LoC, Openverse, Creative Commons YouTube) gerçek görsel ve video klip bulur, indirir, lisans/atıf dosyası yazar. Tek sorgu araması da yapar, bir senaryo ya da seslendirme metnini sahnelere bölüp her sahneye B-roll eşlemesi de yapar. Kullanıcı stok görsel, stok video, B-roll, arşiv görüntüsü, tarihi fotoğraf, "şu metne görsel bul", "bu senaryoya footage", "telifsiz video", "VidRush gibi" dediğinde ya da bir video için yapay zekâ üretimi yerine gerçek görüntü gerektiğinde bu skill'i kullan. AI ile görsel/video üretmek için değil.
---

# Stok Medya

Gerçek görsel ve klipleri ücretsiz kaynaklardan bulur. Mantık VidRush'ın "Footage Agent"ına benzer: görsel, söylenen cümleye göre seçilir; kaynaklar lisans katmanlarına ayrılır; seçilen her dosyanın kaynağı ve lisansı kayda geçer.

Script: `~/.claude/skills/stok-medya/scripts/stokmedya.py` (yalnızca Python stdlib). Çıktı JSON'dur; chat'e ham JSON dökme, özetle.

## Çıktı konumu

Varsayılan: `$HOME/Claude Personal Projects/stok-medya/cikti/<konu-slug>/`.
Kullanıcı medyayı belirli bir projede kullanacaksa `--out "$HOME/Claude Personal Projects/<proje>/<alt-klasör>"` ver. Proje belli değilse varsayılanı kullan. İş bitince tam yolu kullanıcıya yaz.

## Kaynak katmanları

| Katman | Kaynaklar | Anahtar | Not |
|---|---|---|---|
| `stok` | pexels, pixabay | `PEXELS_API_KEY`, `PIXABAY_API_KEY` | Modern kısa klip ve foto; ticari kullanım serbest, atıf gerekmez |
| `pd` | wikimedia, nasa, loc, internetarchive, openverse | yok | Tarihi/arşiv; çoğu atıf ister, lisans öğeye göre değişir |
| `web` | youtube (yalnız Creative Commons filtreli) + elle URL | `YOUTUBE_API_KEY`, `yt-dlp` | En riskli katman; aşağıdaki web kurallarına uy |
| `sosyal` | x (X/Twitter API v2, son 7 gün) | `X_BEARER_TOKEN` | **Ücretli**: dönen gönderi başına $0,005. Yalnız referans, asla indirilmez |

Anahtarlar `$HOME/Claude Personal Projects/stok-medya/.env` dosyasında durur; script her çalışmada okur. Anahtar değerlerini chat'e yazdırma, .env içeriğini gösterme. Anahtarı olmayan kaynak sessizce atlanır. İlk çalıştırmada hangi anahtarların eksik olduğunu kullanıcıya bir satırla söyle; çünkü anahtar olmadan video havuzu çok daralır (anahtarsız video kaynakları yalnız NASA ve Internet Archive).

İlk sonuç seçiminde öncelik sırası: stok, sonra pd, sonra web. Stok klipler kısa ve kullanıma hazır; arşiv filmleri uzun ve büyük olduğu için ikinci sırada.

## Mod 1: Tek sorgu araması

Kullanıcı "X'in görselini/videosunu bul" dediğinde:

```bash
python3 ~/.claude/skills/stok-medya/scripts/stokmedya.py ara "1930s car factory assembly line"
```

- **Standart: 60 görsel + 10 video** (`--tur hepsi` varsayılan). Kullanıcı daha az ya da daha çok isterse `--hedef N`; "hepsi/sınırsız" derse `--hedef 0` (kaynakların verdiği her şey, yüzlerce olabilir). Tek tür için `--tur image` ya da `--tur video`.
- Script her kaynaktan API'nin izin verdiği kadar çeker, kaynaklar arasında sırayla karıştırır (stok, pd, web), her kaynağın içinde sorgu kelimesini başlıkta taşıyanları öne alır. Hiçbir sonucu atmaz; çünkü kullanıcı sayıyı istiyor, seçimi kendisi yapacak.
- Sorguyu İngilizce yaz; tüm kaynakların indeksi İngilizce. Kullanıcı Türkçe yazdıysa çevir.
- Tam liste dosyaya yazılır: `<klasör>/galeri.html` (küçük resimli ızgara, tıklayınca kaynak sayfası) ve `sonuclar.json`. Chat'e 70 satır dökme; token israfı olur. Script stdout'ta yalnız özet verir (tür başına adet, kaynak dağılımı, ilk `--goster` kayıt).
- Chat'te şunu göster: adetler ve kaynak dağılımı, ilk kayıtlardan konuya gerçekten uyan 5-8 tanesi (kaynak, içerik, lisans, link), galeri dosyasının tam yolu ve açma komutu (`open "<galeri yolu>"`). Hedefin altında kaldıysa nedenini söyle (anahtarsız kaynak, kaynak hatası, dar konu).
- İndirme yalnız kullanıcı isterse: aynı komuta `--indir` ekle. 70 dosya indirileceği için önce sayıyı söyle.

### Haiku doğrulaması (varsayılan)

Ham arama sonuçları gürültülüdür: Pixabay etiket eşleşmesiyle alakasız görsel döndürür ("tesla" sorgusuna Nikola Tesla, plazma topu gibi). Kullanıcı galeride yalnız istediği şeyi görmek istiyor. Bu yüzden Mod 1'de her aramadan sonra Haiku doğrulaması yapılır:

0. **Referans (konu ne olursa olsun):** Ölçütü yazmadan önce konunun **güncel** görünümünü doğrula. Model, ürün, bina, kişi, olay zamanla değişir ve senin bildiğin hal eski olabilir (örnek: bir aracın 2017 prototipi ile 2026 üretim modeli tamamen farklı görünüyordu ve tüm fotoğraflar yanlış nesli gösterdi). WebSearch ile resmi ya da güncel 1-3 görsel bul, `kontak` komutuna `--referans <url-ya-da-yol> ...` olarak ver. `_dogrulama/referans.jpg` oluşur. Haiku prompt'una "önce referans.jpg'ye bak, adayları buna göre karşılaştır" yaz. Tarif yazmak yetmez; örnek ver.
1. **Geniş havuz:** `ara "<sorgu>" --hedef 0`. Eleme çok şey atacağı için hedefle kesme. Sorgu çok darsa (yıl, model kodu) daha geniş ikinci bir sorguyu ayrı klasöre çek, kayıtlarını düz liste olarak `ekle` ile ana klasöre kat.
2. **Kontak sayfaları:** `kontak "<klasör>"`. Önizlemeler `<klasör>/_dogrulama/sayfa_NNN.jpg` dosyalarına 12'li ızgara halinde dizilir (Pillow gerekir). Her hücrede `i12` / `v40` kimliği yazar. Kimlik ile başlık listesi `adaylar.json` dosyasında. Önizlemesi olmayan kayıt elenir.
3. **Haiku ajanları:** Agent aracı, `model: "haiku"`, arka planda, ajan başına ~13 sayfa, paralel. Prompt'a şunları yaz: konunun görsel tarifi (neye benzer), kesin kabul ölçütü, karıştırılabilecek şeylerin ret listesi (eski nesil, benzer modeller, isim benzerliği, illüstrasyon, oyuncak) ve "emin değilsen reddet". Karar başlığa değil resme göre verilir. Her ajan `_dogrulama/karar_N.json` dosyasına `{"kabul": [...], "notlar": {...}}` yazar.
4. **Uygula:** `dogrula "<klasör>"`. Kabul edilenler kalır, varsayılan hedefe (60/10) kesilir. Galeri ve `sonuclar.json` yenilenir, elenenler `elenenler.json` dosyasına gider. X kayıtları dokunulmadan kalır. İndirme istenmişse `--indir` ekle.
5. **Video ikinci tur (zorunlu):** Önizleme tek karedir; ekran kaydını, fotoğraf üstüne yakınlaştırmayı (Ken Burns) ve 2,5D paralaks animasyonunu göstermez. Videolar indirildiyse `kontak "<klasör>" --dosya` çalıştır: her klipten 4 kare alınır ve **hareket testi** uygulanır (`hareket` komutuyla tek tek de çalışır). Kararlar: `gercek`, `supheli`, `foto_efekt`, `ekran_kaydi`, `sabit`. Hücre etiketinde gerçek olmayan karar yazar. `dogrula` son üçünü Haiku kabul etse de eler (`elenme: "hareket: ..."`); yalnız kullanıcı isterse `--hareket-serbest`. `supheli` elenmez: 4 karesine sen bak, katmanlar farklı hızda kayıyorsa ama içerikte hiçbir şey değişmiyorsa (duman, ışık, tekerlek, insan) fotoğraf animasyonudur, çıkar. Sonra `dogrula "<klasör>" --sil`.
6. **Spot kontrol:** Kabul edilenlerin kontak sayfalarını kendin de aç, yanlış kabul varsa çıkar. Raporda "N aday incelendi, M kaldı" yaz. Kalan sayı hedefin altındaysa doldurmak için alakasız içerik ekleme; kaynakların bu konuda az içerik verdiğini söyle.

Doğrulama yanlış kabulü çok azaltır ama sıfır garanti etmez (küçük önizleme, benzer modeller). Kullanıcıya bunu bir satırla söyle.

Hareket testi eşikleri 40 gerçek çekim ve 17 fotoğraf animasyonuyla ölçüldü: sahtelerin hiçbiri `gercek` çıkmadı (12 `foto_efekt`, 5 `supheli`); gerçeklerin 1'i elendi, 2'si `supheli` oldu. Eşikler `scripts/stokmedya.py` içinde `HAREKET_*` sabitleri. Değiştirirsen `python3 -m pytest` ile testleri çalıştır.

## Mod 2: Metne/senaryoya B-roll eşleme

Kullanıcı bir senaryo, seslendirme metni ya da sahne listesi verdiğinde:

1. **Sahnelere böl.** Her sahne 1-2 cümlelik anlatım birimi olsun. Sahne süresi verilmemişse ~2,5 kelime/saniye ile tahmin et.
2. **Sorgu üret.** Her sahne için 2-3 İngilizce sorgu yaz, en özelden en genele sırala. Görseli söylenen kelimeden çıkar; köşeli parantezli sahne talimatlarını değil, anlatılan somut nesneyi/mekânı/eylemi ara. Soyut cümlelerde ("ekonomi çöktü") somut karşılık bul ("empty stock exchange floor", "1929 bank run crowd"). Son sorgu her zaman geniş bir yedek olsun; çünkü dar konularda havuz boşalır.
3. **Tür seç.** Varsayılan `video`. Tarihi olay, kişi portresi, belge gibi videosu muhtemelen olmayan sahnelerde `image` seç.
4. **`sahneler.json` yaz** (çıktı klasörüne):
   ```json
   [{"id": 1, "metin": "1453 baharında surların önünde...", "sorgular": ["Theodosian walls Istanbul", "ancient city walls siege painting", "medieval stone fortress walls"], "tur": "image", "sure": 4}]
   ```
5. **Çalıştır:**
   ```bash
   python3 ~/.claude/skills/stok-medya/scripts/stokmedya.py esle "<out>/sahneler.json" --out "<out>" --gorsele-dus
   ```
   Script her sahnede sorguları sırayla dener, daha önce kullanılmamış ilk indirilebilir sonucu seçer (aynı klip iki sahneye gitmez), `manifest.json` ve `atif.txt` yazar.
6. **Raporla.** Bulunan/bulunamayan sahne sayısını, kaynak dağılımını ve atıf gereken dosyaları özetle. Bulunamayan sahneler için daha geniş sorgularla `sahneler.json`'u güncelleyip yalnız onları yeniden çalıştırmayı öner.

Seçim mantığı bilinçli olarak "sorgu + ilk sonuç": hızlı ve ücretsiz. Uyumsuz klip olabilir; kullanıcı belirli bir sahneyi beğenmezse o sahne için Mod 1 ile aday listesi göster, kullanıcı seçsin.

## Web katmanı kuralları

Web katmanı telif riskini taşıyan katman; VidRush'ın telif şikâyeti aldığı yer de burası. Bu yüzden:

- YouTube'da yalnız `videoLicense=creativeCommon` araması yapılır; script bunu zorunlu tutar. CC BY bile olsa kanal adı ve link atıfta yer almalı.
- YouTube'dan indirme `yt-dlp` gerektirir ve YouTube kullanım şartlarıyla çelişebilir. `yt-dlp` kurulu değilse kurmadan önce kullanıcıya bunu söyle ve onay al. Kullanıcı istemezse YouTube sonuçlarını yalnız link olarak listele.
- Genel web görseli için önce WebSearch/WebFetch ile kaynağı bul, lisansını sayfadan kontrol et, sonra:
  ```bash
  python3 ~/.claude/skills/stok-medya/scripts/stokmedya.py url-indir "<doğrudan-dosya-url>" --out "<out>" --sayfa "<sayfa-url>" --lisans "<bulunan lisans ya da bilinmiyor>" --baslik "<kısa ad>"
  ```
  Lisans bulunamadıysa `bilinmiyor` bırak; `atif.txt` bu dosyaları ayrı bir uyarı bölümünde listeler. Kullanıcıya "lisansı bilinmeyen N dosya var, yayından önce kontrol et" diye açıkça söyle.
- Haber sitelerinden, Getty/Shutterstock gibi filigranlı ya da ücretli stok sitelerinden, sosyal medya hesaplarından dosya indirme. Bunlar ücretsiz kaynak değildir.

## X (Twitter) katmanı

X'teki güncel paylaşımlar kullanıcı için önemli; konunun şu an nasıl konuşulduğunu ve hangi görsellerin dolaştığını gösterir. Ama X medyası stok değildir: telif paylaşandadır. Bu yüzden:

- Script X sonuçlarını yalnız link + küçük resim olarak listeler, `indir()` X kaydını reddeder. Kullanıcı bir X görselini kullanmak isterse paylaşandan izin alması gerektiğini söyle.
- **Maliyet:** X API'nin ücretsiz arama katmanı yok (Şubat 2026'dan beri kullandıkça öde). Varsayılan `--x-adet 20` → arama başına ~$0,10. Özetteki `x.maliyet_usd` alanını kullanıcıya her aramada bir satırla bildir. Kullanıcı X'i istemezse `--x-adet 0`.
- Arama yalnız son 7 günü kapsar; eski olaylar için X sonucu boş gelebilir, bu normal.
- `X_BEARER_TOKEN` boşsa (şu anki varsayılan) ücretsiz yedeği her aramada uygula: `ara` bittikten sonra WebSearch ile `site:x.com <sorgu>` (allowed_domains: x.com, twitter.com) ara. Yalnız tekil gönderi linklerini (`/status/`) al, profil sayfalarını alma. Konuyla gerçekten ilgili olanları `<klasör>/x_web.json` dosyasına yaz ve galeriye ekle:
  ```bash
  python3 ~/.claude/skills/stok-medya/scripts/stokmedya.py ekle "<klasör>" "<klasör>/x_web.json"
  ```
  Kayıt biçimi: `{"source":"x","type":"video|image","title":"<kısa Türkçe özet>","page_url":"https://x.com/.../status/...","author":"@kullanici"}`. Gönderide video/görsel olduğu belli değilse `type: "image"` ver. Chat özetinde X'ten gelen sayıyı ayrıca belirt.

## Kara liste

`~/.claude/skills/stok-medya/kara-liste.txt`: satır başına bir alan adı, kaynak adı, yazar ya da YouTube kanal ID'si. Eşleşen sonuç hiç dönmez. Kullanıcı bir kaynaktan şikâyet (telif uyarısı, kalitesiz içerik) bildirirse ilgili satırı bu dosyaya ekle. Listeyi kısa tut; her giriş havuzu daraltır.

## Arşiv videosu notu

Internet Archive ve NASA tek çekim değil, bütün film barındırır. Script 150 MB üstü dosyaları atlar ve en küçük mp4 türevini seçer. Uzun bir filmden tek sahne gerekiyorsa ffmpeg ile kes (`ffmpeg -ss <bas> -t <sure> -i film.mp4 -c copy sahne.mp4`); doğru anı bulmak için önce `ffmpeg -vf fps=1/10` ile kareler çıkarıp bak.

## Çıktı dosyaları

- `manifest.json`: sahne başına `durum`, `sorgu`, `dosya`, `kaynak`, `lisans`, `yazar`, `sayfa`. Montaj (ffmpeg) bu dosyadan beslenir.
- `atif.txt`: video açıklamasına yapıştırılacak kaynak listesi + lisansı bilinmeyenler uyarısı.
- `attribution.json`: Mod 1 indirmelerinde tüm kayıtlar.
