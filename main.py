import argparse
import logging

import uvicorn
from Api.app import app_generator

if __name__ == '__main__':
    parser = argparse.ArgumentParser("Equilibrium")

    parser.add_argument(
        "--dev",
        help="Start Equilibrium in dev mode (disables GPIO and Bluetooth access, Bonjour registration).",
        action="store_true"
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

    logging.basicConfig(format="%(asctime)s %(name)-20s - %(levelname)-8s - %(message)s", force=True)

    app = app_generator(args.dev)

    uvicorn.run(app, host='0.0.0.0', port=args.port, log_config=None)
