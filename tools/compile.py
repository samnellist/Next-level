import subprocess, sys
ESB = "node_modules/.bin/esbuild"
BABEL_TAG = '<script src="https://cdnjs.cloudflare.com/ajax/libs/babel-standalone/7.23.5/babel.min.js"></script>\n'
OPEN = '<script type="text/babel" data-presets="react">'
for sp in sys.argv[1:]:
    src = open(f"./{sp}.html").read()
    i = src.index(OPEN); j = src.index("</script>", i)
    out = subprocess.run([ESB, "--loader=jsx", "--target=es2017", "--minify", "--legal-comments=none"], input=src[i + len(OPEN):j], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[:800]
    built = src[:i] + "<script>" + out.stdout.replace("</script", "<\\/script") + src[j:]
    assert built.count(BABEL_TAG) == 1
    open(f"./dist/{sp}.html", "w").write(built.replace(BABEL_TAG, ""))
    print(sp, "compiled", len(built) // 1024, "KB")
