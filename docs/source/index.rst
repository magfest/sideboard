.. toctree::
   :maxdepth: 2


Welcome to Sideboard
====================

Sideboard makes it easy to do three main things:

* expose and consume services

* host a dynamic website

* run background tasks

Sideboard also has lots of utility methods for things like configuration, depdendency management, database methods, authentication, etc.  This documentation consists of a tutorial and API reference.



Tutorial
========

In this tutorial we'll walk through creating an simple web application which exposes a service, hosts a dynamic website, and runs background tasks.  Specifically, a web application that keeps track of whether the world has ended.

There are a lot of websites out there which tell you whether the world has ended, such as

* `HasTheWorldEnded.webs.com <http://hastheworldended.webs.com/>`_

* `HasTheLargeHadronColliderDestroyedTheWorldYet.com <http://hasthelargehadroncolliderdestroyedtheworldyet.com/>`_

Our plugin will periodically check those websites, store the results of our checks in our database, expose a service which allows others to make RPC calls to check our aggregated result, and mount a website which shows the results to an authenticated user in their web browser.



Dependencies
------------

Before doing anything with Sideboard, you will need the following to be installed on your machine:

* Python 2.7

* `virtualenv <http://www.virtualenv.org/>`_ 1.9 or later

* `paver <http://paver.github.io/paver/>`_ 1.2 or later

* `distribute <http://pythonhosted.org/distribute/>`_ 0.6.36 or later

* development packages (so that you can compile Python extension modules) for Python, OpenLDAP, and OpenSSL (on CentOS these are packaged respectively as python-devel, openldap-devel, and openssl-devel)



Getting Started
---------------

Let's start by cloning the Sideboard repo and running it without any plugins:

.. code-block:: none

    $ git clone https://github.com/magfest/sideboard
    $ cd sideboard/
    $ paver make_venv
    $ ./env/bin/python sideboard/run_server.py

Now you can go to `<http://localhost:8282/>`_ and you'll see a page show you Sideboard's version and all of the installed plugins (currently none).

So let's create a plugin with paver:

.. code-block:: none

    ./env/bin/paver create_plugin --name=ragnarok

This will create the following directory structure in your ``plugins`` directory:

.. code-block:: none

    ragnarok/
    |-- conftest.py
    |-- development-defaults.ini
    |-- docs
    |   |-- _build
    |   |-- conf.py
    |   |-- index.rst
    |   |-- Makefile
    |   |-- _static
    |   `-- _templates
    |-- fabfile.py
    |-- MANIFEST.in
    |-- package-support
    |   `-- ragnarok.cfg
    |-- ragnarok
    |   |-- configspec.ini
    |   |-- __init__.py
    |   |-- sa.py
    |   |-- service.py
    |   |-- templates
    |   |   `-- index.html
    |   |-- tests
    |   |   `-- __init__.py
    |   `-- _version.py
    |-- requirements.txt
    |-- setup.cfg
    `-- setup.py


We haven't added any new dependencies to this plugin yet (in its ``requirements.txt`` file), but if we had then we'd run

.. code-block:: none

    paver install_deps

Now you can re-run

.. code-block:: none

    ./env/bin/python sideboard/run_server.py

and go back to `<http://localhost:8282/>`_ and see that your plugin is now installed.  Click on the ``/ragnarok`` link and you'll see the example page.



SQLAlchemy
----------

The default database backend is `SQLite <http://www.sqlite.org/>`_ so we'll keep that unchanged.  We're going to want a database table to store the websites we're checking, and another table to store the results of our checks.  So let's open the file ``ragnarok/sa.py`` and where it says ``put your table declarations here`` paste the following

.. code-block:: python

    class Website(Base):
        url = Column(Text(), nullable=False)
        search_for = Column(Text(), nullable=False)
        
        __table_args__ = (UniqueConstraint('url'),)
        
        @property
        def last_checked(self):
            if self.results:
                return max(r.checked for r in self.results)

    class Result(Base):
        website_id = Column(UUID(), ForeignKey('website.id', ondelete='CASCADE'), nullable=False)
        website = relationship(Website, backref='results')
        world_ended = Column(Boolean(), nullable=False)
        checked = Column(UTCDateTime(), default=lambda: datetime.now(UTC))

In order for that code to work, let's update our imports at the top of the file:

.. code-block:: python

    import uuid
    from datetime import datetime

    from pytz import UTC

    import sqlalchemy
    from sqlalchemy.orm import relationship
    from sqlalchemy.types import Text, Boolean
    from sqlalchemy.schema import Column, ForeignKey, UniqueConstraint

    from ragnarok import config
    from sideboard.lib.sa import SessionManager, UUID, UTCDateTime, declarative_base

