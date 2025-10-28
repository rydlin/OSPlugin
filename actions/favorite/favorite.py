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

        # Launch the backend process - copy to user directory for Flatpak compatibility
        backend_source = os.path.join(self.plugin_base.PATH, "actions", "favorite", "backend", "backend.py")
        backend_dest_dir = os.path.expanduser("~/.var/app/com.core447.StreamController/data/backends")
        os.makedirs(backend_dest_dir, exist_ok=True)
        backend_path = os.path.join(backend_dest_dir, "favorite_backend.py")

        # Copy backend file to user directory
        try:
            with open(backend_source, 'r') as src:
                with open(backend_path, 'w') as dst:
                    dst.write(src.read())
            log.debug(f"Copied backend to user directory: {backend_path}")
        except Exception as e:
            log.error(f"Failed to copy backend to user directory: {e}")
            # Fall back to original path
            backend_path = backend_source

        self.launch_backend(backend_path=backend_path, open_in_terminal=False)

        try:
            self.favorites = self.get_favorites()
            if not self.favorites:
                log.warning("No favorites could be loaded - users will need to configure manually")
        except Exception as e:
            log.error(f"Failed to load favorites during initialization: {e}")
            self.favorites = []
        
    def on_ready(self):
        self.set_media(media_path=os.path.join(self.plugin_base.PATH, "assets", "favorites.png"), size=0.8)

    def get_config_rows(self) -> list:
        rows = []

        # Favorite number selector
        self.favorite_row = Adw.SpinRow().new_with_range(min=1, max=10, step=1)
        self.favorite_row.set_title(self.plugin_base.lm.get("favorite.entry.title"))
        self.favorite_row.set_subtitle(self.plugin_base.lm.get("favorite.entry.subtitle"))

        # Load from config
        settings = self.get_settings()
        self.favorite_row.set_value(settings.get("favorite", 1))
        self.favorite_row.connect("changed", self.on_favorite_change)
        rows.append(self.favorite_row)

        # Manual desktop file entry (for Flatpak or when auto-detection fails)
        self.desktop_entry = Adw.EntryRow()
        self.desktop_entry.set_title("Desktop File Name")
        self.desktop_entry.set_subtitle("Enter desktop file name (e.g., firefox.desktop)")

        current_desktop = settings.get("desktop_file", "")
        self.desktop_entry.set_text(current_desktop)
        self.desktop_entry.connect("changed", self.on_desktop_change)
        rows.append(self.desktop_entry)

        return rows
    
    def on_favorite_change(self, *args):
        settings = self.get_settings()
        settings["favorite"] = round(self.favorite_row.get_value(), 1)
        self.set_settings(settings)

    def on_desktop_change(self, *args):
        settings = self.get_settings()
        settings["desktop_file"] = self.desktop_entry.get_text().strip()
        self.set_settings(settings)

    def on_key_down(self):
        settings = self.get_settings()
        favorite = settings.get("favorite", 1)
        desktop_name = settings.get("desktop_file", "").strip()

        # If no manual desktop file is configured and no auto-detected favorites
        if not desktop_name and not self.favorites:
            log.warning("No desktop file configured and no favorites auto-detected.")
            log.info("Please configure a desktop file name in the action settings.")
            return

        # Use manual desktop file if configured, otherwise use auto-detected favorites
        if desktop_name:
            log.debug(f"Using manually configured desktop file: {desktop_name}")
        elif self.favorites:
            if favorite < 1 or favorite > len(self.favorites):
                log.warning(f"Invalid favorite index: {favorite}. Must be between 1 and {len(self.favorites)}.")
                return
            # Ensure favorite is an integer for list indexing
            favorite_index = int(favorite) - 1
            desktop_name = self.favorites[favorite_index]
            log.debug(f"Using auto-detected favorite #{favorite}: {desktop_name}")
        else:
            log.error("No desktop file available for launching")
            return

        log.debug(f"Attempting to launch: {desktop_name}")

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

        # Backend already includes flatpak-spawn --host prefix when needed
        try:
            log.info(f"Running command: {command}")
            p = multiprocessing.Process(target=subprocess.Popen, args=[command], kwargs={"shell": True, "start_new_session": True, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "cwd": os.path.expanduser("~")})
            p.start()
            log.debug(f"Started process for command: {command}")
        except Exception as e:
            log.error(f"Failed to run command '{command}': {e}")
            self.show_error()

        return ""


    def get_favorites(self):
        """Get GNOME favorites list. In Flatpak, this will be empty since we can't access host settings."""
        log.debug("Attempting to get GNOME favorites list")

        if os.getenv('FLATPAK_ID'):
            # In Flatpak, we cannot access GNOME settings from the host
            # The favorites functionality will work by having users manually configure desktop file names
            log.info("Running in Flatpak - GNOME favorites cannot be auto-detected")
            log.info("Users should manually configure favorite desktop file names")
            return []

        # Non-Flatpak: use gsettings to get favorites
        try:
            log.debug("Running gsettings to get favorite apps")
            result = subprocess.run(['gsettings', 'get', 'org.gnome.shell', 'favorite-apps'],
                                  capture_output=True, text=True, check=True)
            favorites_str = result.stdout.strip()
            favorites = ast.literal_eval(favorites_str) if favorites_str else []
            log.info(f"Successfully loaded {len(favorites)} favorite apps: {favorites}")
            return favorites
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

    