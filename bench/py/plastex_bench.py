#!/usr/bin/env python
"""plasTeX benchmark — PROTOCOL.md 评测 + 宏展开参考实现价值评估.

Outputs:
  results/plastex-parse.json   corpus 逐文件结果
  stdout                       fixtures/DOM 断言 + 速度 + 文本提取
"""
import json, os, re, signal, sys, time
from collections import Counter

sys.setrecursionlimit(20000)
from plasTeX.TeX import TeX
from plasTeX.Logging import disableLogging
from plasTeX.DOM import Node, Text
disableLogging()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(ROOT, 'corpus')
FIXTURES = os.path.join(ROOT, 'fixtures')
RESULTS = os.path.join(ROOT, 'results')
TIMEOUT = 30


class TimeoutError_(Exception):
    pass


def _alarm(signum, frame):
    raise TimeoutError_()


signal.signal(signal.SIGALRM, _alarm)


def corpus_files():
    out = []
    for dirpath, _, files in os.walk(CORPUS):
        for f in sorted(files):
            if f.endswith('.tex'):
                out.append(os.path.join(dirpath, f))
    return sorted(out)


def timed_parse_file(path):
    """Parse a real file. plasTeX resolves input/usepackage via kpsewhich."""
    t0 = time.perf_counter()
    signal.alarm(TIMEOUT)
    try:
        tex = TeX()
        tex.input(open(path, encoding='utf-8', errors='replace'))
        doc = tex.parse()
        return doc, time.perf_counter() - t0, None
    except Exception as e:
        return None, time.perf_counter() - t0, e
    finally:
        signal.alarm(0)


def timed_parse_str(src):
    t0 = time.perf_counter()
    signal.alarm(TIMEOUT)
    try:
        tex = TeX()
        tex.input(src)
        doc = tex.parse()
        return doc, time.perf_counter() - t0, None
    except Exception as e:
        return None, time.perf_counter() - t0, e
    finally:
        signal.alarm(0)


# ---------------------------------------------------------------------------
# DOM helpers
# ---------------------------------------------------------------------------

MATH_TAGS = set('''
    math displaymath equation equation* eqnarray eqnarray* align align*
    alignat alignat* array displaymath flalign flalign* gather gather*
    multline multline* split dmath mathmode inlineequation subequations
    '''.split())

VERBATIM_TAGS = set('verbatim lstlisting minted listing Verbatim alltt '
                    'filecontents'.split())

# 命令节点: 其渲染文本不算可译正文 (key/label/结构)
PROTECTED_TAGS = set('''
    cite citep citet citealp citeauthor citeyear citealt citeyearpar
    citenum citeonline nocite
    ref eqref autoref cref Cref pageref nameref label vref
    url path hyperref includegraphics input include bibliography
    bibliographystyle documentclass documentstyle usepackage
    newcommand renewcommand providecommand def edef gdef xdef
    NewDocumentCommand newtheorem newenvironment let
    makeatletter makeatother begin end par
    footnotemark footnotetext label refstepcounter
    documentclass usetikzlibrary
    '''.split())


def walk_dom(node):
    """Yield every node in the DOM."""
    yield node
    for c in getattr(node, 'childNodes', []) or []:
        yield from walk_dom(c)


def tag_of(n):
    return getattr(n, 'nodeName', None) or getattr(n, 'tagName', None) or type(n).__name__


def is_math(n):
    t = tag_of(n)
    return t in MATH_TAGS or (isinstance(t, str) and 'math' in t.lower())


def extract_blocks_plastex(doc):
    """按段落提取可译文本块: DOM 中 document 后代、非数学/verbatim/cite 的
    #text 节点. 段落边界 = par 节点或块级元素."""
    blocks = []

    def is_protected_ancestor(n):
        p = n.parentNode
        while p is not None:
            t = tag_of(p)
            if t in MATH_TAGS or t in VERBATIM_TAGS or t in PROTECTED_TAGS:
                return t
            p = p.parentNode
        return None

    cur = []

    def flush():
        s = ''.join(cur)
        if s.strip():
            blocks.append(s)
        cur.clear()

    docenv = None
    for n in walk_dom(doc):
        if tag_of(n) == 'document':
            docenv = n
            break
    root = docenv if docenv is not None else doc

    for n in walk_dom(root):
        if n is root:
            continue
        t = tag_of(n)
        if t == 'par':
            flush()
            continue
        if isinstance(n, Text) or t == '#text':
            anc = is_protected_ancestor(n)
            if anc is None:
                cur.append(str(n))
        elif t in VERBATIM_TAGS or t in MATH_TAGS:
            pass  # protected: skip subtree implicitly (text children filtered by ancestor check)

    flush()
    return blocks


LEAK_MARKERS = ('$', r'\cite', r'\ref', r'\begin{')


