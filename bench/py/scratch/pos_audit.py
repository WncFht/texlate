"""Sample the position-audit failures + bare strings for TexSoup report."""
import os, json
import TexSoup
from TexSoup.data import TexExpr, TexNode

ROOT = '/Users/fanghaotian/src/texlate/bench'
rows = json.load(open(ROOT + '/results/texsoup-parse.json'))

bad_examples = []
bare_examples = []
for r in rows:
    if not r['ok'] and not r.get('ok_t1'):
        continue
    src = open(os.path.join(ROOT, r['file']), encoding='utf-8', errors='replace').read()
    try:
        soup = TexSoup.TexSoup(src)
    except Exception:
        try:
            soup = TexSoup.TexSoup(src, tolerance=1)
        except Exception:
            continue
    for node in soup.descendants:
        p = getattr(node, 'position', None)
        s = str(node)
        if p is None:
            if len(bare_examples) < 8:
                bare_examples.append((r['file'], type(node).__name__, s[:50]))
            continue
        if p < 0 or src[p:p+len(s)] != s:
            if len(bad_examples) < 15:
                bad_examples.append((r['file'], type(getattr(node,'expr',node)).__name__,
                                     p, s[:60], src[p:p+60] if 0 <= p < len(src) else '?'))

print('== NON-SLICE-EXACT nodes (str(node) != src[pos:pos+len]) ==')
for f, t, p, s, expect in bad_examples:
    print('%s\n   %s@%d got %r want %r' % (f, t, p, s, expect))
print('\n== BARE nodes without position ==')
for f, t, s in bare_examples:
    print('%s  %s %r' % (f, t, s))
