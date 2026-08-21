"""Downloads the web UI build matching WEB_UI_VERSION from the
Equilibrium-Flutter releases and extracts it into web/. Used both by the
Dockerfile (at build time) and manually for bare-metal installs/upgrades:

    python scripts/fetch_web_ui.py
"""

import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path
from urllib.error import HTTPError

REPO = "LeoKlaus/Equilibrium-Flutter"
ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"


def main() -> None:
    version = (ROOT / "WEB_UI_VERSION").read_text().strip()
    asset = f"equilibrium-web-{version}.tar.gz"
    url = f"https://github.com/{REPO}/releases/download/{version}/{asset}"

    print(f"Fetching web UI {version} from {url}")
    try:
        with urllib.request.urlopen(url) as response:
            archive_bytes = response.read()
    except HTTPError as e:
        print(f"Failed to download {url}: {e}", file=sys.stderr)
        sys.exit(1)

    archive_path = ROOT / asset
    archive_path.write_bytes(archive_bytes)

    if WEB_DIR.exists():
        shutil.rmtree(WEB_DIR)
    WEB_DIR.mkdir()

    with tarfile.open(archive_path) as tar:
        tar.extractall(WEB_DIR, filter="data")

    archive_path.unlink()

    if not (WEB_DIR / "index.html").exists():
        print(f"Extraction succeeded but {WEB_DIR / 'index.html'} is missing - bad archive?", file=sys.stderr)
        sys.exit(1)

    print(f"Web UI {version} installed to {WEB_DIR}")


if __name__ == "__main__":
    main()
