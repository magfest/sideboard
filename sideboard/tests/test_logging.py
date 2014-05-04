from __future__ import unicode_literals
import logging
import unittest

from six import StringIO


class LoggerSetupTest(unittest.TestCase):
    def _stream(self):
        return StringIO()

    def _logger(self, logger_name, stream):
        logging.getLogger().addHandler(logging.StreamHandler(stream))
        return logging.getLogger(logger_name)

    def test_importing_sideboard_doesnt_break_dummy_logger(self):
        stream = self._stream()
        dummy_logger = self._logger('dummy', stream)
        dummy_logger.warning('do not break dummy logger')
        assert stream.getvalue() == 'do not break dummy logger\n'

