#!/usr/bin/env python3
"""Apply the patches in patches/ to your own copy of Colonization for Windows.

    python3 patch.py list
    python3 patch.py status --exe COLONIZE.EXE
    python3 patch.py apply --all --exe COLONIZE.EXE --in-place     # keeps COLONIZE.EXE.orig
    python3 patch.py apply water-cycling --exe COLONIZE.EXE --out COLWATER.EXE
    python3 patch.py revert --all --exe COLONIZE.EXE --in-place
    python3 patch.py verify --exe COLONIZE.EXE                      # the maintainer's check

Standard library only; Python 3.8 or later. Nothing is downloaded or uploaded.

What it refuses
---------------
Each patch changes a few bytes IN PLACE and never changes a length, so the result is
your own binary with those bytes different. A patch file lists, for every site, the
bytes the original has there and the bytes the patch puts there. Before writing
anything the tool checks every site of every patch you asked for: a site holding
neither is a different build of the game (or a damaged file), and the whole operation
stops with nothing written. Applying a patch twice, or reverting one that is not
there, leaves it alone.

Your file is never overwritten unless you say --in-place, and then the original is
kept beside it as .orig (once: an existing .orig is never replaced).

How a site is found
-------------------
Every site names its address twice -- as selector:offset (segment 1 is 1000, 8 per
segment; a relocation record by segment and index) and as a file offset -- and the two
must agree through the EXE's own NE header. A patch that adds code over dead code also
moves relocation records; before writing, `audit` walks every relocation chain in the
segments it touches and refuses if the loader would write anywhere the patch did not
declare. `verify` additionally re-assembles `code` sites with nasm and decodes `insn`
sites with ndisasm, when those are installed.
"""
import argparse, glob, hashlib, json, os, shutil, struct, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PATCHES = os.path.join(HERE, 'patches')


# ------------------------------------------------------------------ the NE header
def segments(b):
    """[(file offset, length, flags)] by segment index 1..n, from the EXE's own NE header."""
    if b[:2] != b'MZ':
        raise SystemExit('patch: not an MZ executable')
    ne = struct.unpack_from('<H', b, 0x3c)[0]
    if b[ne:ne + 2] != b'NE':
        raise SystemExit('patch: not an NE (Win16) executable')
    count = struct.unpack_from('<H', b, ne + 0x1c)[0]
    table = ne + struct.unpack_from('<H', b, ne + 0x22)[0]
    shift = struct.unpack_from('<H', b, ne + 0x32)[0]
    out = [None]
    for i in range(count):
        sector, length, flags = struct.unpack_from('<HHH', b, table + i * 8)
        out.append((sector << shift, length or 0x10000, flags))
    return out


def seg_of(sel):
    return (sel - 0x1000) // 8 + 1


def resolve(segs, at):
    """'1060:3c96' -> file offset, bounds-checked against that segment's length."""
    sel, off = (int(x, 16) for x in at.split(':'))
    index = seg_of(sel)
    if (sel - 0x1000) % 8 or not 1 <= index < len(segs):
        raise SystemExit(f'patch: {at}: no segment for selector {sel:04x}')
    base, length, _ = segs[index]
    return base + off, off, length


# ------------------------------------------------------------------ relocations
# An NE segment with RELOCINFO (0x100) is followed in the file by a word count and
# that many 8-byte records: address type, flags, the site's offset, then the target.
# A NON-additive record's site holds the offset of the next site to patch with the
# same value, 0xffff ending the chain; the loader walks it. So a record can be moved
# to a new site only if that site holds 0xffff -- `audit` checks exactly that.
RELOC_TYPES = {0: ('LOBYTE', 1), 2: ('SEGMENT', 2), 3: ('FAR_ADDR', 4), 5: ('OFFSET', 2)}


def reloc_table(b, segs, index):
    """(file offset of record 0, record count) for segment `index`, or (None, 0)."""
    base, length, flags = segs[index]
    if not flags & 0x100:
        return None, 0
    return base + length + 2, struct.unpack_from('<H', b, base + length)[0]


def describe_reloc(rec):
    """8 record bytes -> 'FAR_ADDR -> 9:07f1 @0de2' (segment number : offset)."""
    kind, flags, site = rec[0], rec[1], struct.unpack_from('<H', rec, 2)[0]
    name = RELOC_TYPES.get(kind, (f'type{kind}', 0))[0]
    add = ' additive' if flags & 4 else ''
    a, b2 = struct.unpack_from('<HH', rec, 4)
    target = {0: f'{rec[4]}:{b2:04x}' if rec[4] != 0xff else f'entry#{b2}',
              1: f'import {a}.{b2}', 2: f'import {a} name@{b2:#x}',
              3: 'osfixup'}[flags & 3]
    return f'{name}{add} -> {target} @{site:04x}'


