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

    def event_callback(self, event: InputEvent, data: dict = None):
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

        # Extract the command name from desktop filename (remove .desktop extension)
        command = desktop_name.replace('.desktop', '')

        # Launch using the same method as EasyCommand
        self.run_command(command)

    def run_command(self, command):
        if command is None:
            return

        if is_in_flatpak():
            command = "flatpak-spawn --host " + command

        p = multiprocessing.Process(target=subprocess.Popen, args=[command], kwargs={"shell": True, "start_new_session": True, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "cwd": os.path.expanduser("~")})
        p.start()
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
            os.path.expanduser('~/.local/share/applications')
        ]
        
        for path in search_paths:
            full_path = os.path.join(path, desktop_name)
            if os.path.isfile(full_path):
                return full_path
        
        log.error(f"Error: {desktop_name} not found in standard directories")
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

            # Look for desktop file patterns
            desktop_pattern = r'([a-zA-Z0-9_-]+\.desktop)'
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

    