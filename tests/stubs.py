"""
Stubs for testing Favorite.py without full dependencies.
"""

import os
from unittest.mock import MagicMock


class MockPluginBase:
    def __init__(self):
        self.PATH = os.path.dirname(os.path.dirname(__file__))
        self.lm = MagicMock()
        self.lm.get = MagicMock(return_value="Mocked String")


class MockInputEvent:
    def __init__(self):
        pass


class MockActionBase:
    def __init__(self, *args, **kwargs):
        self.plugin_base = MockPluginBase()
        self.has_configuration = False

    def get_settings(self):
        return {}

    def set_settings(self, settings):
        pass

    def set_media(self, **kwargs):
        pass


# Mock GTK classes
class MockAdwSpinRow:
    def __init__(self):
        self.value = 1

    def new_with_range(self, min, max, step):
        return self

    def set_title(self, title):
        pass

    def set_subtitle(self, subtitle):
        pass

    def set_value(self, value):
        self.value = value

    def get_value(self):
        return self.value

    def connect(self, signal, callback):
        pass


class MockGtkIconTheme:
    def __init__(self):
        pass

    @staticmethod
    def get_default():
        return MockGtkIconTheme()

    def lookup_icon(self, icon_name, size, flags):
        mock_info = MagicMock()
        mock_info.get_filename.return_value = f"/mock/path/{icon_name}.png"
        return mock_info


# Mock modules
import sys
from unittest.mock import MagicMock

# Mock gi.repository
gi_mock = MagicMock()
gi_mock.require_version = MagicMock()
sys.modules['gi'] = gi_mock
sys.modules['gi.repository'] = MagicMock()
sys.modules['gi.repository.Gtk'] = MagicMock()
sys.modules['gi.repository.Adw'] = MagicMock()

# Mock loguru
loguru_mock = MagicMock()
sys.modules['loguru'] = loguru_mock

# Apply mocks
import gi.repository.Gtk as Gtk
import gi.repository.Adw as Adw
from loguru import logger as log

Gtk.IconTheme = MockGtkIconTheme
Adw.SpinRow = MockAdwSpinRow

# Mock backend modules
sys.modules['src'] = MagicMock()
sys.modules['src.backend'] = MagicMock()
sys.modules['src.backend.DeckManagement'] = MagicMock()
sys.modules['src.backend.DeckManagement.InputIdentifier'] = MagicMock()
sys.modules['src.backend.DeckManagement.DeckController'] = MagicMock()
sys.modules['src.backend.PageManagement'] = MagicMock()
sys.modules['src.backend.PageManagement.Page'] = MagicMock()
sys.modules['src.backend.PluginManager'] = MagicMock()
sys.modules['src.backend.PluginManager.ActionBase'] = MagicMock()
sys.modules['src.backend.PluginManager.PluginBase'] = MagicMock()

from src.backend.DeckManagement.InputIdentifier import InputEvent
from src.backend.DeckManagement.DeckController import DeckController
from src.backend.PageManagement.Page import Page
from src.backend.PluginManager.ActionBase import ActionBase
from src.backend.PluginManager.PluginBase import PluginBase

# Replace with our mocks
sys.modules['src.backend.PluginManager.ActionBase'].ActionBase = MockActionBase
sys.modules['src.backend.DeckManagement.InputIdentifier'].InputEvent = MockInputEvent