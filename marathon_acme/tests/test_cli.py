import re

from click.testing import CliRunner

from marathon_acme.cli import main


def test_email_required():
    """
    The program is expected to exit with an error code and message if '--email'
    is not provided.
    """
    runner = CliRunner()
    result = runner.invoke(main, [])

    assert result.exit_code == 2
    assert re.search('Error: Missing option "--email"', result.output)


def test_email_provided():
    """
    The program is expected to exit with code 0 if '--email' is provided.
    """
    runner = CliRunner()
    result = runner.invoke(main, ['--email', 'test@example.com'])

    assert result.exit_code == 0
