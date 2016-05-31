from datetime import datetime, timedelta

from testtools import TestCase
from testtools.matchers import Equals, Is, MatchesDict

from twisted.web.http_headers import Headers

from marathon_acme.tests.matchers import HasHeader, IsAroundTime


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
        match = matcher.match(Headers({'Something else': ['abc']}))

        self.assertThat(match.describe(),
                        Equals('The response does not have a "test" header'))
        self.assertThat(match.get_details(),
                        Equals({'raw headers': {b'Something else': [b'abc']}}))

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


class TestIsAroundTime(TestCase):
    def test_is_around_before(self):
        """
        When a timestamp is before the matcher's time and within the before
        delta, no mismatch should be returned.
        """
        ts = datetime.utcnow()
        matcher = IsAroundTime(ts, before_delta=timedelta(milliseconds=100))
        match = matcher.match(ts - timedelta(milliseconds=50))

        self.assertThat(match, Is(None))

    def test_is_not_around_before(self):
        """
        When a timestamp is before the matcher's time but not within the before
        delta, a mismatch should be returned.
        """
        ts = datetime.utcnow()
        actual_ts = ts - timedelta(milliseconds=100)
        matcher = IsAroundTime(ts, before_delta=timedelta(milliseconds=50))
        match = matcher.match(actual_ts)

        self.assertThat(match.describe(), Equals(
            '%s is not within 0.05s before %s. It is 0.1s before.' % (
                actual_ts.isoformat(), ts.isoformat())
        ))

        self.assertThat(match.details(), MatchesDict({
            'expected_datetime': Equals(ts),
            'actual_datetime': Equals(actual_ts),
            'expected_timedelta': Equals(timedelta(milliseconds=50)),
            'actual_timedelta': Equals(timedelta(milliseconds=100)),
        }))

    def test_is_around_after(self):
        """
        When a timestamp is after the matcher's time and within the after
        delta, no mismatch should be returned.
        """
        ts = datetime.utcnow()
        matcher = IsAroundTime(ts, after_delta=timedelta(milliseconds=100))
        match = matcher.match(ts + timedelta(milliseconds=50))

        self.assertThat(match, Is(None))

    def test_is_not_around_after(self):
        """
        When a timestamp is after the matcher's time but not within the after
        delta, a mismatch should be returned.
        """
        ts = datetime.utcnow()
        actual_ts = ts + timedelta(milliseconds=100)
        matcher = IsAroundTime(ts, after_delta=timedelta(milliseconds=50))
        match = matcher.match(actual_ts)

        self.assertThat(match.describe(), Equals(
            '%s is not within 0.05s after %s. It is 0.1s after.' % (
                actual_ts.isoformat(), ts.isoformat())
        ))

        self.assertThat(match.details(), MatchesDict({
            'expected_datetime': Equals(ts),
            'actual_datetime': Equals(actual_ts),
            'expected_timedelta': Equals(timedelta(milliseconds=50)),
            'actual_timedelta': Equals(timedelta(milliseconds=100)),
        }))

    def test_matcher_string(self):
        """ The matcher string should be correctly formatted. """
        ts = datetime(2016, 5, 31, 12, 57)
        matcher = IsAroundTime(ts, timedelta(seconds=12),
                               timedelta(seconds=34))

        self.assertThat(str(matcher), Equals(
            'IsAroundTime(2016-05-31 12:57:00, 0:00:12, 0:00:34)'))
