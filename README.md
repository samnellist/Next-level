# Next Level Sport — source

- `cricket.html`, `football.html`, `rugby.html`, `hockey.html`, `golf.html` — the five sport apps (React + JSX in one file each).
- `admin.html` — the admin app.
- `site/` — the other files on the Netlify site (home page, privacy, terms, support, icons).
- `firestore-rules.txt` — Firebase security rules.

## Build for Netlify
The source files use JSX, so they are compiled before upload:

    npm install esbuild
    mkdir -p dist
    python3 tools/compile.py cricket football rugby hockey golf

(edit the ESB path at the top of tools/compile.py to `node_modules/.bin/esbuild`)
Then upload `dist/*.html` + everything in `site/` + `admin.html` to Netlify.
