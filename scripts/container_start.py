"""Initialize only the configured mounted media directory, then drop privileges."""
import os
from pathlib import Path
import sys


def main():
    directory = Path(os.environ.get("TEAM_LOGO_DIRECTORY", "/data/team-logos"))
    mount = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "/data"))
    if not mount.is_mount() or not directory.is_absolute() or not directory.resolve().is_relative_to(mount.resolve()) or directory.is_symlink():
        raise SystemExit("No se encontró el volumen persistente de logotipos.")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.getuid() == 0:
        os.chown(directory, 10001, 10001)
        os.chmod(directory, 0o700)
        os.setgroups([])
        os.setgid(10001)
        os.setuid(10001)
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
