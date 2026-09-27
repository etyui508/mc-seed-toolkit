# MC Seed Toolkit

**Recover the world seed of a Minecraft server from a world download, then use that seed to
locate structures and coordinates.**

Client-side only: it never touches the server, needs no OP and no admin rights.

> 中文说明看 [README.zh.md](README.zh.md)（Chinese version of this page）。

---

## Quick start (30 seconds)

| Your setup | How to launch |
| --- | --- |
| **Windows** | Double-click **`START.bat`** (uses the bundled Java, keeps Chinese text from garbling) |
| **WSL / Linux** | `cd` into this folder and run `bash run.sh` (`./run.sh` may fail — the execute bit doesn't survive a zip) |

You get a menu:

```
  1. Find the world seed        <- start here on your first run
  2. Structures / coordinates   (seed + version -> positions)
  3. Settings                   (seed / version / paths / Java)
  4. Check for updates
  5. Send feedback
  6. Terms / privacy policy
  7. Export / copy results
  8. Roll back an update
  0. Quit
```

On first launch it asks **which language you want**, then walks you through a short setup
(version / save folder / Java / update channel). Every question takes Enter for the default.

The interface ships in **中文 and English**; switch anytime from Settings.

## Requirements

* **Python 3.8+** (for the toolkit itself)
* **Java 17+** — the *full* edition bundles a JRE under `runtime/`, the lite edition uses
  whatever Java you already have

## Finding the seed

The toolkit combines four independent signals. Each one narrows the search:

| Signal | Bits | Where it comes from |
| --- | --- | --- |
| End pillars (the 10 obsidian towers) | 16 | the downloaded End save |
| Structure placement (monument, ancient city, fortress…) | 3–8 each | block markers in the save |
| Slime chunks | ~3.3 each | the recorder mod's observation file |
| `sha256(seed)` ("hashed seed") | locks the top 16 bits | the recorder mod's observation file |

Once ~48 bits are collected the low 48 bits of the seed are pinned down; the hashed seed
then fixes the high 16 bits and verifies the result — the full 64-bit seed falls out and is
saved for the structure calculators.

The seed search is fully local. No server access, no OP, no external service.

## Ore density — which chunk is the richest

Main menu → `2` → `31` counts the ores inside a save you have **already downloaded** and
ranks the chunks by how many you'd find in each one. Diamonds count their deepslate
variant too, and you can limit it to a depth range (e.g. `-64 -16`). The Nether and End are
scanned separately when their folders are present.

It counts real blocks rather than predicting them, so it is exact — but it only covers the
chunks you actually downloaded. Fly the downloader over the area you care about first.

## Two mods you install on your client

Both are client-side; the server never sees them.

| Mod | What it does | Forge build? |
| --- | --- | --- |
| **SeedHelper** (ours, MIT) | records the hashed seed, End pillar tops, slime chunks and biome samples into `seedhelper-observations.txt` | yes — `tools/port-to-forge.py` converts the Fabric source to a native Forge build |
| **Archive World Downloader** | saves the terrain you fly through into a local single-player save | yes, upstream ships both Fabric and Forge builds |

Ready-made jars for 1.16.5 – 1.21.11 live in `mods/<version>/`. For other versions you can
build them yourself:

```bash
python3 tools/build-mods.py --only-seedhelper 1.20.1
```

## Updates

* Two channels: **stable** and **beta**.
* The manifest is **signed** (Ed25519) — an unsigned or tampered manifest is rejected, and
  the download is verified by SHA-256 before anything is replaced.
* Files are swapped in atomically; your seed, save paths, records and bundled Java are never
  touched. Every update keeps a backup, so **main menu → 8** rolls back.
* If an update fails, the tool keeps running on the old version and tells you why.

## Feedback

Main menu → 5 opens a one-click report that attaches the diagnostic log (paths, seeds and
usernames are masked). Feedback lands on a self-hosted form; nothing else is ever uploaded.

## Running the tests

```bash
bash tools/tests/run-tests.sh          # unit + integration
bash tools/tests/run-tests.sh --full   # adds the slow ones
python3 tools/tests/test_reject.py     # 22 tamper-resistance checks
```

## What's in the folder

| Path | Contents |
| --- | --- |
| `app/` | the toolkit itself (`tool.py` is the entry point) |
| `app/structures/` | one module per structure or tool (31 registry entries) |
| `app/lang/` | UI translations (`en.json`, …) |
| `mods/` | ready-made client mods for 21 Minecraft versions |
| `mod-src/` | SeedHelper source (Fabric, intermediary names) |
| `variants/forge-1.20.1/` | SeedHelper ported to a native Forge build |
| `tools/` | builders: mods, Forge port, cubiomes, release signing, GitHub push |
| `docs/` | principles, version support, security notes, terms |
| `记录/` | runtime records — coordinates, logs, update backups (created on first use) |

`使用说明.md` is the full manual; it is currently **Chinese only**.

## Three things to watch out for

1. **The End central island must be downloaded.** Those 10 pillars are the single biggest
   chunk of information (16 bits); without them the seed is usually out of reach.
2. **Check the server rules first.** Downloading the map and recovering the seed is banned on
   plenty of servers — the toolkit is client-side, but the rules are the rules.
3. **Modded world generation breaks the math.** If a server changes terrain generation
   (new biomes, new structures), the vanilla placement algorithms no longer describe it.

## Links

* Source and releases: <https://github.com/etyui508/mc-seed-toolkit>
* SeedHelper mod: <https://github.com/etyui508/seedhelper>
* License: MIT
