from streamcontroller_plugin_tools import BackendBase
import os
import configparser
import subprocess
from loguru import logger as log

class Backend(BackendBase):
    def __init__(self):
        super().__init__()
        self.desktop_cache = {}
        self._load_desktop_files()
        log.info(f"Loaded {len(self.desktop_cache)} desktop file entries")

    def _load_desktop_files(self):
        """Load and cache all desktop files from standard locations."""
        search_paths = [
            '/usr/share/applications',
            '/usr/local/share/applications',
            os.path.expanduser('~/.local/share/applications')
        ]

        for path in search_paths:
            if os.path.exists(path):
                try:
                    for filename in os.listdir(path):
                        if filename.endswith('.desktop'):
                            filepath = os.path.join(path, filename)
                            self._parse_desktop_file(filepath)
                except (OSError, PermissionError) as e:
                    log.debug(f"Cannot access {path}: {e}")

    def _parse_desktop_file(self, filepath):
        """Parse a desktop file and extract the executable command."""
        try:
            config = configparser.ConfigParser()
            config.read(filepath)

            if 'Desktop Entry' in config and 'Exec' in config['Desktop Entry']:
                exec_cmd = config['Desktop Entry']['Exec']
                # Remove field codes like %U, %F, etc.
                exec_cmd = exec_cmd.split('%')[0].strip()
                # Take the first command (before any arguments)
                command = exec_cmd.split()[0]

                # Use filename as key (e.g., 'firefox.desktop')
                filename = os.path.basename(filepath)
                self.desktop_cache[filename] = command
                log.debug(f"Cached {filename} -> {command}")

        except Exception as e:
            log.debug(f"Error parsing {filepath}: {e}")

    def get_command_for_desktop(self, desktop_name):
        """Get the executable command for a desktop file using GNOME tools."""

        # Method 1: Try GNOME's desktop-file-utils (most reliable)
        try:
            # Use desktop-file-validate to check if file exists and is valid
            result = subprocess.run(['desktop-file-validate', desktop_name],
                                  capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                # File is valid, use gapplication (GNOME's official launcher)
                log.debug(f"Using gapplication for valid desktop file {desktop_name}")
                return f"gapplication launch {desktop_name}"
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Method 2: Try gapplication directly (may work even without validation)
        try:
            # Quick test if gapplication can handle this desktop file
            result = subprocess.run(['gapplication', 'list-apps'],
                                  capture_output=True, text=True, timeout=3)
            if desktop_name in result.stdout:
                log.debug(f"Found {desktop_name} in gapplication list")
                return f"gapplication launch {desktop_name}"
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Method 3: Our cached desktop file parsing
        command = self.desktop_cache.get(desktop_name)
        if command:
            log.debug(f"Using cached command {command} for {desktop_name}")
            return command

        # Method 4: gtk-launch as final GNOME-native fallback
        try:
            result = subprocess.run(['gtk-launch', '--help'],
                                  capture_output=True, text=True, timeout=1)
            if result.returncode == 0:
                log.debug(f"Using gtk-launch for {desktop_name}")
                return f"gtk-launch {desktop_name}"
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return None

    def get_all_favorites(self):
        """Get all cached desktop entries (for debugging)."""
        return dict(self.desktop_cache)

backend = Backend()