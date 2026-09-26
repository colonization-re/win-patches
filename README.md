# win-patches

Fixes and small features for **Sid Meier's Colonization for Windows** (1995), which you
apply to **your own copy** of `COLONIZE.EXE`. The repository contains no game files.

Each patch changes a handful of bytes in place and never changes the file's length.

| patch | kind | what you see |
| --- | --- | --- |
| [`water-cycling`](patches/water-cycling.json) | feature | River currents and beach surf move while the map waits for your orders, as they do in the DOS version. Open sea, lakes, marsh and fog stay still. **Game Options → Water Color Cycling** turns it off. |
| [`pedia-colonist-icons`](patches/pedia-colonist-icons.json) | fix | Colonopedia → Free Colonist: four figures that were drawn on top of each other each get their own square. |
| [`cheat-picture-viewer`](patches/cheat-picture-viewer.json) | feature | The Cheat menu's **Show Colony Sites** item, which did nothing, becomes the developers' hidden **Picture Viewer**. It shows any of the game's 107 pictures and sprites. |
| [`intro-pages-5s`](patches/intro-pages-5s.json) | qol | New game: the introduction pages turn every 5 seconds instead of every 10. |

Every patch file explains what it changes and why, and what to look for in the game.

## Apply them

Keep a copy of your original `COLONIZE.EXE` whichever way you choose.

### In a browser

Go to **<https://colonization-re.github.io/win-patches/>**, which serves the latest
[release](https://github.com/colonization-re/win-patches/releases). Every release also
carries the page as `win-patches.html`, and a checkout has it as
[`dist/index.html`](dist/index.html): the site serves that file unchanged. It is one
self-contained file and works from disk. Choose your `COLONIZE.EXE`,
tick the patches you want and download the result. Everything happens in the page: the
file is never uploaded. The page makes no network requests at all, and its
Content-Security-Policy tells the browser to refuse any it might try.

Loading an already patched file shows which patches it carries, and unticking one takes
it out again.

### With Python

Python 3.8 or later, standard library only:

```sh
python3 patch.py list
python3 patch.py status --exe COLONIZE.EXE                       # what the file carries
python3 patch.py apply --all --exe COLONIZE.EXE --in-place       # keeps COLONIZE.EXE.orig
python3 patch.py apply water-cycling --exe COLONIZE.EXE --out COLWATER.EXE
python3 patch.py revert --all --exe COLONIZE.EXE --in-place
```

Before it writes anything, the tool checks every byte of every patch you asked for
against your file. If a single one doesn't match, it stops and writes nothing: that means
a different build or a damaged file. It never overwrites your file unless you pass
`--in-place`, and then it keeps the original as `.orig`.

### With an IPS patcher

Each patch is also an IPS file, in [`ips/`](ips/) and attached to every
[release](https://github.com/colonization-re/win-patches/releases). They work with any IPS tool, for
example [Floating IPS](https://github.com/Alcaro/Flips) or the browser-based
[RomPatcher.js](https://www.marcrobledo.com/RomPatcher.js/). **IPS does not check the file
it patches**, so first make sure yours is the build below. The browser page and
`patch.py` do that check for you.

## Which COLONIZE.EXE

The patches are made for the **updated 1995 release**, the version MicroProse's update
produces:

```
COLONIZE.EXE  1,227,264 bytes
SHA-256       59a0e173452924603112cf410483021c02ef0cd3512e310d8966b21e0c176291
```

- **The pre-update version:** the update leaves it beside the new file as `COLONIZE.$00`.
  It's a different build, and the patches refuse it.
- **The DOS version** (`VICEROY.EXE`) is a different program altogether.

`python3 patch.py status --exe COLONIZE.EXE` or the browser page tells you which build you
have.

## Running the game today

A patched `COLONIZE.EXE` runs anywhere the original does:
- **Windows 3.1, 95 and 98:** directly.
- **64-bit Windows:** through [otvdm/winevdm](https://github.com/otya128/winevdm).
- **macOS and Linux:** through Wine with otvdm inside it. On Apple Silicon, Wine 11
  (for example [Gcenx's macOS builds](https://github.com/Gcenx/macOS_Wine_builds)) works;
  Apple's Game Porting Toolkit Wine 7.7 does not, because it crashes when a new game
  generates its map.

With otvdm under Wine, set every module in otvdm's `dll/` folder to native, for example
`WINEDLLOVERRIDES="krnl386.exe16=n;..."`. Wine's own 16-bit modules can't run the game.

## How the patches are made

The patches come from [win-decomp](https://github.com/colonization-re/win-decomp), the
reconstruction of the game's source code. That is where each change is found, checked in
an emulator against the shipped binary, and tested in play. This repository only holds
the result.

[`patches/`](patches/) holds one JSON file per patch. Every site lists:
- where it is, as a segment address and as a file offset;
- the original bytes;
- the new bytes;
- a check that the bytes mean what the patch says: the instruction before and after, a
  string, a relocation record, or an assembly source such as
  [`water-cycling.asm`](patches/water-cycling.asm) that must assemble to exactly the new
  bytes.

A patch that adds code puts it over a function the game never calls, and re-points
relocation records the game already has. So the file's layout, its segment table and the
number of relocations stay exactly as shipped.

```sh
python3 build.py                        # regenerate ips/ and dist/index.html
python3 build.py --check                # what CI runs; needs no game files
python3 patch.py verify --exe COLONIZE.EXE
```

`patch.py verify` needs the unpatched game. It resolves every address through the EXE's
own header and checks the original bytes are there. It decodes each instruction, when
`ndisasm` is installed, and re-assembles code, when `nasm` is. It then walks every
relocation chain in each segment a patch touches, to prove the loader writes nothing into
the new code.

## What a patch file contains

For each site, the few original bytes it replaces and the bytes it puts there. The
original bytes are there so the tool can recognise your build and undo the patch. There
is no game code beyond that, and no game data, art or text.

*Sid Meier's Colonization* is © 1994–1995 MicroProse Software, Inc. This project is not
affiliated with or endorsed by MicroProse, Take-Two Interactive, Firaxis Games or Sid
Meier.
