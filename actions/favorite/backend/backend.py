from streamcontroller_plugin_tools import BackendBase
import os
import configparser
import subprocess
from loguru import logger as log

class Backend(BackendBase):
    def __init__(self):
        super().__init__()
        log.info("GNOME Favorite backend initialized - using host system tools only")


    def get_command_for_desktop(self, desktop_name):
        """Get the executable command for a desktop file using GNOME tools on host."""

        log.debug(f"Resolving command for desktop file: {desktop_name}")

        # Since backend runs in Flatpak, use flatpak-spawn --host for all host commands

        # Method 1: Check if gapplication on host knows about this desktop file
        try:
            log.debug("Checking gapplication list-apps on host")
            result = subprocess.run(['flatpak-spawn', '--host', 'gapplication', 'list-apps'],
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                if desktop_name in result.stdout:
                    log.info(f"Found {desktop_name} in host gapplication registry")
                    return f"flatpak-spawn --host gapplication launch {desktop_name}"
                else:
                    log.debug(f"{desktop_name} not found in gapplication registry")
            else:
                log.debug(f"gapplication list-apps failed with return code {result.returncode}")
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
            log.debug(f"gapplication check failed: {e}")

        # Method 2: Validate desktop file exists and is valid on host
        try:
            log.debug(f"Validating desktop file {desktop_name} on host")
            result = subprocess.run(['flatpak-spawn', '--host', 'desktop-file-validate', desktop_name],
                                  capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                log.info(f"Desktop file {desktop_name} validated successfully on host")
                return f"flatpak-spawn --host gapplication launch {desktop_name}"
            else:
                log.debug(f"Desktop file validation failed: {result.stderr.strip()}")
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
            log.debug(f"desktop-file-validate failed: {e}")

        # Method 3: Use gtk-launch on host as final GNOME-native method
        try:
            log.debug("Checking gtk-launch availability on host")
            result = subprocess.run(['flatpak-spawn', '--host', 'gtk-launch', '--help'],
                                  capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                log.info(f"Using gtk-launch on host for {desktop_name}")
                return f"flatpak-spawn --host gtk-launch {desktop_name}"
            else:
                log.debug("gtk-launch not available on host")
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
            log.debug(f"gtk-launch check failed: {e}")

        log.warning(f"No command found for {desktop_name} using GNOME methods on host")
        return None


backend = Backend()