import argparse
import logging
import os

import uvicorn

from api import LOG_FORMAT
from api.app import app_generator


def _log_level_from_env(default: int = logging.WARNING) -> int:
    """Reads the LOG_LEVEL env var (e.g. "DEBUG", "INFO") - lets the log
    level be set without a command line flag, for cases like Docker where
    passing arguments is less convenient than setting an environment
    variable. A --debug/--verbose flag on the command line still takes
    precedence over this, same as it would over the argparse default."""
    env_value = os.environ.get("LOG_LEVEL")
    if not env_value:
        return default

    level = logging.getLevelNamesMapping().get(env_value.upper())
    if level is None:
        print(f"Ignoring unrecognized LOG_LEVEL {env_value!r}, falling back to default.")
        return default
    return level


if __name__ == '__main__':
    parser = argparse.ArgumentParser("Equilibrium")

    parser.add_argument(
        "--dev",
        help="Start Equilibrium in dev mode (disables GPIO and Bluetooth access, Bonjour registration).",
        action="store_true"
    )

    parser.add_argument(
        '--debug',
        help="Even more verbose logging, is always true if in dev mode. Can also be set via the "
             "LOG_LEVEL environment variable (e.g. LOG_LEVEL=DEBUG).",
        action="store_const", dest="loglevel", const=logging.DEBUG,
        default=_log_level_from_env(),
    )

    parser.add_argument(
        '-v', '--verbose',
        help="More verbose logging.",
        action="store_const", dest="loglevel", const=logging.INFO,
    )

    parser.add_argument(
        '-p', '--port',
        help="Define a custom port.",
        dest="port",
        default=8000,
        type=int
    )

    args = parser.parse_args()

    if args.dev:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=args.loglevel)

    logging.basicConfig(format=LOG_FORMAT, force=True)

    app = app_generator(args.dev)

    uvicorn.run(app, host='0.0.0.0', port=args.port, log_config=None)
