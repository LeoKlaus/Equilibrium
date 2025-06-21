import argparse
import logging

import uvicorn
from Api.app import app_generator

if __name__ == '__main__':
    parser = argparse.ArgumentParser("Equilibrium")
    parser.add_argument(
        "--dev",
        help="Start Equilibrium in dev mode (disables GPIO and Bluetooth access, Bonjour registration).",
        action="store_const", dest="dev_mode", const=True,
        default=False
    )

    parser.add_argument(
        '--debug',
        help="Even more verbose logging, is always true if in dev mode.",
        action="store_const", dest="loglevel", const=logging.DEBUG,
        default=logging.WARNING,
    )

    parser.add_argument(
        '-v', '--verbose',
        help="More verbose logging.",
        action="store_const", dest="loglevel", const=logging.INFO,
    )

    args = parser.parse_args()

    if args.dev_mode:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=args.loglevel)

    app = app_generator(args.dev_mode)
    uvicorn.run(app)
