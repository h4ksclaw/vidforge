"""Upload files to s.h4ks.com — the asset hosting endpoint.

Used by debug reports to host images, audio, and HTML previews.
"""

import subprocess
from pathlib import Path

UPLOAD_URL = "https://s.h4ks.com"


def upload_file(path: str | Path) -> str | None:
    """Upload a local file to s.h4ks.com and return the URL.

    Returns None if upload fails.
    """
    path = Path(path)
    if not path.exists():
        return None

    try:
        result = subprocess.run(
            ["curl", "-s", "-F", f"file=@{path}", UPLOAD_URL],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return _parse_url(result.stdout.strip())
    except (subprocess.TimeoutExpired, OSError):
        return None


def _parse_url(output: str) -> str | None:
    """Parse s.h4ks.com response — either a bare URL or 'File already exists: URL'."""
    if not output:
        return None
    if output.startswith("http"):
        return output.strip()
    if "https://" in output:
        return "https://" + output.split("https://")[-1].strip()
    return None
