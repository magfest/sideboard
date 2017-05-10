from __future__ import unicode_literals
from sideboard.lib import cleanup_profiler, profile
from sideboard.config import config


def some_function():
    pass


def test_profile_is_noop(monkeypatch):
    monkeypatch.setitem(config['cherrypy'], 'profiling.on', False)
    profiled = profile(some_function)
    assert profiled is some_function

    monkeypatch.setitem(config['cherrypy'], 'profiling.on', True)
    profiled = profile(some_function)
    assert profiled is not some_function
