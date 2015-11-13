#!/usr/bin/env python3

from __future__ import absolute_import

import logging.config
import argparse
import logging
import sys
import os

from fluxclient.utils.version import StrictVersion


def check_fluxclient():
    from fluxclient import VERSION as V
    sys.modules.pop("fluxclient")
    if ".".join(V) < StrictVersion('0.5a2'):
        raise RuntimeError("Your fluxclient need to update (>=0.5a2)")


check_fluxclient()


def setup_logger(debug, logfile=None):
    LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"
    LOG_FORMAT = "[%(asctime)s,%(levelname)s,%(name)s] %(message)s"

    log_level = logging.DEBUG if options.debug else logging.INFO

    handlers = {}
    if sys.stdout.isatty():
        handlers['console'] = {
            'level': log_level,
            'formatter': 'default',
            'class': 'logging.StreamHandler',
        }

    if logfile:
        handlers['file'] = {
            'level': log_level,
            'formatter': 'default',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': logfile,
            'maxBytes': 5 * (2 ** 20),  # 10M
            'backupCount': 1
        }

    logging.config.dictConfig({
        'version': 1,
        'disable_existing_loggers': True,
        'formatters': {
            'default': {
                'format': LOG_FORMAT,
                'datefmt': LOG_DATEFMT
            }
        },
        'handlers': handlers,
        'loggers': {},
        'root': {
            'handlers': list(handlers.keys()),
            'level': 'DEBUG',
            'propagate': True
        }
    })


parser = argparse.ArgumentParser(description='FLUX Ghost')
parser.add_argument("--assets", dest='assets', type=str,
                    default=None, help="Assets folder")
parser.add_argument("--ip", dest='ipaddr', type=str, default='127.0.0.1',
                    help="Bind to IP Address")
parser.add_argument("--port", dest='port', type=int, default=8000,
                    help="Port")
parser.add_argument("--log", dest='logfile', type=str, default=None,
                    help="Output log to specific")
parser.add_argument('-d', '--debug', dest='debug', action='store_const',
                    const=True, default=False, help='Enable debug')
parser.add_argument('-s', '--simulate', dest='simulate', action='store_const',
                    const=True, default=False, help='Simulate data')

options = parser.parse_args()
setup_logger(debug=options.debug, logfile=options.logfile)

if options.debug:
    from fluxghost.http_server_debug import HttpServer
else:
    from fluxghost.http_server import HttpServer

if options.simulate:
    os.environ["flux_simulate"] = "1"

if not options.assets:
    options.assets = os.path.join(
        os.path.dirname(
            os.path.abspath(__file__)),
        "fluxghost", "assets")

server = HttpServer(assets_path=options.assets,
                    enable_discover=True,
                    address=(options.ipaddr, options.port,),)

server.serve_forever()