from testtools.matchers import (
    AfterPreprocessing, Equals, IsInstance, MatchesAll, MatchesStructure,
    Mismatch
)
from testtools.twistedsupport import failed


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


def WithErrorTypeAndMessage(error_type, message):
    """
    Check that a Twisted failure was caused by a certain error type with a
    certain message.
    """
    return MatchesAll(
        MatchesStructure(value=IsInstance(error_type)),
        AfterPreprocessing(lambda f: f.getErrorMessage(), Equals(message))
    )
