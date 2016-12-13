from datetime import datetime, timedelta
from operator import methodcaller

from testtools.content import text_content
from testtools.matchers import AfterPreprocessing as After
from testtools.matchers import (
    Equals, GreaterThan, IsInstance, LessThan, MatchesAll, MatchesAny,
    MatchesDict, MatchesStructure, Mismatch)
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


def IsSseResponse():
    """
    Match a status code of 200 on a treq.response object and check that a
    header is set to indicate that the content type is an event stream.
    """
    return MatchesStructure(
        code=Equals(200),
        headers=HasHeader('Content-Type', ['text/event-stream'])
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
        uri=After(lambda u: urisplit(u).getquerydict(), Equals(query))
    )


def matches_time_or_just_before(time, tolerance=timedelta(seconds=10)):
    """
    Match a time to be equal to a certain time or just before it. Useful when
    checking for a time that is now +/- some amount of time.
    """
    return MatchesAll(
        GreaterThan(time - tolerance),
        MatchesAny(LessThan(time), Equals(time)))


def _parse_marathon_event_timestamp(timestamp):
    """ Parse Marathon's ISO8601-like timestamps into a datetime. """
    return datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%fZ')


def IsMarathonEvent(event_type, **kwargs):
    """
    Match a dict (deserialized from JSON) as a Marathon event. Matches the
    event type and checks for a recent timestamp.

    :param event_type: The event type ('eventType' field value)
    :param kwargs: Any other matchers to apply to the dict
    """
    matching_dict = {
        'eventType': Equals(event_type),
        'timestamp': After(_parse_marathon_event_timestamp,
                           matches_time_or_just_before(datetime.utcnow()))
    }
    matching_dict.update(kwargs)
    return MatchesDict(matching_dict)
