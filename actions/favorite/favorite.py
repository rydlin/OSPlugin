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
gi.require_version("Gio", "2.0")
from gi.repository import Gtk, Adw, Gio

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

        # Launch the backend process
        backend_path = os.path.join(self.plugin_base.PATH, "actions", "favorite", "backend", "backend.py")
        self.launch_backend(backend_path=backend_path, open_in_terminal=False)

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

        # Get command from backend only (no fallbacks since backend should handle everything)
        try:
            command = self.backend.get_command_for_desktop(desktop_name)
            if command:
                log.info(f"Launching {desktop_name} with backend command: {command}")
                self.run_command(command)
            else:
                log.error(f"Backend could not determine command for {desktop_name}")
                self.show_error()
        except Exception as e:
            log.error(f"Backend communication failed: {e}")
            self.show_error()

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
                        # Fourth try: Use backend for GNOME tools
                        try:
                            # The backend should handle GNOME tools better
                            log.debug("All direct access methods failed, backend will handle command resolution")
                        except Exception as e:
                            log.debug(f"Backend preparation failed: {e}")

                        log.warning("All methods to access GNOME favorites failed in Flatpak.")
                        log.info("Consider configuring favorite apps manually in the action settings.")
                        # Return empty list for now - backend will handle command resolution
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


    def _extract_command_from_filename(self, desktop_name):
        """
        Extract command from desktop filename as a fallback.
        Uses a mapping of known applications for reliability.
        """
        if not desktop_name or not desktop_name.endswith('.desktop'):
            return None

        # Known mappings for common applications
        known_apps = {
            'org.gnome.Evolution.desktop': 'evolution',
            'org.gnome.Nautilus.desktop': 'nautilus',
            'org.gnome.Console.desktop': 'kgx',
            'org.gnome.TextEditor.desktop': 'gedit',
            'org.gnome.Calculator.desktop': 'gnome-calculator',
            'org.gnome.Calendar.desktop': 'gnome-calendar',
            'org.gnome.Software.desktop': 'gnome-software',
            'org.gnome.Settings.desktop': 'gnome-control-center',
            'firefox.desktop': 'firefox',
            'chromium.desktop': 'chromium',
            'google-chrome.desktop': 'google-chrome-stable',
            'code.desktop': 'code',
            'org.freecad.FreeCAD.desktop': 'freecad',
            'discord.desktop': 'discord',
            'steam.desktop': 'steam',
            'spotify.desktop': 'spotify',
            'vlc.desktop': 'vlc',
            'org.gnome.Terminal.desktop': 'gnome-terminal',
            'org.kde.dolphin.desktop': 'dolphin',
            'org.kde.kate.desktop': 'kate',
        }

        if desktop_name in known_apps:
            command = known_apps[desktop_name]
            log.debug(f"Found known command '{command}' for '{desktop_name}'")
            return command

        # Fallback: simple filename extraction
        name = desktop_name[:-8]  # Remove '.desktop'
        if '.' in name:
            parts = name.split('.')
            if len(parts) >= 2:
                command = parts[-1].lower()
                log.debug(f"Extracted command '{command}' from filename '{desktop_name}'")
                return command

        command = name.lower()
        log.debug(f"Simple command '{command}' from filename '{desktop_name}'")
        return command

    