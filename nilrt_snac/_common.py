import pathlib

def get_distro():
    try:
        os_release = pathlib.Path("/etc/os-release")
        if os_release.exists():
            with open(os_release, "r") as f:
                for line in f:
                    if line.startswith("ID="):
                        return line.split("=")[1].strip()
    except NameError:
        return None
