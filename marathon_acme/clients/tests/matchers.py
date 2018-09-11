from testtools.matchers import (
    AfterPreprocessing as After, Equals, MatchesStructure)

from uritools import urisplit


def HasRequestProperties(method, url, query=None):
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
    if query is None:
        query = {}
    return MatchesStructure(
        method=Equals(method.encode('ascii')),
        path=Equals(url.encode('ascii')),
        uri=After(lambda u: urisplit(u).getquerydict(), Equals(query))
    )
