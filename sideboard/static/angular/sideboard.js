
angular.module('sideboard', [])
    .factory('WebSocketService', function ($q, $log, $window, $timeout, $rootScope) {
        var self = {
            WS_URL: ($window.location.protocol === 'https:' ? 'wss' : 'ws') + '://' + $window.location.host + '/ws',

            CONNECTING: WebSocket.CONNECTING,
            OPEN:       WebSocket.OPEN,
            CLOSING:    WebSocket.CLOSING,
            CLOSED:     WebSocket.CLOSED,

            POLL_TIMEOUT: 3000,
            POLL_INTERVAL: 30000,
            CALL_TIMEOUT: 10000,

            currReconnectWait: 1000,
            MIN_RECONNECT_WAIT: 1000,
            MAX_RECONNECT_WAIT: 30000,

            requests: {},

            currId: 1,
            nextId: function () {
                return self.currId++;
            },

            objectify: function (x) {
                return typeof(x) === 'string' ? {client: x} :
                       angular.isObject(x) && !angular.isArray(x) ? x : {};
            },

            removeIgnoredField: function (request, field) {
                if (request[field]) {
                    $log.warn('ignoring "' + field + '" field in WebSocket RPC request');
                }
                delete request[field];
            },

            normalizeRequest: function (request, opts) {
                opts = opts || {};
                request = angular.extend({
                    error: opts.error || angular.identity,
                    callback: opts.callback || angular.identity
                }, self.objectify(request));
                if (opts.single) {
                    self.removeIgnoredField(request, 'client');
                    request.callbackId = request.callbackId || ('callback-' + self.nextId());
                } else {
                    self.removeIgnoredField(request, 'callbackId');
                    request.client = request.client || ('client-' + self.nextId());
                }
                return request;
            },

            getStatus: function() {
                if (self.ws) {
                    return self.ws.readyState;
                } else {
                    return self.CLOSED;
                }
            },
            getStatusString: function() {
                return self.isConnecting() ? 'CONNECTING' :
                       self.isOpen()       ? 'OPEN'       :
                       self.isClosing()    ? 'CLOSING'    : 'CLOSED';
            },
            isOpen:       function () { return self.getStatus() === self.OPEN; },
            isConnecting: function () { return self.getStatus() === self.CONNECTING; },
            isClosing:    function () { return self.getStatus() === self.CLOSING; },
            isClosed:     function () { return self.getStatus() === self.CLOSED; },

            onNext: function (eventName, callback) {
                var un = $rootScope.$on('WebSocketService.' + eventName, function () {
                    try {
                        callback();
                    } catch(ex) {
                        $log.error('error invoking', eventName, 'callback', ex);
                    }
                    un();
                });
            },

            poll: function () {
                self.call({
                    method: 'sideboard.poll',
                    timeout: self.POLL_TIMEOUT
                }).then(self.schedulePoll, function () {
                    $log.error('closing websocket due to poll failure; will attempt to reconnect');
                    self.close(1002, 'poll failed');
                    self.connect();
                });
            },
            schedulePoll: function () {
                self.stopPolling();
                self._poller = $timeout(self.poll, self.POLL_INTERVAL);
            },
            stopPolling: function () {
                $timeout.cancel(self._poller);
            },

            _connect: function () {
                self.ws = new WebSocket(self.WS_URL);
                self.ws.onopen = self.onOpen;
                self.ws.onclose = self.onClose;
                self.ws.onerror = self.onError;
                self.ws.onmessage = self.onMessage;
            },
            connect: function(callback) {
                callback = callback || angular.noop;
                if (self.isConnecting()) {
                    self.onNext('open', callback);
                } else if (self.isClosing()) {
                    self.onNext('close', function () {
                        self.connect(callback);
                    });
                } else if (self.isClosed()) {
                    self._connect();
                    self.onNext('open', callback);
                } else if (self.isOpen()) {
                    callback();
                } else {
                    $log.error('Error which should never happen: websocket is in an unknown state', self.getStatus());
                }
            },

            close: function (code, reason) {
                if (self.ws) {
                    try {
                        if (!self.isClosed()) {
                            self.ws.onopen = self.ws.onclose = self.ws.onerror = self.ws.onmessage = null;
                            self.ws.close(code || 1000, reason || 'manual close');
                        }
                        self.onClose();
                    } catch (ex) {
                        $log.error('error calling close on', self.getStatusString(), 'websocket', ex);
                    }
                    delete self.ws;
                }
            },

            refireSubscriptions: function () {
                angular.forEach(self.requests, function (request) {
                    if (request.method && request.client) {
                        self.send(request);
                    }
                });
            },

            onOpen: function () {
                self.currReconnectWait = self.MIN_RECONNECT_WAIT;
                self.schedulePoll();
                self.refireSubscriptions();
                $rootScope.$broadcast('WebSocketService.open');
            },
            onError: function (event) {
                $log.error('websocket error', event);
                self.close();
            },
            onClose: function () {
                self.stopPolling();
                $timeout(self.connect, self.currReconnectWait);
                self.currReconnectWait = Math.min(self.MAX_RECONNECT_WAIT, 2 * self.currReconnectWait);
                $rootScope.$broadcast('WebSocketService.close');
            },
            onMessage: function (event) {
                var json;
                try {
                    json = JSON.parse(event.data || 'null');
                } catch (ex) {
                    $log.error('websocket message parse error', event, ex);
                    return;
                }
                if (!json || !angular.isObject(json)) {
                    $log.error('websocket message parsed to a non-object', json);
                } else {
                    self.handleMessage(json);
                }
            },

            handleMessage: function (message) {
                var request = self.requests[message.client || message.callback];
                if (request) {
                    $log.debug('websocket received', message);
                    var funcAttr = message.error ? 'error' : 'callback',
                        dataAttr = message.error ? 'error' : 'data';
                    try {
                        request[funcAttr](message[dataAttr]);
                    } catch(ex) {
                        $log.error('Error executing websocket', funcAttr, 'function:', ex);
                    }
                    if (request.callbackId) {
                        delete self.requests[request.callbackId];
                    }
                    $rootScope.$digest();
                } else {
                    $log.error('unknown client and/or callback id', message);
                }
            },

            send: function(request) {
                if (request.method && (request.client || request.callbackId)) {
                    self.requests[request.client || request.callbackId] = request;
                }
                var message = JSON.stringify({
                    action: request.action,
                    method: request.method,
                    params: request.params,
                    client: request.client,
                    callback: request.callbackId
                });
                $log.debug('websocket send', message);
                self.ws.send(message);
            },
            connectAndSend: function (request) {
                self.connect(function () {
                    self.send(request);
                });
            },

            subscribe: function(request) {
                request = self.normalizeRequest(request, {single: false});
                if (request.method) {
                    self.connectAndSend(request);
                    return request.client;
                } else {
                    $log.error('"method" is a required field for WebSocketService.subscribe()');
                }
            },

            unsubscribe: function() {
                var clients = [];
                angular.forEach(arguments, function (request) {
                    request = self.objectify(request);
                    if (request.client && self.requests[request.client]) {
                        if (request.callback) {
                            $log.warn('ignoring callback field, which is invalid for unsubscribe', request);
                        }
                        clients.push(request.client);
                        delete self.requests[request.client];
                    } else {
                        $log.error('Unsubscribe called with unknown client id', request);
                    }
                });
                if (self.isOpen() && clients.length) {
                    self.send({action: 'unsubscribe', client: clients});
                }
            },

            call: function(request) {
                if (typeof(request) === 'string') {
                    request = {
                        method: request,
                        params: Array.prototype.slice.call(arguments, 1)
                    };
                }
                request = self.objectify(request);
                var errorMessage = !request.method ? '"method" required for WebSocketService.call()' :
                                   request.callback ? '"callback" is not a valid field for WebSocketService.call()' :
                                   request.error ? '"error" is not a valid field for WebSocketService.call()' : null;
                if (!errorMessage) {
                    var deferred = $q.defer();
                    request = self.normalizeRequest(request, {
                        single: true,
                        error: deferred.reject,
                        callback: deferred.resolve
                    });
                    request.timeout = request.timeout || self.CALL_TIMEOUT;
                    var rejectAfterTimeout = $timeout(function () {
                        $log.error('no response received for', request.timeout, 'milliseconds', request);
                        deferred.reject('websocket call timed out');
                    }, request.timeout);
                    self.connectAndSend(request);
                    return deferred.promise.finally(function () {
                        $timeout.cancel(rejectAfterTimeout);
                        delete self.requests[request.callbackId];
                    });
                } else {
                    $log.error(errorMessage);
                    return $q.reject(errorMessage);
                }
            }
        };
        return self;
    });
