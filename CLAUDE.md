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
  `col-css.json`. Don't edit it. Page-local styles in `web/index.html` are namespaced
  `wp-`.
- **Keep `status` honest.** "Seen in play" means a person saw it in the running game.
  Emulator checks and byte checks are not that.

## Before committing a patch change

```sh
python3 patch.py verify --exe /path/to/unpatched/COLONIZE.EXE   # needs the game
python3 build.py && python3 build.py --check
```

Then, in win-decomp, `vendor/re-agent-venv/bin/python tools/patch_probe.py`.
