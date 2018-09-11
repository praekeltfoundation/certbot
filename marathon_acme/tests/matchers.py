from datetime import timedelta
from operator import methodcaller

from testtools.content import text_content
from testtools.matchers import AfterPreprocessing as After
from testtools.matchers import (
    Equals, GreaterThan, IsInstance, LessThan, MatchesAll, MatchesAny,
    MatchesStructure, Mismatch)


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
        return 'HasHeader(%s, %r)' % (self.key, self.expected,)

    def match(self, headers):
        """
        :param twisted.web.http_headers.Headers headers:
            The response or request headers object.
        """
        if not headers.hasHeader(self.key):
            headers_content = text_content(
                repr(dict(headers.getAllRawHeaders())))
            return Mismatch(
                'The response does not have a "%s" header' % (self.key,),
                details={'raw headers': headers_content})

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
        After(methodcaller('getErrorMessage'), Equals(message))
    )


def matches_time_or_just_before(time, tolerance=timedelta(seconds=10)):
    """
    Match a time to be equal to a certain time or just before it. Useful when
    checking for a time that is now +/- some amount of time.
    """
    return MatchesAll(
        GreaterThan(time - tolerance),
        MatchesAny(LessThan(time), Equals(time)))
