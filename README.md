# find-anything (stok-medya)

Herhangi bir konu için gerçek görsel ve video klip bulan bir Claude Code skill'i. Ücretsiz stok ve arşiv
kaynaklarında arar (Pexels, Pixabay, Wikimedia, Internet Archive, NASA, LoC, Openverse, Creative Commons
YouTube), sonuçları doğrular, indirir ve lisans/atıf dosyası yazar.

- `SKILL.md`: Claude'un izlediği akış (tek sorgu araması, senaryoya B-roll eşleme, Haiku doğrulaması).
- `scripts/stokmedya.py`: komut satırı aracı (`ara`, `esle`, `url-indir`, `ekle`, `kontak`, `dogrula`, `hareket`).

## Doğrulama

Arama sonuçları gürültülüdür. Akış iki katmanla süzer:

1. **Konu:** adaylar numaralı kontak sayfalarına dizilir; Haiku alt ajanları, konunun güncel görünümünü
   gösteren bir referans sayfasıyla karşılaştırarak kabul/ret verir.
2. **Hareket (videolar):** `hareket` komutu bir klibin gerçek hareketli çekim mi, yoksa ekran kaydı,
   fotoğraf üstüne yakınlaştırma (Ken Burns, döndürme, 2,5D paralaks) ya da sabit kare mi olduğunu
   konudan bağımsız ölçer. `dogrula` gerçek olmayanları Haiku kabul etse de eler.

## Kurulum

```bash
git clone https://github.com/andacdd/find-anything ~/.claude/skills/stok-medya
cd ~/.claude/skills/stok-medya && git config core.hooksPath hooks
```

Gereksinimler: Python 3, `ffmpeg`, Pillow, numpy; YouTube indirmesi için `yt-dlp`. API anahtarları
(`PEXELS_API_KEY`, `PIXABAY_API_KEY`, `YOUTUBE_API_KEY`, isteğe bağlı `X_BEARER_TOKEN`) `STOKMEDYA_ENV`
ile gösterilen `.env` dosyasından okunur. Çıktı klasörü `STOKMEDYA_CIKTI` ile değişir.

## Test

```bash
python3 -m pytest
```

Sentetik videolar test sırasında ffmpeg ile üretilir. `tests/fixtures/` altındaki birkaç saniyelik,
320 px örnekler hareket testinin eşiklerini sabitleyen gerçek dünya regresyon örnekleridir.

## Lisans

MIT, bkz. `LICENSE`. Arama adaptörlerinin kaynağı için `scripts/LICENSE-webmedia.txt`.
