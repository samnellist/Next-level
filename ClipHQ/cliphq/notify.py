"""Desktop notifications (Windows toast) + an event list the web pages show (incl. your phone)."""
from __future__ import annotations

import shutil
import subprocess

from . import db
from .config import IS_WINDOWS, load_settings

_PS = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$t = [System.Security.SecurityElement]::Escape($env:CHQ_TITLE)
$m = [System.Security.SecurityElement]::Escape($env:CHQ_MSG)
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$t</text><text>$m</text></binding></visual></toast>")
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
"""


def notify(title: str, message: str, kind: str = "info") -> None:
    db.event(kind, f"{title}: {message}")
    if not load_settings().get("notify_desktop", True):
        return
    try:
        import os
        env = dict(os.environ, CHQ_TITLE=title[:80], CHQ_MSG=message[:200])
        if IS_WINDOWS:
            subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _PS], env=env,
                             creationflags=0x08000000, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif shutil.which("notify-send"):
            subprocess.Popen(["notify-send", title, message])
    except Exception:
        pass
