"""
cherrypy.lib.profiler.py
https://github.com/cherrypy/cherrypy/blob/master/cherrypy/lib/profiler.py
http://docs.cherrypy.org/en/latest/pkg/cherrypy.lib.html#module-cherrypy.lib.profiler
"""
import io
import os
import os.path
import cProfile
import pstats
from datetime import datetime
from functools import wraps
from glob import glob

import cherrypy
from sideboard.config import config
from sideboard.lib import entry_point, listify


_count = 0


def _new_func_strip_path(func_name):
    """Make profiler output more readable by adding `__init__` modules' parents
    """
    filename, line, name = func_name
    if filename.endswith('__init__.py'):
        return os.path.basename(filename[:-12]) + filename[-12:], line, name
    return os.path.basename(filename), line, name

pstats.func_strip_path = _new_func_strip_path


@entry_point
def cleanup_profiler():
    profiling_path = config['cherrypy'].get('profiling.path', None)
    if profiling_path:
        for f in glob(os.path.join(profiling_path, '*.prof')):
            os.remove(f)


def profile(func):
    if config['cherrypy'].get('profiling.on', False):
        profiling_path = config['cherrypy'].get('profiling.path', None)
        if config['cherrypy'].get('profiling.aggregate', False):
            p = ProfileAggregator(profiling_path)
        else:
            p = Profiler(profiling_path)

        @wraps(func)
        def wrapper(*args, **kwargs):
            return p.run(func, *args, **kwargs)
        return wrapper
    else:
        return func


class Profiler(object):

    # https://docs.python.org/3/library/profile.html#pstats.Stats.sort_stats
    sort_fields = [
        ('cumulative', 'Cumulative Time'),
        ('filename', 'File Name'),
        ('ncalls', 'Call Count'),
        ('pcalls', 'Primitive Call Count'),
        ('line', 'Line Number'),
        ('name', 'Function Name'),
        ('nfl', 'Function/File/Line'),
        ('stdname', 'Standard Name'),
        ('tottime', 'Total Time')]

    def __init__(self, path=None):
        if not path:
            path = os.path.join(os.path.dirname(__file__), 'profile')
        self.path = path
        if not os.path.exists(path):
            os.makedirs(path)

    def new_filename(self):
        date = datetime.now().strftime("%Y-%m-%d_%H:%M:%S.%f")
        return '{}_{}.prof'.format(date, _count)

    def run(self, func, *args, **params):
        """Dump profile data into self.path."""
        global _count
        c = _count = _count + 1
        path = os.path.join(self.path, self.new_filename())
        prof = cProfile.Profile()
        result = prof.runcall(func, *args, **params)
        prof.dump_stats(path)
        return result

    def statfiles(self):
        """:rtype: list of available profiles.
        """
        return [f for f in os.listdir(self.path) if f.endswith('.prof')]

    def stats(self, filename, sortby='cumulative'):
        """:rtype stats(index): output of print_stats() for the given profile.
        """
        sio = io.StringIO()
        s = pstats.Stats(os.path.join(self.path, filename), stream=sio)
        if config['cherrypy'].get('profiling.strip_dirs', False):
            s.strip_dirs()
        s.sort_stats(sortby)
        s.print_stats()
        response = sio.getvalue()
        sio.close()
        return response

    @cherrypy.expose
    def index(self):
        return """<html>
        <head><title>Sideboard Profiler</title></head>
        <frameset cols='280, 1*'>
            <frame src='menu' />
            <frame name='main' src='' />
        </frameset>
        </html>
        """

    @cherrypy.expose
    def menu(self):
        yield '<h2>Profiling Runs</h2>'
        runs = self.statfiles()
        if not runs:
            yield "<p>No profiling runs</p>"
        else:
            runs.sort()
            for run in runs:
                yield '<a href="report?filename={0}" target="main">{0}</a>' \
                    '<br>'.format(run)
            yield '<br><hr><br>'
            yield '<a href="cleanup" target="_top">' \
                'Delete all profiling runs</a>'

    @cherrypy.expose
    def report(self, filename, sortby='cumulative'):
        yield '<span>Sort by: </span>'
        for (field, label) in Profiler.sort_fields:
            if field == sortby:
                yield '<span>{}</span> '.format(label)
            else:
                yield '<a href="report?filename={}&sortby={}">{}' \
                    '</a> '.format(filename, field, label)
        yield '<pre>'
        yield self.stats(filename, sortby)
        yield '</pre>'

    @cherrypy.expose
    def cleanup(self):
        cleanup_profiler()
        raise cherrypy.HTTPRedirect('.')


class ProfileAggregator(Profiler):

    def __init__(self, path=None):
        super(ProfileAggregator, self).__init__(path)
        global _count
        self.count = _count = _count + 1
        self.profiler = cProfile.Profile()

    def run(self, func, *args, **params):
        path = os.path.join(self.path, self.new_filename())
        result = self.profiler.runcall(func, *args, **params)
        self.profiler.dump_stats(path)
        return result
