"""
To have unittest.TestCase subclasses converted to py.test-style tests, it's imperative that
unittest is in sys.modules at the appropriate time, and APPARENTLY this works. This file is
guaranteed to be imported by py.test (which looks for hooks here) and the import of unittest
here is enough it is NOT enough to import unittest in your plugins or inside of a hook you
specify here
"""
import unittest
import sideboard