def reloc_writes(b, segs, index):
    """Every record of segment `index` -> the (start, end) byte ranges the loader
    writes for it, following non-additive chains through the segment's own bytes."""
    base, length, _ = segs[index]
    first, count = reloc_table(b, segs, index)
    out = []
    for k in range(count):
        rec = b[first + 8 * k:first + 8 * k + 8]
        width = RELOC_TYPES.get(rec[0], ('', 0))[1]
        site, spans = struct.unpack_from('<H', rec, 2)[0], []
        while True:
            if site + max(width, 2) > length or len(spans) > length:
                raise SystemExit(f'patch: SEG{index} record #{k}: chain leaves '
                                 f'the segment at {site:#x}')
            spans.append((site, site + width))
            if rec[1] & 4:                          # additive: one site, no chain
                break
            site = struct.unpack_from('<H', b, base + site)[0]
            if site == 0xffff:
                break
        out.append(spans)
    return out


# ------------------------------------------------------------------ manifests
def label(s):
    r = s.get('reloc')
    return f'SEG{r["segment"]} reloc #{r["index"]}' if r else s['at']


def load(patch_dir):
    out = {}
    for path in sorted(glob.glob(os.path.join(patch_dir, '*.json'))):
        p = json.load(open(path))
        p['_dir'] = os.path.dirname(os.path.abspath(path))
        for s in p['sites']:
            s['expect_b'] = bytes.fromhex(s['expect'])
            s['new_b'] = bytes.fromhex(s['new'])
            if len(s['expect_b']) != len(s['new_b']):
                raise SystemExit(f'patch: {p["name"]} {label(s)}: new is '
                                 f'{len(s["new_b"])} bytes, expect is {len(s["expect_b"])}'
                                 ' -- a patch may not change a length')
            if 'reloc' in s and len(s['expect_b']) != 8:
                raise SystemExit(f'patch: {p["name"]} {label(s)}: a relocation '
                                 'record is 8 bytes')
        out[p['name']] = p
    return out


def locate(p, b, segs):
    """Each site's file offset, with its address and `file_offset` required to agree.

    A code or data site is addressed as selector:offset; a relocation record as its
    segment and index in that segment's table -- both resolved through THIS file's
    own NE header, so the manifest's file_offset is a second opinion, not the source."""
    offs = []
    for s in p['sites']:
        if 'reloc' in s:
            r = s['reloc']
            first, count = reloc_table(b, segs, r['segment'])
            if first is None or not 0 <= r['index'] < count:
                raise SystemExit(f'patch: {p["name"]} {label(s)}: no such record')
            fo = first + 8 * r['index']
        else:
            fo, off, length = resolve(segs, s['at'])
            if off + len(s['expect_b']) > length:
                raise SystemExit(f'patch: {p["name"]} {label(s)}: runs past the '
                                 'segment end')
        if 'file_offset' in s and int(s['file_offset'], 16) != fo:
            raise SystemExit(f'patch: {p["name"]} {label(s)}: resolves to {fo:#x}, '
                             f'manifest says {s["file_offset"]}')
        offs.append(fo)
    return offs


def state(p, b, segs):
    """'original' | 'applied' | 'partial' | 'mismatch', and the per-site detail."""
    seen = []
    for s, fo in zip(p['sites'], locate(p, b, segs)):
        have = b[fo:fo + len(s['expect_b'])]
        seen.append('original' if have == s['expect_b'] else
                    'applied' if have == s['new_b'] else 'mismatch')
    if 'mismatch' in seen:
        return 'mismatch', seen
    if all(x == 'original' for x in seen):
        return 'original', seen
    if all(x == 'applied' for x in seen):
        return 'applied', seen
    return 'partial', seen


def sha(b):
    return hashlib.sha256(b).hexdigest()


# ------------------------------------------------------------------ decoding
def ndisasm(code, org):
    """The first instruction ndisasm decodes from `code` at origin `org`, or None."""
    exe = shutil.which('ndisasm')
    if not exe:
        return None
    with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
        f.write(code)
    try:
        out = subprocess.run([exe, '-b16', '-o', hex(org), f.name],
                             capture_output=True, text=True, check=True).stdout
    finally:
        os.unlink(f.name)
    first = out.splitlines()[0].split(None, 2)
    return first[2].strip() if len(first) == 3 else None


