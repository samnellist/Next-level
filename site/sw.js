// Next Level Sport — service worker: lets the apps open without signal.
//
// - Pages (cricket.html etc.): network first, so new versions show up
//   straight away; the saved copy is used when there's no signal.
// - React, Firebase and the heading font: saved once, then served from the phone.
// - Logins, saving data (Firestore), PayPal and admin are never touched here.
//   Logs saved offline wait in Firebase's own offline store and send themselves
//   when the phone is back online.
//
// If you ever change the CDN versions in the apps, bump VERSION.
const VERSION = "nl-v1";
const PAGES = VERSION + "-pages";
const LIBS = VERSION + "-libs";

const SHELL = ["./", "./index.html", "./manifest.webmanifest", "./icon-192.png", "./icon-512.png", "./apple-touch-icon.png", "./favicon-32.png"];
const CORS_LIBS = [
  "https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js",
  "https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.2.0/umd/react-dom.production.min.js",
];
const OPAQUE_LIBS = [
  "https://www.gstatic.com/firebasejs/10.12.2/firebase-app-compat.js",
  "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth-compat.js",
  "https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore-compat.js",
];
const LIB_HOSTS = ["cdnjs.cloudflare.com", "fonts.googleapis.com", "fonts.gstatic.com"];

async function put(cacheName, req, res) {
  if (!res || !(res.ok || res.type === "opaque")) return;
  const c = await caches.open(cacheName);
  await c.put(req, res);
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const pages = await caches.open(PAGES);
      await Promise.all(SHELL.map((u) => pages.add(u).catch(() => {})));
      await Promise.all(CORS_LIBS.map((u) => fetch(u, { mode: "cors" }).then((r) => put(LIBS, u, r)).catch(() => {})));
      await Promise.all(OPAQUE_LIBS.map((u) => fetch(u, { mode: "no-cors" }).then((r) => put(LIBS, u, r)).catch(() => {})));
      await self.skipWaiting();
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keep = [PAGES, LIBS];
      const names = await caches.keys();
      await Promise.all(names.filter((n) => n.startsWith("nl-") && !keep.includes(n)).map((n) => caches.delete(n)));
      await self.clients.claim();
    })()
  );
});

// The app asks for the page it's on to be saved right after it first loads.
self.addEventListener("message", (event) => {
  const d = event.data || {};
  if (d.type !== "cache-page" || typeof d.url !== "string") return;
  const url = new URL(d.url, self.registration.scope);
  if (url.origin !== self.location.origin || !/\.html$|\/$/.test(url.pathname) || /admin\.html$/.test(url.pathname)) return;
  event.waitUntil(
    caches.open(PAGES).then((c) => c.match(url.pathname).then((hit) => hit || fetch(url.pathname).then((r) => r.ok && c.put(url.pathname, r)).catch(() => {})))
  );
});

function timeout(ms) {
  return new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), ms));
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  if (url.origin === self.location.origin) {
    if (/admin(\.html|\.webmanifest|-icon)/.test(url.pathname) || url.pathname.endsWith("/sw.js")) return;
    const isPage = req.mode === "navigate" || url.pathname.endsWith(".html") || url.pathname.endsWith("/");
    if (isPage) {
      // Network first (with a short wait on weak signal), then the saved copy.
      event.respondWith(
        (async () => {
          const net = fetch(req).then((res) => {
            if (res.ok) put(PAGES, url.pathname, res.clone());
            return res;
          });
          try {
            return await Promise.race([net, timeout(6000)]);
          } catch (e) {
            const saved = (await caches.match(url.pathname, { cacheName: PAGES })) || (await caches.match(req, { ignoreSearch: true }));
            if (saved) return saved;
            try {
              return await net;
            } catch (e2) {
              return (await caches.match("./index.html")) || new Response("<h1 style='font-family:sans-serif'>You're offline</h1><p style='font-family:sans-serif'>Open this page once with signal so it works offline next time.</p>", { headers: { "Content-Type": "text/html; charset=utf-8" } });
            }
          }
        })()
      );
      return;
    }
    // Icons, manifest: saved copy first, refreshed in the background.
    event.respondWith(
      caches.match(req).then((hit) => {
        const net = fetch(req)
          .then((res) => {
            if (res.ok) put(PAGES, req, res.clone());
            return res;
          })
          .catch(() => hit);
        return hit || net;
      })
    );
    return;
  }

  // React, Firebase scripts and fonts: saved copy first (these URLs never change).
  const isLib = LIB_HOSTS.includes(url.hostname) || (url.hostname === "www.gstatic.com" && url.pathname.startsWith("/firebasejs/"));
  if (!isLib) return; // Firestore, logins, PayPal etc. go straight to the network.
  event.respondWith(
    caches.match(req).then(
      (hit) =>
        hit ||
        fetch(req).then((res) => {
          put(LIBS, req, res.clone());
          return res;
        })
    )
  );
});