Notice that we're using the `pytz module <http://pytz.sourceforge.net/>`_ so we need to install that in our plugin's virtualenv.  (We're also going to use the ``requests`` module later on in this tutorial, but Sideboard already has that as a dependency.)  Open the ``requirements.txt`` file in your plugin root directory and add the following lines:

.. code-block:: none

    pytz==2013b

Now we can run 

.. code-block:: none

    paver install_deps

from the top-level Sideboard directory.  If you'd prefer, you can activate the Sideboard virtualenv and then run

.. code-block:: none

    python setup.py develop

from the plugin root directory.

Now we can play around in the REPL by running your Sideboard virtualenv's ``python``:

>>> import sideboard
>>> from ragnarok import sa
>>> with sa.Session() as session:
...   session.add(sa.Website(url="http://hastheworldended.webs.com", search_for="NO"))
...   session.add(sa.Website(url="http://hasthelargehadroncolliderdestroyedtheworldyet.com", search_for="NOPE"))
... 
>>>

We used our ``Session`` object as a context manager, which committed automatically at the end of the block.  We can confirm this by querying our database (note that Sideboard gives us a sensible repr, which by default displays the values of all of the unique columns):

>>> with sa.Session() as session:
...   session.query(sa.Website).all()
... 
[<Website id='799cedfd-2255-4f35-87bf-aa4e545131b3' url=u'http://hastheworldended.webs.com'>, <Website id='417c341a-b026-4cdd-8201-2fe904727c20' url=u'http://hasthelargehadroncolliderdestroyedtheworldyet.com'>]


Service
-------

Okay, so we want to write some code that checks these websites, and we want to be able to configure whether or not it goes through a proxy (as will be the case in many corporate environments).  So let's add a proxy url to our settings by opening the file ``ragnarok/configspec.ini`` and adding the following line:

.. code-block:: none

    proxy = string(default="")

This tells our configuration parser that there's a ``proxy`` setting which defaults to the empty string.  If you are in an environment that has a proxy, you should add this setting to your development settings by opening the file ``development-defaults.ini`` and adding the following line:

.. code-block:: none

    proxy = "http://whatever.your.proxy.address.is/"

Now that we've done the necessary database and configuration work, we can write a service to write and expose some methods, so open the file ``ragnarok/service.py`` and replace what's there with the following code:

.. code-block:: python

    from __future__ import unicode_literals
    import requests

    from ragnarok import sa, config
    from sideboard.lib import subscribes, notifies, DaemonTask

    @subscribes('apocalypse')
    def all_checks():
        websites = {}
        with sa.Session() as session:
            for website in session.query(sa.Website).all():
                websites[website.url] = {
                    'result': any(r.world_ended for r in website.results),
                    'last_checked': website.last_checked
                }
        return websites

    @subscribes('apocalypse')
    def true_or_false():
        return any(website['result'] for website in all_checks().values())

    @notifies('apocalypse')
    def check_for_apocalypse():
        rsess = requests.Session()
        if config['proxy']:
            rsess.proxies = {'http': config['proxy'], 'https': config['proxy']}
        with sa.Session() as session:
            for website in session.query(sa.Website).all():
                page = rsess.get(website.url).text
                ended = website.search_for not in page
                session.add(sa.Result(website=website, world_ended=ended))

    DaemonTask(check_for_apocalypse, interval=60*60*24)

Here's what we did with the above code:

* implemented a publicly exposed ``all_checks`` function which returns a dictionary mapping website urls to whether or not that website has ever told us that the world has ended as well as the last time that we contacted that website

* implemented a publicly exposed ``true_or_false`` function which returns a bool indicating whether or not any website has ever told us that the world has ended

* implemented a ``check_for_apocalypse`` method which goes out through the configured proxy and checks all of the websites and stores the results

* configured a ``DaemonTask`` to automatically execute the ``check_for_apocalypse`` function once every 24 hours

* defined an ``apocalypse`` channel such that if anyone subscribes to the result of the ``all_checks`` or ``true_or_false`` function, then every time the ``check_for_apocalypse`` function is called, those methods will be re-run and the latest data will be pushed to the clients if the results have changed

So let's test out these methods in the REPL by running the ``python`` from Sideboard's virtualenv:

>>> import sideboard
>>> from ragnarok import service
>>> service.check_for_apocalypse()
>>> from pprint import pprint
>>> pprint(service.all_checks())
{u'http://hasthelargehadroncolliderdestroyedtheworldyet.com': {u'last_checked': datetime.datetime(2014, 4, 6, 4, 49, 12, 688737, tzinfo=<UTC>),
                                                               u'result': False},
 u'http://hastheworldended.webs.com': {u'last_checked': datetime.datetime(2014, 4, 6, 4, 49, 12, 687760, tzinfo=<UTC>),
                                       u'result': False}}
>>> service.true_or_false()
False

We've already exposed our service (see the ``services.register`` line in ``ragnarok/__init__.py``), so now when we run Sideboard, other people will be able to call our publicly exposed functions.



Making a Website
----------------

So let's make a webpage that actually displays this information.  Open the file ``ragnarok/__init__.py`` and replace the ``Root`` class with the following:

.. code-block:: python

    @render_with_templates(config['template_dir'])
    class Root(object):
        def index(self):
            return {
                'all_checks': service.all_checks(),
                'apocalypse': service.true_or_false()
            }

So this sets us up to be able to change our index.html to be a template that uses this data.  So now open ``ragnarok/templates/index.html`` and replace the contents with the following:

.. code-block:: html

    <!doctype html>
    <html>
        <head>
            <title>Ragnarok Aggregation</title>
        </head>
        <body>
            <h1>{{ apocalypse }}</h1>
            {% for website, status in all_checks.items() %}
                <h2>{{ website }} - {{ status.result }}</h2>
            {% endfor %}
        </body>
    </html>

So now we can go back to `<http://localhost:8282/ragnarok/>`_ and see a summary of our end-of-the-world checks.  One thing to note about this page handler is that it returns a dictionary.  Since the page handler is called ``index``, the dictionary it returns is used to render the ``index.html`` `jinja template <http://jinja.pocoo.org/>`_ in our configured templates directory.

So let's make this extra-dynamic; we'll use websockets to subscribe to our service so that anytime our data changes, we'll automatically get an update.  We're using `Angular <http://angularjs.org/>`_ because Sideboard comes with some WebSocket helpers which are written with Angular.

.. code-block:: html

    <!doctype html>
    <html ng-app="ragnarok">
        <head>
            <title>Ragnarok Sanity Check</title>
            <script src="//ajax.googleapis.com/ajax/libs/angularjs/1.2.15/angular.min.js"></script>
            <script src="/static/angular/sideboard.js"></script>
            <script>
                angular.module('ragnarok', ['sideboard'])
                    .controller('RagnarokCtrl', function ($scope, WebSocketService) {
                        WebSocketService.subscribe({
                            method: 'ragnarok.all_checks',
                            callback: function (allChecks) {
                                $scope.allChecks = allChecks;
                            }
                        });
                        $scope.refresh = function () {
                            WebSocketService.call('ragnarok.check_for_apocalypse');
                        };
                    });
            </script>
        </head>
        <body ng-controller="RagnarokCtrl">
            <button ng-click="refresh()">Refresh</button>
            <table>
                <tr>
                    <th>URL</th>
                    <th>World Ended</th>
                    <th>Last Updated</th>
                </tr>
                <tr ng-repeat="(url, status) in allChecks">
                    <td>{{ url }}</td>
                    <td>{{ status.result }}</td>
                    <td>{{ status.last_checked }}</td>
                </tr>
            </table>
        </body>
    </html>

Note that when you press the "Refresh" button the data gets automatically updated even though all we did was make call to the server without doing anything with the response.  That happened because of the following sequence of steps:

* we subscribe to the ``ragnarok.all_checks`` method when the page loads, so our callback will be called anytime we get a message from the server with new data

* when the refresh button is pressed, it calls the ``ragnarok.check_for_apocalypse`` method which updates the database

* because of how we used the ``@subscribes`` and ``@notifies`` decorators on these methods, calling ``check_for_apocalypse`` automatically causes the latest data to be pushed to the client which is subscribed to ``all_checks``

* our callback is fired again, which updates the data on the scope and the latest data is rendered to the page

Even without pressing the refresh button, the data on this page would still update every 24 hours since we defined that ``DaemonTask`` which calls ``check_for_apocalypse`` once per day.

Since this is our only plugin, we'd probably like this webpage to be the default page for this Sideboard site, so let's open our plugin's ``sideboard/configspec.ini`` and add the following line:

.. code-block:: none

    default_url = string(default="/ragnarok")

So now if we re-start our web server by re-running ``./env/bin/python sideboard/run_server.py`` and go to `<http://localhost:8282/>`_ we'll be taken directly to this page.



Using Django With Sideboard
===========================

CherryPy is a WSGI container, which means that anything which runs in Apache with ``mod_wsgi`` can run in CherryPy.  In this section we'll focus on creating a Django project inside a Sideboard plugin.  We're specifically documenting how to use Django because it's the most popular Python web framework, but other WSGI-compatible frameworks such as Flask can be used in the same way.

Let's create a new Sideboard plugin, this time without any of the usual pieces and tell it that we'll be including a Django site called ``mysite`` (we'll be following the Django tutorial, which uses that name).

.. code-block:: none

    ./env/bin/paver create_plugin --no_webapp --no_sqlalchemy --no_service --no_sphinx --django=mysite --name=unchained

After doing this, we now have the following directory structure created in the ``plugins`` directory:

.. code-block:: none

    unchained/
    |-- development-defaults.ini
    |-- fabfile.py
    |-- MANIFEST.in
    |-- package-support
    |   `-- unchained.cfg
    |-- requirements.txt
    |-- setup.cfg
    |-- setup.py
    `-- unchained
        |-- configspec.ini
        |-- __init__.py
        |-- tests
        |   `-- __init__.py
        `-- _version.py

Note that this did **not** automatically create the Django project.  The plugin that was created expects that Django project to exist, and it won't work until we create that project manually.  First, we'll need to add Django as a dependency by opening up ``plugins/unchained/requirements.txt`` and adding something like ``Django==1.9.2`` or whatever version of Django you'd like to use.  Then you can run ``python setup.py develop`` in your plugin's directory (or run ``paver install_deps`` from the main Sideboard directory).

After that, you can follow the `Django tutorial <https://docs.djangoproject.com/en/1.9/intro/tutorial01/>`_ to create a site.  As explained in the tutorial, in your top-level ``unchained`` directory you can run ``django-admin startproject mysite`` to creates the Django project alongside your plugin module.  The one thing you'll need to do differently from what the tutorial says is that you'll need to set

.. code-block:: python

    STATIC_URL = '/unchained/static/'

in ``plugins/unchained/mysite/mysite/settings.py`` because we're mounting our Django app at the ``/unchained`` mount point in CherryPy.

This approach maintains a Sideboard plugin whose module lives alongside a standalone Django project.  We do this in order to more easily run ``manage.py`` commands, which shouldn't generally need to know or care about Sideboard.  This also means that you can potentially write a Django app that will run in any mod_wsgi container, then have the Sideboard plugin call into it when you need to do Sideboard-specific things such as exposing ``services`` API calls.

From here you can run through the Django tutorial.  You'll be able to visit `<http://localhost:8282/unchained/admin/>`_ to see the Django admin interface, and once you write the "polls" app you'll be able to visit `<http://localhost:8282/unchained/polls>`_ to access its views.  (You don't currently get links to these in the ``/list_plugins`` page of Sideboard.)

Your Django project will be included in your RPM as packaged by your ``fabfile``.



Writing Unit Tests
------------------

All of our service methods involve querying our database.  Theoretically we could mock out the database calls, but we'd be testing code paths much closer to our production code if we really perform database queries in our unit tests.  Sideboard makes this easy by giving us some built-in `pytest fixtures <http://pytest.org/latest/fixture.html>`_ for swapping out our configured database with a SQLite database file in ``/tmp``, so we can insert test data and then have it restored at the beginning of every test case.

So let's open up ``conftest.py`` and where the comment instructs you to add your test data, add the following lines:

.. code-block:: python

    session.add(sa.Website(url="http://hastheworldended.webs.com", search_for="NO"))
    session.add(sa.Website(url="http://hasthelargehadroncolliderdestroyedtheworldyet.com", search_for="NOPE"))

Now we'll have that test data in our test database before each test.  Let's just test our simplest function: the ``service.true_or_false()`` method, since that just returns a boolean.  So we'll open up ``ragnarok/tests/__init__.py`` and replace the contents with the following:

.. code-block:: python

    from __future__ import unicode_literals
    import pytest
    from ragnarok import sa, service

    def _insert_result(world_ended):
        with sa.Session() as session:
            website = session.query(sa.Website).first()
            session.add(sa.Result(website=website, world_ended=world_ended))

    @pytest.fixture
    def life(db):
        _insert_result(False)

    @pytest.fixture
    def death(db):
        _insert_result(True)

    def test_no_result():
        assert not service.true_or_false()

    def test_world_not_ended(life):
        assert not service.true_or_false()

    def test_world_has_ended(death):
        assert service.true_or_false()

    def test_mixed_results(life, death):
        assert service.true_or_false()

Now with our virtualenv activated, we can run ``py.test`` in the ``ragnarok`` directory and it'll run these 4 tests.  Let's review what we're testing:
* the world has not ended if we've not downloaded any results
* the world has not ended if we've downloaded only a "world has not ended" result
* the world has ended if we've downloaded only a "world has ended" result
* the world has ended if we've downloaded a mix of results

Our ``life`` and ``death`` fixtures are injected to provide the underlying database state.



API Reference
=============

Sideboard provides a few modules full of useful utility functions and classes.  ``sideboard.lib`` has helpers which every plugin should use, and ``sideboard.lib.sa`` is for plugins which use SQLAlchemy as their database methods.

Plugins should never import any sideboard module that is not ``sideboard.lib`` or one of its submodules such as ``sideboard.lib.sa``.



sideboard.lib
-------------


Services
^^^^^^^^

.. class:: services

    ``sideboard.lib.services`` is how your plugin should expose RPC services and consume services exposed by other plugins
    
    .. method:: register(module[, namespace])
    
        Exposes all methods whose names do not begin with underscores in a module (or any object with callable functions).  If the module defines ``__all__``, only methods included in ``__all__`` will be exposed.
    
        :param module: the module you are exposing; any function in this module which is not prefixed with an underscore will be callable
        :param namespace: the prefix which consumers calling your method over RPC will use; if omitted this defaults to your module name

        After a module has been exposed, its methods can be called by other plugins, for example

        .. code-block:: python

            from sideboard.lib import services
            news, weather = services.news, services.weather

            def get_current_events():
                return {
                    "news": news.get_headlines(),
                    "weather": weather.current_weather()
                }

        One of the advantagtes of Sideboard is that your code doesn't need to care where the other plugins are installed; they could be either local or remote.  If they're installed on the same machine, then the above code would just work with nothing else needed, and if they're on a different box, you'd need to add the ``rpc_services`` section to your config file:

        .. code-block:: none

            [rpc_services]
            foo = example.com
            bar = example.com
            baz = secure.com
            news = secure.com
            weather = insecure.biz:8080

            [[secure.com]]
            ca = /path/to/ca.pem
            client_key = /path/to/key.pem
            client_cert = /path/to/cert.pem

            [[insecure.biz:8080]]
            jsonrpc_only = True
            ca =
            client_key =
            client_cert =

        Note that the rpc_services section contains a mapping of service names to hostnames, and you may optionally add a subsection for each hostname, specifying the client cert information.  If omitted, these values will default to the global values of the same names.  So if you're using the same CA for all of your sideboard apps, you probably won't need to include any subsections.

    .. attribute:: jsonrpc

        We use websockets as the default RPC mechanism, but you can also use Jsonrpc as a fallback, using the .jsonrpc attribute of sideboard.lib.services.  You can also configure a service to ONLY use jsonrpc using the ``jsonrpc_only`` config value in the subsection for that host; you probably shouldn't do that unless you're connecting to a non-Sideboard service.

        >>> from sideboard.lib import services
        >>> services.foo.some_func()          # uses websockets
        'Hello World!'
        >>> services.foo.jsonrpc.some_func()  # uses jsonrpc
        'Hello World!'
        >>> services.weather.some_func()      # uses jsonrpc

    .. method:: get_websocket(service_name)

        The services API already opens a websocket connection to each remote host which it's been configured to call out to for RPC services.  This method returns the underlying websocket connection for the specified service name, although you probably won't need to access these websocket connections directly, because
        * if you need to make RPC calls, we recommend just calling into service object methods, e.g. ``services.foo.some_func()``
        * if you need to make a websocket subscription, we recommend using the `Subscription <#Subscription>`_ class


.. attribute:: serializer

    Our RPC mechanisms are all based on JSON, which means we need some way to serialize non-basic data types.  This does not cover parsing of incoming JSON, but instead only defines how outgoing RPC calls serialize their parameters.  Sideboard registers functions for ``datetime.date`` and ``datetime.datetime`` objects, and plugins may register functions for their own objects.

    .. method:: register(type, preprocessor)
        
        Registers a function which pre-processes all objects of the given type, before being serialized to JSON.
        
        This method raises an exception if you try to register a preprocessor for a type which already has been registered.
        
        :param type: class whose instances should be pre-processed by the provided function
        :param preprocessor: function which takes a single argument and returns a value which will then be serialized to JSON
        
        As an example of how this is used, consider this snippet which Sideboard uses to define how ``datetime.date`` objects should be serialized:
        
        .. code-block:: python
            
            serializer.register(date, lambda d: d.strftime('%Y-%m-%d'))


Configuration
^^^^^^^^^^^^^

We use `ConfigObj <http://www.voidspace.org.uk/python/configobj.html>`_ because it lets us write text config files in ini format so that EIG can easily edit them, while still offering data types such as integers and lists, default values, required options, validations, and chains of config files.

So our convention is as follows:

* we have a ``configspec.ini`` file in our Python module's top directory which defines what config options we expect, their data types and default values, etc

* in development, the root directory of our Git repo has a ``development-defaults.ini`` file checked in, with the values we want when running on our machines

* in development, the root directory of our Git repo may also have a ``development.ini`` file which should NOT be checked in, which lets developers override config options for themselves without having those changes pushed out to other developers

* in production, we expect a single config file under ``/etc/sideboard`` with the production config values

* we parse and validate our configuration at import-time, so we fail fast by raising an exception if there's some problem parsing the config files (missing files are simply ignored)

Sideboard doesn't require you to manage your own configuration this way, but we strongly recommend it, and we provide the following function to do all of this for you:


.. function:: parse_config(requesting_file_path)

    This function parses the files mentioned above and returns a config dictionary; it knows where to find those files because you pass in the path of a file in your module's top-level directory, e.g.
    
    .. code-block:: python
    
        config = parse_config(__file__)
    
    In addition to the options you define yourself, this function prepends a few options for your convenience:
    
    * ``module_root``: an absolute path to your top-level module directory
    
    * ``root``: in development this will be an absolute path to the root directory of your plugin's repo, in production this will be an absolute path to the top-level directory of where your plugin is installed under ``/opt``


.. class:: ConfigurationError

    Raised by ``parse_config`` if any parsing or validation errors occur.



WebSocket Pub/Sub
^^^^^^^^^^^^^^^^^

We use `WebSockets <http://en.wikipedia.org/wiki/WebSocket>`_ extensively as our `publish/subscribe <http://en.wikipedia.org/wiki/Publish%E2%80%93subscribe_pattern>`_ transport mechanism for services we expose with our `sideboard.lib.services <#services>`_ API.  We've implemented a simple request/response RPC protocol wherein clients can send a JSON-serialized message such as

.. code-block:: none

    {
        "client": "client-1",
        "method": "admin.logged_in_usernames",
        "params": ["SB1"]
    }

and immediately get back a response that looks like

.. code-block:: none

    {
        "client": "client-1",
        "data": ["admin", "username2"]
    }

This would implicitly create a subscription; behind the scenes, calling the ``admin.logged_in_usernames`` function causes your websocket connection to listen on one or more channels.

Alternatively, you might want to make an RPC call and get a single response without making a subscription, e.g.

.. code-block:: none

    REQUEST:
    {
        "callback": "callback-1",
        "method": "admin.authenticate",
        "params": ["username", "password"]
    }
    
    RESPONSE:
    {
        "callback": "callback-1",
        "data": true
    }

When a function which has been declared to update those channels is called, the following sequence of events occurs:

* all functions for all clients which are listening to any of the channels being notified are re-called for each client

* the new results are compared to the result of the previous call; if there's no difference, then no new message is sent

* otherwise, the latest data is pushed out to the client in a new response, tagged with the appropriate client id


.. function:: subscribes(*channels)
    
    Function decorator used to indicate that calling this function over WebSocket RPC should automatically subscribe the client to the specified channels.  Each argument should be a string which indicates the channel name; these strings can be anything; their contents are not parsed and only need to match some function decorated with ``@notifies``.
    
    .. code-block:: python
        
        name = 'DefaultName'
        
        @subscribes('greeting')
        def message():
            return 'Hello ' + name


.. function:: notifies(*channels)
    
    Function decorator used to indicate that calling this function should trigger the notification to all clients subscribed to the specified channels.
    
    .. code-block:: python
    
        @notifies('greeting')
        def set_name(new_name):
            global name
            name = new_name
            return "ok"


.. function:: notify(channels)
    
    Explicitly cause all client listening on those files 
    
    Unless you have some specific reason to use this function, you should probably just decorate the appropriate function with the ``@notifies`` decorator.

    :param channels: a string or list of strings, which are the names of the channels to notify


So in the above examples listed with the ``@subscribes`` and ``@notifies`` decorators, we might see the following sequence of requests and responses:

.. code-block:: none

    CLIENT-TO-SERVER: {"client": "client-1", "method": "myplugin.message"}
    SERVER-TO-CLIENT: {"client": "client-1", "data": "Hello DefaultName"}
    
    CLIENT-TO-SERVER: {"callback": "callback-1", "method": "myplugin.set_name", "params": ["World"]}
    SERVER-TO-CLIENT: {"callback": "callback-1", "data": "ok"}
    SERVER-TO-CLIENT: {"client": "client-1", "data": "Hello World"}
    
    CLIENT_TO-SERVER: {"callback": "callback-2", "method": "myplugin.set_name", "params": ["World"]}
    SERVER-TO-CLIENT: {"callback": "callback-2", "data": "ok"}
    // no response on client-1 because the response data has not changed



WebSocket Utils
^^^^^^^^^^^^^^^

Sideboard provides several useful classes for establishing websocket connections to other Sideboard servers, implementing the websocket RPC protocol described in the previous section.

.. class:: WebSocket([url[, ssl_opts={}[, connect_immediately=True[, max_wait=2]]]])
    
    Class representing a persistent websocket connection to the specified url (or connecting to this sideboard instance on localhost if url is omitted), with an option dictionary of extra keyword arguments to be passed to ssl.wrap_socket, typically client cert parameters.
    
    You probably won't ever need to instantiate this class directly in your production code, but it's used under the hood to implement the `services API <#services>`_ and is very useful for debugging or one-off scripts.
    
    :param url: the ``ws://`` or ``wss://`` url this websocket should connect to; if the url is omitted then we will connect to localhost on the port which Sideboard runs on
    :param ssl_opts: dictionary of arguments which will be passed to `ssl.wrap_socket() <https://docs.python.org/2/library/ssl.html#ssl.wrap_socket>`_ if this is a secure ``wss://`` connection; this parameter could be used to pass client cert info
    :param connect_immediately: if True (the default), try to open a connection immediately instead of having the connection opened automatically when Sideboard starts
    :param max_wait: if ``connect_immediately`` set, this is passed to the ``.connect()`` method of this class
    
    Instantiating a WebSocket object immediately starts two threads (unless ``connect_immediately`` is false, in which case this will happen when ``.connect()`` is called):
    
    * a thread which listens on the open connection and dispatches incoming messages
    
    * a thread which is responsible for connecting and re-connecting to the server and performs the following actions:
    
      * immediately connect to the url when this class is instantiated
        
      * if unable to connect, attempt to re-connect in the background
        
      * periodically poll the server to make sure we get a response back; if we do not then assume the connection has gone dead and close the socket and attempt to re-connect
        
      * when we re-connect, immediately re-fire all RPC method calls we're subscribed to, which gets the latest data and re-subscribes to the relevant channels

    So instantiating this class does not guarantee that your connection is open; you should check the ``connected`` attribute if you are performing an action and relying on an immediate response.
    
    If you only care about subscibing to a single method, you should probably use the `Subscription class <#Subscription>`_.

    .. method:: call(method, *args, **kwargs)
        
        Sometimes you want to make a synchronous call a method over websocket RPC, even though the websocket protocol is asynchronous.  This method sends an RPC message, then waits for a response and returns it when it arrives.
        
        This method raises an exception if 10 seconds pass without a response, or if we receive an error response to our RPC message.  Note that this 10 second time can be overridden in the Sideboard configuration by changing the ``ws_call_timeout`` option.
        
        :param method: the name of the method to call; you may pass either positional or keyword arguments (but not both) to this method which will be sent as part of the RPC message
    
    .. method:: subscribe(callback, method, *args, **kwargs)
        
        Send an RPC message to subscribe to a method.
        
        This method is safe to call even if the underlying socket is not active; in this case we will log a warning and send the message as the connection is successfully [re-]established.
        
        :param callback: This can be either a function taking a single argument (the data returned by the method) or a dictionary with the following keys:
        
                         * *callback* (required): a function taking a single argument; this is called every time we receive data back from the server
        
                         * *errback* (optional): a function taking a single argument; this is called every time we recieve an error response from the server and passed the error message (if omitted we log an error message and continue)
        
                         * *paramback* (optional): a function taking no arguments; if present, this is called to generate the params for this subscription, both initially and every time the websocket reconnects
        
                         * *client* (optional): the client id to use; this will be automatically generated, and you should omit this unless you really know what you're doing
        
        :param method: the name of the method you want to subscribe to; you may pass either positional or keyword arguments (but not both) to this method which will be sent as part of the RPC message.  If "paramback" is passed (see above) then args/kwargs will be ignored entirely and that will be used to generate the parameters.
        :returns: the automatically generated client id; you can pass this to ``unsubscribe`` if you want to keep this connection open but cancel this one subscription
    
    .. method:: unsubscribe(client1[, client2[, ...]])
        
        Send a message to the server indicating that you no longer want to be subscribed to any channels on the specified client.
        
        :param client: the client id being unsubscribed; this is whatever was returned from the ``subscribe`` method; this method can be passed any number of client ids as positional arguments
    
    .. method:: connect([max_wait=0])
    
        Starts the two background threads described above.  This method returns immediately unless the ``max_wait`` parameter is specified.  If specified, we will wait for up to that many seconds for the underlying connection to be active.  If that much time elapses without a successful connection, a warning will be logged, but we will still return without raising an exception with the websocket in an unconnected state.
        
        This method is safe to call if this websocket is already connected; in that case this method is effectively a noop because nothing will happen.
    
    .. method:: close()
        
        Closes this connection safely; any errors will be logged and swallowed, so this method will never raise an exception.  Both daemon threads are stopped.
        
        Once this method is called, there is no supported way to re-open this websocket object; if you want to re-establish your connection to the same url, you'll need to instantiate a new ``WebSocket`` object.
    
    .. attribute:: connected
        
        boolean indicating whether or not this connection is currently active

    .. attribute:: fallback
    
        Handler function which is called when we receive a message which is not a response to either a ``call`` or ``subscribe`` RPC message.  By default this just logs an error message.  You can override this by either subclassing this class or simply by setting the attribute to a function which takes a single argument (the message received), e.g.
        
        >>> ws = WebSocket()
        >>> ws.fallback = lambda message: do_something_with(message)


.. class:: Subscription(rpc_method, *args, **kwargs)
    
    Sideboard plugins often want to establish a `<#WebSocket>`_ connection to some other Sideboard plugin and subscribe to a function.  This class offers a convenient API for doing this; simply specify a method along with whatever arguments you want to pass, and you'll always have the latest response in the ``result`` field of this class, e.g.
    
    >>> from sideboard.lib import Subscription
    >>> users = Subscription('admin.get_logged_in_users')
    >>> users.result  # this will always be the latest data

    If you want to perform immediate post-processing of the result, you can inherit from this class and override the ``callback`` method which is always passed the latest data, e.g.
    
    >>> class UserList(Subscription):
    ...     def __init__(self):
    ...         self.usernames = []
    ...         Subscription.__init__(self, 'admin.get_logged_in_users')
    ...     
    ...     def callback(self, users):
    ...         self.usernames = [user['username'] for user in users]
    ... 
    >>> users = UserList()

    :param rpc_method: the name of the method you want to subscribe to; you may pass either positional or keyword arguments (but not both) will be sent as part of the RPC message
    
    .. method:: callback(latest_data)
        
        This method is called every time we get a response from the server with new data.  You can override this method in a subclass of ``Subscription`` if you want to do immediate post-processing on the data.
        
        :param latest_data: the return value of the function you are subscribed to
        
    .. method:: refresh()
        
        Manually send a one-time call of the method you're subscribed to and invoke our `callback <#Subscription.callback>`_ with the response.
        
        This method is usually unnecessary if your method subscribes to channels which are fired every time its data updates, which will almost always be true.  You should ignore this method if you don't already know that you need it.


.. class Model(data[, prefix=None, [unpromoted=None, [defaults=None]]]):
    
    
    
    :param data: 
    :param prefix: 
    :param unpromoted: 
    :param defaults: 
    
    .. attribute:: query
        
        
    
    .. attribute:: dirty
        
        
    
    .. attribute:: to_dict()
        
        


Dynamic Websites
^^^^^^^^^^^^^^^^

We provide some convenient helpers for using `Jinja templates <http://jinja.pocoo.org/docs/>`_.  Plugins typically write CherryPy page handlers which render templates, and we want to restrict access to logged-in users which authenticate with LDAP, so Sideboard has some decorators which implement this pattern.

.. function:: render_with_templates([template_dir[, restricted=False]])

    Class decorator which decorates all methods to render templates looked up by method name; for example, a method called ``foo`` which returns a dictionary will render the ``foo.html`` template in the configured template directory.  Methods which return strings simply pass those strings unmodified back to the browser.

    :param template_dir: the directory where jinja will find its templates
    :param restricted: if True, every request for every page handler will be checked for an authenticated session, and if unauthenticated the user will be redirected to the Sideboard-supplied login page


.. function:: ajax(handler_method)

    Method decorator for page handlers where instead of rendering a template, your return value will be serialized to json with the appropriate HTTP headers set.


Here's an example of how these decorators might be used:

.. code-block:: python

    @render_with_templates(config['template_dir'], restricted=True)
    class Root(object):
        def index(self):  # renders index.html in template dir
            return {
                'some_key': 'passed to template',
                'other_key': 'renders in template'
            }
        
        @ajax
        def some_action(self, param):
            return {'data': 'serialized as json'}



Javascript Libraries
^^^^^^^^^^^^^^^^^^^^

As mentioned above in the tutorial, Sideboard ships with an Angular module (called ``sideboard``) which provides a ``WebSocketService``.

.. class:: WebSocketService

    .. method:: subscribe(request)
    
        Make an RPC call which returns data immediately and also every time the response changes.  This method takes a single argument which is an object with the following fields:
        
        :param method: (required) string indicating the service method to call
        :param params: (optional) this may be an array of arguments, an object of keyword arguments, or a single element which will be passed as a single argument to the method on the server
        :param client: (optional) if omitted, a new client id will be generated; you should use this if you want to update an existing subscription rather than create a whole new one
        :param callback: (required) a function which takes a single argument, which is the value of the method response; this callback is invoked every time we get a non-error response to this subscription
        :param error: (optional) a function which takes a single argument; this is called anytime we get a response to this subscription with an ``error`` attr; this function will be passed that value
        :returns: a string which is the client id of the new subscription
        
        If our connection to the server is ever interrupted, this service will re-fire all subscription requests every time the connection is re-established.

    .. method:: unsubscribe(clientId)
    
        Frees the local resources associated with the subscription idenfied by this client id, and sends a message to the server (if our connection is currently open) indicating that we no longer want to receive response messages when the subscription is updated.
        
        :param clientId: the value returned by ``.subscribe()`` which uniquely identifies the subscription being canceled

    .. method:: call(method[, *args])
    
        Sends a one-time RPC request to the server and returns a `promise <http://docs.angularjs.org/api/ng/service/$q>`_ which may be used to consume the response.  The promise is fulfilled with the value we get back from the server.  It will be rejected if we receive an error message from the server, or if the request times out.
        
        This function can be called in one of two ways.  It can take positional arguments, which will be the method and its positional arguments, e.g.
        
        .. code-block:: javascript
        
            WebSocketService.call('foo.bar', arg1, arg2);
        
        or it takes a single object with the following fields:
        
        :param method: (required) string value of the method being called
        :param params: (optional) identical to the ``params`` field passed to ``WebSocketService.subscribe()``; this may be either a single value, an array of positional arguments, or an object of keyword arguments
        :param timeout: (optional) integer value in milliseconds which will override the default value of 10000 milliseconds (10 seconds)


Invoking either ``call`` or ``subscribe`` will automatically open a websocket connection to the server if one is not already active.  Once a connection is open, the service sends periodic poll requests in the background; if no repsonse is received the connection is closed and re-opened; this helps detect early when a connection has gone dead without the actual socket object closing.  If we can't connect to the server, we automatically retry periodically until we succeed.

This service broadcasts a ``WebSocketService.open`` event on ``$rootScope`` every time a connection is successfully opened, and broadcasts a ``WebSocketService.close`` event every time the connection goes dead; this may be useful if your webapp wants to monitor the current connection status to display a warning to the user.



Background Tasks
^^^^^^^^^^^^^^^^

One of the most common things our web applications want to do is run tasks in the background.  This can include either tasks which are performed once when the server starts (e.g. initializing the database), or running background tasks which periodically perform some action.

When we refer to "Sideboard starting" and "Sideboard stopping" we are referring specifically to when Sideboard starts its CherryPy server; this happens after all plugins have been imported, so you can safely call into other plugins in these tasks and functions.


.. function:: on_startup(func[, priority=50])
    
    Cause a function to get called on startup.  You can use this as a decorator or directly call it.  The priority level indicates the order in which the startup functions should be called, where low numbers come before high numbers.
    
    .. code-block:: python
    
        @on_startup
        def f():
            print("Hello World!")
        
        @on_startup(priority=40)
        def g():
            print("Hello Kitty!")
        
        def h():
            print("Goodbye World!")
        
        on_startup(h, priority=60)
    
    :param func: The function to be called on startup; this function must be callable with no arguments.
    :param priority: Order in which startup functions will be called (lower priority items are called first); this can be any integer and the numbers are used for nothing other than ordering the handlers.


.. function:: on_shutdown(func[, priority=50])
    
    Cause a function to get called on startup; this is invoked in exactly the same way as ``on_startup``
    
    :param func: The function to be called on shutdown; this function must be callable with no arguments.
    :param priority: Order in which shutdown functions will be called (lower priority items are called first); this can be any integer and the numbers are used for nothing other than ordering the handlers.


.. attribute:: stopped

    ``threading.Event`` which is reset when Sideboard starts and set when it stops; this may be useful with looping and sleeping in background tasks you write in your Sideboard plugins


.. class:: DaemonTask(func[, threads=1[, interval=0.1]])
    
    This utility class lets you run a function periodically in the background.  These background daemon threads starts and stops automatically when Sideboard starts and stops.  Exceptions are automatically caught and logged.
    
    :param func: the function to be executed in the background; this must be callable with no arguments
    :param interval: the number of seconds to wait between function invocations
    :param threads: the number of threads which will call this function; sometimes you may want a pool of threads all calling the same function

    .. attribute:: running
    
        boolean indicating whether this ``DaemonTask`` has been started and not yet been stopped; since Sideboard manages the starting and stopping of ``DaemonTask`` instances, you can probably just ignore this attribute

    .. method:: start()
    
        Starts a pool of daemon threads for this background task; this is always safe to call even if the threads are already running.
        
        Since this is called automatically when Sideboard starts, you can usually just ignore this method.
    
    .. method:: stop()
    
        Stops the pool of threads for this background task; this is always safe to call even if the threads are already stopped.  This method blocks until all of the threads have stopped, or exits after 5 seconds and logs a warning if any are still running after we've told them to stop.
        
        Since this is called automatically when Sideboard stops, you can usually just ignore this method.


.. class:: TimeDelayQueue()

    Subclass of `Queue.Queue <http://docs.python.org/2/library/queue.html#Queue.Queue>`_ which adds an optional ``delay`` parameter to the ``put`` method which does not add the item to the queue until after the specified amount of time.  This is used internally but is included in our public API in case it's useful to anyone else.

    .. method:: put(item[, block=True[, timeout=None[, delay=0]]]):
    
        Identical to `Queue.put() <http://docs.python.org/2/library/queue.html#Queue.Queue.put>`_ except that there's an extra delay argument; if nonzero then the ``item`` will be added to the queue after ``delay`` seconds.  This method will still return immediately; the item will be added in a background thread.


.. class:: Caller(func[, threads=1])

    Utility class allowing code to call the provided function in a separate pool of threads.  For example, if you need to call a long-running function in the handler for an HTTP request, you might want to just kick off the method in a background thread so that you can return from the page handler immediately.
    
    >>> caller = Caller(long_running_func)
    >>> caller.defer('arg1', arg2=True)        # called immediately (in another thread)
    >>> caller.delay(5, 'argOne', arg2=False)  # called after a 5 second delay (in another thread)

    :param func: the function to be executed in the background; this must be callable with no arguments
    :param threads: the number of threads which will call this function; sometimes you may want a pool of threads all calling the same function

    This is a subclass of `DaemonTask <#DaemonTask>`_, so it has ``.start()`` and ``.stop()`` methods as well as a ``.running`` attribute which you can probably ignore, since Sideboard manages the starting and stopping of this class' instances.

    .. method:: defer(*args, **kwargs)
    
        Pass a set of arguments and keyword arguments which will be used to call this instance's function in a background thread.
    
    .. method:: delay(seconds, *args, **kwargs)
    
        Call this instance's function in a background thread after the specified delay with the passed position and keyword arguments.


.. class:: GenericCaller([threads=1])

    Like the ``Caller`` class above, except that instead of calling the same method with provided arguments, this lets you spin up a pool of background threads which will call any methods you specify, e.g.
    
    >>> from __future__ import print_function
    >>> gc = GenericCaller()
    >>> gc.defer(print, 'Hello', 'World', sep=', ', end='!')     # prints "Hello, World!"
    >>> gc.delay(5, print, 'Hello', 'World', sep=', ', end='!')  # prints "Hello, World!" after 5 seconds

    :param threads: the number of threads which will call this function; sometimes you may want a pool of threads all calling the same function

    This is a subclass of `DaemonTask <#DaemonTask>`_, so it has ``.start()`` and ``.stop()`` methods as well as a ``.running`` attribute which you can probably ignore, since Sideboard manages the starting and stopping of this class' instances.


Miscellaneous
^^^^^^^^^^^^^

.. attribute:: log
    
    ``logging.Logger`` subclass which automatically adds module / class / function names to the log messages.  Plugins should always import and use this logger instead of defining their own or using ``logging.getLogger()``.


.. function:: is_listy(x)

    Returns a boolean indicating whether x is "listy", which we define as a sized iterable which is not a map or string.  This is a utility method which we use internally and it was useful enough that it's exposed for plugins to use.  We're not saying it was a mistake to make strings iterable in Python, but sometimes we think it very loudly.


.. function:: listify(x)

    returns a list version of x if x is a `listy <#is_listy>`_ iterable, otherwise returns a list with x as its only element, for example:
    
    .. code-block:: none
    
        listify(5)       => [5]
        listify('hello') => ['hello']
        listify([5, 6])  => [5, 6]
        listify((5,))    => [5]


.. function:: cached_property

    A decorator for making read-only, `memoized <http://en.wikipedia.org/wiki/Memoization>`_ properties.  This is especially useful when writing properties on SQLAlchemy model classes.


.. class:: threadlocal
    
    Utility class for storing global, thread-local data as a key-value store.  This data is not persisted across requests, so anything you store here will be garbage collected at some unspecified time after your request has completed.  Functions exposed as `services <#services>`_ can be called over websocket RPC, JSON-RPC, and from CherryPy page handlers responding to an HTTP request.  Before dispatching to the appropriate methods, Sideboard initializes your thread-local data store with the following values:
    
    * *username* (websocket / HTTP request only): the currently-logged-in user
    
    * *websocket* (websocket only): the actual `WebSocket <#WebSocket>`_ object handling the current method call
    
    This class should not be instantiated; all of the methods listed below are classmethods and can be called directly, e.g. ``threadlocal.get_client()``
    
    .. classmethod:: get(key[, default=None])
        
        Returns the value associated with the specified key.
        
        :param key: name (as a string) of the value to return
        :param default: returned if the key is not present; this value is **not** returned if the value is present but is ``None`` or otherwise falsey
    
    .. classmethod:: set(key, value)
        
        Store a value identified by a key.  This method returns nothing.
        
        :param key: name (as a string) of the value to store
        :param value: the value to store; this can be anything and does not need to be pickleable or otherwise serializable
    
    .. classmethod:: setdefault(key, value)
        
        Check whether the given key already has a value set; if not then set the provided value.  Either way, return whatever the current value now is.
        
        :param key: name (as a string) of the value to optionally-set-and-definitely-return
        :param value: default value to set if no value is already set for this key
    
    .. classmethod:: get_client()
        
        Returns the websocket client id used to make this request, or None if not applicable.  This value may be present in both websocket and jsonrpc requests; in the latter case it would be present as the ``websocket_client`` key of the request, e.g. a jsonrpc request that looks like this:
        
        .. code-block:: python
        
            {
                "jsonrpc": "2.0",
                "id": "106893",
                "method": "user.set_zip_code",
                "params": ["20191"],
                "websocket_client": "client-623"
            }
    
    .. attribute:: client_data

        Class property which returns a dictionary.  For websocket subscriptions, this dictionary is persisted and then restored before the function is re-called, so that methods can store data on a per-subscription basis.  This is like a server "session" except that it's per-subscription instead of per-user.



sideboard.lib.sa
----------------

Sideboard plugins typically use SQLAlchemy as their ORM; if you don't want to use SQLAlchemy then you can ignore this entire section.  We use the `declarative syntax <http://docs.sqlalchemy.org/en/rel_0_8/orm/extensions/declarative.html>`_ and offer utility methods to make this better.


.. function:: declarative_base(BaseClass)
    
    Class decorator for defining your SQLAlchemy base.  You should use this instead of using `sqlalchemy.ext.declarative.declarative_base <http://docs.sqlalchemy.org/en/rel_0_8/orm/extensions/declarative.html#sqlalchemy.ext.declarative.declarative_base>`_ because this adds several utility methods to your base class, described here:
    
    .. function:: to_dict([attrs])
        
        Serialize this model to a dictionary; by default this will serialize all non-foreign-key attributes.
        
        :param attrs: a list of which attribute names which should be serialized; this is in the same format as the ``data`` parameter to ``crud.read`` (which will eventually be documented)
    
    .. function:: from_dict(attrs)
        
        Set the attributes of this model instance to the provided values.
        
        :param attrs: a possibly-nested dictionary of values to apply to this model instance
    
    .. attribute:: __tablename__
        
        SQLAlchemy lets you define how you want your tables to be named in the database with this attribute.  We define this to be the separated-with-underscores version of the class name, e.g. a model class named ``FooBar`` would have the tablename ``foo_bar``.


.. class:: SessionManager
    
    Subclass this to get a context manager for working with database sessions; your transaction will be committed at the end of your context block, or rolled back on an exception.
    
    .. function:: initialize_db([drop=False])
        
        Create all of your database tables if they don't already exist.  This is called automatically as soon as your subclass is defined, at import time.
        
        :param drop: if True, drop those tables before creating them if they already exist - this should only be called during testing, such as in a unit test
    
        .. warning::
            
            This function creates all tables defined by subclasses of your declarative base class.  This means that if you define your declarative base class, then define this subclass, then define your models, then this function will not create any tables when it is automatically called at import time, because those subclasses don't exist yet.
            
            So if you want to make use of this automatically-create-my-tables feature, you need to define all of your model objects before you define your ``SessionManager`` subclass.
    
    .. attribute:: engine
    
        You must define this as a class attribute to tell your context manager how to make sessions.  You would typically use `sqlalchemy.create_engine() <http://docs.sqlalchemy.org/en/rel_0_8/core/engines.html#sqlalchemy.create_engine>`_ to generate this attribute.

    .. attribute:: session_factory
    
        Optional class-attribute for defining how sessions are created.  If omitted, then this will be filled in using `sqlalchemy.orm.session.sessionmaker <http://docs.sqlalchemy.org/en/latest/orm/session.html#sqlalchemy.orm.session.sessionmaker>`_ with autocommit and autoflush both turned off, but you should define this yourself if you want any non-default options.
        
        You should not set this attribute yourself unless you really know what you're doing.

    .. attribute:: BaseClass
        
        Optional class-attribute for telling your session objects what declarative base you're using.  This is set automatically if you use the ``declarative_base`` class decorator described above.  You should only set this if you want some non-default behavior such as having more than one declarative base.
        
        You should not set this attribute yourself unless you really know what you're doing.

    .. attribute:: SessionMixin
        
        Sometimes you want to write utility methods on your session objects; for example, instead of saying
        
        .. code-block:: python
            
            session.query(Foo).filter_by(id=id).one()
        
        you'd want to just say the much simpler
        
        .. code-block:: python
            
            session.get_foo(id)
        
        If you define a ``SessionMixin`` class inside your ``SessionManager`` subclass, any methods on your mixin will be monkeypatched onto your session objects, so that you can write any utility method you want.  So to write the ``get_foo`` method in the above example, you'd say
        
        .. code-block:: python
            
            @declarative_base
            class Base(object):
                id = Column(UUID(), nullable=False, default=uuid.uuid4)
            
            class Foo(Base):
                bar = Column(UnicodeText(), default='Hello World')
            
            class Session(SessionManager):
                engine = sqlalchemy.create_engine('sqlite:////tmp/testing.db')
                
                class SessionMixin(object):
                    def get_foo(self, id):
                        return self.query(Foo).filter_by(id=id).one()


Custom Columns
^^^^^^^^^^^^^^

SQLAlchemy lets you `write custom column types <http://docs.sqlalchemy.org/en/rel_0_8/core/types.html#custom-types>`_ and there are several columns which we've found ourselves writing and using a lot, which we've included with Sideboard.

.. class:: UUID
    
    SQLAlchemy column type for storing UUIDs.  If the underlying database is Postgresql, we'll use its built-in UUID column type, otherwise we'll store the UUID as a string.  You should assign `uuid.UUID <http://docs.python.org/2/library/uuid.html#uuid.UUID>`_ objects to this column, and values returned by this column will be strings, e.g. ``'01309a8f-2979-4273-9820-45e677e478b3'``.

    This class would typically be used as follows:
    
    .. code-block:: python
    
        id = Column(UUID(), nullable=False, default=uuid.uuid4)

.. class:: JSON
    
    SQLAlchemy column type for storing JSON.  Values assigned to this column will automatically be serialized to JSON (an exception will be raised if the value cannot be serialized), and getting a value back from this column will return the parsed object.
    
    This class would typically be used as follows:
    
    .. code-block:: python
    
        extra_data = Column(JSON(), nullable=False, default={}, server_default='{}')

.. class:: UTCDateTime
    
    SQLAlchemy column type for storing timestamps in UTC.  Values assigned to this column must be ``datetime`` objects with a timezone; the value will be automatically converted to UTC before being stored in the database.  Values returned by this column will always be ``datetime`` object with a UTC timezone.
    
    This class would typically be used as follows:
    
    .. code-block:: python
    
        created = Column(UTCDateTime(), nullable=False, default=lambda: datetime.now(pytz.UTC))
    
    .. warning::
    
        ``UTCDateTime`` uses `pytz <http://pytz.sourceforge.net/>`_ in its implementation, so if your plugin does not have ``pytz`` installed, this class will not be defined, and trying to import it will raise an ``ImportError``.


CRUD
^^^^

.. class:: CrudException

    All exceptions thrown by any rest method are wrapped and re-raised as instances of this class.

.. function:: crudable

.. function:: crud_validation

.. function:: text_length_validation

.. function:: regex_validation



Tests
=====

The tutorial describes the use of our provided `pytest fixtures <http://pytest.org/latest/fixture.html>`_ to write meaningful tests which actually perform database queries against a test SQLite database.

Here we'll briefly document the fixtures that Sideboard provides:

.. function:: service_patcher()

    Pytest fixture which is a function you can use to override a service with a test service.  You can pass either an object (which will be registered as the replacement service) or a dictionary (which will be converted to an object).  This override will be cleaned up after the test.  For example:

    .. code-block:: python

        from sideboard.lib import services
        from sideboard.tests import service_patcher

        foo, bar = services.foo, services.bar

        class mock_foo(object):
            def get_num(self):
                return 5

        mock_bar = {'get_num': lambda: 6}

        @pytest.fixture
        def mock_foo_and_bar(service_patcher):
            service_patcher('foo', mock_foo())
            service_patcher('bar', mock_bar)

        def test_foo_and_bar(mock_foo_and_bar):
            assert 11 == foo.get_num() + bar.get_num()

.. function:: config_patcher()

    Pytest fixture which can be used to override your configuration for testing, which restores the original configuration at the end of the test.  Here's a simple example:

    .. code-block:: python

        from ragnarok import config
        from sideboard.tests import config_patcher

        def message():
            return 'Hello ' + config['default.name']

        def test_message(config_patcher):
            config_patcher('World', 'default.name', config=config)
            assert 'Hello World' == message()

.. function:: sideboard.tests.patch_session(Session)

    This is invoked in the ``conftest.py`` that our ``paver create_plugin`` provides, and you probably don't need to use this anywhere else.  This function monkeypatches your ``Session`` class to use a SQLite database in ``/tmp`` instead of whatever you already had configured.