def check_decode(p, s, b, patched, segs):
    """ndisasm must read the instruction the manifest says, before and after."""
    insn = s.get('insn')
    if insn:
        fo, off, _ = resolve(segs, insn['at'])
        got = (ndisasm(b[fo:fo + 16], off), ndisasm(patched[fo:fo + 16], off))
        if got[0] is None:
            return 'SKIP (no ndisasm)'
        want = (insn['before'], insn['after'])
        if got != want:
            raise SystemExit(f'patch: {p["name"]} {label(s)}: decodes as {got}, '
                             f'manifest says {want}')
        return f'{got[0]}  ->  {got[1]}'
    text = s.get('text')
    if text:
        fo, _, _ = resolve(segs, s['at'])
        n = len(s['expect_b'])
        got = tuple(x[fo:fo + n].split(b'\0')[0].decode('latin-1') for x in (b, patched))
        if got != (text['before'], text['after']):
            raise SystemExit(f'patch: {p["name"]} {label(s)}: text is {got}')
        return f'"{got[0]}"  ->  "{got[1]}"'
    rel = s.get('reloc')
    if rel:
        got = (describe_reloc(s['expect_b']), describe_reloc(s['new_b']))
        if got != (rel['before'], rel['after']):
            raise SystemExit(f'patch: {p["name"]} {label(s)}: decodes as {got}, '
                             f'manifest says {(rel["before"], rel["after"])}')
        return f'{got[0]}  ->  {got[1]}'
    code = s.get('code')
    if code:
        # The source is the patch; the hex in the manifest is its assembled form.
        exe = shutil.which('nasm')
        if not exe:
            return 'SKIP (no nasm)'
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, 'code.bin')
            subprocess.run([exe, '-f', 'bin', '-o', out,
                            os.path.join(p['_dir'], code['source'])], check=True)
            built = open(out, 'rb').read()
        if built != s['new_b']:
            raise SystemExit(f'patch: {p["name"]} {label(s)}: {code["source"]} '
                             'assembles to different bytes than the manifest holds')
        return f'{code["source"]} assembles to these {len(built)} bytes'
    raise SystemExit(f'patch: {p["name"]} {label(s)}: site states none of '
                     'insn, text, reloc or code')


def audit(p, b, patched, segs):
    """What the LOADER will write, before and after, in every segment the patch touches.

    A patch that writes code over bytes some relocation record still points into
    would be corrupted at load time -- silently, and differently on every machine. So,
    walking every record's chain in both files: a record the patch did not edit must
    write exactly what it wrote before, and nothing inside new code; a record it did
    edit must write only the operand its `reloc.writes` names. Returns a summary."""
    code = []                                       # (segment, start, end) of new code
    for s in p['sites']:
        if 'at' in s and 'code' in s:
            sel, off = (int(x, 16) for x in s['at'].split(':'))
            code.append((seg_of(sel), off, off + len(s['new_b'])))
    edited = {(s['reloc']['segment'], s['reloc']['index']): s['reloc']
              for s in p['sites'] if 'reloc' in s}
    touched = sorted({c[0] for c in code} | {k[0] for k in edited})
    lines = []
    for index in touched:
        old, new = reloc_writes(b, segs, index), reloc_writes(patched, segs, index)
        inside = lambda a, z: [c for c in code if c[0] == index and a < c[2] and z > c[1]]
        for k, spans in enumerate(new):
            if (index, k) in edited:
                want = edited[(index, k)].get('writes')
                got = [f'{a:04x}' for a, _ in spans]
                if want is not None and got != [want]:
                    raise SystemExit(f'patch: {p["name"]} SEG{index} reloc #{k} '
                                     f'writes at {got}, manifest says [{want}]')
                continue
            if spans != old[k]:
                raise SystemExit(f'patch: {p["name"]}: SEG{index} reloc #{k}, which '
                                 f'the patch does not edit, now writes {spans} (was '
                                 f'{old[k]}) -- a chain runs through new bytes')
            for a, z in spans:
                if inside(a, z):
                    raise SystemExit(f'patch: {p["name"]}: SEG{index} reloc #{k} '
                                     f'writes {a:#x}..{z:#x}, inside the new code')
        lines.append(f'SEG{index}: {len(new)} records, '
                     f'{sum(1 for k in edited if k[0] == index)} edited, the rest '
                     'unchanged and clear of the new code')
    return lines


def write_sites(p, b, segs, forward=True):
    out = bytearray(b)
    for s, fo in zip(p['sites'], locate(p, b, segs)):
        new = s['new_b'] if forward else s['expect_b']
        out[fo:fo + len(new)] = new
    return bytes(out)


# ------------------------------------------------------------------ commands
def pick(patches, names, every):
    if every:
        return list(patches.values())
    missing = [n for n in names if n not in patches]
    if missing or not names:
        raise SystemExit(f'patch: unknown or no patch: {missing or "(none)"}; '
                         f'have {", ".join(patches)}')
    return [patches[n] for n in names]


def cmd_list(patches, a):
    for p in patches.values():
        n = sum(len(s['expect_b']) for s in p['sites'])
        print(f'{p["name"]:24} {p["kind"]:8} {len(p["sites"])} site(s) {n:3} B  {p["title"]}')


