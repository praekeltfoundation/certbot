import cgi

from requests.exceptions import HTTPError

from twisted.logger import LogLevel, Logger

from uritools import uricompose, uridecode, urisplit

from marathon_acme.clients._tx_util import default_client


def get_single_header(headers, key):
    """
    Get a single value for the given key out of the given set of headers.

    :param twisted.web.http_headers.Headers headers:
        The set of headers in which to look for the header value
    :param str key:
        The header key
    """
    raw_headers = headers.getRawHeaders(key)
    if raw_headers is None:
        return None

    # Take the final header as the authorative
    header, _ = cgi.parse_header(raw_headers[-1])
    return header


def raise_for_status(response):
    """
    Raises a `requests.exceptions.HTTPError` if the response did not succeed.
    Adapted from the Requests library:
    https://github.com/kennethreitz/requests/blob/v2.8.1/requests/models.py#L825-L837
    """
    http_error_msg = ''

    if 400 <= response.code < 500:
        http_error_msg = '%s Client Error for url: %s' % (
            response.code, uridecode(response.request.absoluteURI))

    elif 500 <= response.code < 600:
        http_error_msg = '%s Server Error for url: %s' % (
            response.code, uridecode(response.request.absoluteURI))

    if http_error_msg:
        raise HTTPError(http_error_msg, response=response)

    return response


def raise_for_header(response, key, expected):
    header = get_single_header(response.headers, key)
    if header is None:
        raise HTTPError('Expected header "%s" to be "%s" but header not found '
                        'in response' % (key, expected,))

    if header != expected:
        raise HTTPError('Expected header "%s" to be "%s" but found "%s" '
                        'instead' % (key, expected, header,))

    return response


class HTTPClient(object):
    DEFAULT_TIMEOUT = 5
    log = Logger()

    def __init__(self, url=None, client=None, timeout=DEFAULT_TIMEOUT,
                 reactor=None):
        """
        Create a client with the specified default URL.
        """
        self.url = url
        self._timeout = timeout
        # Keep track of the reactor because treq uses it for timeouts in a
        # clumsy way
        self._client, self._reactor = default_client(reactor, client)

    def _log_request_response(self, response, method, path, kwargs):
        self.log.debug(
            '{method} {path} with args {args} returned: {code}',
            method=method, path=path, args=kwargs, code=response.code)
        return response

    def _log_request_error(self, failure, url):
        self.log.failure('Error performing request to url "{url}"', failure,
                         LogLevel.error, url=url)
        return failure

    def _compose_url(self, url, kwargs):
        """
        Compose a URL starting with the given URL (or self.url if that URL is
        None) and using the values in kwargs.

        :param str url:
            The base URL to use. If None, ``self.url`` will be used instead.
        :param dict kwargs:
            A dictionary of values to override in the base URL. Relevant keys
            will be popped from the dictionary.
        """
        if url is None:
            url = self.url

        if url is None:
            raise ValueError(
                'url not provided and this client has no url attribute')

        split_result = urisplit(url)
        userinfo = split_result.userinfo

        # Build up the kwargs to pass to uricompose
        compose_kwargs = {}
        for key in ['scheme', 'host', 'port', 'path', 'fragment']:
            if key in kwargs:
                compose_kwargs[key] = kwargs.pop(key)
            else:
                compose_kwargs[key] = getattr(split_result, key)

        if 'params' in kwargs:
            compose_kwargs['query'] = kwargs.pop('params')
        else:
            compose_kwargs['query'] = split_result.query

        # Take the userinfo out of the URL and pass as 'auth' to treq so it can
        # be used for HTTP basic auth headers
        if 'auth' not in kwargs and userinfo is not None:
            # treq expects a 2-tuple (username, password)
            kwargs['auth'] = tuple(userinfo.split(':', 2))

        return uricompose(**compose_kwargs)

    def request(self, method, url=None, **kwargs):
        """
        Perform a request.

        :param: method:
            The HTTP method to use (example is `GET`).
        :param: url:
            The URL to use. The default value is the URL this client was
            created with (`self.url`) (example is `http://localhost:8080`)
        :param: kwargs:
            Any other parameters that will be passed to `treq.request`, for
            example headers. Or any URL parameters to override, for example
            path, query or fragment.
        """
        url = self._compose_url(url, kwargs)

        kwargs.setdefault('timeout', self._timeout)

        d = self._client.request(method, url, reactor=self._reactor, **kwargs)

        d.addCallback(self._log_request_response, method, url, kwargs)
        d.addErrback(self._log_request_error, url)

        return d
