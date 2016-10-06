from __future__ import unicode_literals
import os
import argparse

from sideboard.lib import mainloop, entry_point, log

parser = argparse.ArgumentParser(description='Run Sideboard as a daemon without starting CherryPy')
parser.add_argument('--pidfile', required=True, help='absolute path of file where process pid will be stored')


@entry_point
def mainloop_daemon():
    log.info('starting Sideboard daemon process')
    args = parser.parse_args()
    if os.fork() == 0:
        pid = os.fork()
        if pid == 0:
            mainloop()
        else:
            log.debug('writing pid ({}) to pidfile ({})', pid, args.pidfile)
            try:
                with open(args.pidfile, 'w') as f:
                    f.write('{}'.format(pid))
            except:
                log.error('unexpected error writing pid ({}) to pidfile ({})', pid, args.pidfile, exc_info=True)


@entry_point
def mainloop_foreground():
    mainloop()
