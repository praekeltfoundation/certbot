import pytest
from testtools import ExpectedException
from testtools.matchers import Equals, MatchesStructure
from twisted.internet.task import Clock

from marathon_acme.cli import main


class TestCli(object):
    def test_storage_dir_required(self):
        """
        When the program is run with no arguments, it should exit with code 2
        because there is one required argument.
        """
        with ExpectedException(SystemExit, MatchesStructure(code=Equals(2))):
            main(Clock(), raw_args=[])

    @pytest.mark.skip(reason='if we run this...too much happens')
    def test_storage_dir_provided(self):
        """
        When the program is run with an argument, it should run successfully.
        """
        main(Clock(), raw_args=['/var/lib/marathon-acme'])
