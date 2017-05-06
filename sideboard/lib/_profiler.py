import io
import os
import os.path
import pstats
from functools import wraps
from glob import glob

import cherrypy
from cherrypy.lib.profiler import Profiler as CherrypyProfiler, \
    ProfileAggregator as CherrypyProfileAggregator
from sideboard.config import config
from sideboard.lib import entry_point, listify


@entry_point
def cleanup_profiler():
    profiling_path = config['cherrypy'].get('profiling.path', None)
    if profiling_path:
        for f in glob(os.path.join(profiling_path, 'cp_*.prof')):
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


class Profiler(CherrypyProfiler):
    def stats(self, filename, sortby='cumulative'):
        """:rtype stats(index): output of print_stats() for the given profile.
        """
        sio = io.StringIO()
        s = pstats.Stats(os.path.join(self.path, filename), stream=sio)
        if config['cherrypy'].get('profiling.strip_dirs', False):
            s.strip_dirs()
        s.sort_stats(*config['cherrypy'].get(
            'profiling.sort_stats', listify(sortby)))
        s.print_stats()
        response = sio.getvalue()
        sio.close()
        return response

    @cherrypy.expose
    def menu(self):
        for html in super(Profiler, self).menu():
            yield html
        yield '<br><hr><br>'
        yield '<a href="cleanup" target="_top">Delete all profiling runs</a>'

    @cherrypy.expose
    def cleanup(self):
        cleanup_profiler()
        raise cherrypy.HTTPRedirect('.')


class ProfileAggregator(CherrypyProfileAggregator):
    def stats(self, filename, sortby='cumulative'):
        return Profiler.stats(self, filename, sortby)
