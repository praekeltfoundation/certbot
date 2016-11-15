import os

from fixtures import TempDir
from testtools import ExpectedException, run_test_with, TestCase
from testtools.matchers import Equals, MatchesStructure
from testtools.twistedsupport import (
    AsynchronousDeferredRunTest, flush_logged_errors)
from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks
from twisted.internet.error import ConnectionRefusedError
from txacme.urls import LETSENCRYPT_STAGING_DIRECTORY

from marathon_acme.cli import main


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

        # Expect to be unable to connect
        flush_logged_errors(ConnectionRefusedError)
