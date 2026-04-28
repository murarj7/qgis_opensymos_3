import os
import sys

# Fix import paths
plugin_dir = os.path.dirname(__file__)
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)

from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.PyQt.QtGui import QIcon

class Opensymos:
    """Main OpenSymos plugin class."""
    
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = "&OpenSymos"
        self.main_dialog = None
        self.config_dialog = None
        
    def initGui(self):
        """Create GUI elements."""
        icon_path = os.path.join(self.plugin_dir, 'icons', 'icon.png')
        
        # 1. Main action - Open main dialog
        self.main_action = QAction(
            QIcon(icon_path) if os.path.exists(icon_path) else QIcon(),
            "Open OpenSymos",
            self.iface.mainWindow()
        )
        self.main_action.triggered.connect(self.open_main_dialog)
        self.main_action.setWhatsThis("Open OpenSymos dispersion model")
        
        # 2. Separator
        self.separator_action = QAction(self.iface.mainWindow())
        self.separator_action.setSeparator(True)
        
        # 3. Help action
        self.help_action = QAction(
            "Help",
            self.iface.mainWindow()
        )
        self.help_action.triggered.connect(self.show_help)
        self.help_action.setWhatsThis("OpenSymos help documentation")
        
        # 4. About action
        self.about_action = QAction(
            "About OpenSymos",
            self.iface.mainWindow()
        )
        self.about_action.triggered.connect(self.show_about)
        self.about_action.setWhatsThis("About OpenSymos plugin")
        
        # Add all actions to menu
        self.iface.addPluginToMenu(self.menu, self.main_action)
        self.iface.addPluginToMenu(self.menu, self.separator_action)
        self.iface.addPluginToMenu(self.menu, self.help_action)
        self.iface.addPluginToMenu(self.menu, self.about_action)
        
        # Add main action to toolbar
        self.iface.addToolBarIcon(self.main_action)
        
        # Store actions for cleanup
        self.actions.extend([
            self.main_action,
            self.separator_action,
            self.help_action,
            self.about_action
        ])
        
    def open_main_dialog(self):
        """Open main dialog."""
        from ui.main_dialog import MainDialog
        
        if not self.main_dialog:
            self.main_dialog = MainDialog(self.iface.mainWindow())
        
        self.main_dialog.show()
        self.main_dialog.raise_()
        self.main_dialog.activateWindow()
        
    def show_help(self):
        """Show help dialog."""
        QMessageBox.information(
            self.iface.mainWindow(),
            "OpenSymos Help",
            "OpenSymos Dispersion Model Plugin\n\n"
            "Workflow:\n"
            "1. Load data layers in QGIS\n"
            "2. Open OpenSymos from toolbar\n"
            "3. Configure data in tabs:\n"
            "   - Terrain (raster)\n"
            "   - Sources (point/line/polygon)\n"
            "   - Receptors (points)\n"
            "   - Wind data (XML)\n"
            "4. Validate data using 'Validate All' button\n"
            "5. Run calculation when ready\n"
            "6. View results\n\n"
            "Note: All layers must have valid coordinate system (CRS)."
        )
        
    def show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self.iface.mainWindow(),
            "About OpenSymos",
            "<h2>OpenSymos QGIS Plugin</h2>"
            "<p>Version: 1.0.0 (Development)</p>"
            "<p>Dispersion modeling tool based on SYMOS-3 methodology.</p>"
            "<p>Author: Your Name</p>"
            "<p>License: GPL v3</p>"
            "<p>GitHub: <a href='https://github.com/ruz76/qgis_opensymos_3'>"
            "https://github.com/ruz76/qgis_opensymos_3</a></p>"
        )
        
    def unload(self):
        """Remove plugin from QGIS."""
        # Close dialogs
        if self.main_dialog:
            self.main_dialog.close()
        if self.config_dialog:
            self.config_dialog.close()
        
        # Remove all menu items
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            
        # Remove from toolbar
        self.iface.removeToolBarIcon(self.main_action)