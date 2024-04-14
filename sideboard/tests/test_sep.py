from __future__ import unicode_literals
import sys

import pytest
from mock import Mock

from sideboard import sep
from sideboard.lib import entry_point
from sideboard.lib._utils import _entry_points
from sideboard.sep import run_plugin_entry_point


class FakeExit(Exception):
    pass


class TestSep(object):
    @pytest.fixture(autouse=True)
    def automocks(self, monkeypatch):
        monkeypatch.setattr(sep, 'exit', Mock(side_effect=FakeExit), raising=False)
        prev_argv, prev_points = sys.argv[:], _entry_points.copy()
        yield
        sys.argv[:] = prev_argv
        _entry_points.clear()
        _entry_points.update(prev_points)

    def test_no_command(self):
        sys.argv[:] = ['sep']
        pytest.raises(FakeExit, run_plugin_entry_point)
        sep.exit.assert_called_with(1)

    def test_help(self):
        for flag in ['-h', '--help']:
            sys.argv[:] = ['sep', flag]
            pytest.raises(FakeExit, run_plugin_entry_point)
            sep.exit.assert_called_with(0)
            sep.exit.reset_mock()

    def test_invalid(self):
        sys.argv[:] = ['sep', 'nonexistent_entry_point']
        pytest.raises(FakeExit, run_plugin_entry_point)
        sep.exit.assert_called_with(2)

    def test_valid_entry_point(self):
        action = Mock()

        @entry_point
        def foobar():
            action(sys.argv)

        sys.argv[:] = ['sep', 'foobar', 'baz', '--baf']
        run_plugin_entry_point()
        action.assert_called_with(['foobar', 'baz', '--baf'])
