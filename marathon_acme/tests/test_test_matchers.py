from testtools import TestCase
from testtools.content import text_content
from testtools.matchers import Equals, Is

from twisted.web.http_headers import Headers

from marathon_acme.tests.matchers import HasHeader


class TestHasHeader(TestCase):

    def test_header_present(self):
        """
        When the header key and values match, match() should return None.
        """
        matcher = HasHeader('test', ['abc', 'def'])
        match = matcher.match(Headers({'Test': ['abc', 'def']}))

        self.assertThat(match, Is(None))

    def test_header_key_not_present(self):
        """
        When the header key isn't present, match() should return a mismatch
        with the correct description and some details.
        """
        matcher = HasHeader('test', ['abc'])
        headers = Headers({'Something else': ['abc']})
        match = matcher.match(headers)

        self.assertThat(match.describe(),
                        Equals('The response does not have a "test" header'))
        headers_content = text_content(repr(dict(headers.getAllRawHeaders())))
        self.assertThat(match.get_details(),
                        Equals({'raw headers': headers_content}))

    def test_header_value_mismatch(self):
        """
        When the header has a different value to that expected, match() should
        return a mismatch.
        """
        matcher = HasHeader('test', ['abc'])
        match = matcher.match(Headers({'Test': ['abcd']}))

        self.assertThat(match.describe(),
                        Equals("['abcd'] != ['abc']"))

    def test_header_value_different_order(self):
        """
        When multiple values for the same header appear in a different order to
        that expected, match() should return a mismatch.
        """
        matcher = HasHeader('test', ['abc', 'def'])
        match = matcher.match(Headers({'Test': ['def', 'abc']}))

        self.assertThat(match.describe(),
                        Equals("['def', 'abc'] != ['abc', 'def']"))
