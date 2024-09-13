"""These tests validate that the nilrt-snac CLI workflows function as expected."""
from subprocess import CompletedProcess
import re

from nilrt_snac import __version__
from tests.integration.fixtures import nilrt_snac_cli


def test_help(nilrt_snac_cli):
    """The CLI --help arg prints usage information and exits code 0."""
    cli = nilrt_snac_cli

    def check_help_output(proc: CompletedProcess):
        assert proc.returncode == 0
        assert re.match(r"^usage: nilrt-snac ", proc.stdout)
        assert len(proc.stderr) == 0

    check_help_output(cli.run(["--help"]))
    check_help_output(cli.run(["-h"]))


def test_noargs(nilrt_snac_cli):
    """When called with no arguments, the CLI should print usage and exit code 2."""
    cli = nilrt_snac_cli
    proc = cli.run([])
    assert proc.returncode == 2  # Code 2 is universally accepted to mean "badargs"
    assert len(proc.stdout) == 0
    assert "--help" in proc.stderr


def test_verify(nilrt_snac_cli):
    """The CLI verify command can be called to validate the system's SNAC configuration."""
    proc = nilrt_snac_cli.run(["verify"])
    # return code should either be 0 (OK) or 129 (Check failed), depending
    # on if this system is in SNAC mode.
    assert proc.returncode in {0, 129}
    assert "Verifying " in proc.stdout


def test_version(nilrt_snac_cli):
    """The CLI --version argument prints version information and exits."""
    cli = nilrt_snac_cli
    
    def check_version_output(proc: CompletedProcess):
        # --version should return code 0
        assert proc.returncode == 0

        # --version stdout should match the following rules.
        stdouts = str(proc.stdout).splitlines(keepends=True)
        # First line should contain the product name
        assert re.match(r"^nilrt-snac \d+\.\d+\.\d+$", stdouts[0])
        # Second line should be a copyright notice.
        assert re.match(r"^copyright\W.*emerson", stdouts[1], re.IGNORECASE)
        # Third line should be the MIT license declarative
        assert re.match("^license MIT.*", stdouts[2], re.IGNORECASE)
        # After that, we don't really care.

        # --version should print no stderr
        assert len(proc.stderr) == 0

    check_version_output(cli.run(["--version"]))
    check_version_output(cli.run(["-V"]))
    # should disregard additional commands.
    check_version_output(cli.run(["--version", "verify"]))
