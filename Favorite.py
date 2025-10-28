from src.backend.DeckManagement.InputIdentifier import InputEvent
from src.backend.DeckManagement.DeckController import DeckController
from src.backend.PageManagement.Page import Page
from src.backend.PluginManager.ActionBase import ActionBase
from src.backend.PluginManager.PluginBase import PluginBase

import time

# Import gtk modules
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

import ast
import glob
import configparser
import os
import subprocess
import multiprocessing
import threading
from loguru import logger as log

try:
    import dbus
    HAS_DBUS = True
except ImportError:
    HAS_DBUS = False
    log.warning("dbus module not available, some features may be limited")


def is_in_flatpak() -> bool:
    return os.path.isfile('/.flatpak-info')

class Favorite(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.has_configuration = True
        try:
            self.favorites = self.get_favorites()
        except Exception as e:
            log.error(f"Failed to load favorites during initialization: {e}")
            self.favorites = []
        
    def on_ready(self):
        self.set_media(media_path=os.path.join(self.plugin_base.PATH, "assets", "favorites.png"), size=0.8)

    def get_config_rows(self) -> list:
        self.favorite_row = Adw.SpinRow().new_with_range(min=1, max=10, step=1)
        self.favorite_row.set_title(self.plugin_base.lm.get("favorite.entry.title"))
        self.favorite_row.set_subtitle(self.plugin_base.lm.get("favorite.entry.subtitle"))

        # Load from config
        settings = self.get_settings()
        self.favorite_row.set_value(settings.get("favorite", 1))

        self.favorite_row.connect("changed", self.on_favorite_change)

        return [self.favorite_row]
    
    def on_favorite_change(self, *args):
        settings = self.get_settings()
        settings["favorite"] = round(self.favorite_row.get_value(), 1)
        self.set_settings(settings)

    def on_key_down(self):
        favorite = self.get_settings().get("favorite", 1)
        if not self.favorites:
            log.warning("No favorite apps configured.")
            return
        if favorite < 1 or favorite > len(self.favorites):
            log.warning(f"Invalid favorite index: {favorite}. Must be between 1 and {len(self.favorites)}.")
            return
        # Ensure favorite is an integer for list indexing
        favorite_index = int(favorite) - 1
        desktop_name = self.favorites[favorite_index]

        # Try multiple approaches to get the command
        command = self._get_command_from_desktop(desktop_name)
        if not command:
            # Fallback: try to extract command from desktop filename
            command = self._extract_command_from_filename(desktop_name)

        if command:
            self.run_command(command)
        else:
            log.error(f"Could not determine command for {desktop_name}")

    def run_command(self, command):
        if command is None or command.strip() == "":
            log.warning("No command to run")
            return

        original_command = command
        if is_in_flatpak():
            command = "flatpak-spawn --host " + command

        try:
            log.info(f"Running command: {command}")
            p = multiprocessing.Process(target=subprocess.Popen, args=[command], kwargs={"shell": True, "start_new_session": True, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "cwd": os.path.expanduser("~")})
            p.start()
            log.debug(f"Started process for command: {original_command}")
        except Exception as e:
            log.error(f"Failed to run command '{original_command}': {e}")

        return ""


    def get_favorites(self):
        if os.getenv('FLATPAK_ID'):
            # In Flatpak, try multiple approaches to access favorites
            try:
                # First try: dconf command (if available)
                result = subprocess.run(['dconf', 'read', '/org/gnome/shell/favorite-apps'],
                                      capture_output=True, text=True, check=True)
                favorites_str = result.stdout.strip()
                return ast.literal_eval(favorites_str) if favorites_str else []
            except (subprocess.CalledProcessError, FileNotFoundError):
                # Second try: Use flatpak-spawn to run dconf on host
                try:
                    result = subprocess.run(['flatpak-spawn', '--host', 'dconf', 'read', '/org/gnome/shell/favorite-apps'],
                                          capture_output=True, text=True, check=True)
                    favorites_str = result.stdout.strip()
                    return ast.literal_eval(favorites_str) if favorites_str else []
                except (subprocess.CalledProcessError, FileNotFoundError):
                    # Third try: Use flatpak-spawn to run gsettings on host
                    try:
                        result = subprocess.run(['flatpak-spawn', '--host', 'gsettings', 'get', 'org.gnome.shell', 'favorite-apps'],
                                              capture_output=True, text=True, check=True)
                        return ast.literal_eval(result.stdout.strip())
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        # Fourth try: Read dconf database directly with Python
                        try:
                            favorites = self._read_dconf_database()
                            if favorites is not None:
                                return favorites
                        except Exception as e:
                            log.debug(f"Direct dconf database reading failed: {e}")

                        # Fifth try: D-Bus access if available
                        if HAS_DBUS:
                            try:
                                favorites = self._get_favorites_via_dbus()
                                if favorites is not None:
                                    return favorites
                            except Exception as e:
                                log.debug(f"D-Bus access failed: {e}")

                        log.warning("All methods to access GNOME favorites failed in Flatpak.")
                        log.info("Consider configuring favorite apps manually in the action settings.")
                        return []

        # Non-Flatpak: use gsettings
        try:
            result = subprocess.run(['gsettings', 'get', 'org.gnome.shell', 'favorite-apps'],
                                  capture_output=True, text=True, check=True)
            return ast.literal_eval(result.stdout.strip())
        except (subprocess.CalledProcessError, ValueError, SyntaxError) as e:
            log.error(f"Error retrieving favorites: {e}")
            return []



    def find_desktop_file(self,desktop_name):
        """
        Find the full path of a .desktop file by searching standard directories.

        Args:
            desktop_name (str): Name of the .desktop file (e.g., 'firefox.desktop')

        Returns:
            str: Full path to the .desktop file, or None if not found
        """
        search_paths = [
            '/usr/share/applications',
            '/usr/local/share/applications',
            os.path.expanduser('~/.local/share/applications'),
            '/var/lib/flatpak/exports/share/applications',  # Flatpak host exports
            os.path.expanduser('~/.local/share/flatpak/exports/share/applications')  # User Flatpak exports
        ]

        log.debug(f"Searching for desktop file: {desktop_name}")
        for path in search_paths:
            full_path = os.path.join(path, desktop_name)
            log.debug(f"Checking path: {full_path}")
            try:
                # Try to open the file to ensure it's readable
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    f.read(1)  # Just read one character to test accessibility
                log.debug(f"Found desktop file: {full_path}")
                return full_path
            except (FileNotFoundError, PermissionError, OSError) as e:
                log.debug(f"Path not accessible: {full_path} - {e}")
                continue

        log.warning(f"Desktop file {desktop_name} not found in any search path")
        return None

    def get_app_name(self, desktop_name):
        """
        Retrieve the display name of an application from its .desktop file.
        
        Args:
            desktop_name (str): Name of the .desktop file (e.g., 'firefox.desktop')
            
        Returns:
            str: Application name, or None if not found or invalid
        """
        desktop_path = self.find_desktop_file(desktop_name)
        if not desktop_path:
            return None
        
        # Parse the .desktop file
        config = configparser.ConfigParser()
        try:
            config.read(desktop_path)
            if 'Desktop Entry' in config and 'Name' in config['Desktop Entry']:
                return config['Desktop Entry']['Name']
            else:
                log.error(f"Error: 'Name' field not found in {desktop_name}")
                return None
        except Exception as e:
            log.error(f"Error parsing {desktop_name}: {e}")
            return None

    def get_app_icon(self, desktop_name, size=48):
        """
        Retrieve the icon (name or path) from a .desktop file, optionally resolving to a file path.
        
        Args:
            desktop_name (str): Name of the .desktop file (e.g., 'firefox.desktop')
            size (int): Preferred icon size in pixels (for GTK lookup, default 48)
            
        Returns:
            str: Icon name or file path, or None if not found or invalid
        """
        desktop_path = self.find_desktop_file(desktop_name)
        if not desktop_path:
            return None
        
        # Parse the .desktop file
        config = configparser.ConfigParser()
        try:
            config.read(desktop_path)
            if 'Desktop Entry' in config and 'Icon' in config['Desktop Entry']:
                icon = config['Desktop Entry']['Icon']
            else:
                log.error(f"Error: 'Icon' field not found in {desktop_name}")
                return None
        except Exception as e:
            log.error(f"Error parsing {desktop_name}: {e}")
            return None
        
        # If icon is an absolute path and exists, return it
        if os.path.isabs(icon) and os.path.isfile(icon):
            return icon
        
        # try to resolve icon name to a file path
        try:
            icon_theme = Gtk.IconTheme.get_default()
            icon_info = icon_theme.lookup_icon(icon, size, 0)
            if icon_info:
                icon_path = icon_info.get_filename()
                if icon_path and os.path.isfile(icon_path):
                    return icon_path
        except Exception as e:
            log.error(f"Error resolving icon {icon} with GTK: {e}")
        # Fallback: return the icon name
        return icon

    def _get_command_from_desktop(self, desktop_name):
        """
        Extract the command to run from a desktop file.
        In Flatpak, use flatpak-spawn to read host files.
        """
        if is_in_flatpak():
            # In Flatpak, use flatpak-spawn to read the desktop file from host
            try:
                # Try multiple possible locations for the desktop file
                possible_paths = [
                    f'/usr/share/applications/{desktop_name}',
                    f'/usr/local/share/applications/{desktop_name}',
                    f'/var/lib/flatpak/exports/share/applications/{desktop_name}',
                    os.path.expanduser(f'~/.local/share/flatpak/exports/share/applications/{desktop_name}')
                ]

                content = None
                desktop_path = None

                # Try to read from each possible location
                for path in possible_paths:
                    try:
                        log.debug(f"Trying to read desktop file from host path: {path}")
                        result = subprocess.run(['flatpak-spawn', '--host', 'cat', path],
                                              capture_output=True, text=True, check=True)
                        content = result.stdout
                        desktop_path = path
                        log.debug(f"Successfully read desktop file from host: {path}")
                        break
                    except subprocess.CalledProcessError as e:
                        log.debug(f"Failed to read from {path}: {e}")
                        continue

                if not content:
                    log.debug(f"Desktop file not found on host in any location: {desktop_name}")
                    return None

                # Parse the content to find Exec line
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith('Exec='):
                        exec_cmd = line[5:].strip()  # Remove 'Exec=' prefix
                        # Remove field codes like %U, %F, etc. and take first command
                        exec_cmd = exec_cmd.split('%')[0].strip()
                        # If there are arguments, take just the command
                        command = exec_cmd.split()[0]
                        log.debug(f"Found command '{command}' for {desktop_name} from host {desktop_path}")
                        return command

                log.debug(f"No Exec= line found in host file {desktop_path}")
                return None

            except Exception as e:
                log.debug(f"Error reading desktop file from host: {e}")
                return None
        else:
            # Non-Flatpak: use direct file access
            desktop_path = self.find_desktop_file(desktop_name)
            if not desktop_path:
                log.debug(f"Desktop file not found: {desktop_name}")
                return None

            try:
                # Read the file manually to find the first Exec= line
                with open(desktop_path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith('Exec='):
                            exec_cmd = line[5:].strip()  # Remove 'Exec=' prefix
                            # Remove field codes like %U, %F, etc. and take first command
                            exec_cmd = exec_cmd.split('%')[0].strip()
                            # If there are arguments, take just the command
                            command = exec_cmd.split()[0]
                            log.debug(f"Found command '{command}' for {desktop_name} from {desktop_path}")
                            return command

                log.debug(f"No Exec= line found in {desktop_path}")
                return None

            except Exception as e:
                log.debug(f"Error reading Exec from {desktop_name}: {e}")
                return None

    def _read_dconf_database(self):
        """
        Attempt to read GNOME favorites directly from the dconf database file.
        This is a fallback method for when dconf/gsettings commands are not available.
        """
        try:
            import pathlib
            dconf_path = pathlib.Path.home() / '.config' / 'dconf' / 'user'

            if not dconf_path.exists():
                return None

            # The dconf database is binary. We'll try to extract favorites data using
            # a combination of binary search and text extraction
            with open(dconf_path, 'rb') as f:
                data = f.read()

            # Look for the favorites key in the binary data
            # The key '/org/gnome/shell/favorite-apps' might appear as text
            key_bytes = b'/org/gnome/shell/favorite-apps'
            key_pos = data.find(key_bytes)

            if key_pos == -1:
                # Try alternative key patterns
                alt_keys = [
                    b'favorite-apps',
                    b'/org/gnome/shell/favorite',
                    b'favorite-apps\x00'
                ]
                for alt_key in alt_keys:
                    key_pos = data.find(alt_key)
                    if key_pos != -1:
                        break

            if key_pos == -1:
                return None

            # Extract a reasonable chunk of data after the key
            # This is heuristic - the actual format is complex
            start_pos = max(0, key_pos - 100)  # Look a bit before
            end_pos = min(len(data), key_pos + 500)  # Look quite a bit after

            chunk = data[start_pos:end_pos]

            # Try to find array-like patterns in the binary data
            # Look for patterns like ['app1.desktop', 'app2.desktop']
            import re

            # Convert chunk to string, ignoring decode errors
            try:
                chunk_str = chunk.decode('utf-8', errors='ignore')
            except UnicodeDecodeError:
                chunk_str = chunk.decode('latin-1', errors='ignore')

            # Look for desktop file patterns (including reverse domain notation)
            desktop_pattern = r'([a-zA-Z0-9_.-]+\.desktop)'
            matches = re.findall(desktop_pattern, chunk_str)

            if matches:
                # Remove duplicates while preserving order
                seen = set()
                unique_matches = []
                for match in matches:
                    if match not in seen:
                        seen.add(match)
                        unique_matches.append(match)

                log.debug(f"Extracted favorites from dconf database: {unique_matches}")
                return unique_matches

            return None

        except Exception as e:
            log.debug(f"Error reading dconf database: {e}")
            return None

    def _get_favorites_via_dbus(self):
        """
        Attempt to get favorites via D-Bus if available.
        """
        if not HAS_DBUS:
            return None

        try:
            # Try to connect to GNOME Shell's D-Bus interface
            bus = dbus.SessionBus()
            proxy = bus.get_object('org.gnome.Shell', '/org/gnome/Shell')
            interface = dbus.Interface(proxy, 'org.gnome.Shell')

            # Try different method names that might exist
            for method_name in ['GetFavoriteApps', 'getFavoriteApps', 'favoriteApps']:
                try:
                    favorites = interface.get_dbus_method(method_name)()
                    if favorites:
                        return list(favorites)
                except dbus.exceptions.DBusException:
                    continue

            return None

        except Exception as e:
            log.debug(f"D-Bus access failed: {e}")
            return None

    def _extract_command_from_filename(self, desktop_name):
        """
        Extract command from desktop filename as a fallback.
        Handles common patterns like org.gnome.Evolution.desktop -> evolution
        """
        if not desktop_name or not desktop_name.endswith('.desktop'):
            return None

        # Remove .desktop extension
        name = desktop_name[:-8]  # Remove '.desktop'

        # Handle reverse domain notation (org.gnome.Evolution -> evolution)
        if '.' in name:
            parts = name.split('.')
            # For reverse domain, take the last meaningful part
            # org.gnome.Evolution -> Evolution -> evolution
            if len(parts) >= 2:
                last_part = parts[-1]
                # Convert CamelCase to lowercase
                import re
                # Split on uppercase letters and join with hyphens, then lowercase
                command = re.sub(r'([a-z0-9])([A-Z])', r'\1-\2', last_part).lower()
                command = re.sub(r'([A-Z])([A-Z][a-z])', r'\1-\2', command).lower()
                log.debug(f"Extracted command '{command}' from filename '{desktop_name}'")
                return command

        # For simple names like 'firefox.desktop' -> 'firefox'
        command = name.lower()
        log.debug(f"Extracted simple command '{command}' from filename '{desktop_name}'")
        return command

    