"""Analyze TexSoup round-trip divergences and parse failures on corpus."""
import json, os, sys
import TexSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rows = json.load(open(os.path.join(ROOT, 'results/texsoup-parse.json')))


def first_diffs(a, b, k=5):
    """Return up to k (pos, a-seg, b-seg) diffs between strings a and b."""
    diffs = []
    i = j = 0
    while i < len(a) and j < len(b) and len(diffs) < k:
        if a[i] == b[j]:
            i += 1; j += 1; continue
        # find resync: scan ahead in both
        found = None
        for di in range(0, 80):
            for dj in range(0, 80):
                if a[i+di:i+di+20] == b[j+dj:j+dj+20] and di + dj > 0:
                    found = (di, dj); break
            if found: break
        if not found:
            diffs.append((i, a[i:i+60], b[j:j+60])); break
        di, dj = found
        diffs.append((i, a[i:i+di], b[j:j+dj]))
        i += di; j += dj
    return diffs, len(a), len(b)


print('======== ROUND-TRIP DIVERGED FILES ========')
for r in rows:
    if r.get('roundtrip') != 'diverged':
        continue
    f = os.path.join(ROOT, r['file'])
    src = open(f, encoding='utf-8', errors='replace').read()
    try:
        soup = TexSoup.TexSoup(src)
    except Exception:
        try:
            soup = TexSoup.TexSoup(src, tolerance=1)
        except Exception:
            continue
    out = str(soup)
    diffs, la, lb = first_diffs(src, out)
    print('\n--- %s  (src=%dB out=%dB, %d diffs shown)' % (r['file'], la, lb, len(diffs)))
    for pos, sa, sb in diffs[:4]:
        ctx = repr(src[max(0,pos-40):pos+40])
        print('   @%d ctx %s' % (pos, ctx))
        print('      SRC -%r' % sa[:70])
        print('      OUT +%r' % sb[:70])

print('\n======== PARSE FAILURES ========')
for r in rows:
    if r['ok']:
        continue
    f = os.path.join(ROOT, r['file'])
    src = open(f, encoding='utf-8', errors='replace').read()
    err = r['error']
    # extract line/offset info
    import re
    m = re.search(r'Line: (\d+), Offset: ?(\d+)', err or '')
    print('\n--- %s: %s' % (r['file'], (err or '')[:130]))
    if m:
        ln, off = int(m.group(1)), int(m.group(2))
        lines = src.split('\n')
        lo = max(0, ln-2)
        for i in range(lo, min(len(lines), ln+2)):
            print('   %4d| %s' % (i, lines[i][:110]))
        print('        ' + ' ' * off + '^' if off < 110 else '')
