import json

from uritools import urisplit


def parse_query(uri):
    """
    Parse the query dict from the given URI. When Twisted parses "args" from
    the URI, it leaves out query parameters that have no value. In those cases
    we rather use uritools to parse the query parameters.
    """
    return urisplit(uri).getquerydict()


def read_json_response(request):
    """ Read JSON from the UTF-8 encoded body of the given request. """
    return json.loads(request.content.read().decode('utf-8'))


def write_json_response(request, json_data, response_code=200):
    """
    Write UTF-8 encoded JSON to the body of a request, set the Content-Type
    header and finish() the request.
    """
    request.setResponseCode(response_code)
    request.setHeader('Content-Type', 'application/json; charset=utf-8')
    request.write(json.dumps(json_data).encode('utf-8'))
    request.finish()
