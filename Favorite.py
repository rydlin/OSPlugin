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
from loguru import logger as log

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
        self.launch_app(self.favorites[favorite - 1])

    def launch_app(self, desktop_name):
        try:
            subprocess.run(['gtk-launch', desktop_name], check=True)
            log.info(f"Launched {desktop_name}")
        except subprocess.CalledProcessError as e:
            log.error(f"Failed to launch {desktop_name}: {e}")
        except FileNotFoundError:
            log.error(f"gtk-launch command not found. Cannot launch {desktop_name}")
        except Exception as e:
            log.error(f"Unexpected error launching {desktop_name}: {e}")

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
                    except (subprocess.CalledProcessError, FileNotFoundError, ValueError, SyntaxError) as e:
                        log.warning(f"All methods to access GNOME favorites failed in Flatpak: {e}")
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
    