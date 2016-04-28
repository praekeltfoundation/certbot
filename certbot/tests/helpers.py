import json

import testtools

from testtools.twistedsupport import AsynchronousDeferredRunTest


class TestCase(testtools.TestCase):
    """ TestCase class for use with Twisted asynchornous tests. """
    run_tests_with = AsynchronousDeferredRunTest.make_factory(timeout=0.01)


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
