#!/usr/bin/env python3
"""Regenerate everything derived from patches/*.json, or check that it is current.

    python3 build.py            # ips/*.ips and dist/index.html
    python3 build.py --check    # fail if either is stale, or a manifest is inconsistent
    python3 build.py --notes    # print the release notes for VERSION (the release workflow)

Neither needs the game. The derived files are committed so the web page works from a
checkout (or GitHub Pages) with no build, and --check is what CI runs to keep them
honest. What --check proves without the EXE:

  * every site is well formed: equal-length `expect`/`new`, a file offset, 8-byte
    relocation records;
  * no two patches write the same byte, so any subset can be applied;
  * each `code` site's .asm assembles (when nasm is installed) to exactly its `new`;
  * the vendored col.css matches its pin (web/vendor/col-css.json);
  * VERSION is MAJOR.MINOR.PATCH; the page shows it, and a release is tagged with it;
  * ips/ and dist/ are byte-identical to a fresh build.

What only `python3 patch.py verify --exe COLONIZE.EXE` can prove, because it needs the
game: that every address resolves through the EXE's own NE header, that the original
bytes are there, and that no relocation chain runs through new code.
"""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import patch                                                        # noqa: E402

IPS_DIR = os.path.join(HERE, 'ips')
TEMPLATE = os.path.join(HERE, 'web', 'index.html')
VENDOR = os.path.join(HERE, 'web', 'vendor')
PAGE = os.path.join(HERE, 'dist', 'index.html')
SITE = 'https://colonization-re.github.io/win-patches/'
WEB_FIELDS = ('name', 'kind', 'title', 'why', 'known_limits', 'test', 'status', 'target')


def version():
    v = open(os.path.join(HERE, 'VERSION')).read().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', v):
        raise SystemExit(f'build: VERSION is {v!r}, not MAJOR.MINOR.PATCH')
    return v


def check_manifests(patches):
    problems, owner = [], {}
    for p in patches.values():
        for s in p['sites']:
            where = f'{p["name"]} {patch.label(s)}'
            if 'file_offset' not in s:
                problems.append(f'{where}: no file_offset')
                continue
            fo = int(s['file_offset'], 16)
            for i in range(fo, fo + len(s['new_b'])):
                if owner.get(i, p['name']) != p['name']:
                    problems.append(f'{where}: byte {i:#x} is also written by {owner[i]}')
                owner[i] = p['name']
            if 'code' in s:
                problems += check_code(p, s, where)
    return problems


def check_code(p, s, where):
    nasm = shutil.which('nasm')
    if not nasm:
        print(f'  SKIP {where}: nasm not installed, the .asm is not re-assembled')
        return []
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, 'code.bin')
        subprocess.run([nasm, '-f', 'bin', '-o', out,
                        os.path.join(p['_dir'], s['code']['source'])], check=True)
        built = open(out, 'rb').read()
    return [] if built == s['new_b'] else [f'{where}: {s["code"]["source"]} assembles '
                                           'to different bytes than the manifest holds']


def ips(p):
    """IPS: 'PATCH', then (3-byte offset, 2-byte length, bytes)..., then 'EOF'. It has
    no checksum of its target, so the README states the SHA-256 it was made against."""
    rec = bytearray(b'PATCH')
    for s in p['sites']:
        fo = int(s['file_offset'], 16)
        if fo == 0x454f46 or fo >= 1 << 24 or len(s['new_b']) >= 1 << 16:
            raise SystemExit(f'build: {p["name"]} {patch.label(s)}: cannot be an IPS record')
        rec += fo.to_bytes(3, 'big') + len(s['new_b']).to_bytes(2, 'big') + s['new_b']
    return bytes(rec + b'EOF')


def notes(patches):
    """The release body. GitHub appends the commit list after it."""
    target = next(iter(patches.values()))['target']['sha256']
    rows = '\n'.join(f'| **{p["title"]}** `{p["name"]}` | {p["kind"]} | {p["status"]} |'
                     for p in patches.values())
    return f"""Patch your own `COLONIZE.EXE` in the browser at <{SITE}>, which now serves this \
release. `win-patches.html` below is the same page: save it and it works offline.

| patch | kind | status |
| --- | --- | --- |
{rows}

For the updated 1995 release, SHA-256 `{target}`. The page and `patch.py` (in the source \
archive) check your file before they change it. The `.ips` files do not, so check its \
SHA-256 first.
"""


def page(patches):
    pin = json.load(open(os.path.join(VENDOR, 'col-css.json')))
    css = open(os.path.join(VENDOR, pin['asset']), 'rb').read()
    if hashlib.sha256(css).hexdigest() != pin['sha256']:
        raise SystemExit(f'build: web/vendor/{pin["asset"]} does not match its pin '
                         f'({pin["tag"]}); do not edit the vendored file')
    web_patches = sorted(patches.values(), key=lambda p: (p['name'] != 'water-cycling',
                                                          p['name']))
    data = [dict({k: p[k] for k in WEB_FIELDS if k in p},
                 sites=[{k: s[k] for k in ('file_offset', 'expect', 'new')}
                        for s in p['sites']])
            for p in web_patches]
    html = open(TEMPLATE).read()
    for token, value in (('/*COL_CSS*/', css.decode()),
                         ('/*VERSION*/', json.dumps(version())),
                         ('/*PATCHES*/', json.dumps(data, separators=(',', ':')))):
        if html.count(token) != 1:
            raise SystemExit(f'build: the template must hold {token} exactly once')
        html = html.replace(token, value)
    return html.encode()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--check', action='store_true', help='change nothing; fail if stale')
    ap.add_argument('--notes', action='store_true', help='print the release notes')
    a = ap.parse_args(argv)
    patches = patch.load(patch.PATCHES)
    if a.notes:
        print(notes(patches), end='')
        return 0
    problems = check_manifests(patches)
    want = {os.path.join(IPS_DIR, n + '.ips'): ips(p) for n, p in patches.items()}
    want[PAGE] = page(patches)
    stray = {os.path.join(IPS_DIR, f) for f in os.listdir(IPS_DIR) if f.endswith('.ips')
             } - set(want) if os.path.isdir(IPS_DIR) else set()
    for path, data in want.items():
        rel = os.path.relpath(path, HERE)
        have = open(path, 'rb').read() if os.path.exists(path) else None
        if have == data:
            print(f'  ok     {rel}')
        elif a.check:
            problems.append(f'{rel} is stale: run python3 build.py')
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, 'wb').write(data)
            print(f'  wrote  {rel}  {len(data)} B')
    for path in sorted(stray):
        if a.check:
            problems.append(f'{os.path.relpath(path, HERE)} has no manifest')
        else:
            os.remove(path)
            print(f'  removed {os.path.relpath(path, HERE)}')
    for line in problems:
        print(f'FAIL {line}')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
