# Paparazzi

**Find real photos and video footage for any topic — and prove the footage is real.**

Paparazzi is a [Claude Code](https://claude.com/claude-code) skill and a command-line tool. Tell Claude what you need ("B-roll of 1930s car factories", "photos of the new Tesla Roadster", "footage for this script") and it searches free stock and archive libraries, verifies every result, downloads what passes, and writes the license and attribution file for you.

It is built for video editors, YouTubers and researchers who need real footage, not AI-generated images.

---

## Why it exists

Raw search results are noisy. A search for "tesla roadster" returns portraits of Nikola Tesla, plasma balls, toy cars and the wrong model generation. Worse, many "videos" are not footage at all: they are screen recordings of someone scrolling through photos, or still photos with a slow zoom (the Ken Burns effect) passed off as video.

Paparazzi filters both problems out before anything reaches you:

| Problem | How Paparazzi catches it |
|---|---|
| Off-topic results | Every candidate is checked visually by Claude Haiku |
| Outdated look (old model, old building) | Candidates are compared against a reference sheet of the subject's *current* appearance |
| AI-made or watermarked thumbnails | Rejected during the visual check |
| Screen recordings | Motion test detects a static, uniform frame around the content |
| Photo slideshows (zoom, pan, rotation) | Motion test checks whether a single camera transform explains all change between frames |
| Frozen clips | Motion test detects frames that never change |

---

## How it works

```
 search ──► contact sheets ──► Haiku visual check ──► apply ──► download ──► motion test ──► final set
 (ara)       (kontak)            (sub-agents)          (dogrula)  (--indir)    (kontak --dosya)  (dogrula --sil)
```

1. **Search** a wide pool across all sources at once.
2. **Contact sheets** lay out every candidate in numbered 12-image grids, plus a reference sheet showing what the subject looks like today.
3. **Haiku sub-agents** review the sheets in parallel and accept only clear matches. When unsure, they reject.
4. **Apply** the decisions: accepted items stay, rejected ones move to `elenenler.json` (rejected list).
5. **Download** the accepted media.
6. **Motion test** samples frame pairs from each clip and classifies it as `gercek` (real footage), `supheli` (suspicious, check manually), `foto_efekt` (photo animation), `ekran_kaydi` (screen recording) or `sabit` (static). The last three are removed automatically, even if Haiku accepted them.

### Sources

| Tier | Sources | Key needed | Notes |
|---|---|---|---|
| Stock | Pexels, Pixabay | `PEXELS_API_KEY`, `PIXABAY_API_KEY` | Free for commercial use, no attribution required |
| Public domain / archive | Wikimedia Commons, NASA, Library of Congress, Internet Archive, Openverse | none | Licenses vary per item; most require attribution |
| Web | YouTube (Creative Commons filter only) | `YOUTUBE_API_KEY`, `yt-dlp` | Riskiest tier; licenses are set by uploaders |
| Social | X / Twitter (last 7 days) | `X_BEARER_TOKEN` | Paid API; listed as reference links only, never downloaded |

Sources without a key are skipped silently. Without any keys you still get Wikimedia, NASA, LoC, Internet Archive and Openverse.

---

## Installation

### Requirements

- Python 3.9+
- [ffmpeg](https://ffmpeg.org/) for frame extraction and clip cutting
- Python packages: `Pillow`, `numpy` (and `pytest` to run the tests)
- [`yt-dlp`](https://github.com/yt-dlp/yt-dlp), only if you want YouTube downloads

```bash
brew install ffmpeg yt-dlp          # macOS; use your package manager elsewhere
pip install pillow numpy pytest
```

### As a Claude Code skill

```bash
git clone https://github.com/andacdd/paparazzi ~/.claude/skills/stok-medya
cd ~/.claude/skills/stok-medya
git config core.hooksPath hooks     # optional: run the tests before every commit
```

Claude Code loads the skill automatically. Keep the folder name `stok-medya`: it must match the skill name in `SKILL.md`.

### API keys

Create a `.env` file and point Paparazzi to it:

```bash
cat > ~/paparazzi.env <<'EOF'
PEXELS_API_KEY=your_key
PIXABAY_API_KEY=your_key
YOUTUBE_API_KEY=your_key
X_BEARER_TOKEN=
EOF

export STOKMEDYA_ENV=~/paparazzi.env
export STOKMEDYA_CIKTI=~/paparazzi-output    # where results are written
```

Add the two `export` lines to your shell profile (`~/.zshrc` or `~/.bashrc`) to make them permanent. Every key is optional. All are free to obtain except X, which charges per post returned.

| Key | Where to get it |
|---|---|
| `PEXELS_API_KEY` | https://www.pexels.com/api/ |
| `PIXABAY_API_KEY` | https://pixabay.com/api/docs/ |
| `YOUTUBE_API_KEY` | Google Cloud Console → YouTube Data API v3 |
| `X_BEARER_TOKEN` | https://developer.x.com (paid) |

---

## Usage

### With Claude Code (recommended)

Ask in plain language. The skill triggers on requests for stock footage, B-roll, archive images or "real footage instead of AI".

> Find B-roll for the 1929 stock market crash.

> Get me 20 verified photos and 10 real video clips of the new Tesla Roadster, then zip them.

> Here is my voice-over script. Match a clip to every sentence.

Claude runs the full pipeline, reviews the borderline cases itself, and reports how many candidates were checked, how many survived, and which files need attribution.

### From the command line

Command names are Turkish. Here is what each one does:

| Command | Meaning | What it does |
|---|---|---|
| `ara "<query>"` | search | Searches all sources, writes `galeri.html` and `sonuclar.json` |
| `esle <scenes.json>` | match | Matches one clip to each scene of a script |
| `kontak <folder>` | contact sheet | Builds numbered review sheets for visual checking |
| `dogrula <folder>` | verify | Applies accept/reject decisions, optionally downloads |
| `hareket <video...>` | motion | Classifies clips as real footage or fake motion |
| `url-indir <url>` | download URL | Downloads one file from a page you found yourself |
| `ekle <folder> <records.json>` | add | Adds manually found items to an existing search |

```bash
S=~/.claude/skills/stok-medya/scripts/stokmedya.py

# Search: 60 images + 10 videos by default (--hedef 0 = everything the sources return)
python3 $S ara "1930s car factory assembly line"

# Images only, 30 results, and download them
python3 $S ara "lighthouse storm" --tur image --hedef 30 --indir

# Check whether clips are real footage
python3 $S hareket clip1.mp4 clip2.mp4

# Build review sheets with a reference image of the subject's current look
python3 $S kontak ~/paparazzi-output/lighthouse-storm --referans https://example.com/reference.jpg
```

**`ara` options:** `--tur image|video|hepsi` (type), `--hedef N` (results per type), `--indir` (download), `--out <folder>`, `--katman stok,pd,web,sosyal` (source tiers), `--kaynak pexels,wikimedia` (specific sources), `--x-adet N` (X posts; 0 disables).

**`dogrula` options:** `--indir` (download kept items), `--sil` (delete rejected files), `--hedef N`, `--hareket-serbest` (skip the motion test).

**Script matching:** write a `scenes.json` like the one below, then run `esle`. Each scene gets the first unused result from its queries, tried from most specific to most general.

```json
[{"id": 1, "metin": "In the spring of 1453...", "sorgular": ["Theodosian walls Istanbul", "medieval city walls siege", "stone fortress walls"], "tur": "image", "sure": 4}]
```

`metin` = narration text, `sorgular` = queries, `tur` = `video` or `image`, `sure` = duration in seconds.

---

## Output

Each search writes to its own folder:

| File | Contents |
|---|---|
| `galeri.html` | Thumbnail grid of all results; click to open the source page |
| `sonuclar.json` | Full result list with source, license, author and file name |
| `elenenler.json` | Rejected items and the reason (`haiku` or `hareket: <class>`) |
| `atif.txt` | Ready-to-paste attribution list, with a separate warning section for unknown licenses |
| `manifest.json` | Script matching only: scene → clip, source, license |
| `_dogrulama/` | Review sheets, reference sheet and decision files |

---

## The motion test

`hareket` decides whether a clip contains real motion. It is topic-independent and uses only ffmpeg and numpy.

At ten points in the clip it takes two frames 0.4 seconds apart and tries to explain the change between them with a **single** scale + rotation + shift. An animated still photo is explained almost perfectly; real footage always leaves a residual (moving objects, smoke, light, parallax, sensor noise). Screen recordings are caught by a uniform, non-black frame on all four sides.

Thresholds were calibrated on 40 real clips and 17 photo animations:

| | `gercek` | `supheli` | auto-removed |
|---|---|---|---|
| Real footage (40) | 37 | 2 | 1 |
| Photo animations (17) | **0** | 5 | 12 |

No fake clip passed as real. `supheli` (suspicious) clips are kept but flagged. They are mostly 2.5D parallax animations, where a photo is split into layers that move at different speeds; these overlap with low-motion real footage, so a person (or Claude) looks at the frames. The thresholds are the `HAREKET_*` constants in `scripts/stokmedya.py`.

---

## Licensing and copyright

- **Stock tier** (Pexels, Pixabay): free for commercial use.
- **Archive tier**: check `atif.txt`; most items need attribution.
- **YouTube Creative Commons**: the uploader sets the license and it is often wrong. If a clip contains footage owned by someone else (brand videos, TV), the CC label does not cover it.
- **X**: never downloaded. Ask the poster for permission.
- Items with unknown licenses are listed separately in `atif.txt`. Check them before publishing.

Paparazzi finds and organizes media. You are responsible for how you use it.

---

## Tests

```bash
cd ~/.claude/skills/stok-medya
python3 -m pytest
```

Synthetic test videos are generated with ffmpeg at test time. `tests/fixtures/` holds a few 4-second, 320 px real-world clips that pin the motion test against known screen recordings, photo animations and real footage.

## Acknowledgements

The search adapters are adapted from [connerkward/web-media-getter-skill](https://github.com/connerkward/web-media-getter-skill) (MIT). See `scripts/LICENSE-webmedia.txt`.

## License

[MIT](LICENSE) © 2026 Andaç Demirdelen
