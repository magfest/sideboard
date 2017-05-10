"""
Adds profiling tools and a web interface for viewing profiling results.

The Sideboard profiler borrows heavily from the `CherryPy profiler
<https://github.com/cherrypy/cherrypy/blob/master/cherrypy/lib/profiler.py>`_,
but with a few added features and nicer formatting.

 * Adds the ability to sort results by different columns.
 * Adds the ability to cleanup profile data files.
 * Uses a better naming scheme for profile data files.
 * Uses `cProfile` instead of `profile` for better performance.

Profiling data can be collected using the @profile decorator on functions and
methods. The profiling results can be viewed at http://servername/profile/.

Good candidates for profiling are the outermost functions that generate your
web pages, usually exposed as cherrypy endpoints via @cherrypy.expose::

    import cherrypy
    from sideboard.lib import profile

    class Root(object):
        @cherrypy.expose
        @profile
        def index(self):
            # Create and return the index page
            return '<html/>'


But any regular function can be profiled using the @profile decorator::

    from sideboard.lib import profile

    @profile
    def some_interesting_function():
       # Do some stuff


The following config options control how the profiler operates, see
configspec.ini for more details::

    [cherrypy]
    profiling.on = True
    profiling.path = "%(root)s/data/profiler"
    profiling.aggregate = False
    profiling.strip_dirs = False

"""
from __future__ import unicode_literals
import io
import os
import os.path
import cProfile
import pstats
from datetime import datetime
from functools import wraps
from glob import glob

import cherrypy
from sideboard.lib import config, entry_point, listify


def _new_func_strip_path(func_name):
    """
    Adds the parent module to profiler output for `__init__.py` files.

    Copied verbatim from cherrypy/lib/profiler.py.
    """
    filename, line, name = func_name
    if filename.endswith('__init__.py'):
        return os.path.basename(filename[:-12]) + filename[-12:], line, name
    return os.path.basename(filename), line, name

pstats.func_strip_path = _new_func_strip_path


@entry_point
def cleanup_profiler():
    """
    Deletes all `*.prof` files in the profiler's data directory.

    This is useful when you've created tons of profile files that you're no
    longer interested in. Exposed as a `sep` command::

        $ sep cleanup_profiler

    The profiler directory is specified in the config by::

        [cherrypy]
        profiling.path = 'path/to/profile/data'

    """
    profiling_path = config['cherrypy']['profiling.path']
    for f in glob(os.path.join(profiling_path, '*.prof')):
        os.remove(f)


def profile(func):
    """
    Decorator to capture profile data from a method or function.

    If profiling is disabled then this decorator is a no-op, and the original
    function is returned unmodified. Since the original function is returned,
    this decorator does not incur any performance penalty if profiling is
    disabled. To enable or disable profiling use the following setting in your
    config::

        [cherrypy]
        profiling.on = True  # Or False to disable

    Args:
        func (function): The function to profile.

    Returns:
        function: Either a wrapped version of `func` with profiling enabled,
            or `func` itself if profiling is disabled.

    See Also:
        configspec.ini
    """
    if config['cherrypy']['profiling.on']:
        profiling_path = config['cherrypy']['profiling.path']
        if config['cherrypy']['profiling.aggregate']:
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
    """
    Mostly copied from cherrypy/lib/profiler.py.

     * Adds the ability to sort results by different columns.
     * Adds the ability to cleanup profile data files.
     * Uses a better naming scheme for profile data files.
    """

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

    def __init__(self, path=config['cherrypy']['profiling.path']):
        self.path = path
        if not os.path.exists(path):
            os.makedirs(path)

    def new_filename(self, func):
        date = datetime.now().strftime("%Y-%m-%d_%H:%M:%S.%f")
        name = func.__name__ if func.__name__ else 'unknown'
        return '{}_{}.prof'.format(date, name)

    def run(self, func, *args, **params):
        """Dump profile data into self.path."""
        path = os.path.join(self.path, self.new_filename(func))
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
        if config['cherrypy']['profiling.strip_dirs']:
            s.strip_dirs()
        s.sort_stats(sortby)
        s.print_stats()
        response = sio.getvalue()
        sio.close()
        return response

    @cherrypy.expose
    def index(self):
        return '''<html>
        <head><title>Sideboard Profiler</title></head>
        <frameset cols="300, 1*">
            <frame src="menu"/>
            <frame name="main" src="" />
        </frameset>
        </html>
        '''

    @cherrypy.expose
    def menu(self):
        yield '<h2>Profiling Runs</h2>'
        runs = self.statfiles()
        if not runs:
            yield 'No profiling runs'
        else:
            yield '<div style="white-space: nowrap;">'
            runs.sort()
            for run in runs:
                yield '<a href="report?filename={0}" target="main">{0}</a>' \
                    '<br>'.format(run)
            yield '</div><br><hr><br>'
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
        """
        Deletes all `*.prof` files in the profiler's data directory.

        To delete all profile data files hit
        http://servername/profile/cleanup/.

        The profiler directory is specified by::

            [cherrypy]
            profiling.path = 'path/to/profile/data'

        See Also:
            `cleanup_profiler`
        """
        cleanup_profiler()
        raise cherrypy.HTTPRedirect('.')


class ProfileAggregator(Profiler):
    """
    Mostly copied from cherrypy/lib/profiler.py.

     * Uses a better naming scheme for profile data files.
    """

    def __init__(self, path=None):
        super(ProfileAggregator, self).__init__(path)
        self.profiler = cProfile.Profile()

    def run(self, func, *args, **params):
        path = os.path.join(self.path, self.new_filename(func))
        result = self.profiler.runcall(func, *args, **params)
        self.profiler.dump_stats(path)
        return result
