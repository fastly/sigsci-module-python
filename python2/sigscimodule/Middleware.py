"""
Signal Sciences module
Python 2.x
"""

from platform import python_version
import time
import logging
import socket
import random

from StringIO import StringIO as BytesBuffer

from urllib import quote

try:
    from sigsci.umsgpack import packb, unpackb
except BaseException:
    from .umsgpack import packb, unpackb

# wsgi
#  - http://www.giantflyingsaucer.com/blog/?p=4877
#  - http://blog.dscpl.com.au/2012/10/wsgi-middleware-and-hidden-write.html
#  - http://lucumr.pocoo.org/2007/5/21/getting-started-with-wsgi/
#
# msgpack
#  - https://github.com/vsergeev/u-msgpack-python
#
# socket
#  - https://docs.python.org/2/library/socket.html
#

VERSION = "1.4.1"


class Middleware(object):
    """
    SigSci Middleware Modules for Python 2
    """
    # pylint: disable=too-many-instance-attributes
    # pylint: disable=too-few-public-methods
    # pylint: disable=too-many-branches

    def __init__(
            self,
            application,
            agent_socket="/var/run/sigsci.sock",
            socket_timeout_millis=100,
            max_post_body=100000):
        self.application = application
        self.python_version = "python " + python_version()
        self.module_version = "sigsci-module-python " + VERSION

        # send back full data if...
        self.max_response_millis = 1000
        self.max_response_size = 524288

        # skip reading post body if too big
        self.max_post_size = max_post_body

        # todo, switch on socket type
        if len(agent_socket) == 2:
            # assume it is a tuple (ip, port)
            self.sock_family = socket.AF_INET
        else:
            # assume it is stringlike and unix domain socket
            self.sock_family = socket.AF_UNIX
        self.sock_address = agent_socket

        # convert back to seconds
        if socket_timeout_millis == 0:
            # we don't want 0 -- that means non-blocking
            socket_timeout_millis = 100
        self.sock_timeout = socket_timeout_millis / 1000.0

    def _get_socket(self):
        sock = socket.socket(self.sock_family)
        sock.settimeout(self.sock_timeout)
        return sock

    def _send_data(self, sock, rpcname, payload):
        sock.connect(self.sock_address)
        obj = [0, _get_rpcid(), rpcname, [payload]]
        rawsend = packb(obj)
        sock.sendall(rawsend)
        rawrecv = sock.recv(4096)
        recv = unpackb(rawrecv)
        if len(recv) != 4:
            logging.error("received corrupted reply from agent")
        return recv[3]

    def _send_rpc(self, rpcname, payload):
        resp = None
        sock = self._get_socket()
        try:
            resp = self._send_data(sock, rpcname, payload)
        except socket.error as exc:
            logging.warning("unable to send data for %s: %s", rpcname, exc)
        finally:
            sock.close()
        return resp

    def _is_anomalous(self, response):
        return response.status >= 300 or \
            response.bytesout > self.max_response_size or \
            response.millis > self.max_response_millis

    def __call__(self, environ, start_response):
        # time.time() unix seconds since epoch as a floating-point number
        start = time.time()

        rdata = {
            'AccessKeyID': '',
            'ModuleVersion': self.module_version,
            'ServerVersion': self.python_version,
            'ServerFlavor': '',
            'ServerName': _get_server_name(environ),
            'Timestamp': int(start),
            'NowMillis': int(start * 1000),
            'RemoteAddr': environ.get('REMOTE_ADDR', ''),
            'Method': environ['REQUEST_METHOD'],
            'Scheme': environ.get('wsgi.url_scheme', 'http'),
            'URI': _get_uri(environ),
            'Protocol': environ['SERVER_PROTOCOL'],
            'TLSProtocol': environ.get('SSL_PROTOCOL', ''),
            'TLSCipher': environ.get('SSL_CIPHER', ''),
            'HeadersIn': _get_request_headers(environ),
            'PostBody': _get_post_body(environ, self.max_post_size),
        }

        resp = self._send_rpc("RPC.PreRequest", rdata)

        # fail open due to errors
        if resp is None:
            logging.warning("allowing original request to pass")
            iterable = None
            try:
                iterable = self.application(environ, start_response)
                for data in iterable:
                    yield data
            except GeneratorExit:
                return
            if hasattr(iterable, 'close'):
                iterable.close()
            return

        # to simplify code later on
        rdata['RequestID'] = resp.get('RequestID', '')

        # don't save this, it's big and we don't need it later on
        rdata['PostBody'] = ''

        waf_resp = resp['WAFResponse']
        # 'RequestHeaders': [['X-SigSci-Tags', 'FOO'], ['X-Sigsci-Redirect', '']]

        # if is block code
        if 300 <= waf_resp <= 599:

            # send update to agent
            update = {
                'RequestID': rdata['RequestID'],
                'ResponseCode': waf_resp,
                'ResponseSize': 0,
                'ResponseMillis': _get_duration(start),
                'HeadersOut': [],
            }
            self._send_rpc("RPC.UpdateRequest", update)

            headers = []

            # if is redirect code (300 - 399)
            if waf_resp <= 399:
                location = ''
                for k, v in resp['RequestHeaders']:
                    if k == 'X-Sigsci-Redirect':
                        location = v
                        break

                if location != '':
                    headers = [('Location', location)]

            # block request
            start_response(str(waf_resp) + ' NOT ACCEPTABLE', headers)

            return

        # if we got a response and it's not 200 or 300-599, log and fail open
        if waf_resp != 200:
            logging.info(
                "Received unknown waf response code from agent: " +
                str(waf_resp))

        # set fake request headers from agent response
        # so app can see what happened
        _set_request_headers(environ, resp)

        response = ResponseData()

        def wrap_start_response(status, headers):
            """
            captures status and response headers
            """
            response.status = int(status[0:3])
            response.headers = headers
            return start_response(status, headers)
            # write = start_response(status, headers, exc_info)
            # def _write(data): write(data)
            # return _write

        appiter = None
        try:
            appiter = self.application(environ, wrap_start_response)
            for data in appiter:
                response.bytesout += len(data)
                yield data
        except GeneratorExit:
            return

        if hasattr(appiter, 'close'):
            appiter.close()
        response.millis = _get_duration(start)

        rpcname = None
        if rdata['RequestID'] != '':
            # we have been asked to send response data
            rpcname = "RPC.UpdateRequest"
            updatedata = {}
        elif self._is_anomalous(response):
            # slightly abnormal behavior.. send it all back again
            rpcname = "RPC.PostRequest"
            updatedata = rdata
            updatedata["WAFResponse"] = waf_resp
        else:
            # NORMAL!
            return

        # need to send an update
        # fill in data structure with response stuff
        updatedata['RequestID'] = rdata['RequestID']
        updatedata['ResponseCode'] = response.status
        updatedata['ResponseSize'] = response.bytesout
        updatedata['ResponseMillis'] = response.millis
        updatedata['HeadersOut'] = response.headers
        self._send_rpc(rpcname, updatedata)
        # done!


