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

* `HasTheWorldEndedYet.com <http://hastheworldendedyet.com/>`_

* `HasTheLargeHadronCollidorDestroyedTheWorldYet.com <http://hasthelargehadroncollidordestroyedtheworldyet.com/>`_

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

    $ git clone https://github.com/appliedsec/sideboard.git
    $ cd sideboard/
    $ paver make_sideboard_venv
    $ ./env/bin/python sideboard/run_server.py

Now you can go to `<http://localhost:8282/>`_ and you'll see a page show you Sideboard' version and all of the installed plugins (currently none).

So let's create a plugin with paver:

.. code-block:: none

    ./env/bin/paver create_plugin --name=ragnarok

This will create the following directory structure in your ``plugins`` directory:

.. code-block:: none

    .
    `-- ragnarok
        |-- development-defaults.ini
        |-- ragnarok
        |   |-- configspec.ini
        |   |-- __init__.py
        |   |-- sa.py
        |   |-- service.py
        |   |-- templates
        |   |   `-- index.html
        |   |-- tests
        }       `-- __init__.py
        |   `-- _version.py
        |-- requirements.txt
        |-- setup.cfg
        `-- setup.py

Next we'll make a separate virtualenv for our new plugin:

.. code-block:: none

    paver make_plugin_venvs

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
        
        def __repr__(self):
            return '<{}>'.format(self.url)

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
    from sqlalchemy.schema import Column, ForeignKey

    from ragnarok import config
    from sideboard.lib.sa import SessionManager, UUID, UTCDateTime, declarative_base

Notice that we're using the `pytz module <http://pytz.sourceforge.net/>`_ so we need to install that in our plugin's virtualenv.  So open the ``requirements.txt`` file in your plugin root directory and add the following line:

.. code-block:: none

    pytz==2013b

Now we can run 

.. code-block:: none

    ./env/bin/python setup.py develop

from our plugin root directory and pytz will be installed.

Now we can play around in the REPL by running ``./env/bin/python`` in the top-level Sideboard directory (not your top-level plugin directory):

>>> from ragnarok import sa
>>> with sa.Session() as session:
...   session.add(sa.Website(url="http://hastheworldendedyet.com", search_for="not yet"))
...   session.add(sa.Website(url="http://hasthelargehadroncolliderdestroyedtheworldyet.com", search_for="NOPE"))
... 
>>>

We used our ``Session`` object as a context manager, which committed automatically at the end of the block.  We can confirm this by querying our database:

