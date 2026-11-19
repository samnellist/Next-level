"""Start Clip HQ: python run.py  (or double-click 'Start Clip HQ.bat')."""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
import webbrowser

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn  # noqa: E402

from cliphq import certs, db  # noqa: E402
from cliphq.config import load_settings  # noqa: E402
from cliphq.pipeline import worker  # noqa: E402
from cliphq.server import app  # noqa: E402
from cliphq.watcher import watchers  # noqa: E402


def main() -> None:
    st = load_settings()
    port, sport = int(st["port"]), int(st["https_port"])
    import socket
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", port)) == 0:
            print("Clip HQ is already running - opening it in your browser.")
            webbrowser.open(f"http://localhost:{port}")
            time.sleep(2)
            return
    db.init()
    worker.start()
    watchers.start()
    tls = None
    try:
        tls = certs.ensure_certs()
    except Exception as e:
        print("HTTPS for the phone is off:", e)
    ips = certs.local_ips()
    print("\n" + "=" * 62)
    print("  Clip HQ is running.  Keep this window open while you use it.")
    print(f"  On this laptop:  http://localhost:{port}")
    for ip in ips[:2]:
        print(f"  On your iPhone (same Wi-Fi):  https://{ip}:{sport}/m")
    print("  To stop Clip HQ: close this window.")
    print("=" * 62 + "\n")

    servers = [uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning"))]
    if tls:
        servers.append(uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=sport, log_level="warning",
                                                     ssl_certfile=tls[0], ssl_keyfile=tls[1])))
    if "--no-browser" not in sys.argv:
        threading.Thread(target=lambda: (time.sleep(2), webbrowser.open(f"http://localhost:{port}")), daemon=True).start()

    async def serve_all():
        await asyncio.gather(*(s.serve() for s in servers))
    asyncio.run(serve_all())


if __name__ == "__main__":
    main()
