import TexSoup

src = open("/Users/fanghaotian/src/texlate/bench/fixtures/tricky-209.tex").read()
soup = TexSoup.TexSoup(src)
out = str(soup)
for i, (a, b) in enumerate(zip(src, out)):
    if a != b:
        print("diff@%d SRC %r" % (i, src[max(0, i - 30) : i + 30]))
        print("       OUT %r" % (out[max(0, i - 30) : i + 30],))
        break
print("lens", len(src), len(out))
print("SRC tail", repr(src[-60:]))
print("OUT tail", repr(out[-60:]))
