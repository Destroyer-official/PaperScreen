"""Zero-dependency Windows toast notifications via PowerShell + WinRT.

Research basis: break-reminder adherence is the bottleneck for 20-20-20
effectiveness (PMID 41322997; Tal 2023). Reminders must be visible but
non-blocking and non-annoying -> native toasts, never console spam.

Spawns a short-lived powershell.exe (WinRT projection isn't available to
plain Python without winrt wheels; this keeps the zero-dependency promise).
"""

from __future__ import annotations

import subprocess
from typing import Optional

_PS_TEMPLATE = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml(@'
<toast scenario="{scenario}">
  <visual>
    <binding template="ToastGeneric">
      <text>{title}</text>
      <text>{body}</text>
    </binding>
  </visual>
  <audio src="ms-winsoundevent:Notification.Default"/>
</toast>
'@)
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
$appId = '{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
"""


def _escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def show(title: str, body: str, reminder: bool = False) -> bool:
    """Show a toast. Returns True if powershell exited 0."""
    scenario = "reminder" if reminder else "default"
    # reminder scenario keeps the toast in Action Center until dismissed
    script = _PS_TEMPLATE.format(title=_escape(title), body=_escape(body), scenario=scenario)
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


__all__ = ["show"]
