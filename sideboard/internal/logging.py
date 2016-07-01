from __future__ import unicode_literals, absolute_import
import os
import logging.config

import logging_unterpolation

from sideboard.config import config


class IndentMultilinesLogFormatter(logging.Formatter):
    def format(self, record):
        s = super(IndentMultilinesLogFormatter, self).format(record)
        # indent all lines that start with a newline so they are easier for external log programs to parse
        s = s.rstrip('\n').replace('\n','\n    ')
        return s


def _configure_logging():
    logging_unterpolation.patch_logging()
    fname='/etc/sideboard/logging.cfg'
    if os.path.exists(fname):
        logging.config.fileConfig(fname, disable_existing_loggers=True)
    else:
        format_str = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        logging.config.dictConfig({
        'version': 1,
        'root': {
            'level': config['loggers']['root'],
            'handlers': config['handlers'].dict().keys()
        },
        'loggers': {
            name: {'level': level}
            for name, level in config['loggers'].items() if name != 'root'
        },
        'handlers': config['handlers'].dict(),
        'formatters': {
            'default': {
                'format': format_str,
            },
            'indent_multiline': {
                '()': IndentMultilinesLogFormatter,
                'format': format_str,
            },
        }
    })
