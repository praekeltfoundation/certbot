from datetime import datetime, timedelta

from testtools.matchers import (
    AfterPreprocessing, Equals, GreaterThan, IsInstance, LessThan, MatchesAll,
    MatchesAny, MatchesStructure, Mismatch
)

from uritools import urisplit


class HasHeader(Equals):
    def __init__(self, key, values):
        """
        Checks for a certain header with certain values in the headers of a
        response or request. Note that headers may be specified multiple times
        and that the order of repeated headers is important.

        :param str key:
            The header name/key.
        :param list values:
            The list of values for the header.
        """
        super(HasHeader, self).__init__(values)
        self.key = key

    def __str__(self):
        return 'HasHeader(%s, %r)' % (self.key, self.values,)

    def match(self, headers):
        """
        :param twisted.web.http_headers.Headers headers:
            The response or request headers object.
        """
        if not headers.hasHeader(self.key):
            return Mismatch(
                'The response does not have a "%s" header' % (self.key,),
                details={'raw headers': dict(headers.getAllRawHeaders())})

        raw_values = headers.getRawHeaders(self.key)
        return super(HasHeader, self).match(raw_values)


def IsJsonResponseWithCode(code):
    """
    Match the status code on a treq.response object and check that a header is
    set to indicate that the content type is JSON.
    """
    return MatchesStructure(
        code=Equals(code),
        headers=HasHeader('Content-Type', ['application/json'])
    )


def WithErrorTypeAndMessage(error_type, message):
    """
    Check that a Twisted failure was caused by a certain error type with a
    certain message.
    """
    return MatchesAll(
        MatchesStructure(value=IsInstance(error_type)),
        AfterPreprocessing(lambda f: f.getErrorMessage(), Equals(message))
    )


def HasRequestProperties(method=None, url=None, query={}):
    """
    Check if a HTTP request object has certain properties.

    Parses the query dict from the request URI rather than using the request
    "args" property as the args do not include query parameters that have no
    value.

    :param str method:
        The HTTP method.
    :param str url:
        The HTTP URL, without any query parameters. Should already be percent
        encoded.
    :param dict query:
        A dictionary of HTTP query parameters.
    """
    return MatchesStructure(
        method=Equals(method.encode('ascii')),
        path=Equals(url.encode('ascii')),
        uri=AfterPreprocessing(lambda u: urisplit(u).getquerydict(),
                               Equals(query))
    )


def IsBetween(minimum, maximum):
    """
    Match if a value is greater than or equal to minimum or less than or equal
    to maximum.
    """
    return MatchesAll(
        MatchesAny(GreaterThan(minimum), Equals(minimum)),
        MatchesAny(LessThan(maximum), Equals(maximum)))


def IsRecentMarathonTimestamp():
    """
    Match whether a Marathon timestamp string describes a time within the last
    second.
    """
    return AfterPreprocessing(
        lambda ts: datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S.%fZ'),
        IsBetween(datetime.utcnow() - timedelta(seconds=1),
                  datetime.utcnow()))
