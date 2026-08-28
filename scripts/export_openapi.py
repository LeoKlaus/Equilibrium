"""Exports the app's OpenAPI schema to a JSON file, without needing any
RF24/Bluetooth/GPIO hardware or a database - app.openapi() is purely
static, derived from the route/model definitions, and never triggers
the lifespan (which is where all the hardware/DB setup lives). Used by
the openapi.yml workflow to publish a schema for every release tag.

    python scripts/export_openapi.py --version 1.3.0 --output openapi.json
"""

import argparse
import json
from pathlib import Path

from api.app import app_generator

# app_generator() mounts StaticFiles(directory="web") for the web UI,
# which isn't fetched in this CI job (see fetch_web_ui.py) and isn't
# needed for schema export - it just needs to exist so the mount
# itself doesn't raise.
_WEB_DIR = Path("web")


def export(version: str | None) -> dict:
    _WEB_DIR.mkdir(exist_ok=True)

    app = app_generator()
    schema = app.openapi()
    if version:
        schema["info"]["version"] = version
    return schema


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--output", default="openapi.json",
        help="Path to write the schema to (default: openapi.json).",
    )
    parser.add_argument(
        "--version", default=None,
        help="Overrides info.version in the schema (e.g. the git tag being released). "
             "Left as the app's own default if omitted.",
    )
    args = parser.parse_args()

    schema = export(args.version)
    Path(args.output).write_text(json.dumps(schema, indent=2))
    print(f"Wrote OpenAPI schema (version {schema['info']['version']}) to {args.output}")


if __name__ == "__main__":
    main()
