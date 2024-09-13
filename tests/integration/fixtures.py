from pathlib import Path
import subprocess as sp

import pytest


class NILRT_SNAC_CLI():

    def __init__(self):
        self.bin_path = Path(__file__).resolve().parents[4] / "sbin" / "nilrt-snac"
        print(f"bin_path={self.bin_path}")

    def run(self, argv: list | str, **kwargs):
        if isinstance(argv, list):
            argv.insert(0, str(self.bin_path))
        else:
            argv = f"{self.bin_path} {argv}"

        kwargs["encoding"] = kwargs.get("encoding", "utf-8")
        kwargs["stdout"] = sp.PIPE
        kwargs["stderr"] = sp.PIPE

        proc = sp.run(argv, **kwargs)

        print(f"<args>{proc.args}</args>")
        print(f"<returncode>{proc.returncode}</returncode>")
        print(f"<stdout>{proc.stdout}</stdout>")
        print(f"<stderr>{proc.stderr}</stderr>")

        return proc


@pytest.fixture(scope="module")
def nilrt_snac_cli():
    yield NILRT_SNAC_CLI()