def _valid_content_type(ctype):
    """
    returns True if content-type/mime-type is something that should be
    forwarded to the agent.
    """
    if ctype is None:
        return False
    ctype = ctype.lower()
    if ctype.startswith('application/x-www-form-urlencoded'):
        return True
    if ctype.startswith('multipart/form-data'):
        return True
    if ctype.startswith('application/graphql'):
        return True
    if 'json' in ctype or 'javascript' in ctype:
        return True
    if 'xml' in ctype:
        return True
    return False


def _get_rpcid():
    # may need to use a lock or other mechanism
    # using 31 bits so it fits in normal word and msgpack and
    # not using python's arbitrary long integer type
    return int(random.getrandbits(31))


def _get_duration(start):
    now = time.time()
    millis = int((now - start) * 1000)
    # might happen due to non-monotonic clocks, NTP drift,....
    if millis < 0:
        millis = 0
    return millis


def _get_request_headers(environ):
    """
    converts WSGI headers back into normal HTTP headers
    """
    request_headers = []
    for key in environ:
        if key.startswith("HTTP_"):
            request_headers.append(
                (key[5:].replace('_', '-').lower(), environ[key]))
    if environ.get('CONTENT_TYPE'):
        request_headers.append(('content-type', environ["CONTENT_TYPE"]))
    if environ.get('CONTENT_LENGTH'):
        request_headers.append(('content-length', environ["CONTENT_LENGTH"]))
    return request_headers


def _get_server_name(environ):
    """
    attempts to determine server name via WSGI
    """
    if environ.get('HTTP_HOST'):
        return environ['HTTP_HOST']
    return environ['SERVER_NAME']


def _get_uri(environ):
    """
    reconstruct URI from WSGI
    """
    uri = quote(environ.get('SCRIPT_NAME', ''))
    uri += quote(environ.get('PATH_INFO', ''))
    if environ.get('QUERY_STRING'):
        uri += '?' + environ['QUERY_STRING']
    return uri


def _get_post_body(environ, max_len):
    try:
        content_length = int(environ.get('CONTENT_LENGTH', '-1'))
        if content_length <= 0 or content_length > max_len:
            return ""
    except ValueError:
        return ""

    if not _valid_content_type(environ.get('CONTENT_TYPE', '')):
        return ""

    body = environ["wsgi.input"].read(content_length)
    if hasattr(environ["wsgi.input"], 'close'):
        environ["wsgi.input"].close()
    environ["wsgi.input"] = BytesBuffer(body)
    return body


def _set_request_headers(environ, resp):
    """
    Using the agent response, set various 'fake' request headers
    to provide info on what happened to the application
    """
    # add standard info headers
    # transform to wsgi format with HTTP_ prefix
    # and all "-" --> "_"
    environ["HTTP_X_SIGSCI_REQUESTID"] = str(resp.get('RequestID', ''))
    environ["HTTP_X_SIGSCI_AGENTRESPONSE"] = str(resp['WAFResponse'])

    # add any extra headers
    if 'RequestHeaders' in resp:
        for kvpair in resp['RequestHeaders']:
            name = str('HTTP_' + kvpair[0].replace("-", "_").upper())
            environ[name] = str(kvpair[1])


# hack to work around closure
# work around python's lack of closures
# https://stackoverflow.com/questions/4020419/why-arent-python-nested-functions-called-closures
# not quite right but simple explanation:
#  python nested functions can read outer variables
#  but not write out variables if they are a primitive type
#  wrapping the int value in array allows the reference to be
#  read and written to.
# https://stackoverflow.com/questions/15148496/python-passing-an-integer-by-reference


class ResponseData(object):  # pylint: disable=too-few-public-methods
    """
    data to capture in the HTTP response
    """

    def __init__(self):
        self.headers = []
        self.bytesout = 0
        self.status = 0
        self.millis = 0
