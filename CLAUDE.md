# CLAUDE.md

Patches for the original *Colonization for Windows* `COLONIZE.EXE`, applied by players to
their own copy. Nothing else lives here: no decompilation, no reverse engineering, no
game files.

## What this repo is downstream of

Patches are found, and their behaviour checked, in
[win-decomp](https://github.com/colonization-re/win-decomp):
- `tools/patch_probe.py` runs each patched function in the emulator against the shipped
  binary;
- `tools/run-colonization.sh --patched NAME` plays it.

That repo reads the manifests from here, so this is the single copy.

A manifest's `why` may name game functions and addresses. That is fine: it's the
explanation. Don't bring over evidence paths, tools or anything else from win-decomp.

## The rules

- **Same length, always.** `patch.py` refuses a site whose `new` and `expect` differ in size.
  The EXE's layout, segment table and relocation count must stay as shipped.
- **Every site says what its bytes mean**, and the tools check it:
  - `insn`: one instruction, as `ndisasm -b16` prints it;
  - `text`: a string;
  - `reloc`: a relocation record, with the operand it `writes`;
  - `code`: a block, whose `.asm` beside the JSON must assemble to exactly `new`.
- **New code goes over code nothing calls, and stops short of the first relocation site
  it does not take over.** Far operands in new code are `dw 0xffff, 0x0000`, the chain
  terminator a non-additive record expects. `patch.py verify` and `apply` audit this.
- **No two patches write the same byte**, so any subset applies. `build.py --check`
  enforces it.
- `ips/` and `dist/index.html` are **generated**; run `python3 build.py`, never hand-edit
  them. `build.py --check` (CI) fails when they are stale.
- `web/vendor/col.css` is [web-ui](https://github.com/colonization-re/web-ui) pinned by
  `col-css.json`. Don't edit it. It is the page's stylesheet: use a `col-` class where one
  exists, and namespace the few page-local styles in `web/index.html` `wp-`. To move the
  pin, replace the file with another release's `col.css` asset (`gh release download TAG
  -R colonization-re/web-ui -p col.css -D web/vendor --clobber`), then update `tag`,
  `sha256`, `bytes` and `vendored` in `col-css.json`.
- The page must not fetch anything. Its CSP (`default-src 'none'`) enforces that, so keep
  CSS, data and scripts inline.
- **Keep `status` honest.** "Seen in play" means a person saw it in the running game.
  Emulator checks and byte checks are not that.

## Releasing

The site, <https://colonization-re.github.io/win-patches/>, changes only on a release.
Pushing to `main` publishes nothing.

```sh
echo 0.0.2 > VERSION && python3 build.py        # the page shows the version
git commit -am "Release 0.0.2"
git tag v0.0.2 && git push origin main v0.0.2
```

`release.yml` refuses a tag that isn't `v` + `VERSION` at that commit. It runs
`build.py --check`, then publishes the release with `win-patches.html`, the IPS files
and `SHA256SUMS.txt`. Only after that does it deploy `dist/` to Pages as committed. Keep
those asset names: `releases/latest/download/win-patches.html` depends on them.

## Before committing a patch change

```sh
python3 patch.py verify --exe /path/to/unpatched/COLONIZE.EXE   # needs the game
python3 build.py && python3 build.py --check
```

Then, in win-decomp, `vendor/re-agent-venv/bin/python tools/patch_probe.py`.
