from testtools import ExpectedException
from testtools.matchers import Equals, MatchesStructure

from marathon_acme.cli import main


class TestCli(object):
    def test_storage_dir_required(self):
        """
        When the program is run with no arguments, it should exit with code 2
        because there is one required argument.
        """
        with ExpectedException(SystemExit, MatchesStructure(code=Equals(2))):
            main([])

    def test_storage_dir_provided(self):
        """
        When the program is run with an argument, it should run successfully.
        """
        main(['/var/lib/marathon-acme'])