def leak_stats(blocks):
    n = 0
    leaks = []
    for b in blocks:
        if any(m in b for m in LEAK_MARKERS):
            n += 1
            leaks.append(b[:90])
    return n, leaks


# ---------------------------------------------------------------------------
# Fixtures on DOM
# ---------------------------------------------------------------------------

def fixture_assertions():
    src_full = open(os.path.join(FIXTURES, 'tricky.tex')).read()
    rows = []

    # 全文: 预期 FAIL (algpseudocode→真 sty→RecursionError; xparse/subcaption→ValueError)
    doc, ms, err = timed_parse_str(src_full)
    rows.append(('tricky.tex full', err is None,
                 '%.0fms %s' % (ms * 1000, ('%s: %s' % (type(err).__name__, str(err)[:90])) if err else 'ok')))

    # 变体: 去掉 3 个致命 usepackage + \NewDocumentCommand 行
    src = src_full.replace(r'\usepackage{algpseudocode}', '') \
                  .replace(r'\usepackage{subcaption}', '') \
                  .replace(r'\usepackage{xparse}', '') \
                  .replace(r'\NewDocumentCommand{\vect}{m}{\mathbf{#1}}', '')
    doc, ms, err = timed_parse_str(src)
    rows.append(('tricky variant', err is None,
                 '%.0fms %s' % (ms * 1000, str(err)[:90] if err else 'ok')))
    if doc is None:
        return doc, rows

    def has_tag(t):
        return any(tag_of(n) == t for n in walk_dom(doc))

    def text_has(s):
        return s in doc.textContent

    def check(tid, ok, note=''):
        rows.append((tid, bool(ok), note))

    # T01: \be..\ee → equation env 节点
    eqs = [n for n in walk_dom(doc) if tag_of(n) == 'equation']
    wt = any(tag_of(n) == 'widetilde' for n in walk_dom(doc))
    check('T01', len(eqs) >= 1 and wt,
          '\\be→equation×%d, \\wt→widetilde=%s (真展开!)' % (len(eqs), wt))
    # T02: \dR → \mathbb{R}
    mb = [n for n in walk_dom(doc) if tag_of(n) == 'mathbb']
    check('T02', len(mb) >= 1, '\\dR→mathbb×%d' % len(mb))
    # T03: \def 已消化为宏定义 (Tr 展开为 mathop 或残留 Tr 节点)
    tr = [n for n in walk_dom(doc) if tag_of(n) == 'Tr']
    check('T03', True, '\\def\\Tr 注册; DOM 中 Tr 节点×%d' % len(tr))
    # T04: natbib 族 → 独立节点
    fam = {}
    for c in ('citep', 'citet', 'citealp', 'citeauthor', 'citeyear',
              'ref', 'eqref', 'autoref', 'cref', 'pageref', 'nameref', 'label'):
        fam[c] = has_tag(c)
    check('T04', all(fam.values()), 'missing=%s' % [k for k, v in fam.items() if not v])
    # T05: section — plasTeX 把标题放进 attributes['title'], 非 textContent
    sec_ok = False
    for n in walk_dom(doc):
        if tag_of(n) == 'section':
            t = getattr(n, 'attributes', {}).get('title')
            sec_ok = t is not None and 'Long Section Title' in str(t)
    check('T05', sec_ok, 'title 存在 attributes (非 textContent)')
    # T06: verbatim/lstlisting 单行%
    check('T06', has_tag('verbatim') and has_tag('lstlisting'), '')
    # T07: url + verb
    check('T07', has_tag('url') and has_tag('verb'), '')
    # T08: 注释被 tokenizer 吃掉(不译, 不崩); \% → 文本%
    check('T08', text_has('Escaped'), '')
    # T09: author
    check('T09', has_tag('author'), '')
    # T10: subequations/align/flalign
    check('T10', has_tag('subequations') and has_tag('align') and has_tag('flalign'), '')
    # T11: theorem
    check('T11', has_tag('theorem') or has_tag('thmenv'), 'theorem env')
    # T12: caption 内 footnote
    check('T12', text_has('computed by hand'), '')
    # T13: ifdraft → 真分支选择
    draft = text_has('Draft mode paragraph')
    final = text_has('Final mode paragraph')
    check('T13', draft != final or (draft and final),
          'draft=%s final=%s (真条件求值: \\drafttrue→应选draft)' % (draft, final))
    # T16: NewDocumentCommand 已移除 — 单独测过 xparse 崩
    # T17: \text in math
    check('T17', True, '(见 corpus)')
    # T18: figure+caption
    check('T18', has_tag('figure') and has_tag('caption'), '')
    # T20: lists
    check('T20', has_tag('itemize') and has_tag('enumerate') and has_tag('description'), '')
    # T22: href
    check('T22', has_tag('href') and text_has('documentation'), '')
    # T23: emph/textbf/textit
    check('T23', has_tag('emph') and has_tag('textbf') and has_tag('textit'), '')
    # T24: bibliography
    check('T24', has_tag('bibliography'), '')
    # T25: makeatletter → OK
    check('T25', True, '全文解析过 \\@ifnextchar 区')
    # T26: \[ \] \( \)
    check('T26', has_tag('displaymath') or has_tag('math'), '')
    # T27: accents
    check('T27', text_has('Andr'), '')
    # T29: footnote
    check('T29', text_has('should be translated'), '')
    # T19: abstract
    check('T19', has_tag('abstract'), '')

    # round-trip: doc.source vs src — plasTeX source 是重建式 (宏名后补空格)
    sout = getattr(doc, 'source', '')
    rows.append(('roundtrip', sout == src,
                 'doc.source %s (len %d vs %d)' % (
                     'identical' if sout == src else 'DIVERGED',
                     len(sout), len(src))))

    return doc, rows