>>> with sa.Session() as session:
...   session.query(sa.Website).all()
... 
[<http://hastheworldendedyet.com>, <http://hasthelargehadroncolliderdestroyedtheworldyet.com>]



Service
-------

Okay, so we want to write some code that checks these websites, which means we'll need to go through a proxy.  Let's add a proxy url to our settings by opening the file ``ragnarok/configspec.ini`` and adding the following line:

.. code-block:: none

    proxy = string

This tells our configuration parser that the ``proxy`` setting is required, so we'll add this setting to our development settings by opening the file ``development-defaults.ini`` and adding the following line:

.. code-block:: none

    proxy = "http://proxy1.test.tld/"

When we write our RPM packaging, we'll need to make sure that the config file we include with our RPM includes this setting; otherwise we'll get an error when our config settings are validated because we'll be missing a required config option.

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
                websites[website.url] = any(r.world_ended for r in website.results)
        return websites

    @subscribes('apocalypse')
    def true_or_false():
        return any(all_checks().values())

    @notifies('apocalypse')
    def _check_for_apocalypse():
        rsess = requests.Session()
        rsess.proxies = {'http': config['proxy'], 'https': config['proxy']}
        with sa.Session() as session:
            for website in session.query(sa.Website).all():
                page = rsess.get(website.url).content
                ended = website.search_for not in page
                session.add(sa.Result(website=website, world_ended=ended))

    DaemonTask(_check_for_apocalypse, interval=60*60*24)

Here's what we did with the above code:

* implemented a publicly exposed ``all_checks`` function which returns a dictionary mapping website urls to whether or not that website has ever told is that the world has ended

* implemented a publicly exposed ``true_or_false`` function which returns a bool indicating whether or not any website has ever told us that the world has ended

* implemented a non-exposed (because it starts with an underscore) ``_check_for_apocalypse`` method which goes out through the configured proxy and checks all of the websites and stores the results

* configured a ``DaemonTask`` to automatically execute the ``_check_for_apocalypse`` function once every 24 hours

* defined an ``apocalypse`` channel such that if anyone subscribes to the result of the ``all_checks`` or ``true_or_false`` function, then every time the ``_check_for_apocalypse`` function is called, those methods will be re-run and the latest data will be pushed to the clients if the results have changed

So let's test out these methods in the REPL by running ``./env/bin/python`` from the top-level Sideboard directory (*not* your top-level plugin directory):

>>> import sideboard
>>> from ragnarok import service
>>> service._check_for_apocalypse()
>>> service.all_checks()
{u'http://hastheworldendedyet.com': False, u'http://hasthelargehadroncolliderdestroyedtheworldyet.com': False}
>>> service.true_or_false()
False

We've already exposed our service (see the ``services.register`` line in ``ragnarok/__init__.py``), so now when we run Sideboard, other people will be able to call our publicly exposed functions.



Making a Website
----------------

So let's make a webpage that actually displays this information.  Open the file ``ragnarok/__init__.py`` and replace the ``Root`` class with the following:

.. code-block:: python

    @render_with_templates(config['template_dir'], restricted=True)
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
            <h1>$(( apocalypse ))$</h1>
            $(% for website, latest in all_checks.items() %)$
                <h2>$(( website ))$ - $(( latest ))$</h2>
            $(% endfor %)$
        </body>
    </html>

So now we can go back to `<http://localhost:8282/ragnarok/>`_ and see a summary of our end-of-the-world checks.  A few things to note about our latest code:

* Our site is now password-protected with your LDAP creds; we got this by adding the ``restricted=True`` keyword argument to the ``@render_with_templates`` decorator

* We return a dictionary from our page handler; since the page handler is called ``index``, the dictionary it returns is used to render the ``index.html`` `jinja template <http://jinja.pocoo.org/>`_ in our configured templates directory

* Notice that the jinja template tokens are not the default; they have been swapped out so that they do not conflict with `angular <http://angularjs.org/>`_ which is our Javascript framework of choice

So let's make this extra-dynamic; we'll use websockets to subscribe to our service so that anytime our data changes, we'll automatically get an update:

.. code-block:: html

    <!doctype html>
    <html>
        <head>
            <title>Ragnarok Aggregation</title>
            <script type="text/javascript" src="/static/websockets.js"></script>
            <script type="text/javascript">
                SocketManager.subscribe({
                    method: "ragnarok.true_or_false",
                    callback: function(world_ended) {
                        document.getElementById("ended").innerHTML = world_ended;
                    }
                });
                SocketManager.subscribe({
                    method: "ragnarok.all_checks",
                    callback: function(websites) {
                        var html = "";
                        for(var url in websites) {
                            html += "<h2>" + url + " => " + websites[url] + "</h2>";
                        }
                        document.getElementById("websites").innerHTML = html;
                    }
                });
            </script>
        </head>
        <body>
            <h1 id="ended"></h1>
            <div id="websites"></div>
        </body>
    </html>

So now we're using our exposed service by using the ``/static/websockets.js`` Javascript library which is included with Sideboard.  Now we can leave this webpage open and anytime our data changes, the latest info on whether the world has ended will automatically be pushed out to us.

Since this is our only plugin, we'd probably like this webpage to be the defauly page for this Sideboard site, so let's open our plugin's ``sideboard/configspec.ini`` and add the following line:

.. code-block:: none

    default_url = string(default="/ragnarok")

So now if we re-start our web server by re-running ``./env/bin/python sideboard/run_server.py`` and go to `<http://localhost:8282/>`_



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
    
        exposes everything in a module (or any object with callable functions)
    
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

We use websockets as the default RPC mechanism, but you can also use Jsonrpc as a fallback, using the .jsonrpc attribute of sideboard.lib.services.  You can also configure a service to ONLY use jsonrpc using the ``jsonrpc_only`` config value in the subsection for that host; you probably shouldn't do that unless you're connecting to a non-Sideboard service.

>>> from sideboard.lib import services
>>> services.foo.some_func()          # uses websockets
'Hello World!'
>>> services.foo.jsonrpc.some_func()  # uses jsonrpc
'Hello World!'
>>> services.weather.some_func()      # uses jsonrpc



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

.. class:: WebSocket([url[, ssl_opts={}]])
    
    Class representing a persistent websocket connection to the specified url (or connecting to this sideboard instance on localhost if necessary), with an option dictionary of extra keyword arguments to be passed to ssl.wrap_socket, typically client cert parameters.
    
    Instantiating a WebSocket object immediately starts two threads:
    
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
        
        This method raises an exception if 10 seconds pass without a response, or if we receive an error response to our RPC message.
        
        :param method: the name of the method to call; you may pass either positional or keyword arguments (but not both) to this method which will be sent as part of the RPC message
    
    .. method:: subscribe(callback, method, *args, **kwargs)
        
        Send an RPC message to subscribe to a method.
        
        This method is safe to call even if the underlying socket is not active; in this case we will log a warning and send the message as the connection is successfully [re-]established.
        
        :param callback: This can be either a function taking a single argument (the data returned by the method) or a dictionary with the following keys:
        
                         * *callback* (required): a function taking a single argument; this is called every time we receive data back from the server
        
                         * *errback* (required): a function taking a single argument; this is called every time we recieve an error response from the server and passed the error message
        
                         * *client* (optional): the client id to use; this will be automatically generated, and you should omit this unless you really know what you're doing
        
        :param method: the name of the method you want to subscribe to; you may pass either positional or keyword arguments (but not both) to this method which will be sent as part of the RPC message
        :returns: the automatically generated client id; you can pass this to ``unsubscribe`` if you want to keep this connection open but cancel this one subscription
    
    .. method:: unsubscribe(client)
        
        Send a message to the server indicating that you no longer want to be subscribed to any channels on the specified client.
        
        :param client: the client id being unsubscribed; this is whatever was returned from the ``subscribe`` method
    
    .. method:: close()
        
        Closes this connection safely; any errors will be logged and swallowed, so this method will never raise an exception.  Both daemon threads are stopped.
        
        Once this method is called, there is no supported way to re-open this websocket object; if you want to re-establish your connection to the same url, you'll need to instantiate a new ``WebSocket`` object.
    
    .. attribute:: connected
        
        boolean indicating whether or not this connection is currently active


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



Background Tasks
^^^^^^^^^^^^^^^^

One of the most common things our web applications want to do is run tasks in the background.  This can include either tasks which are performed once when the server starts (e.g. initializing the database), or running background tasks which periodically perform some action.

When we refer to "Sideboard starting" and "Sideboard stopping" we are referring specifically to when Sideboard starts its CherryPy server; this happens after all plugins have been imported, so you can safely call into other plugins in these tasks and functions.


.. function:: on_startup(func[, priority=50])
    
    Cause a function to get called on startup.  You can use this as a decorator, or directly call it and pass a priority level which indicates the order in which the startup functions should be called.
    
    .. code-block:: python
    
        @on_startup
        def f():
            print("Hello World!")
        
        def g():
            print("Hello Kitty!")
        
        on_startup(g, priority=40)
    
    :param func: The function to be called on startup; this function must be callable with no arguments.
    :param priority: Order in which startup functions will be called (lower priority items are called first); this can be any integer and the numbers are used for nothing other than ordering the handlers.


.. function:: on_shutdown(func[, priority=50])
    
    Cause a function to get called on startup; this is invoked in exactly the same way as ``on_startup``
    
    :param func: The function to be called on shutdown; this function must be callable with no arguments.
    :param priority: Order in which shutdown functions will be called (lower priority items are called first); this can be any integer and the numbers are used for nothing other than ordering the handlers.


.. attribute:: stopped

    ``threading.Event`` which is reset when Sideboard starts and set when it stops; this may be useful with infinitely looping and sleeping in background tasks


.. class:: DaemonTask(func[, threads=1[, start_now=False]])
    
    This utility class lets you run a function periodically in the background.  This background thread starts and stops automatically when Sideboard starts and stops.  Exceptions are automatically caught and logged.
        
    :param func: the function to be executed in the background; this must be callable with no arguments
    :param interval: the number of seconds to wait between function invocations
    :param threads: the number of threads which will call this function; sometimes you may want a pool of threads all calling the same function
    :param start_now: if truthy, start the pool of threads immediately instead of waiting for Sideboard to start; this is unlikely to be what you want, so only pass this if you have a really good reason

    .. method:: start()
    
    .. method:: stop()


.. class:: TimeDelayQueue([start_now=False])

    Subclass of `Queue.Queue <http://docs.python.org/2/library/queue.html#Queue.Queue>`_ which adds an optional ``delay`` parameter to the ``put`` method which does not add the item to the queue until after the specified amount of time.  This is used internally but is included in our public API in case it's useful to anyone else.

    .. method:: put(item[, block=True[, timeout=None[, delay=0]]]):
    
        Identical to `Queue.put() <http://docs.python.org/2/library/queue.html#Queue.Queue.put>`_ except that there's an extra delay argument; if nonzero then the ``item`` will be added to the queue after ``delay`` seconds.  This method will still return immediately; the item will be added in a background thread.


.. class:: Caller(func[, threads=1[, start_now=False]])

    Utility class allowing code to call the provided function in a separate pool of threads.  For example, if you need to call a long-running function in the handler for an HTTP request, you might want to just kick off the method in a background thread so that you can return from the page handler immediately.
    
    >>> caller = Caller(long_running_func)
    >>> caller.start()
    >>> caller.defer('arg1', arg2=True)        # called immediately (in another thread)
    >>> caller.delay(5, 'argOne', arg2=False)  # called after a 5 second delay (in another thread)

    :param func: the function to be executed in the background; this must be callable with no arguments
    :param threads: the number of threads which will call this function; sometimes you may want a pool of threads all calling the same function
    :param start_now: if truthy, start the pool of threads immediately instead of waiting for Sideboard to start; this is unlikely to be what you want, so only pass this if you have a really good reason

    .. method:: start()
    
    .. method:: stop()
    
    .. method:: defer(*args, **kwargs)
    
    .. method:: delay(seconds, *args, **kwargs)


.. class:: GenericCaller([threads=1[, start_now=False]])

    Like the ``Caller`` class above, except that instead of calling the same method with provided arguments, this lets you spin up a pool of background threads which will call any methods you specify, e.g.
    
    >>> from __future__ import print_function
    >>> gc = GenericCaller()
    >>> gc.defer(print, 'Hello', 'World', sep=', ', end='!')     # prints "Hello, World!"
    >>> gc.delay(5, print, 'Hello', 'World', sep=', ', end='!')  # prints "Hello, World!" after 5 seconds

    :param threads: the number of threads which will call this function; sometimes you may want a pool of threads all calling the same function
    :param start_now: if truthy, start the pool of threads immediately instead of waiting for Sideboard to start; this is unlikely to be what you want, so only pass this if you have a really good reason



Miscellaneous
^^^^^^^^^^^^^

.. attribute:: log
    
    ``logging.Logger`` subclass which automatically adds module / class / function names to the log messages.  Plugins should always import and use this logger instead of defining their own or using ``logging.getLogger()``.


.. function:: listify(x)

    returns a list version of x if x is a listy iterable, otherwise returns a list with x as its only element, for example:
    
    .. code-block:: none
    
        listify(5)       => [5]
        listify('hello') => ['hello']
        listify([5, 6])  => [5, 6]
        listify((5,))    => [5]


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
    
    .. classmethod:: get_client()
        
        Returns the websocket client id used to make this request, or None if not applicable.  This value may be present in both websocket and jsonrpc requests; in the latter case it would be present as the ``websocket_client`` key of the request, e.g. a jsonrpc request that looks like this:
        
        .. code-block:: python
        
            {
                "jsonrpc": "2.0",
                "id": "106893",
                "method": "feeds.set_weather_location",
                "params": ["20191"],
                "websocket_client": "client-623"
            }


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

Sideboard has a lot of great test helpers to make it easier to write unit tests for your plugins.

They're really awesome.

They're also not documented yet.
