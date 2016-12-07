import os

from fixtures import TempDir
from testtools import ExpectedException, run_test_with, TestCase
from testtools.assertions import assert_that
from testtools.matchers import Equals, MatchesStructure
from testtools.twistedsupport import (
    AsynchronousDeferredRunTest, flush_logged_errors)
from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks
from twisted.internet.error import CannotListenError, ConnectionRefusedError
from txacme.urls import LETSENCRYPT_STAGING_DIRECTORY

from marathon_acme.cli import main, parse_listen_addr


class TestCli(TestCase):
    # These are testtools-style tests so we can run aynchronous tests

    def test_storage_dir_required(self):
        """
        When the program is run with no arguments, it should exit with code 2
        because there is one required argument.
        """
        with ExpectedException(SystemExit, MatchesStructure(code=Equals(2))):
            main(reactor, raw_args=[])

    @inlineCallbacks
    @run_test_with(AsynchronousDeferredRunTest.make_factory(timeout=10.0))
    def test_storage_dir_provided(self):
        """
        When the program is run with an argument, it should start up and run.
        The program is expected to fail because it is unable to connect to
        Marathon.

        This test takes a while because we have to let txacme go through it's
        initial sync (registration + issuing of 0 certificates) before things
        can be halted.
        """
        temp_dir = self.useFixture(TempDir())
        yield main(reactor, raw_args=[
            temp_dir.path,
            '--acme', LETSENCRYPT_STAGING_DIRECTORY.asText(),
            '--marathon', 'http://localhost:28080'  # An address we can't reach
        ])

        # Expect a 'certs' directory to be created
        self.assertThat(os.path.isdir(temp_dir.join('certs')), Equals(True))

        # Expect a default certificate to be created
        self.assertThat(os.path.isfile(temp_dir.join('default.pem')),
                        Equals(True))

        # Expect to be unable to connect to Marathon
        flush_logged_errors(ConnectionRefusedError)

    @inlineCallbacks
    @run_test_with(AsynchronousDeferredRunTest.make_factory(timeout=5.0))
    def test_cannot_listen(self):
        """
        When the program is run with an argument and a listen address specified
        with a port that we can't listen on (e.g. port 1), a CannotListenError
        is expected to be logged and the program should stop.
        """
        temp_dir = self.useFixture(TempDir())
        yield main(reactor, raw_args=[
            temp_dir.path,
            '--listen', ':1',  # A port we can't listen on
        ])

        # Expect a 'certs' directory to be created
        self.assertThat(os.path.isdir(temp_dir.join('certs')), Equals(True))

        # Expect a default certificate to be created
        self.assertThat(os.path.isfile(temp_dir.join('default.pem')),
                        Equals(True))

        # Expect to be unable to listen
        flush_logged_errors(CannotListenError)


class TestParseListenAddr(object):
    def test_parse_no_colon(self):
        """
        When a listen address is parsed with no ':' character, an error is
        raised.
        """
        with ExpectedException(
            ValueError,
            r"'foobar' does not have the correct form for a listen address: "
                '\[ipaddress\]:port'):
            parse_listen_addr('foobar')

    def test_parse_no_ip_address(self):
        """
        When a listen address is parsed with no IP address, an endpoint
        description with the listen address's port but no interface is
        returned.
        """
        assert_that(parse_listen_addr(':8080'), Equals('tcp:8080'))

    def test_parse_ipv4(self):
        """
        When a listen address is parsed with an IPv4 address, an appropriate
        interface is present in the returned endpoint description.
        """
        assert_that(parse_listen_addr('127.0.0.1:8080'),
                    Equals('tcp:8080:interface=127.0.0.1'))

    def test_parse_ipv6(self):
        """
        When a listen address is parsed with an IPv4 address, an appropriate
        interface is present in the returned endpoint description.
        """
        assert_that(parse_listen_addr('[::]:8080'),
                    Equals('tcp6:8080:interface=\:\:'))

    def test_parse_invalid_ipaddress(self):
        """
        When a listen address is parsed with an invalid IP address, an error
        is raised.
        """
        with ExpectedException(
            ValueError,
                r"u?'hello' does not appear to be an IPv4 or IPv6 address"):
            parse_listen_addr('hello:8080')

    def test_parse_invalid_port(self):
        """
        When a listen address is parsed with an invalid port, an error is
        raised.
        """
        with ExpectedException(
                ValueError,
                r"'foo' does not appear to be a valid port number"):
            parse_listen_addr(':foo')

        with ExpectedException(
                ValueError,
                r"'0' does not appear to be a valid port number"):
            parse_listen_addr(':0')

        with ExpectedException(
                ValueError,
                r"'65536' does not appear to be a valid port number"):
            parse_listen_addr(':65536')

        with ExpectedException(
                ValueError,
                r"'' does not appear to be a valid port number"):
            parse_listen_addr(':')
