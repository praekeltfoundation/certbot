from datetime import datetime, timedelta

from testtools.matchers import (
    AfterPreprocessing, Equals, IsInstance, MatchesAll, MatchesStructure,
    Mismatch
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


class IsAroundTime(object):
    """ Match if a timestamp is within a certain interval of a time. """
    def __init__(self, time, before_delta=timedelta(0),
                 after_delta=timedelta(0)):
        self.time = time
        self.before_delta = before_delta
        self.after_delta = after_delta

    def __str__(self):
        return 'IsAroundTime(%s, %s, %s)' % (self.time, self.before_delta,
                                             self.after_delta)

    def match(self, actual):
        if actual < self.time:
            before_delta = self.time - actual
            if before_delta > self.before_delta:
                return IsAroundTimeMismatch(
                    self.time, actual, self.before_delta, before_delta)
        elif actual > self.time:
            after_delta = actual - self.time
            if after_delta > self.after_delta:
                return IsAroundTimeMismatch(
                    self.time, actual, self.after_delta, after_delta)

        return None


class IsAroundTimeMismatch(object):
    def __init__(self, expected, actual, expected_td, actual_td):
        self.expected = expected
        self.actual = actual
        self.expected_td = expected_td
        self.actual_td = actual_td

    def describe(self):
        before_or_after = 'before' if self.actual < self.expected else 'after'
        return '%s is not within %ss %s %s. It is %ss %s.' % (
            self.actual.isoformat(),
            self.expected_td.total_seconds(),
            before_or_after,
            self.expected.isoformat(),
            self.actual_td.total_seconds(),
            before_or_after
        )

    def details(self):
        return {
            'expected_datetime': self.expected,
            'actual_datetime': self.actual,
            'expected_timedelta': self.expected_td,
            'actual_timedelta': self.actual_td
        }


def IsRecentMarathonTimestamp():
    """
    Match whether a Marathon timestamp string describes a time within the last
    second.
    """
    return AfterPreprocessing(
        lambda ts: datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S.%fZ'),
        IsAroundTime(datetime.utcnow(),
                     before_delta=timedelta(seconds=1)))
