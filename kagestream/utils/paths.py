import os
import subprocess
import sys

from kagestream.constants import APP_NAME, PROJECT_ROOT


def is_frozen():
    return getattr(sys, "frozen", False)


def app_dir():
    return os.path.dirname(sys.executable) if is_frozen() else PROJECT_ROOT


def external_app_dir():
    appimage_path = os.environ.get("APPIMAGE")
    if appimage_path:
        return os.path.dirname(os.path.realpath(appimage_path))

    return app_dir()


def user_data_dir():
    if sys.platform == "win32":
        base = (
            os.environ.get("LOCALAPPDATA")
            or os.environ.get("APPDATA")
            or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        )
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(
            os.path.expanduser("~"), ".local", "share"
        )

    return os.path.join(base, APP_NAME)


def user_bin_dir():
    return os.path.join(user_data_dir(), "bin")


def open_folder(path):
    folder = os.path.dirname(path) if os.path.isfile(path) else path

    try:
        if sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", folder])
        elif sys.platform == "win32":
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
    except Exception:
        pass
