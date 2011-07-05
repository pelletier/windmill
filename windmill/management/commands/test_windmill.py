#   Copyright (c) 2008-2009 Mikeal Rogers <mikeal.rogers@gmail.com>
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

from django.core.management.base import BaseCommand
from windmill.authoring import djangotest
import sys, os
from time import sleep
import types
import logging


class ServerContainer(object):
    start_test_server = djangotest.start_test_server
    stop_test_server = djangotest.stop_test_server

def attempt_import(name, suffix):
    """
    Try to import a Python module.
    Returns None if we're unable to load the module (either because it does not
    exist or because it triggers an error which causes an ImportError).
    Otherwise it just returns the module.
    """
    try:
        mod = __import__(name+'.'+suffix)
    except ImportError:
        mod = None
    if mod is not None:
        s = name.split('.')
        mod = __import__(s.pop(0))
        for x in s+[suffix]:
            mod = getattr(mod, x)
    return mod


class Command(BaseCommand):

    help = "Run windmill tests. Specify a browser, if one is not passed Firefox will be used"

    args = '<label label ...>'
    label = 'label'

    def handle(self, *labels, **options):

        from windmill.conf import global_settings
        from windmill.authoring.djangotest import WindmillDjangoUnitTest

        # Find a browser name in the command line arguments.
        # One it's found, remove the browser from the arguments list.
        if 'ie' in labels:
            global_settings.START_IE = True
            sys.argv.remove('ie')
        elif 'safari' in labels:
            global_settings.START_SAFARI = True
            sys.argv.remove('safari')
        elif 'chrome' in labels:
            global_settings.START_CHROME = True
            sys.argv.remove('chrome')
        else:
            # If no browser is specified, default to firefox.
            global_settings.START_FIREFOX = True
            if 'firefox' in labels:
                sys.argv.remove('firefox')

        # Now remove from the arguments list the command call.
        if 'manage.py' in sys.argv:
            sys.argv.remove('manage.py')
        if 'test_windmill' in sys.argv:
            sys.argv.remove('test_windmill')
        # At this point, sys.argv only contains the name of the tests to run
        # (if any).

        # Start a Django server. It will automatically find a port it is
        # allowed to listen on.
        server_container = ServerContainer()
        server_container.start_test_server()

        # We access this port using .server_thread.port
        global_settings.TEST_URL = 'http://127.0.0.1:%d' % server_container.server_thread.port

        from windmill.authoring import setup_module, teardown_module
        from django.conf import settings

        # Let's try to automatically discover tests in installed Django
        # applications.
        # For example, if you have
        #   INSTALLED_APPS =  ('foo', 'bar')
        # Windmill will try to load:
        #   foo.tests
        #   foo.wmtests
        #   foo.windmilltests
        #   bar.tests
        #   bar.wmtests
        #   bar.windmilltests
        #
        tests = []
        for name in settings.INSTALLED_APPS:
            # TODO put this suffix list in the configuration file.
            for suffix in ['tests', 'wmtests', 'windmilltests']:
                x = attempt_import(name, suffix)
                if x is not None: tests.append((suffix,x,));

        # Now `tests` contains the list of modules which **could** contain some
        # Windmill tests.

        wmtests = []
        
        # In `tests`, modules are stored in the form (module_name, module).
        # As we import *.a_suffix, module_name can only be one of the suffixes.
        for (ttype, mod) in tests:
            if ttype == 'tests':
                # For each attribute of the module which is a Class and is
                # subclass of WindmillDjangoUnitTest
                for ucls in [getattr(mod, x) for x in dir(mod)
                             if ( type(getattr(mod, x, None)) in (types.ClassType, types.TypeType) )
                             and issubclass(getattr(mod, x), WindmillDjangoUnitTest)]:
                    # Add it tot the test list
                    wmtests.append(ucls.test_dir)

            else:
                # If the file is __init.py(c)
                if mod.__file__.endswith('__init__.py') or mod.__file__.endswith('__init__.pyc'):
                    # We add the whole submodule to the tests
                    wmtests.append(os.path.join(*os.path.split(os.path.abspath(mod.__file__))[:-1]))
                else:
                    # Otherwise we just add the module itself
                    wmtests.append(os.path.abspath(mod.__file__))

        # We check if we finally found some usable tests
        if len(wmtests) is 0: # Seriously, testing with `is`, seriously?
            print 'Sorry, no windmill tests found.'
        else:

            # (Note: this is probably the hairiest and the most
            # incomprehensible piece of code I ever read. Perl scripts don't
            # count)

            # If we have something to test
            testtotals = {}

            # Prepare the logger
            x = logging.getLogger()
            x.setLevel(0)

            from windmill.dep import functest
            bin = functest.bin

            # We grab the CLIRunner class. This class wraps each tests and how
            # they are displayed on the console screen.
            runner = functest.runner
            # We override the `final` classmethod (which seems to be called
            # when the test suite is over). We want it to update the totals
            # (FIXME I think they should be called `status` because it's
            # a record of how many tests passed/failed/skipepd).
            runner.CLIRunner.final = classmethod(lambda self, totals: testtotals.update(totals) )
            # FIXME OK so why only the very first module found should be
            # loaded?
            setup_module(tests[0][1])

            # Update the command line arguments (SRSLY guys, have you ever
            # heard of functions arguments?)
            sys.argv = sys.argv + wmtests

            # Run the command line function (the one which does the full job).
            bin.cli()

            # Teardown the tested module (let's call it "The One").
            teardown_module(tests[0][1])

            # OK. If we failed, quit the program.
            if testtotals['fail'] is not 0:
                sleep(.5)
                sys.exit(1)
