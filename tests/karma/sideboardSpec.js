
describe('WebSocketService', function () {
    beforeEach(module('sideboard'));

    var $log, $timeout, $rootScope, WebSocketService;
    beforeEach(inject(function (_$log_, _$timeout_, _$rootScope_, _WebSocketService_) {
        $log = _$log_;
        $timeout = _$timeout_;
        $rootScope = _$rootScope_;
        WebSocketService = _WebSocketService_;

        spyOn($log, 'warn');
        spyOn($log, 'error');
    }));
    afterEach(function () {
        delete WebSocketService.ws;
        WebSocketService.currId = 1;
        WebSocketService.results = {};
        WebSocketService.currReconnectWait = WebSocketService.MIN_RECONNECT_WAIT;
    });

    describe('objectify', function () {
        it('converts a string to an object whose client value is the string', function () {
            expect(WebSocketService.objectify('foo')).toEqual({client: 'foo'});
        });
        it('returns an object unmodified when passed an object', function () {
            expect(WebSocketService.objectify({foo: 5})).toEqual({foo: 5});
        });
        it('returns an empty object when passed a non-object', function () {
            angular.forEach([null, undefined, false, 0, true, 1, [], [1]], function (val) {
                expect(WebSocketService.objectify(val)).toEqual({});
            });
        });
    });

    describe('removeIgnoredField', function () {
        it('removes the specified field and logs a warning when the field is present', function () {
            var request = {foo: 1, bar: 2};
            WebSocketService.removeIgnoredField(request, 'foo');
            expect(request).toEqual({bar: 2});
            expect($log.warn).toHaveBeenCalled();
        });
        it('does nothing when the field is not present', function () {
            var request = {bar: 2};
            WebSocketService.removeIgnoredField(request, 'foo')
            expect(request).toEqual({bar: 2});
            expect($log.warn).not.toHaveBeenCalled();
        });
    });

    describe('normalizeRequest', function () {
        var f = function () { }, g = function () { };
        beforeEach(function () {
            this.addMatchers({
                toNormalizeTo: function (expected) {
                    var normalized = WebSocketService.normalizeRequest.apply(null, angular.isArray(this.actual) ? this.actual : [this.actual]);
                    angular.forEach(expected, function (val, key) {
                        expect(normalized[key]).toEqual(val);
                    });
                    return true;
                }
            });
        });
        it('assigns callback and client ids when not present', function () {
            expect([{}, {single: false}]).toNormalizeTo({client: 'client-1'});
            expect([{}, {single: true}]).toNormalizeTo({callbackId: 'callback-2'});
            expect([{client: 'xxx'}, {single: false}]).toNormalizeTo({client: 'xxx'});
            expect([{callbackId: 'yyy'}, {single: true}]).toNormalizeTo({callbackId: 'yyy'});
        });
        it('strips client ids from single requests and callback ids from subscription requests', function () {
            expect([{client: 'xxx'}, {single: true}]).toNormalizeTo({callbackId: 'callback-1', client: undefined})
            expect([{callbackId: 'yyy'}, {single: false}]).toNormalizeTo({client: 'client-2', callbackId: undefined});
        });
        it('sets defaults for the callback and error methods if not present', function () {
            expect({}).toNormalizeTo({callback: angular.identity, error: angular.identity});
            expect({callback: f, error: g}).toNormalizeTo({callback: f, error: g});
            expect([{}, {callback: f, error: g}]).toNormalizeTo({callback: f, error: g});
            expect([{callback: f, error: g}, {callback: angular.noop, error: angular.noop}]).toNormalizeTo({callback: f, error: g});
        });
    });

    describe('getStatus', function () {
        it('returns CLOSED if no websocket object exists', function () {
            expect(WebSocketService.getStatus()).toEqual(WebSocketService.CLOSED);
        });
        it('returns the websocket object readyState if we have a websocket instantiated', function () {
            WebSocketService.ws = {readyState: 999};
            expect(WebSocketService.getStatus()).toEqual(999);
        });
    });

    describe('onNext', function () {
        it('only invokes the callback the next time the event is broadcast', function () {
            var f = jasmine.createSpy();
            WebSocketService.onNext('foo', f);
            expect(f).not.toHaveBeenCalled();
            $rootScope.$broadcast('WebSocketService.foo');
            expect(f).toHaveBeenCalled();
            $rootScope.$broadcast('WebSocketService.foo');
            expect(f.callCount).toEqual(1);
            expect($log.error).not.toHaveBeenCalled();
        });
        it('catches and logs callback errors', function () {
            var f = function () { throw new Error(''); };
            WebSocketService.onNext('foo', f);
            expect($log.error).not.toHaveBeenCalled();
            $rootScope.$broadcast('WebSocketService.foo');
            expect($log.error).toHaveBeenCalled();
            $log.error.reset();
            $rootScope.$broadcast('WebSocketService.foo');
            expect($log.error).not.toHaveBeenCalled();
        });
    });

    describe('refireSubscriptions', function () {
        it('only refires requests with a method and client id', function () {
            WebSocketService.requests = [
                {action: 'someAction'},
                {method: 'foo.bar', client: 'xxx'},
                {method: 'foo.baz', callbackId: 'yyy'},
                {method: 'foo.baf', client: 'zzz'}
            ];
            spyOn(WebSocketService, 'send');
            WebSocketService.refireSubscriptions();
            expect(WebSocketService.send.callCount).toEqual(2);
            expect(WebSocketService.send).toHaveBeenCalledWith({method: 'foo.bar', client: 'xxx'});
            expect(WebSocketService.send).toHaveBeenCalledWith({method: 'foo.baf', client: 'zzz'});
        });
    });

    describe('send', function () {
        var neither = {method: 'x.y'}, client = {method: 'x.y', client: 'aaa'}, callback = {method: 'x.y', callbackId: 'bbb'},
            both = {method: 'x.y', client: 'ccc', callbackId: 'ddd'};
        beforeEach(function () {
            WebSocketService.ws = {send: jasmine.createSpy()};
            this.addMatchers({
                toHaveBeenSent: function () {
                    request = angular.copy(this.actual);
                    request.callback = request.callbackId;
                    delete request.callbackId;
                    expect(WebSocketService.ws.send).toHaveBeenCalledWith(JSON.stringify(request));
                    return true;
                }
            });
        });
        it('registers method request with its callback or client id', function () {
            angular.forEach([client, callback, neither, both], function (request) {
                WebSocketService.send(request);
                expect(request).toHaveBeenSent();
            });
            expect(WebSocketService.ws.send.callCount).toEqual(4);
            expect(WebSocketService.requests).toEqual({
                aaa: client,
                bbb: callback,
                ccc: both
            });
        });
        it('serializes all relevant fields and ignores irrelevant ones', function () {
            var relevant = {action: 1, method: 2, params: 3, client: 4, callback: 5};
            var request = angular.extend({irrelevant: 6}, relevant);
            WebSocketService.send(request);
            expect(relevant).toHaveBeenSent();
        });
    });

    describe('close', function () {
        var ws;
        beforeEach(function () {
            ws = WebSocketService.ws = {
                close: jasmine.createSpy(),
                readyState: WebSocketService.OPEN
            };
            spyOn(WebSocketService, 'onClose');
        });
        afterEach(function () {
            expect($log.error).not.toHaveBeenCalled();
        });
        it('passes default close options along to the underlying websocket', function () {
            WebSocketService.close(1, 'reason');
            expect(ws.close).toHaveBeenCalledWith(1, 'reason');
        });
        it('passes close options along to the underlying websocket', function () {
            WebSocketService.close();
            expect(ws.close).toHaveBeenCalledWith(1000, 'manual close');
        });
        it('unsets event handlers, deletes the ws attribute, and calls onClose()', function () {
            WebSocketService.close();
            expect(WebSocketService.ws).not.toBeDefined();
            expect(WebSocketService.onClose).toHaveBeenCalled();
            angular.forEach(['onopen', 'onclose', 'onmessage', 'onerror'], function (attr) {
                expect(ws[attr]).toBe(null);
            });
        });
        it('is safe to call when already closed', function () {
            WebSocketService.close();
            WebSocketService.close();
        });
        it('catches and logs errors', function () {
            ws.close = function () { throw new Error('fail'); };
            WebSocketService.close();
            expect($log.error).toHaveBeenCalled();
            $log.error.reset();
        });
    });

    describe('unsubscribe', function () {
        beforeEach(function () {
            spyOn(WebSocketService, 'send');
            WebSocketService.requests = {xxx: {}, zzz: {}};
            WebSocketService.ws = {readyState: WebSocketService.CLOSED};
        });
        afterEach(function () {
            expect($log.warn).not.toHaveBeenCalled();
            expect($log.error).not.toHaveBeenCalled();
        });
        it('logs an error when passed an invalid request', function () {
            angular.forEach([undefined, {}, 'yyy', {client: 'yyy'}, ['xxx']], function (val) {
                WebSocketService.unsubscribe(val);
                expect($log.error).toHaveBeenCalled();
                $log.error.reset();
            });
        });
        it('logs a warning when passed an object with a callback id', function () {
            WebSocketService.unsubscribe({client: 'xxx', callback: 'yyy'});
            expect($log.warn).toHaveBeenCalled();
            $log.warn.reset();
        });
        it('removes a subscription even when the websocket is closed', function () {
            WebSocketService.unsubscribe('xxx');
            expect(WebSocketService.requests.xxx).not.toBeDefined();
        });
        it('removes a subscription when passed a full request object', function () {
            WebSocketService.unsubscribe({client: 'xxx'});
            expect(WebSocketService.requests.xxx).not.toBeDefined();
        });
        it('sends an unsubscribe request to the server when connection is open', function () {
            angular.forEach(['CONNECTING', 'CLOSING', 'CLOSED'], function (attr) {
                WebSocketService.ws.readyState = WebSocketService[attr];
                WebSocketService.unsubscribe('xxx');
                WebSocketService.requests = {xxx: {}};
            });
            expect(WebSocketService.send).not.toHaveBeenCalled();
            WebSocketService.ws.readyState = WebSocketService.OPEN;
            WebSocketService.unsubscribe('xxx');
            expect(WebSocketService.send).toHaveBeenCalledWith({action: 'unsubscribe', client: ['xxx']});
        });
        it('sends multiple unsubscribe requests when passed multiple clients', function () {
            WebSocketService.ws.readyState = WebSocketService.OPEN;
            WebSocketService.unsubscribe('xxx', 'zzz');
            expect(WebSocketService.send).toHaveBeenCalledWith({action: 'unsubscribe', client: ['xxx', 'zzz']});
            expect(WebSocketService.requests).toEqual({});
        });
    });

    describe('subscribe', function () {
        beforeEach(function () {
            spyOn(WebSocketService, 'connectAndSend');
        });
        it('logs an error on requests without a method', function () {
            angular.forEach(['x.y', {}], function (request) {
                WebSocketService.subscribe(request);
                expect($log.error).toHaveBeenCalled();
                expect(WebSocketService.connectAndSend).not.toHaveBeenCalled();
            });
        });
        it('connects and calls send and returns the client', function () {
            var mockNormalized = {method: 'foo.bar', client: 'abc'};
            spyOn(WebSocketService, 'normalizeRequest').andReturn(mockNormalized);
            var client = WebSocketService.subscribe({method: 'x.y'});
            expect(WebSocketService.connectAndSend).toHaveBeenCalledWith(mockNormalized);
            expect(client).toEqual('abc');
        });
    });

    describe('call', function () {
        beforeEach(function () {
            WebSocketService.ws = {
                send: jasmine.createSpy(),
                readyState: WebSocketService.OPEN
            };
            this.addMatchers({
                toBeRejected: function () {
                    var fulfilled, rejected;
                    this.actual.then(function () {
                        fulfilled = true;
                    }, function () {
                        rejected = true;
                    });
                    $rootScope.$digest();
                    expect(rejected).toBeTruthy();
                    expect(fulfilled).not.toBeTruthy();
                    return true;
                },
                toBeFulfilledWith: function (expected) {
                    var fulfilled, rejected;
                    this.actual.then(function (result) {
                        fulfilled = result;
                    }, function () {
                        rejected = true;
                    });
                    $rootScope.$digest();
                    expect(rejected).not.toBeTruthy();
                    expect(fulfilled).toEqual(expected);
                    return true;
                }
            });
        });
        it('rejects its returned promise when given no method', function () {
            spyOn(WebSocketService, 'connectAndSend');
            var promise = WebSocketService.call({});
            expect($log.error).toHaveBeenCalled();
            expect(WebSocketService.connectAndSend).not.toHaveBeenCalled();
            expect(promise).toBeRejected();
        });
        angular.forEach(['callback', 'error'], function (attr) {
            it('rejects its returned promise when given a ' + attr + ' method', function () {
                spyOn(WebSocketService, 'connectAndSend');
                var request = {};
                request[attr] = angular.noop;
                var promise = WebSocketService.call(request);
                expect($log.error).toHaveBeenCalled();
                expect(WebSocketService.connectAndSend).not.toHaveBeenCalled();
                expect(promise).toBeRejected();
            });
        });
        it('connects and sends on a valid request', function () {
            spyOn(WebSocketService, 'connectAndSend');
            var mockNormalized = {callbackId: 'xxx'};
            spyOn(WebSocketService, 'normalizeRequest').andReturn(mockNormalized);
            WebSocketService.call('foo.bar');
            expect(WebSocketService.connectAndSend).toHaveBeenCalledWith(mockNormalized);
            expect($log.error).not.toHaveBeenCalled();
        });
        it('rejects its returned promise after timing out', function () {
            var promise = WebSocketService.call('foo.bar');
            $timeout.flush();
            expect(promise).toBeRejected();
            expect($log.error).toHaveBeenCalled();
        });
        it('cancels timeout after a successful response', function () {
            spyOn($timeout, 'cancel');
            var promise = WebSocketService.call('foo.bar');
            expect($timeout.cancel).not.toHaveBeenCalled();
            expect(WebSocketService.requests['callback-1'].timeout).toEqual(WebSocketService.CALL_TIMEOUT);
            WebSocketService.requests['callback-1'].callback({foo: 'bar'});
            expect(promise).toBeFulfilledWith({foo: 'bar'});
            expect($timeout.cancel).toHaveBeenCalled();
        });
        it('can override the default timeout', function () {
            WebSocketService.call({method: 'foo.bar', timeout: 12345});
            expect(WebSocketService.requests['callback-1'].timeout).toEqual(12345);
        });
    });

    describe('onMessage', function () {
        beforeEach(function () {
            spyOn(WebSocketService, 'handleMessage');
        });
        it('logs an error on invalid input', function () {
            angular.forEach([null, {data: null}, {data: 'null'}, {data: '1'}, {data: 1}, {data: 'not json'}], function (event) {
                WebSocketService.onMessage(event);
                expect(WebSocketService.handleMessage).not.toHaveBeenCalled();
                expect($log.error).toHaveBeenCalled();
                $log.error.reset();
            });
        });
        it('calls through to handleMessage on valid input', function () {
            WebSocketService.onMessage({data: '{"foo": "bar"}'});
            expect(WebSocketService.handleMessage).toHaveBeenCalledWith({foo: 'bar'});
            expect($log.error).not.toHaveBeenCalled();
        });
    });

    describe('handleMessage', function () {
        var call, subscription;
        beforeEach(function () {
            call = {
                callbackId: 'xxx',
                error: jasmine.createSpy(),
                callback: jasmine.createSpy()
            };
            subscription = {
                client: 'yyy',
                error: jasmine.createSpy(),
                callback: jasmine.createSpy()
            }
            WebSocketService.requests = {xxx: call, yyy: subscription};
        });
        it('logs an error on an unknown request', function () {
            WebSocketService.handleMessage({});
            expect($log.error).toHaveBeenCalled();
        });
        it('invokes callback when given data', function () {
            WebSocketService.handleMessage({callback: 'xxx', data: 'foo'});
            expect(call.callback).toHaveBeenCalledWith('foo');
            expect(call.error).not.toHaveBeenCalled();
            expect($log.error).not.toHaveBeenCalled();
        });
        it('invokes error handler when given an error', function () {
            WebSocketService.handleMessage({callback: 'xxx', data: 'foo', error: 'bar'});
            expect(call.callback).not.toHaveBeenCalled();
            expect(call.error).toHaveBeenCalledWith('bar');
            expect($log.error).not.toHaveBeenCalled();
        });
        it('catches and logs an exception on a callback error', function () {
            call.callback = function () { throw new Error('fail'); };
            WebSocketService.handleMessage({callback: 'xxx'});
            expect(call.error).not.toHaveBeenCalled();
            expect($log.error).toHaveBeenCalled();
        });
        it('unregisters a callback but not a subscription after dispatching', function () {
            WebSocketService.handleMessage({callback: 'xxx'});
            WebSocketService.handleMessage({client: 'yyy'});
            expect(call.callback).toHaveBeenCalled();
            expect(subscription.callback).toHaveBeenCalled();
            expect(WebSocketService.requests).toEqual({yyy: subscription});
        });
    });
});
