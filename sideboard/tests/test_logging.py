from __future__ import unicode_literals

import unittest


class LoggerSetupTest(unittest.TestCase):
    def _stream(self):
        from StringIO import StringIO
        return StringIO()

    def _logger(self, logger_name, stream):
        import logging

        logging.getLogger().addHandler(logging.StreamHandler(stream))
        return logging.getLogger(logger_name)

    def test_importing_sideboard_doesnt_break_dummy_logger(self):
        stream = self._stream()
        dummy_logger = self._logger('dummy', stream)
        dummy_logger.warning('do not break dummy logger')
        self.assertEqual(stream.getvalue(), 'do not break dummy logger\n')