def cmd_verify(patches, a):
    b = open(a.exe, 'rb').read()
    segs = segments(b)
    print(f'{a.exe}  sha256 {sha(b)[:16]}...')
    bad = 0
    for p in patches.values():
        if sha(b) != p['target']['sha256']:
            print(f'  {p["name"]}: FAIL -- targets {p["target"]["sha256"][:16]}..., '
                  'not this file')
            bad += 1
            continue
        st, _ = state(p, b, segs)
        if st != 'original':
            print(f'  {p["name"]}: FAIL -- the shipped bytes are {st}')
            bad += 1
            continue
        patched = write_sites(p, b, segs)
        print(f'  {p["name"]}: OK')
        for s in p['sites']:
            print(f'      {label(s)}  {check_decode(p, s, b, patched, segs)}')
        for line in audit(p, b, patched, segs):
            print(f'      fixups {line}')
    # Two patches writing the same byte could not be applied independently.
    owner = {}
    for p in patches.values():
        for s, fo in zip(p['sites'], locate(p, b, segs)):
            for i in range(fo, fo + len(s['expect_b'])):
                if i in owner and owner[i] != p['name']:
                    print(f'  OVERLAP at {i:#x}: {owner[i]} and {p["name"]}')
                    bad += 1
                owner[i] = p['name']
    return 1 if bad else 0


def cmd_status(patches, a):
    b = open(a.exe, 'rb').read()
    segs = segments(b)
    print(f'{a.exe}  sha256 {sha(b)[:16]}...')
    for p in patches.values():
        st, seen = state(p, b, segs)
        print(f'  {p["name"]:24} {st}' + ('' if st in ('original', 'applied')
                                         else f'  {seen}'))


def transform(patches, a, forward):
    todo = pick(patches, a.names, a.all)
    b = open(a.exe, 'rb').read()
    segs = segments(b)
    out = b
    for p in todo:
        st, seen = state(p, out, segs)
        done, undone = ('applied', 'original') if forward else ('original', 'applied')
        if st == done:
            print(f'  {p["name"]}: already {done}, left alone')
            continue
        if st != undone:
            raise SystemExit(f'patch: {p["name"]}: this file is {st} {seen} -- a '
                             'different build, or damaged. Nothing was written.')
        before, out = out, write_sites(p, out, segs, forward)
        if forward:
            audit(p, before, out, segs)             # refuses before anything is written
        print(f'  {p["name"]}: {"applied" if forward else "reverted"}')
    if a.in_place:
        dst = a.exe
        if not os.path.exists(a.exe + '.orig'):
            shutil.copy2(a.exe, a.exe + '.orig')
            print(f'  original kept as {a.exe}.orig')
    else:
        dst = a.out
        if dst is None and a.out_dir:                # a caller's default, e.g. a build tree
            dst = os.path.join(a.out_dir, 'all' if a.all else
                               '+'.join(p['name'] for p in todo), 'COLONIZE.EXE')
        if dst is None:
            raise SystemExit('patch: say where to write: --out NEW.EXE, or --in-place '
                             '(which keeps the original as .orig)')
        if os.path.abspath(dst) == os.path.abspath(a.exe):
            raise SystemExit('patch: --out is the input; use --in-place to mean that')
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    open(dst, 'wb').write(out)
    print(f'{dst}  sha256 {sha(out)[:16]}...')


def main(argv=None, exe=None, out_dir=None, patches=PATCHES):
    """`exe` and `out_dir` are defaults a wrapper may supply (a research tree that
    keeps the shipped EXE and a build directory); a player gives --exe and --out."""
    ap = argparse.ArgumentParser(prog='patch.py', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--patches', default=patches, help='directory of *.json manifests')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('list', help='the patches and what they do')
    for name, what in (('status', 'which patches a file already carries'),
                       ('verify', 'check every patch against the unpatched EXE')):
        sp = sub.add_parser(name, help=what)
        sp.add_argument('--exe', default=exe, required=exe is None)
    for name, what in (('apply', 'apply patches'), ('revert', 'take patches back out')):
        sp = sub.add_parser(name, help=what)
        sp.add_argument('names', nargs='*', help='patch names; see `list`')
        sp.add_argument('--all', action='store_true', help='every patch')
        sp.add_argument('--exe', default=exe, required=exe is None)
        g = sp.add_mutually_exclusive_group()
        g.add_argument('--out', help='write the result here')
        g.add_argument('--in-place', action='store_true',
                       help='overwrite --exe, keeping the original as .orig')
        sp.set_defaults(out_dir=out_dir)
    a = ap.parse_args(argv)

    found = load(a.patches)
    return {'list': cmd_list, 'verify': cmd_verify, 'status': cmd_status,
            'apply': lambda p, a: transform(p, a, True),
            'revert': lambda p, a: transform(p, a, False)}[a.cmd](found, a) or 0


if __name__ == '__main__':
    sys.exit(main())