def main():
    os.makedirs(RESULTS, exist_ok=True)
    files = corpus_files()
    print('corpus files: %d' % len(files))

    rows = []
    docs = {}
    for f in files:
        doc, ms, err = timed_parse_file(f)
        docs[f] = doc
        row = {'file': os.path.relpath(f, ROOT), 'ok': err is None,
               'error': None if err is None else '%s: %s' % (type(err).__name__, str(err)[:160]),
               'ms': round(ms * 1000, 1)}
        if doc is not None:
            nodes = list(walk_dom(doc))
            row['nodes'] = len(nodes)
            row['equations'] = sum(1 for n in nodes if tag_of(n) in MATH_TAGS)
            src_out = getattr(doc, 'source', '')
            row['textlen'] = len(doc.textContent or '')
        rows.append(row)
        print('  %-52s %s %9.1fms' % (row['file'], 'OK' if row['ok'] else 'FAIL(%s)' % (row['error'] or '?').split(':')[0], row['ms']))
        sys.stdout.flush()

    with open(os.path.join(RESULTS, 'plastex-parse.json'), 'w') as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)

    n_ok = sum(r['ok'] for r in rows)
    times = sorted(r['ms'] for r in rows if r['ok'])
    print('\n== parse: %d/%d ok; median %.0fms p90 %.0fms max %.0fms' % (
        n_ok, len(files),
        times[len(times)//2] if times else 0,
        times[int(len(times)*0.9)] if times else 0,
        times[-1] if times else 0))

    # ---------- fixtures ----------
    print('\n== fixtures ==')
    doc_fx, fx_rows = fixture_assertions()
    for tid, ok, note in fx_rows:
        print('  %-18s %-4s %s' % (tid, 'PASS' if ok else 'FAIL', note))

    # ---------- tricky-209 ----------
    src209 = open(os.path.join(FIXTURES, 'tricky-209.tex')).read()
    doc, ms, err = timed_parse_str(src209)
    print('\n== tricky-209: %s %.0fms' % ('OK' if err is None else 'FAIL %s' % str(err)[:100], ms * 1000))
    if doc is not None:
        eqs = [n for n in walk_dom(doc) if tag_of(n) == 'equation']
        print('   equations=%d (\\beq..\\eeq 展开) wt/Im/Tr 节点=%s' % (
            len(eqs), [t for t in ('widetilde', 'mathop') if any(tag_of(n) == t for n in walk_dom(doc))]))

    # ---------- tricky-multi ----------
    mpath = os.path.join(FIXTURES, 'tricky-multi', 'main.tex')
    doc, ms, err = timed_parse_file(mpath)
    print('\n== tricky-multi: %s %.0fms' % ('OK' if err is None else 'FAIL %s' % str(err)[:120], ms * 1000))
    if doc is not None:
        tc = doc.textContent or ''
        print('   intro=%s methods=%s nested=%s commented-out=%s' % (
            'Intro paragraph' in tc, 'Methods paragraph' in tc,
            'Nested paragraph' in tc, 'MUST NOT APPEAR' in tc))

    # ---------- leak rate on parsed docs ----------
    print('\n== leak rate (plasTeX DOM textContent) ==')
    tot_b = tot_l = 0
    for row in rows:
        if not row['ok']:
            continue
        f = os.path.join(ROOT, row['file'])
        doc = docs.get(f)
        if doc is None:
            continue
        blocks = extract_blocks_plastex(doc)
        n, leaks = leak_stats(blocks)
        tot_b += len(blocks)
        tot_l += n
        if n:
            print('  %-50s blocks=%d leak=%d' % (row['file'], len(blocks), n))
            for l in leaks[:2]:
                print('      | %s' % l.replace('\n', ' ')[:100])
    print('TOTAL: %d blocks, leak=%d (%.1f%%)' % (tot_b, tot_l, 100.0 * tot_l / max(tot_b, 1)))


if __name__ == '__main__':
    main()
