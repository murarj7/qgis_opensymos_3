import os
import sys

# Add plugin directory to path
plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)

from qgis.PyQt.QtWidgets import QDialog, QMessageBox, QApplication, QFileDialog
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QPixmap
from qgis.PyQt import uic
from qgis.core import (
    QgsProject,
    QgsMessageLog,
    Qgis,
    QgsUnitTypes,
    QgsPointXY,
)

from opensymos.utils import (
    LineToPointConverter,
    PolygonToPointConverter,
    RegularReceptorGenerator,
    AroundFeaturesGenerator,
)
from opensymos.core import (
    Calculator,
    Source,
    Receptor,
    ResultsCollection,
    CalculationWorker,
    WindRose,
    Terrain,
)

try:
    from utils.layer_manager import LayerManager
    LAYER_MANAGER_AVAILABLE = True
except ImportError as e:
    QgsMessageLog.logMessage(f"LayerManager import error: {e}", "OpenSymos", Qgis.Warning)
    LAYER_MANAGER_AVAILABLE = False


class MainDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        # Load UI file
        ui_path = os.path.join(os.path.dirname(__file__), "main_dialog.ui")
        uic.loadUi(ui_path, self)

        # Initialize variables
        self.wind_file_path = None
        self.wind_results = None
        self.terrain_layer_valid = False
        self.sources_layer_valid = False
        self.receptors_layer_valid = False
        self.wind_data_valid = False
        self.calculation_aborted = False

        # Setup tabs
        self.setup_settings_tab()
        self.setup_terrain_tab()
        self.setup_sources_tab()
        self.setup_receptors_tab()
        self.setup_wind_tab()
        self.setup_calculation_tab()

        # Connect main buttons
        self.btn_validate.clicked.connect(self.validate_all)
        self.btn_calculate.clicked.connect(self.go_to_calculation_tab)
        self.big_calc_button.clicked.connect(self.run_calculation)
        self.btn_abort.clicked.connect(self.abort_calculation)
        self.btn_abort.setEnabled(False)

        # Initial refresh
        self.refresh_raster_layers()

    def setup_settings_tab(self):
        """Setup settings tab with pollutant selection and limit value."""
        self.spin_limit.setValue(350)
        self.combo_pollutant.setCurrentText("Sulfur dioxide (SO2)")

    def setup_terrain_tab(self):
        """Setup terrain tab."""
        self.btn_refresh_layers.clicked.connect(self.refresh_raster_layers)
        self.btn_load_raster.clicked.connect(self.load_raster_from_file)
        self.btn_zoom_terrain.clicked.connect(self.zoom_to_terrain)
        self.btn_test_terrain.clicked.connect(self.test_terrain_data)
        self.btn_show_in_map.clicked.connect(self.show_terrain_in_map)
        self.combo_terrain.currentIndexChanged.connect(self.on_terrain_changed)

    def setup_sources_tab(self):
        """Setup sources tab with dynamic page switching."""
        self.combo_source_type.currentIndexChanged.connect(self.stackedWidget_sources.setCurrentIndex)

        self.populate_vector_layers(self.combo_point_layer, ["point"])
        self.populate_vector_layers(self.combo_line_layer, ["line"])
        self.populate_vector_layers(self.combo_area_layer, ["polygon"])

        self.combo_point_layer.currentIndexChanged.connect(
            lambda: self.update_source_attributes("point")
        )
        self.combo_line_layer.currentIndexChanged.connect(
            lambda: self.update_source_attributes("line")
        )
        self.combo_area_layer.currentIndexChanged.connect(
            lambda: self.update_source_attributes("area")
        )

        self.btn_test_sources.clicked.connect(lambda: self.test_data("Sources"))

        self.btn_refresh_point.clicked.connect(
            lambda: self.populate_vector_layers(self.combo_point_layer, ["point"])
        )
        self.btn_refresh_line.clicked.connect(
            lambda: self.populate_vector_layers(self.combo_line_layer, ["line"])
        )
        self.btn_refresh_area.clicked.connect(
            lambda: self.populate_vector_layers(self.combo_area_layer, ["polygon"])
        )

        self.spin_line_spacing.setMinimum(1)
        self.spin_line_spacing.setValue(125)

        self.spin_area_spacing.setMinimum(1)
        self.spin_area_spacing.setValue(250)

    def setup_receptors_tab(self):
        """Setup receptors tab with three optional methods."""
        self.populate_vector_layers(self.combo_import_layer, ["point"])
        self.populate_raster_layers(self.combo_extent_layer)
        self.populate_vector_layers(self.combo_features_layer, "all")

        self.btn_generate_regular.clicked.connect(self.generate_regular_receptors)
        self.btn_generate_around.clicked.connect(self.generate_around_features)
        self.btn_test_receptors.clicked.connect(self.test_receptors_data)

        self.btn_refresh_import.clicked.connect(
            lambda: self.populate_vector_layers(self.combo_import_layer, ["point"])
        )
        self.btn_refresh_regular.clicked.connect(
            lambda: self.populate_raster_layers(self.combo_extent_layer)
        )
        self.btn_refresh_around.clicked.connect(
            lambda: self.populate_vector_layers(self.combo_features_layer, "all")
        )

        self.spin_import_height.setValue(2)
        self.spin_regular_height.setValue(2)
        self.spin_around_height.setValue(2)
        self.spin_spacing.setValue(100)
        self.spin_around_spacing.setValue(50)
        self.spin_min_distance.setValue(50)
        self.spin_max_distance.setValue(500)
        self.spin_max_distance.setMinimum(50)

        self.spin_min_distance.valueChanged.connect(self.update_max_distance_minimum)

        self.groupBox_import.toggled.connect(
            lambda checked: self.reset_groupbox(checked, "import")
        )
        self.groupBox_regular.toggled.connect(
            lambda checked: self.reset_groupbox(checked, "regular")
        )
        self.groupBox_around.toggled.connect(
            lambda checked: self.reset_groupbox(checked, "around")
        )

    def setup_wind_tab(self):
        """Setup wind data tab."""
        self.btn_browse_wind.clicked.connect(self.browse_wind_file)
        self.btn_analyze_wind.clicked.connect(self.analyze_wind_data)
        self.btn_export_csv.clicked.connect(self.export_wind_csv)
        self.btn_export_plot.clicked.connect(self.export_wind_plot)
        self.btn_clear_results.clicked.connect(self.clear_wind_results)

    def setup_calculation_tab(self):
        """Setup calculation tab."""
        self.combo_concentration_type.setCurrentText("Maximum short-time concentration")

    def populate_vector_layers(self, combobox, allowed_types=["point"]):
        """Populate combobox with vector layers."""
        if not LAYER_MANAGER_AVAILABLE:
            combobox.addItem("LayerManager not available")
            combobox.setEnabled(False)
            return

        combobox.clear()
        combobox.addItem("-- Select layer --")

        geom_map = {
            "point": Qgis.GeometryType.Point,
            "line": Qgis.GeometryType.Line,
            "polygon": Qgis.GeometryType.Polygon,
        }

        try:
            layers = LayerManager.get_all_vector_layers()
            for layer in layers:
                layer_geom_type = layer.geometryType()
                if allowed_types == "all":
                    combobox.addItem(layer.name(), layer.id())
                else:
                    for geom_type_name in allowed_types:
                        if geom_type_name in geom_map and geom_map[geom_type_name] == layer_geom_type:
                            combobox.addItem(layer.name(), layer.id())
                            break
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error populating layers: {e}",
                "OpenSymos",
                Qgis.Warning,
            )
            combobox.addItem("Error loading layers")

    def populate_raster_layers(self, combobox):
        """Populate combobox with raster layers."""
        if not LAYER_MANAGER_AVAILABLE:
            combobox.addItem("LayerManager not available")
            combobox.setEnabled(False)
            return

        combobox.clear()
        combobox.addItem("-- Select DEM layer --")

        try:
            layers = LayerManager.get_all_raster_layers()
            for layer in layers:
                combobox.addItem(layer.name(), layer.id())
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error populating rasters: {e}",
                "OpenSymos",
                Qgis.Warning,
            )
            combobox.addItem("Error loading layers")

    def _get_numeric_field_names(self, layer):
        """Return only integer/float-like field names from a layer."""
        numeric_types = {
            QVariant.Int,
            QVariant.UInt,
            QVariant.LongLong,
            QVariant.ULongLong,
            QVariant.Double,
        }

        return [
            field.name()
            for field in layer.fields()
            if field.type() in numeric_types
        ]

    def update_source_attributes(self, source_type):
        """Update attribute comboboxes based on selected layer."""
        mapping = {
            "point": {
                "layer_combo": self.combo_point_layer,
                "id_combo": self.combo_point_id,
                "numeric_combos": [
                    self.combo_point_emission,
                    self.combo_point_height,
                    self.combo_point_volume,
                    self.combo_point_temp,
                    self.combo_point_diam,
                    self.combo_point_vel,
                    self.combo_point_year,
                    self.combo_point_day,
                ],
            },
            "line": {
                "layer_combo": self.combo_line_layer,
                "id_combo": self.combo_line_id,
                "numeric_combos": [
                    self.combo_line_emission,
                    self.combo_line_height,
                    self.combo_line_year,
                    self.combo_line_day,
                ],
            },
            "area": {
                "layer_combo": self.combo_area_layer,
                "id_combo": self.combo_area_id,
                "numeric_combos": [
                    self.combo_area_emission,
                    self.combo_area_height,
                    self.combo_area_year,
                    self.combo_area_day,
                ],
            },
        }

        data = mapping.get(source_type)
        layer_id = data["layer_combo"].currentData()
        layer = QgsProject.instance().mapLayer(layer_id)

        # Clear all combos first
        data["id_combo"].clear()
        for combo in data["numeric_combos"]:
            combo.clear()

        if layer:
            all_fields = [field.name() for field in layer.fields()]
            numeric_fields = self._get_numeric_field_names(layer)

            data["id_combo"].addItems(numeric_fields)  # ID field must be numeric for proper indexing

            # All source parameter fields: numeric only
            for combo in data["numeric_combos"]:
                combo.addItems(numeric_fields)

    def get_selected_source_layers(self):
        """Return all currently selected valid source layers."""
        selected_sources = []

        source_definitions = [
            ("Point", self.combo_point_layer),
            ("Line", self.combo_line_layer),
            ("Area", self.combo_area_layer),
        ]

        for source_type, combo in source_definitions:
            if combo.currentIndex() > 0:
                layer_id = combo.currentData()
                layer = QgsProject.instance().mapLayer(layer_id)
                if layer and layer.isValid():
                    selected_sources.append(
                        {
                            "type": source_type,
                            "layer": layer,
                            "layer_id": layer_id,
                        }
                    )

        return selected_sources
    
    def _set_source_elevation_or_fail(self, source, terrain, object_label="Source"):
        """
        Set source elevation from DEM.
        If source lies outside DEM extent or on NoData, stop calculation.
        """
        if terrain is None:
            source.set_elevation(0.0)
            return True

        z = terrain.get_elevation(source.x, source.y)
        if z is None:
            msg = (
                f"{object_label} {source.id} lies outside DEM extent "
                f"or on a NoData pixel.\n\n"
                "Calculation was cancelled."
            )
            self.text_log.append(f"❌ {msg}")
            QMessageBox.critical(self, "DEM Error", msg)
            self.calculation_finished(None)
            return False

        source.set_elevation(z)
        return True

    def _set_receptor_elevation_or_skip(self, receptor, terrain, skipped_counter):
        """
        Set receptor elevation from DEM.
        If receptor lies outside DEM extent or on NoData, skip it.

        Args:
            receptor: Receptor object
            terrain: Terrain instance
            skipped_counter: dict with key 'count'

        Returns:
            bool: True if receptor is valid and can be used, False if it should be skipped
        """
        if terrain is None:
            receptor.set_elevation(0.0)
            return True

        z = terrain.get_elevation(receptor.x, receptor.y)
        if z is None:
            skipped_counter["count"] += 1
            self.text_log.append(
                f"  ⚠ Receptor {receptor.id} lies outside DEM extent or on NoData pixel - skipped"
            )
            return False

        receptor.set_elevation(z)
        return True

    def get_selected_source_summary(self):
        """Return a short human-readable summary of selected source types."""
        selected_sources = self.get_selected_source_layers()
        if not selected_sources:
            return "none"
        return ", ".join([item["type"] for item in selected_sources])
    
    def get_selected_receptor_methods(self):
        """Return list of selected receptor methods."""
        methods = []

        if self.groupBox_import.isChecked():
            methods.append("Import")

        if self.groupBox_regular.isChecked():
            methods.append("Regular")

        if self.groupBox_around.isChecked():
            methods.append("Around")

        return methods


    def get_selected_receptor_summary(self):
        """Return a short human-readable summary of selected receptor methods."""
        methods = self.get_selected_receptor_methods()
        if not methods:
            return "none"
        return ", ".join(methods)

    def refresh_raster_layers(self):
        """Refresh list of raster layers."""
        if not LAYER_MANAGER_AVAILABLE:
            self.combo_terrain.setEnabled(False)
            self.combo_terrain.clear()
            self.combo_terrain.addItem("LayerManager not available")
            self.lbl_terrain_info.setText(
                "<span style='color: red;'>Error: Could not load layer utilities</span>"
            )
            return

        try:
            self.combo_terrain.clear()
            self.combo_terrain.addItem("-- Select raster layer --")

            layers = LayerManager.get_all_raster_layers()
            if layers:
                for layer in layers:
                    self.combo_terrain.addItem(layer.name(), layer.id())
                self.combo_terrain.setEnabled(True)
                self.lbl_terrain_info.setText("Select a raster layer")
            else:
                self.combo_terrain.addItem("No raster layers found")
                self.combo_terrain.setEnabled(False)
                self.lbl_terrain_info.setText(
                    "<i>No raster layers available. Load a raster file or add one to your QGIS project.</i>"
                )
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error refreshing layers: {e}",
                "OpenSymos",
                Qgis.Warning,
            )
            self.combo_terrain.addItem("Error loading layers")
            self.combo_terrain.setEnabled(False)

    def on_terrain_changed(self, index):
        """Handle terrain layer selection."""
        if index <= 0:
            self.lbl_terrain_info.setText("No layer selected")
            self.terrain_layer_valid = False
            self.update_validation_status()
            return

        if not LAYER_MANAGER_AVAILABLE:
            self.lbl_terrain_info.setText(
                "<span style='color: red;'>Error: LayerManager not available</span>"
            )
            self.terrain_layer_valid = False
            self.update_validation_status()
            return

        try:
            layer_id = self.combo_terrain.currentData()
            layer = QgsProject.instance().mapLayer(layer_id)

            if not layer or not layer.isValid():
                self.lbl_terrain_info.setText(
                    "<span style='color: red;'>Error: Invalid layer</span>"
                )
                self.terrain_layer_valid = False
                self.update_validation_status()
                return

            info = LayerManager.get_raster_info(layer)
            if info:
                crs = layer.crs()
                has_valid_crs = crs.isValid() and crs.authid() != ""
                is_metric = crs.mapUnits() == QgsUnitTypes.DistanceMeters

                if not has_valid_crs:
                    crs_html = (
                        f"<span style='color: red; font-weight: bold;'>⚠ {info['crs']} (INVALID)</span>"
                    )
                    status_html = "<span style='color: red;'>✗ CRS required</span>"
                    self.terrain_layer_valid = False
                elif not is_metric:
                    crs_html = (
                        f"<span style='color: #ff6600; font-weight: bold;'>⚠ {info['crs']} (NON-METRIC)</span>"
                    )
                    status_html = "<span style='color: red;'>✗ Metric CRS required (meters)</span>"
                    self.terrain_layer_valid = False
                else:
                    crs_html = f"<span style='color: #009933;'>{info['crs']}</span>"
                    status_html = "<span style='color: #009933;'>✓ Ready</span>"
                    self.terrain_layer_valid = True

                info_text = f"""
                <div style='font-family: monospace; font-size: 11px;'>
                <b>Name:</b> {info['name']}<br>
                <b>Resolution:</b> <span style='color: #0066cc;'>{info.get('pixel_size', 'Unknown')}</span><br>
                <b>Size:</b> {info['width']} × {info['height']} pixels<br>
                <b>Bands:</b> {info['band_count']}<br>
                <b>CRS:</b> {crs_html}<br>
                <b>Status:</b> {status_html}
                </div>
                """
                self.lbl_terrain_info.setText(info_text)
            else:
                self.lbl_terrain_info.setText(
                    "<span style='color: orange;'>Could not read layer information</span>"
                )
                self.terrain_layer_valid = False

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error getting layer info: {e}",
                "OpenSymos",
                Qgis.Warning,
            )
            self.lbl_terrain_info.setText(
                "<span style='color: red;'>Error loading layer info</span>"
            )
            self.terrain_layer_valid = False

        self.update_validation_status()

    def load_raster_from_file(self):
        """Load raster layer from file."""
        if not LAYER_MANAGER_AVAILABLE:
            QMessageBox.warning(self, "Error", "LayerManager not available")
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Raster File",
            "",
            "Raster files (*.tif *.tiff *.asc *.img *.bil *.jpg *.png);;All files (*.*)",
        )

        if not file_path:
            return

        try:
            layer = LayerManager.load_raster_from_file(file_path)
            if layer:
                self.refresh_raster_layers()
                index = self.combo_terrain.findText(layer.name())
                if index >= 0:
                    self.combo_terrain.setCurrentIndex(index)
                QMessageBox.information(
                    self,
                    "Success",
                    f"Raster layer '{layer.name()}' loaded successfully!",
                )
            else:
                QMessageBox.critical(
                    self,
                    "Error",
                    "Could not load raster file. Please check if the file is valid.",
                )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error loading raster: {str(e)}")

    def zoom_to_terrain(self):
        """Zoom map to selected terrain layer."""
        if self.combo_terrain.currentIndex() <= 0:
            QMessageBox.warning(self, "No Layer", "Please select a raster layer first.")
            return

        try:
            from qgis.utils import iface

            layer_id = self.combo_terrain.currentData()
            layer = QgsProject.instance().mapLayer(layer_id)

            if layer:
                iface.mapCanvas().setExtent(layer.extent())
                iface.mapCanvas().refresh()
                QMessageBox.information(self, "Zoom", "Zoomed to selected layer.")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not zoom to layer: {str(e)}")

    def show_terrain_in_map(self):
        """Ensure terrain layer is visible in map."""
        if self.combo_terrain.currentIndex() <= 0:
            QMessageBox.warning(self, "No Layer", "Please select a raster layer first.")
            return

        layer_id = self.combo_terrain.currentData()
        layer = QgsProject.instance().mapLayer(layer_id)

        if layer:
            layer_tree_root = QgsProject.instance().layerTreeRoot()
            layer_tree_layer = layer_tree_root.findLayer(layer.id())
            if layer_tree_layer:
                layer_tree_layer.setItemVisibilityChecked(True)
                QMessageBox.information(self, "Visibility", "Layer set to visible.")

    def test_terrain_data(self):
        """Test the selected terrain data."""
        if self.combo_terrain.currentIndex() <= 0:
            QMessageBox.warning(self, "No Layer", "Please select a raster layer first.")
            return

        layer_id = self.combo_terrain.currentData()
        layer = QgsProject.instance().mapLayer(layer_id)

        if not layer:
            QMessageBox.critical(self, "Error", "Selected layer not found.")
            return

        crs = layer.crs()
        has_valid_crs = crs.isValid() and crs.authid() != ""
        is_metric = crs.mapUnits() == QgsUnitTypes.DistanceMeters

        if not has_valid_crs or not is_metric:
            msg = (
                "Terrain layer has no valid CRS!"
                if not has_valid_crs
                else f"Terrain layer CRS ({crs.authid()}) is NOT metric!"
            )

            QMessageBox.critical(
                self,
                "CRS Error",
                f"{msg}\n\n"
                "SYMOS requires a metric CRS (meters) for accurate calculations.\n\n"
                "How to fix:\n"
                "1. Right-click the layer -> Export -> Save Layer As...\n"
                "2. Change CRS to a metric one (e.g., EPSG:5514 for JTSK or EPSG:32633 for UTM)\n"
                "3. Use the new exported layer in this plugin.",
            )
            return

        warnings = []

        if layer.bandCount() > 1:
            warnings.append(f"Layer has {layer.bandCount()} bands (only first band will be used)")

        if layer.rasterUnitsPerPixelX() <= 0 or layer.rasterUnitsPerPixelY() <= 0:
            warnings.append("Could not determine pixel resolution")

        if warnings:
            warning_text = "\n".join([f"• {warning}" for warning in warnings])
            QMessageBox.warning(
                self,
                "Terrain Test - Warnings",
                f"Layer '{layer.name()}' has some warnings:\n\n{warning_text}\n\n"
                "Please check these issues before calculation.",
            )
        else:
            QMessageBox.information(
                self,
                "Terrain Test - OK",
                f"Terrain layer OK!\n\n"
                f"✓ Name: {layer.name()}\n"
                f"✓ Size: {layer.width()} × {layer.height()}\n"
                f"✓ CRS: {crs.authid()}\n"
                f"✓ Resolution: {layer.rasterUnitsPerPixelX():.2f} m\n\n"
                "Layer is ready for use in dispersion model.",
            )

    def test_data(self, data_type):
        """Generic test function for vector data types."""
        if data_type == "Sources":
            selected_sources = self.get_selected_source_layers()

            if not selected_sources:
                QMessageBox.warning(self, "No Selection", "Please select at least one source layer first.")
                return

            messages = []
            has_error = False

            for source_info in selected_sources:
                source_type = source_info["type"]
                layer = source_info["layer"]

                if not layer or not layer.isValid():
                    messages.append(f"✗ {source_type}: invalid layer")
                    has_error = True
                    continue

                crs = layer.crs()
                if not crs.isValid() or crs.mapUnits() != QgsUnitTypes.DistanceMeters:
                    messages.append(
                        f"✗ {source_type}: CRS must be metric "
                        f"({crs.authid() if crs.isValid() else 'None'})"
                    )
                    has_error = True
                    continue

                messages.append(f"✓ {source_type}: {layer.name()} ({crs.authid()})")

            if len(selected_sources) > 1:
                messages.append("")
                messages.append(
                    f"Warning: all selected source layers will be used "
                    f"({self.get_selected_source_summary()})"
                )

            if has_error:
                QMessageBox.critical(
                    self,
                    "Sources Test",
                    "\n".join(messages),
                )
            else:
                QMessageBox.information(
                    self,
                    "Sources Test",
                    "\n".join(messages),
                )
            return

        combo = self.combo_receptors

        if combo.currentIndex() <= 0:
            QMessageBox.warning(self, "No Selection", f"Please select a layer for {data_type} first.")
            return

        layer_id = combo.currentData()
        layer = QgsProject.instance().mapLayer(layer_id)

        if not layer or not layer.isValid():
            QMessageBox.critical(self, "Error", f"Selected {data_type} layer is invalid.")
            return

        crs = layer.crs()
        if not crs.isValid() or crs.mapUnits() != QgsUnitTypes.DistanceMeters:
            QMessageBox.critical(
                self,
                "CRS Error",
                f"{data_type} layer must be in a metric CRS (meters)!\n"
                f"Current: {crs.authid() if crs.isValid() else 'None'}",
            )
            return

        if data_type == "Receptors" and layer.geometryType() != Qgis.GeometryType.Point:
            QMessageBox.critical(self, "Geometry Error", "Receptors MUST be points!")
            return

        QMessageBox.information(
            self,
            f"{data_type} Test",
            f"✓ {data_type} data is valid and ready.",
        )

    def generate_regular_receptors(self):
        """Generate regular grid of receptors."""
        if self.combo_extent_layer.currentIndex() <= 0:
            QMessageBox.warning(
                self,
                "Error",
                "Please select a DEM layer in Generate regular receptors first",
            )
            return

        layer_id = self.combo_extent_layer.currentData()
        dem_layer = QgsProject.instance().mapLayer(layer_id)

        if not dem_layer:
            QMessageBox.warning(self, "Error", "Selected DEM layer is not valid")
            return

        if dem_layer.type() != 1:
            QMessageBox.warning(
                self,
                "Error",
                f"Selected layer is not a raster!\n"
                f"Name: {dem_layer.name()}\n"
                f"Type: {dem_layer.type()} (1 = raster)",
            )
            return

        spacing = self.spin_spacing.value()
        if spacing <= 0:
            QMessageBox.warning(self, "Error", "Spacing must be greater than 0")
            return

        height = self.spin_regular_height.value()

        generator = RegularReceptorGenerator()
        result = generator.generate(dem_layer, dem_layer, spacing, height)

        if result:
            QgsProject.instance().addMapLayer(result)
            QMessageBox.information(
                self,
                "Success",
                f"Generated {result.featureCount()} receptor points\n"
                f"Spacing: {spacing}m\n"
                f"Height above terrain: {height}m\n"
                f"Layer: {result.name()}m\n"
                f"Receptors layer added to map.",
            )
        else:
            QMessageBox.critical(
                self,
                "Error",
                "Failed to generate regular receptors.\n"
                "Check the console for detailed error.",
            )

    def generate_around_features(self):
        """Generate receptors around features."""
        if self.combo_terrain.currentIndex() <= 0:
            QMessageBox.warning(
                self,
                "Error",
                "Please select a DEM layer in Terrain tab first.\n\n"
                "The DEM is needed to calculate elevation of receptor points.",
            )
            return

        dem_layer_id = self.combo_terrain.currentData()
        dem_layer = QgsProject.instance().mapLayer(dem_layer_id)

        if not dem_layer or dem_layer.type() != 1:
            QMessageBox.critical(
                self,
                "Error",
                "Selected DEM layer is not valid or not a raster.",
            )
            return

        if self.combo_features_layer.currentIndex() <= 0:
            QMessageBox.warning(
                self,
                "Error",
                "Please select a features layer in Around features group first.",
            )
            return

        features_layer_id = self.combo_features_layer.currentData()
        features_layer = QgsProject.instance().mapLayer(features_layer_id)

        if not features_layer:
            QMessageBox.warning(self, "Error", "Selected features layer is not valid")
            return

        min_dist = self.spin_min_distance.value()
        max_dist = self.spin_max_distance.value()
        spacing = self.spin_around_spacing.value()
        height = self.spin_around_height.value()

        from qgis.core import QgsRectangle

        features_extent = features_layer.extent()
        dem_extent = dem_layer.extent()

        expanded_extent = QgsRectangle(
            features_extent.xMinimum() - max_dist,
            features_extent.yMinimum() - max_dist,
            features_extent.xMaximum() + max_dist,
            features_extent.yMaximum() + max_dist,
        )

        if not dem_extent.contains(expanded_extent):
            QMessageBox.critical(
                self,
                "DEM Extent Error",
                f"The buffer area ({max_dist}m) extends outside the DEM extent.\n\n"
                "Receptors must lie inside the DEM for calculation.\n"
                "Reduce the maximum distance or use a larger DEM."
            )
            return

        generator = AroundFeaturesGenerator()
        result = generator.generate(
            features_layer=features_layer,
            dem_layer=dem_layer,
            min_distance=min_dist,
            max_distance=max_dist,
            spacing=spacing,
            height_above_terrain=height,
        )

        if result:
            QgsProject.instance().addMapLayer(result)
            QMessageBox.information(
                self,
                "Success",
                f"Generated {result.featureCount()} receptor points\n"
                f"Distance: {min_dist} - {max_dist}m\n"
                f"Spacing: {spacing}m\n"
                f"Height above terrain: {height}m\n"
                f"Layer: {result.name()}\n"
                f"Receptors layer added to map.",
            )
        else:
            QMessageBox.critical(
                self,
                "Error",
                "Failed to generate receptors around features.\n"
                "Check the console for detailed error.",
            )

    def reset_groupbox(self, checked, group_type):
        """Reset groupbox to default values when unchecked."""
        if not checked:
            if group_type == "import":
                self.combo_import_layer.setCurrentIndex(0)
                self.spin_import_height.setValue(2)
            elif group_type == "regular":
                self.combo_extent_layer.setCurrentIndex(0)
                self.spin_spacing.setValue(100)
                self.spin_regular_height.setValue(2)
            elif group_type == "around":
                self.combo_features_layer.setCurrentIndex(0)
                self.spin_min_distance.setValue(50)
                self.spin_max_distance.setValue(500)
                self.spin_around_spacing.setValue(50)
                self.spin_around_height.setValue(2)

    def update_max_distance_minimum(self, min_val):
        """Update max distance minimum to be at least min distance."""
        self.spin_max_distance.setMinimum(min_val)
        if self.spin_max_distance.value() < min_val:
            self.spin_max_distance.setValue(min_val)

    def test_receptors_data(self):
        """Test the selected receptor data/generation method."""
        checked_groups = []

        if self.groupBox_import.isChecked():
            if self.combo_import_layer.currentIndex() <= 0:
                QMessageBox.warning(self, "No Layer", "Please select a layer for Import method.")
                return
            checked_groups.append("Import")

        if self.groupBox_regular.isChecked():
            if self.combo_extent_layer.currentIndex() <= 0:
                QMessageBox.warning(self, "No Layer", "Please select a layer for Regular grid method.")
                return
            checked_groups.append("Regular grid")

        if self.groupBox_around.isChecked():
            if self.combo_features_layer.currentIndex() <= 0:
                QMessageBox.warning(
                    self,
                    "No Layer",
                    "Please select a layer for Around features method.",
                )
                return
            checked_groups.append("Around features")

        if not checked_groups:
            QMessageBox.warning(
                self,
                "No Method Selected",
                "Please check at least one receptor generation method.",
            )
            return

        for method in checked_groups:
            if method == "Import":
                self.test_import_method()
            elif method == "Regular grid":
                self.test_regular_method()
            elif method == "Around features":
                self.test_around_method()

        if len(checked_groups) == 1:
            QMessageBox.information(
                self,
                f"{checked_groups[0]} Test",
                f"✓ {checked_groups[0]} method configuration is valid.",
            )
        else:
            QMessageBox.information(
                self,
                "Receptors Test",
                f"✓ Selected methods are valid: {', '.join(checked_groups)}",
            )

    def test_import_method(self):
        """Test import from layer method."""
        layer_id = self.combo_import_layer.currentData()
        layer = QgsProject.instance().mapLayer(layer_id)

        if not layer or not layer.isValid():
            QMessageBox.critical(self, "Error", "Selected import layer is invalid.")
            return False

        crs = layer.crs()
        if not crs.isValid() or crs.authid() == "":
            QMessageBox.critical(
                self,
                "CRS Error",
                "Import layer has no valid CRS defined!\n\n"
                "Please define a CRS for this layer before using it.",
            )
            return False

        if crs.mapUnits() != QgsUnitTypes.DistanceMeters:
            QMessageBox.critical(
                self,
                "CRS Error",
                f"Import layer must be in a metric CRS (meters)!\n"
                f"Current: {crs.authid()} ({crs.mapUnits()})\n\n"
                "Please reproject your layer to a metric CRS (e.g., EPSG:5514, EPSG:32633).",
            )
            return False

        if layer.geometryType() != Qgis.GeometryType.Point:
            QMessageBox.critical(
                self,
                "Geometry Error",
                "Import layer must contain POINT geometries!\n"
                f"Current type: {layer.geometryType()}",
            )
            return False

        return True

    def test_regular_method(self):
        """Test regular grid generation method."""
        layer_id = self.combo_extent_layer.currentData()
        layer = QgsProject.instance().mapLayer(layer_id)

        if not layer or not layer.isValid():
            QMessageBox.critical(self, "Error", "Selected extent layer is invalid.")
            return False

        crs = layer.crs()
        if not crs.isValid() or crs.authid() == "":
            QMessageBox.critical(
                self,
                "CRS Error",
                "Extent layer has no valid CRS defined!\n\n"
                "Please define a CRS for this layer before using it.",
            )
            return False

        if crs.mapUnits() != QgsUnitTypes.DistanceMeters:
            QMessageBox.critical(
                self,
                "CRS Error",
                f"Extent layer must be in a metric CRS (meters)!\n"
                f"Current: {crs.authid()} ({crs.mapUnits()})\n\n"
                "Please reproject your layer to a metric CRS (e.g., EPSG:5514, EPSG:32633).",
            )
            return False

        spacing = self.spin_spacing.value()
        if spacing <= 0:
            QMessageBox.critical(self, "Value Error", "Point spacing must be greater than 0.")
            return False

        return True

    def test_around_method(self):
        """Test around features generation method."""
        layer_id = self.combo_features_layer.currentData()
        layer = QgsProject.instance().mapLayer(layer_id)

        if not layer or not layer.isValid():
            QMessageBox.critical(self, "Error", "Selected features layer is invalid.")
            return False

        crs = layer.crs()
        if not crs.isValid() or crs.authid() == "":
            QMessageBox.critical(
                self,
                "CRS Error",
                "Features layer has no valid CRS defined!\n\n"
                "Please define a CRS for this layer before using it.",
            )
            return False

        if crs.mapUnits() != QgsUnitTypes.DistanceMeters:
            QMessageBox.critical(
                self,
                "CRS Error",
                f"Features layer must be in a metric CRS (meters)!\n"
                f"Current: {crs.authid()} ({crs.mapUnits()})\n\n"
                "Please reproject your layer to a metric CRS (e.g., EPSG:5514, EPSG:32633).",
            )
            return False

        min_distance = self.spin_min_distance.value()
        max_distance = self.spin_max_distance.value()

        if min_distance < 0:
            QMessageBox.critical(self, "Value Error", "Minimum distance must be non-negative.")
            return False

        if max_distance < min_distance:
            QMessageBox.critical(
                self,
                "Value Error",
                "Maximum distance must be greater than or equal to minimum distance.",
            )
            return False

        spacing = self.spin_around_spacing.value()
        if spacing <= 0:
            QMessageBox.critical(self, "Value Error", "Point spacing must be greater than 0.")
            return False

        return True

    def get_receptor_configuration(self):
        """Get current receptor configuration for calculation."""
        config = {
            "methods": [],
            "import": None,
            "regular": None,
            "around": None,
        }

        if self.groupBox_import.isChecked():
            config["methods"].append("import")
            config["import"] = {
                "layer_id": self.combo_import_layer.currentData(),
                "height": self.spin_import_height.value(),
            }

        if self.groupBox_regular.isChecked():
            config["methods"].append("regular")
            config["regular"] = {
                "layer_id": self.combo_extent_layer.currentData(),
                "spacing": self.spin_spacing.value(),
                "height": self.spin_regular_height.value(),
            }

        if self.groupBox_around.isChecked():
            config["methods"].append("around")
            config["around"] = {
                "layer_id": self.combo_features_layer.currentData(),
                "min_distance": self.spin_min_distance.value(),
                "max_distance": self.spin_max_distance.value(),
                "spacing": self.spin_around_spacing.value(),
                "height": self.spin_around_height.value(),
            }

        return config

    # ===== WIND DATA METHODS =====

    def browse_wind_file(self):
        """Browse for wind data XML file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select XML Wind Data File",
            "",
            "XML files (*.xml)",
        )

        if file_path:
            self.wind_file_path = file_path
            self.wind_results = None
            self.wind_file_label.setText(os.path.basename(file_path))
            self.btn_analyze_wind.setEnabled(True)
            self.btn_analyze_wind.setStyleSheet(
                "font-weight: bold; padding: 8px; background-color: #4CAF50; color: white;"
            )
            self.wind_data_valid = True
            self.update_validation_status()
            QgsMessageLog.logMessage(f"Wind file selected: {file_path}", "OpenSymos", Qgis.Info)

    def analyze_wind_data(self):
        """Analyze wind rose data."""
        if not self.wind_file_path:
            QMessageBox.warning(self, "No File", "Please select a wind data file first.")
            return

        if not os.path.exists(self.wind_file_path):
            QMessageBox.critical(self, "File Error", "Selected file does not exist.")
            return

        try:
            from utils.wind_rose_analyzer import analyze_wind_rose

            self.wind_results_text.setPlainText("Analyzing wind data... Please wait.")
            self.wind_bar_plot_label.setText("Creating bar plot...")
            self.wind_rose_plot_label.setText("Creating wind rose...")
            QApplication.processEvents()

            results = analyze_wind_rose(self.wind_file_path, create_plot=True)

            if results["success"]:
                self.wind_results = results
                self.display_wind_results(results)
                self.btn_export_csv.setEnabled(True)
                self.btn_export_plot.setEnabled(True)

                dominant_dir = results["stats"]["dominant_direction_name"]
                dominant_val = results["stats"]["dominant_value"]

                QMessageBox.information(
                    self,
                    "Analysis Complete",
                    f"✓ Wind rose analysis completed successfully!\n\n"
                    f"• Dominant direction: {dominant_dir}\n"
                    f"• Frequency: {dominant_val:.1f}%\n\n"
                    "You can now export the results.",
                )

                self.lbl_status.setText(
                    f"Status: Wind analysis complete ({dominant_dir} {dominant_val:.1f}%)"
                )

            else:
                QMessageBox.critical(
                    self,
                    "Analysis Failed",
                    f"Failed to analyze wind data:\n{results.get('error', 'Unknown error')}",
                )
                self.wind_results_text.setPlainText(
                    f"ERROR: {results.get('error', 'Unknown error')}"
                )

        except ImportError as e:
            QMessageBox.critical(
                self,
                "Import Error",
                f"Cannot import wind rose analyzer:\n{str(e)}\n\n"
                "Make sure utils/wind_rose_analyzer.py exists in the plugin directory.",
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error during wind analysis:\n{str(e)}")

    def on_bar_plot_clicked(self, event):
        """Handle click on bar plot."""
        if self.wind_results and self.wind_results.get("bar_plot_bytes"):
            pixmap = QPixmap()
            pixmap.loadFromData(self.wind_results["bar_plot_bytes"])
            self.show_enlarged_image(pixmap, "Bar Chart - Enlarged View")

    def on_rose_plot_clicked(self, event):
        """Handle click on wind rose plot."""
        if self.wind_results and self.wind_results.get("rose_plot_bytes"):
            pixmap = QPixmap()
            pixmap.loadFromData(self.wind_results["rose_plot_bytes"])
            self.show_enlarged_image(pixmap, "Wind Rose - Enlarged View")

    def show_enlarged_image(self, pixmap, title):
        """Show enlarged image in a separate dialog."""
        from qgis.PyQt.QtWidgets import QDialog, QVBoxLayout, QLabel

        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setMinimumSize(800, 600)

        layout = QVBoxLayout()
        label = QLabel()

        scaled_pixmap = pixmap.scaled(
            1000,
            600,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )

        label.setPixmap(scaled_pixmap)
        label.setAlignment(Qt.AlignCenter)

        layout.addWidget(label)
        dialog.setLayout(layout)

        dialog.exec_()

    def display_wind_results(self, results):
        """Display wind analysis results."""
        self.wind_results_text.setPlainText(results["report"])

        if results.get("bar_plot_bytes"):
            pixmap = QPixmap()
            pixmap.loadFromData(results["bar_plot_bytes"])
            self.wind_bar_plot_label.setPixmap(pixmap)
            self.wind_bar_plot_label.setText("")
            self.wind_bar_plot_label.mousePressEvent = self.on_bar_plot_clicked
            self.wind_bar_plot_label.setCursor(Qt.PointingHandCursor)

        if results.get("rose_plot_bytes"):
            pixmap = QPixmap()
            pixmap.loadFromData(results["rose_plot_bytes"])
            self.wind_rose_plot_label.setPixmap(pixmap)
            self.wind_rose_plot_label.setText("")
            self.wind_rose_plot_label.mousePressEvent = self.on_rose_plot_clicked
            self.wind_rose_plot_label.setCursor(Qt.PointingHandCursor)

    def export_wind_csv(self):
        """Export wind analysis to CSV."""
        if not self.wind_results:
            QMessageBox.warning(self, "No Data", "No analysis results to export.")
            return

        default_name = os.path.splitext(os.path.basename(self.wind_file_path))[0] + "_analysis.csv"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Analysis to CSV",
            default_name,
            "CSV files (*.csv)",
        )

        if file_path:
            try:
                from utils.wind_rose_analyzer import export_to_csv

                export_to_csv(self.wind_results["df"], file_path)
                QMessageBox.information(
                    self,
                    "Export Complete",
                    f"Analysis data exported to:\n{file_path}",
                )
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export CSV:\n{str(e)}")

    def export_wind_plot(self):
        """Export the selected wind analysis plot to PNG."""
        if not self.wind_results:
            QMessageBox.warning(self, "No Data", "No analysis results to export.")
            return

        has_bar_plot = bool(self.wind_results.get("bar_plot_bytes"))
        has_rose_plot = bool(self.wind_results.get("rose_plot_bytes"))

        if not has_bar_plot and not has_rose_plot:
            QMessageBox.warning(self, "No Plots", "No plot data available to export.")
            return

        plot_bytes = None
        plot_name = "Plot"
        default_suffix = "_plot.png"

        if has_bar_plot and has_rose_plot:
            msg = QMessageBox(self)
            msg.setWindowTitle("Select Plot to Export")
            msg.setText("Which plot would you like to export?")
            bar_button = msg.addButton("Bar Plot", QMessageBox.AcceptRole)
            rose_button = msg.addButton("Wind Rose", QMessageBox.AcceptRole)
            cancel_button = msg.addButton(QMessageBox.Cancel)

            msg.exec_()
            clicked = msg.clickedButton()

            if clicked == cancel_button:
                return
            elif clicked == bar_button:
                plot_bytes = self.wind_results["bar_plot_bytes"]
                plot_name = "Bar Plot"
                default_suffix = "_bar_plot.png"
            elif clicked == rose_button:
                plot_bytes = self.wind_results["rose_plot_bytes"]
                plot_name = "Wind Rose"
                default_suffix = "_wind_rose.png"
            else:
                return

        elif has_bar_plot:
            plot_bytes = self.wind_results["bar_plot_bytes"]
            plot_name = "Bar Plot"
            default_suffix = "_bar_plot.png"

        elif has_rose_plot:
            plot_bytes = self.wind_results["rose_plot_bytes"]
            plot_name = "Wind Rose"
            default_suffix = "_wind_rose.png"

        default_name = os.path.splitext(os.path.basename(self.wind_file_path))[0] + default_suffix

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export {plot_name} to PNG",
            default_name,
            "PNG files (*.png)",
        )

        if not file_path:
            return

        try:
            with open(file_path, "wb") as file:
                file.write(plot_bytes)
            QMessageBox.information(
                self,
                "Export Complete",
                f"{plot_name} exported to:\n{file_path}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export plot:\n{str(e)}")

    def clear_wind_results(self):
        """Clear wind analysis results."""
        self.wind_results_text.clear()
        self.wind_bar_plot_label.clear()
        self.wind_bar_plot_label.setText("Bar plot will appear here after analysis")
        self.wind_rose_plot_label.clear()
        self.wind_rose_plot_label.setText("Wind rose will appear here after analysis")
        self.btn_export_csv.setEnabled(False)
        self.btn_export_plot.setEnabled(False)
        self.wind_results = None
        self.btn_analyze_wind.setStyleSheet("font-weight: bold; padding: 8px;")

    # ===== VALIDATION & CALCULATION =====

    def update_validation_status(self):
        """Update validation status based on all inputs."""
        all_valid = self.validate_all_silent()

        if all_valid:
            self.lbl_status.setText("Status: Ready for calculation")
            self.btn_calculate.setEnabled(True)
            self.big_calc_button.setEnabled(True)
        else:
            self.lbl_status.setText("Status: Waiting for data")
            self.btn_calculate.setEnabled(False)
            self.big_calc_button.setEnabled(False)

    def validate_all(self):
        """Validate all input data."""
        messages = []
        used_crs = {}
        all_valid = True

        # ===== TERRAIN =====
        if self.combo_terrain.currentIndex() <= 0:
            messages.append("✗ Terrain: No layer selected")
            self.terrain_layer_valid = False
            all_valid = False
        else:
            layer = QgsProject.instance().mapLayer(self.combo_terrain.currentData())
            if layer and layer.isValid():
                crs = layer.crs()
                if crs.isValid() and crs.authid() != "":
                    if crs.mapUnits() == QgsUnitTypes.DistanceMeters:
                        messages.append(f"✓ Terrain: Valid metric layer ({crs.authid()})")
                        used_crs["Terrain"] = crs.authid()
                        self.terrain_layer_valid = True
                    else:
                        messages.append(f"✗ Terrain: NON-METRIC CRS ({crs.authid()})")
                        self.terrain_layer_valid = False
                        all_valid = False
                else:
                    messages.append("✗ Terrain: No valid CRS defined")
                    self.terrain_layer_valid = False
                    all_valid = False
            else:
                messages.append("✗ Terrain: Invalid layer")
                self.terrain_layer_valid = False
                all_valid = False

        # ===== SOURCES =====
        selected_sources = self.get_selected_source_layers()

        if not selected_sources:
            messages.append("✗ Sources: No layer selected")
            self.sources_layer_valid = False
            all_valid = False
        else:
            sources_valid = True

            for source_info in selected_sources:
                source_type = source_info["type"]
                layer = source_info["layer"]

                crs = layer.crs()
                if crs.isValid() and crs.authid() != "":
                    if crs.mapUnits() == QgsUnitTypes.DistanceMeters:
                        messages.append(f"✓ Sources ({source_type}): {layer.name()} ({crs.authid()})")
                        used_crs[f"Sources ({source_type})"] = crs.authid()
                    else:
                        messages.append(f"✗ Sources ({source_type}): NON-METRIC CRS ({crs.authid()})")
                        sources_valid = False
                        all_valid = False
                else:
                    messages.append(f"✗ Sources ({source_type}): No valid CRS defined")
                    sources_valid = False
                    all_valid = False

            selected_types = [item["type"] for item in selected_sources]
            messages.append(f"• Selected source types: {', '.join(selected_types)}")

            if len(selected_sources) > 1:
                messages.append(
                    "⚠ Warning: Multiple source layers are selected and all of them "
                    f"will be included in the calculation ({', '.join(selected_types)})"
                )

            self.sources_layer_valid = sources_valid

        # ===== RECEPTORS =====
        receptor_config = self.get_receptor_configuration()
        if not receptor_config["methods"]:
            messages.append("✗ Receptors: No method selected")
            self.receptors_layer_valid = False
            all_valid = False
        else:
            receptors_valid = True
            for method in receptor_config["methods"]:
                if method == "import":
                    layer = QgsProject.instance().mapLayer(receptor_config["import"]["layer_id"])
                    if layer and layer.isValid():
                        crs = layer.crs()
                        if crs.isValid() and crs.authid() != "":
                            if crs.mapUnits() == QgsUnitTypes.DistanceMeters:
                                if layer.geometryType() == Qgis.GeometryType.Point:
                                    used_crs["Receptors (Import)"] = crs.authid()
                                    messages.append(f"✓ Receptors (Import): Point layer ({crs.authid()})")
                                else:
                                    messages.append("✗ Receptors (Import): Must be POINT layer")
                                    receptors_valid = False
                                    all_valid = False
                            else:
                                messages.append(f"✗ Receptors (Import): NON-METRIC CRS ({crs.authid()})")
                                receptors_valid = False
                                all_valid = False
                        else:
                            messages.append("✗ Receptors (Import): No valid CRS defined")
                            receptors_valid = False
                            all_valid = False
                    else:
                        messages.append("✗ Receptors (Import): Invalid layer")
                        receptors_valid = False
                        all_valid = False

                elif method == "regular":
                    layer = QgsProject.instance().mapLayer(receptor_config["regular"]["layer_id"])
                    if layer and layer.isValid():
                        crs = layer.crs()
                        if crs.isValid() and crs.authid() != "":
                            if crs.mapUnits() == QgsUnitTypes.DistanceMeters:
                                used_crs["Receptors (Regular)"] = crs.authid()
                                messages.append(f"✓ Receptors (Regular): Extent layer ({crs.authid()})")
                            else:
                                messages.append(f"✗ Receptors (Regular): NON-METRIC CRS ({crs.authid()})")
                                receptors_valid = False
                                all_valid = False
                        else:
                            messages.append("✗ Receptors (Regular): No valid CRS defined")
                            receptors_valid = False
                            all_valid = False
                    else:
                        messages.append("✗ Receptors (Regular): Invalid layer")
                        receptors_valid = False
                        all_valid = False

                elif method == "around":
                    layer = QgsProject.instance().mapLayer(receptor_config["around"]["layer_id"])
                    if layer and layer.isValid():
                        crs = layer.crs()
                        if crs.isValid() and crs.authid() != "":
                            if crs.mapUnits() == QgsUnitTypes.DistanceMeters:
                                used_crs["Receptors (Around)"] = crs.authid()
                                messages.append(f"✓ Receptors (Around): Features layer ({crs.authid()})")
                            else:
                                messages.append(f"✗ Receptors (Around): NON-METRIC CRS ({crs.authid()})")
                                receptors_valid = False
                                all_valid = False
                        else:
                            messages.append("✗ Receptors (Around): No valid CRS defined")
                            receptors_valid = False
                            all_valid = False
                    else:
                        messages.append("✗ Receptors (Around): Invalid layer")
                        receptors_valid = False
                        all_valid = False

            self.receptors_layer_valid = receptors_valid
            selected_receptor_methods = self.get_selected_receptor_methods()
            if selected_receptor_methods:
                messages.append(f"• Selected receptor methods: {', '.join(selected_receptor_methods)}")

                if len(selected_receptor_methods) > 1:
                    messages.append(
                        f"⚠ Warning: Multiple receptor methods are selected ({', '.join(selected_receptor_methods)})"
                    )

        # ===== WIND DATA =====
        if not self.wind_file_path:
            messages.append("✗ Wind: No XML file selected")
            self.wind_data_valid = False
            all_valid = False
        else:
            messages.append("✓ Wind: XML file selected")
            self.wind_data_valid = True

        # ===== CRS CONSISTENCY CHECK =====
        if len(used_crs) > 1:
            unique_crs = set(used_crs.values())
            if len(unique_crs) > 1:
                mismatch_detail = ", ".join([f"{key}: {value}" for key, value in used_crs.items()])
                messages.append("\n❌ CRITICAL: CRS MISMATCH!")
                messages.append("All layers must have identical CRS:")
                messages.append(mismatch_detail)
                all_valid = False
                self.terrain_layer_valid = False
                self.sources_layer_valid = False
                self.receptors_layer_valid = False
            else:
                common_crs = list(unique_crs)[0]
                messages.append(f"\n✓ CRS Alignment: All layers use {common_crs}")

        # ===== FINAL STATUS =====
        if all_valid:
            messages.append("\n✅ ALL INPUTS VALID")
        else:
            messages.append("\n❌ Validation FAILED - Please fix the issues above")

        result_text = "=== VALIDATION RESULTS ===\n" + "\n".join(messages)
        QMessageBox.information(self, "Validation", result_text)

        self.update_validation_status()
        return all_valid

    def validate_all_silent(self):
        """Validate all input data without showing dialog."""
        all_valid = True

        # ===== TERRAIN =====
        if self.combo_terrain.currentIndex() <= 0:
            all_valid = False
        else:
            layer = QgsProject.instance().mapLayer(self.combo_terrain.currentData())
            if layer and layer.isValid():
                crs = layer.crs()
                if not (crs.isValid() and crs.authid() != "" and crs.mapUnits() == QgsUnitTypes.DistanceMeters):
                    all_valid = False
            else:
                all_valid = False

        # ===== SOURCES =====
        selected_sources = self.get_selected_source_layers()

        if not selected_sources:
            all_valid = False
        else:
            for source_info in selected_sources:
                layer = source_info["layer"]
                if not (layer and layer.isValid()):
                    all_valid = False
                else:
                    crs = layer.crs()
                    if not (crs.isValid() and crs.authid() != "" and crs.mapUnits() == QgsUnitTypes.DistanceMeters):
                        all_valid = False

        # ===== RECEPTORS =====
        receptor_config = self.get_receptor_configuration()
        if not receptor_config["methods"]:
            all_valid = False
        else:
            for method in receptor_config["methods"]:
                if method == "import":
                    layer = QgsProject.instance().mapLayer(receptor_config["import"]["layer_id"])
                    if not (layer and layer.isValid()):
                        all_valid = False
                    else:
                        crs = layer.crs()
                        if not (crs.isValid() and crs.authid() != "" and crs.mapUnits() == QgsUnitTypes.DistanceMeters):
                            all_valid = False
                        if layer.geometryType() != Qgis.GeometryType.Point:
                            all_valid = False

                elif method == "regular":
                    layer = QgsProject.instance().mapLayer(receptor_config["regular"]["layer_id"])
                    if not (layer and layer.isValid()):
                        all_valid = False
                    else:
                        crs = layer.crs()
                        if not (crs.isValid() and crs.authid() != "" and crs.mapUnits() == QgsUnitTypes.DistanceMeters):
                            all_valid = False

                elif method == "around":
                    layer = QgsProject.instance().mapLayer(receptor_config["around"]["layer_id"])
                    if not (layer and layer.isValid()):
                        all_valid = False
                    else:
                        crs = layer.crs()
                        if not (crs.isValid() and crs.authid() != "" and crs.mapUnits() == QgsUnitTypes.DistanceMeters):
                            all_valid = False

        # ===== WIND DATA =====
        if not self.wind_file_path:
            all_valid = False

        # ===== CRS CONSISTENCY CHECK =====
        if all_valid:
            crs_list = []

            layer = QgsProject.instance().mapLayer(self.combo_terrain.currentData())
            if layer and layer.isValid():
                crs_list.append(layer.crs().authid())

            for source_info in self.get_selected_source_layers():
                layer = source_info["layer"]
                if layer and layer.isValid():
                    crs_list.append(layer.crs().authid())

            receptor_config = self.get_receptor_configuration()
            for method in receptor_config["methods"]:
                if method == "import":
                    layer = QgsProject.instance().mapLayer(receptor_config["import"]["layer_id"])
                    if layer and layer.isValid():
                        crs_list.append(layer.crs().authid())
                elif method == "regular":
                    layer = QgsProject.instance().mapLayer(receptor_config["regular"]["layer_id"])
                    if layer and layer.isValid():
                        crs_list.append(layer.crs().authid())
                elif method == "around":
                    layer = QgsProject.instance().mapLayer(receptor_config["around"]["layer_id"])
                    if layer and layer.isValid():
                        crs_list.append(layer.crs().authid())

            if len(set(crs_list)) > 1:
                all_valid = False

        return all_valid

    def go_to_calculation_tab(self):
        """Switch to calculation tab only if all data is valid."""
        is_valid = self.validate_all_silent()

        if is_valid:
            self.tabWidget.setCurrentIndex(5)
        else:
            self.validate_all()

    # ===================================================================
    # CALCULATION
    # ===================================================================

    def run_calculation(self):
        """Run SYMOS dispersion calculation in a separate thread."""
        if not self.validate_all_silent():
            self.lbl_status.setText("Status: Validation failed")
            self.text_log.append("❌ Calculation aborted: current inputs are not valid.")
            return

        selected_sources = self.get_selected_source_layers()
        selected_source_types = [item["type"] for item in selected_sources]
        selected_receptor_methods = self.get_selected_receptor_methods()

        if not selected_sources:
            self.lbl_status.setText("Status: Validation failed")
            self.text_log.append("❌ Calculation aborted: no source layers selected.")
            return

        source_warning_text = f"Selected source types: {', '.join(selected_source_types)}"
        if len(selected_sources) > 1:
            source_warning_text += "\n\nWarning: all selected source layers will be included in the calculation."

        receptor_warning_text = f"Selected receptor methods: {', '.join(selected_receptor_methods)}"
        if len(selected_receptor_methods) > 1:
            receptor_warning_text += "\nWarning: multiple receptor methods are selected."

        reply = QMessageBox.question(
            self,
            "Confirm Calculation",
            "Start SYMOS dispersion model calculation?\n\n"
            f"{source_warning_text}\n\n"
            f"{receptor_warning_text}\n\n"
            "This may take several minutes.\n"
            "You can abort the calculation at any time.",
            QMessageBox.Yes | QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        self.lbl_status.setText("Status: Preparing data...")
        self.btn_calculate.setEnabled(False)
        self.big_calc_button.setEnabled(False)
        self.btn_validate.setEnabled(False)
        self.btn_abort.setEnabled(True)
        self.calculation_aborted = False

        self.text_log.clear()
        self.text_log.append("=== SYMOS'97 CALCULATION ===")
        self.text_log.append(f"Selected source types: {', '.join(selected_source_types)}")
        if len(selected_sources) > 1:
            self.text_log.append("⚠ Multiple source layers are selected and all of them will be used.")
        self.text_log.append(f"Concentration type: {self.combo_concentration_type.currentText()}")

        self.text_log.append("\n--- Loading input data ---")

        # 3.1 DEM
        terrain = None
        dem_layer = None
        if self.combo_terrain.currentIndex() > 0:
            dem_layer_id = self.combo_terrain.currentData()
            dem_layer = QgsProject.instance().mapLayer(dem_layer_id)
            if dem_layer:
                from opensymos.core.terrain import Terrain
                try:
                    terrain = Terrain(dem_layer)
                    self.text_log.append(f"✓ DEM: {dem_layer.name()} loaded")
                    self.text_log.append(f"   Pixel size: {terrain.pixel_size:.1f} m")
                    self.text_log.append(f"   Extent: {terrain.extent.toString()}")
                except Exception as e:
                    self.text_log.append(f"⚠ Error loading DEM: {str(e)}")
                    terrain = None
        else:
            self.text_log.append("⚠ No DEM selected - using flat terrain")

        # 3.2 Wind rose
        wind_rose = None

        try:
            from opensymos.core.wind_rose import WindRose
            from utils.wind_rose_analyzer import parse_wind_rose_xml

            df = None

            # Reuse already analyzed data if available
            if hasattr(self, "wind_results") and self.wind_results:
                if isinstance(self.wind_results, dict) and "df" in self.wind_results:
                    analyzed_df = self.wind_results["df"]
                    if analyzed_df is not None and not analyzed_df.empty:
                        df = analyzed_df
                        self.text_log.append(f"✓ Wind rose: using analyzed data ({len(df)} records)")

            # Otherwise load XML directly for calculation
            if df is None:
                if self.wind_file_path and os.path.exists(self.wind_file_path):
                    df = parse_wind_rose_xml(self.wind_file_path)
                    self.text_log.append(f"✓ Wind rose: loaded directly from XML ({len(df)} records)")
                else:
                    self.text_log.append("❌ Wind rose XML file not found")

            if df is not None and not df.empty:
                wind_rose = WindRose(df)
            else:
                self.text_log.append("❌ Wind rose data are missing or empty")
                QMessageBox.critical(
                    self,
                    "Wind Rose Error",
                    "Wind rose data could not be loaded for calculation."
                )
                self.calculation_finished(None)
                return

        except Exception as e:
            error_text = str(e)

            if "Invalid wind rose format" in error_text:
                user_msg = (
                    "Invalid wind rose format.\n\n"
                    "Expected XML structure with elements:\n"
                    "• <trida_stability id=\"...\">\n"
                    "• <bezvetri value=\"...\" />\n"
                    "• <rychlost value=\"...\">\n"
                    "• <cetnosti s=\"...\" sv=\"...\" v=\"...\" jv=\"...\" j=\"...\" jz=\"...\" z=\"...\" sz=\"...\" />"
                )
            else:
                user_msg = f"Failed to load wind rose data:\n{error_text}"

            self.text_log.append(f"❌ Error loading wind rose: {error_text}")
            QMessageBox.critical(self, "Wind Rose Error", user_msg)
            self.calculation_finished(None)
            return

        # 4. Sources
        sources = []
        source_count = 0

        # 4.1 Point sources
        if self.combo_point_layer.currentIndex() > 0:
            layer_id = self.combo_point_layer.currentData()
            layer = QgsProject.instance().mapLayer(layer_id)

            self.text_log.append(f"\n--- Processing point sources: {layer.name()} ---")

            for feature in layer.getFeatures():
                field_names = [field.name() for field in feature.fields()]

                source_id = feature.id()
                for field_name in field_names:
                    if field_name.lower() == "id":
                        source_id = feature[field_name]
                        break

                source = Source(
                    source_id=source_id,
                    geometry=feature.geometry(),
                    source_type="point",
                )

                emission_field = self.combo_point_emission.currentText()
                if emission_field and emission_field in field_names:
                    emission = feature[emission_field]
                else:
                    emission = 0.0
                    self.text_log.append(
                        f"  ⚠ Feature {source_id}: emission field '{emission_field}' not found"
                    )

                height_field = self.combo_point_height.currentText()
                height = feature[height_field] if height_field in field_names else 15.0

                temp_field = self.combo_point_temp.currentText()
                temp = feature[temp_field] if temp_field in field_names else 80.0

                diam_field = self.combo_point_diam.currentText()
                diam = feature[diam_field] if diam_field in field_names else 0.5

                vel_field = self.combo_point_vel.currentText()
                vel = feature[vel_field] if vel_field in field_names else 8.0

                volume_field = self.combo_point_volume.currentText()
                volume = feature[volume_field] if volume_field in field_names else 4.0

                year_field = self.combo_point_year.currentText()
                year_use_raw = feature[year_field] if year_field in field_names else 100.0
                year_use = float(year_use_raw)

                if year_use > 1.0:
                    year_use /= 100.0

                year_use = max(0.0, min(1.0, year_use))

                day_field = self.combo_point_day.currentText()
                day_use_raw = feature[day_field] if day_field in field_names else 24.0
                day_use = float(day_use_raw)

                if day_use > 24.0:
                    day_use = 24.0
                elif day_use < 0.0:
                    day_use = 0.0

                annual_util = year_use * (day_use / 24.0)

                source.set_emission_params(emission, annual_util)
                
                source.set_stack_params(height, temp, diam, vel, volume)

                if not self._set_source_elevation_or_fail(source, terrain, "Source"):
                    return

                sources.append(source)
                source_count += 1

        # 4.2 Line sources
        if self.combo_line_layer.currentIndex() > 0:
            layer_id = self.combo_line_layer.currentData()
            layer = QgsProject.instance().mapLayer(layer_id)

            if layer:
                self.text_log.append(f"\n--- Processing line sources: {layer.name()} ---")

                try:
                    id_field = self.combo_line_id.currentText().strip()
                    emission_field = self.combo_line_emission.currentText().strip()
                    height_field = self.combo_line_height.currentText().strip()
                    year_field = self.combo_line_year.currentText().strip()
                    day_field = self.combo_line_day.currentText().strip()

                    field_names = [field.name() for field in layer.fields()]

                    if emission_field not in field_names:
                        self.text_log.append(
                            f"❌ Line emission field '{emission_field}' not found in layer"
                        )
                    else:
                        line_spacing = float(self.spin_line_spacing.value())

                        self.text_log.append(
                            f"   Converting lines to points (spacing = {line_spacing} m)"
                        )
                        self.text_log.append(
                            f"   Expected total line emission field: {emission_field} [g/s]"
                        )

                        converter = LineToPointConverter()
                        line_points_layer = converter.convert(
                            line_layer=layer,
                            spacing=line_spacing,
                            emission_field=emission_field,
                            id_field=id_field if id_field in field_names else None,
                        )

                        if line_points_layer is None:
                            self.text_log.append("❌ Line-to-point conversion failed")
                        else:
                            self.text_log.append(
                                f"✓ Line-to-point conversion created "
                                f"{line_points_layer.featureCount()} points"
                            )

                            for feature in line_points_layer.getFeatures():
                                point_field_names = [field.name() for field in feature.fields()]

                                if id_field and id_field in point_field_names:
                                    source_id = feature[id_field]
                                elif "orig_line_id" in point_field_names:
                                    source_id = feature["orig_line_id"]
                                else:
                                    source_id = feature.id()

                                source = Source(
                                    source_id=source_id,
                                    geometry=feature.geometry(),
                                    source_type="line",
                                )

                                point_emission = (
                                    feature["point_emission"]
                                    if "point_emission" in point_field_names
                                    else None
                                )

                                if point_emission is None:
                                    self.text_log.append(
                                        f"  ⚠ Line-derived point {feature.id()} has no point_emission, skipping"
                                    )
                                    continue

                                if height_field and height_field in point_field_names:
                                    release_height_val = feature[height_field]
                                else:
                                    release_height_val = Source.DEFAULTS["line"]["release_height"]

                                year_use_raw = (
                                    feature[year_field]
                                    if year_field and year_field in point_field_names
                                    else 100.0
                                )
                                year_use = float(year_use_raw)

                                if year_use > 1.0:
                                    year_use /= 100.0
                                year_use = max(0.0, min(1.0, year_use))

                                day_use_raw = (
                                    feature[day_field]
                                    if day_field and day_field in point_field_names
                                    else 24.0
                                )
                                day_use = float(day_use_raw)
                                day_use = max(0.0, min(24.0, day_use))

                                annual_util = year_use * (day_use / 24.0)

                                source.set_emission_params(float(point_emission), annual_util)
                                source.set_release_height(float(release_height_val))
                                source.set_line_params()

                                segment_id = (
                                    feature["segment_id"] if "segment_id" in point_field_names else None
                                )
                                segment_length = (
                                    feature["segment_length"] if "segment_length" in point_field_names else None
                                )

                                if segment_id is not None and segment_length is not None:
                                    point_geom = feature.geometry().asPoint()
                                    source.set_segment_data(
                                        segment_id=int(segment_id),
                                        start_point=QgsPointXY(point_geom.x(), point_geom.y()),
                                        end_point=QgsPointXY(point_geom.x(), point_geom.y()),
                                        segment_length=float(segment_length),
                                    )

                                if not self._set_source_elevation_or_fail(source, terrain, "Line source"):
                                    return

                                sources.append(source)
                                source_count += 1

                                if source_count % 25 == 0:
                                    self.text_log.append(f"  Loaded {source_count} sources...")

                            self.text_log.append(
                                f"✓ Loaded line sources as {line_points_layer.featureCount()} point approximations"
                            )

                except Exception as e:
                    self.text_log.append(f"❌ Error processing line sources: {str(e)}")

        # 4.3 Area sources
        if self.combo_area_layer.currentIndex() > 0:
            layer_id = self.combo_area_layer.currentData()
            layer = QgsProject.instance().mapLayer(layer_id)

            if layer:
                self.text_log.append(f"\n--- Processing area sources: {layer.name()} ---")

                try:
                    id_field = self.combo_area_id.currentText().strip()
                    emission_field = self.combo_area_emission.currentText().strip()
                    height_field = self.combo_area_height.currentText().strip()
                    year_field = self.combo_area_year.currentText().strip()
                    day_field = self.combo_area_day.currentText().strip()

                    field_names = [field.name() for field in layer.fields()]

                    if emission_field not in field_names:
                        self.text_log.append(
                            f"❌ Area emission field '{emission_field}' not found in layer"
                        )
                    else:
                        area_spacing = float(self.spin_area_spacing.value())

                        self.text_log.append(
                            f"   Converting polygons to points (spacing = {area_spacing} m)"
                        )
                        self.text_log.append(
                            f"   Expected total polygon emission field: {emission_field} [g/s]"
                        )

                        converter = PolygonToPointConverter()
                        area_points_layer = converter.convert(
                            polygon_layer=layer,
                            spacing=area_spacing,
                            emission_field=emission_field,
                            id_field=id_field if id_field in field_names else None,
                        )

                        if area_points_layer is None:
                            self.text_log.append("❌ Polygon-to-point conversion failed")
                        else:
                            self.text_log.append(
                                f"✓ Polygon-to-point conversion created "
                                f"{area_points_layer.featureCount()} points"
                            )

                            for feature in area_points_layer.getFeatures():
                                point_field_names = [field.name() for field in feature.fields()]

                                if id_field and id_field in point_field_names:
                                    source_id = feature[id_field]
                                elif "orig_area_id" in point_field_names:
                                    source_id = feature["orig_area_id"]
                                else:
                                    source_id = feature.id()

                                source = Source(
                                    source_id=source_id,
                                    geometry=feature.geometry(),
                                    source_type="area",
                                )

                                point_emission = (
                                    feature["point_emission"]
                                    if "point_emission" in point_field_names
                                    else None
                                )

                                if point_emission is None:
                                    self.text_log.append(
                                        f"  ⚠ Area-derived point {feature.id()} has no point_emission, skipping"
                                    )
                                    continue

                                if height_field and height_field in point_field_names:
                                    release_height_val = feature[height_field]
                                else:
                                    release_height_val = Source.DEFAULTS["area"]["release_height"]

                                year_use_raw = (
                                    feature[year_field]
                                    if year_field and year_field in point_field_names
                                    else 100.0
                                )
                                year_use = float(year_use_raw)

                                if year_use > 1.0:
                                    year_use /= 100.0
                                year_use = max(0.0, min(1.0, year_use))

                                day_use_raw = (
                                    feature[day_field]
                                    if day_field and day_field in point_field_names
                                    else 24.0
                                )
                                day_use = float(day_use_raw)
                                day_use = max(0.0, min(24.0, day_use))

                                annual_util = year_use * (day_use / 24.0)

                                source.set_emission_params(float(point_emission), annual_util)
                                source.set_release_height(float(release_height_val))
                                source.set_area_params()

                                if not self._set_source_elevation_or_fail(source, terrain, "Area source"):
                                    return

                                sources.append(source)
                                source_count += 1

                                if source_count % 25 == 0:
                                    self.text_log.append(f"  Loaded {source_count} sources...")

                            self.text_log.append(
                                f"✓ Loaded area sources as {area_points_layer.featureCount()} point approximations"
                            )

                except Exception as e:
                    self.text_log.append(f"❌ Error processing area sources: {str(e)}")

        # 5. Receptors
        receptors = []
        receptor_count = 0

        if self.groupBox_import.isChecked() and self.combo_import_layer.currentIndex() > 0:
            layer_id = self.combo_import_layer.currentData()
            layer = QgsProject.instance().mapLayer(layer_id)

            self.text_log.append(f"\n--- Processing imported receptors: {layer.name()} ---")
            imported_count = 0
            skipped_imported = {"count": 0}

            for feature in layer.getFeatures():
                field_names = [field.name() for field in feature.fields()]

                receptor_id = feature.id()
                for field_name in field_names:
                    if field_name.lower() == "id":
                        receptor_id = feature[field_name]
                        break

                receptor = Receptor.from_point_geometry(
                    receptor_id=receptor_id,
                    point_geom=feature.geometry(),
                    height_above=self.spin_import_height.value(),
                )

                if not self._set_receptor_elevation_or_skip(receptor, terrain, skipped_imported):
                    continue

                receptors.append(receptor)
                imported_count += 1
                receptor_count += 1

                if receptor_count % 100 == 0:
                    self.text_log.append(f"  Loaded {receptor_count} receptors...")

            self.text_log.append(f"✓ Loaded {imported_count} imported receptors")
            if skipped_imported["count"] > 0:
                self.text_log.append(
                    f"⚠ Skipped {skipped_imported['count']} imported receptor(s) outside DEM extent or on NoData"
                )

        if self.groupBox_regular.isChecked() and self.combo_extent_layer.currentIndex() > 0:
            extent_layer_id = self.combo_extent_layer.currentData()
            extent_layer = QgsProject.instance().mapLayer(extent_layer_id)

            self.text_log.append(f"\n--- Generating regular grid receptors from: {extent_layer.name()} ---")

            if terrain is None or dem_layer is None:
                self.text_log.append("❌ Cannot generate regular grid receptors without DEM")
            else:
                generator = RegularReceptorGenerator()
                generated_layer = generator.generate(
                    extent_layer=extent_layer,
                    dem_layer=dem_layer,
                    spacing=self.spin_spacing.value(),
                    height_above_terrain=self.spin_regular_height.value(),
                )

                if generated_layer is None:
                    self.text_log.append("❌ Failed to generate regular grid receptors")
                else:
                    regular_count = 0
                    skipped_regular = {"count": 0}

                    for feature in generated_layer.getFeatures():
                        point = feature.geometry().asPoint()

                        receptor = Receptor.from_grid(
                            receptor_id=int(feature.id()),
                            x=point.x(),
                            y=point.y(),
                            grid_type="regular",
                        )
                        receptor.set_height_above(self.spin_regular_height.value())

                        if not self._set_receptor_elevation_or_skip(receptor, terrain, skipped_regular):
                            continue

                        receptors.append(receptor)
                        regular_count += 1
                        receptor_count += 1

                        if receptor_count % 100 == 0:
                            self.text_log.append(f"  Loaded {receptor_count} receptors...")

                    self.text_log.append(f"✓ Generated and loaded {regular_count} regular grid receptors")
                    if skipped_regular["count"] > 0:
                        self.text_log.append(
                            f"⚠ Skipped {skipped_regular['count']} regular receptor(s) outside DEM extent or on NoData"
                        )

        if self.groupBox_around.isChecked() and self.combo_features_layer.currentIndex() > 0:
            features_layer_id = self.combo_features_layer.currentData()
            features_layer = QgsProject.instance().mapLayer(features_layer_id)

            self.text_log.append(f"\n--- Generating receptors around features: {features_layer.name()} ---")

            if terrain is None or dem_layer is None:
                self.text_log.append("❌ Cannot generate around-features receptors without DEM")
            else:
                generator = AroundFeaturesGenerator()
                generated_layer = generator.generate(
                    features_layer=features_layer,
                    dem_layer=dem_layer,
                    min_distance=self.spin_min_distance.value(),
                    max_distance=self.spin_max_distance.value(),
                    spacing=self.spin_around_spacing.value(),
                    height_above_terrain=self.spin_around_height.value(),
                )

                if generated_layer is None:
                    self.text_log.append("❌ Failed to generate receptors around features")
                else:
                    around_count = 0

                    for feature in generated_layer.getFeatures():
                        point = feature.geometry().asPoint()

                        receptor = Receptor.from_grid(
                            receptor_id=int(feature.id()),
                            x=point.x(),
                            y=point.y(),
                            grid_type="around",
                        )
                        receptor.set_height_above(self.spin_around_height.value())

                        if not self._set_elevation_or_fail(receptor, terrain, "Receptor"):
                            return

                        receptors.append(receptor)
                        around_count += 1
                        receptor_count += 1

                        if receptor_count % 100 == 0:
                            self.text_log.append(f"  Loaded {receptor_count} receptors...")

                    self.text_log.append(f"✓ Generated and loaded {around_count} around-features receptors")

        if not receptors:
            self.text_log.append("❌ No valid receptors found")
            QMessageBox.critical(self, "Error", "No valid receptors found for calculation")
            self.calculation_finished(None)
            return

        # 6. Calculation type
        calc_type_text = self.combo_concentration_type.currentText()
        calculation_type = Calculator.MAX_SHORT_TERM
        limit_value = None

        if "Maximum short-time" in calc_type_text:
            calculation_type = Calculator.MAX_SHORT_TERM
            self.text_log.append("\n--- Calculation type: Maximum short-term concentrations ---")
        elif "Mean (year)" in calc_type_text:
            calculation_type = Calculator.ANNUAL_AVERAGE
            self.text_log.append("\n--- Calculation type: Annual average concentrations ---")
            if wind_rose is None:
                self.text_log.append("⚠ Warning: Annual average without wind rose will be approximate")
        elif "Time of limit exceeding" in calc_type_text:
            calculation_type = Calculator.EXCEEDANCE_TIME
            self.text_log.append("\n--- Calculation type: Time of limit exceedance ---")
            limit_value = self.spin_limit.value()
            self.text_log.append(f"   Limit value: {limit_value} μg/m³")
            if wind_rose is None:
                self.text_log.append("⚠ Warning: Exceedance time without wind rose will be approximate")

        pollutant = self.combo_pollutant.currentText()
        self.text_log.append(f"   Pollutant: {pollutant}")

        receptor_height = self.spin_import_height.value()
        if self.groupBox_regular.isChecked():
            receptor_height = self.spin_regular_height.value()
        elif self.groupBox_around.isChecked():
            receptor_height = self.spin_around_height.value()

        self.text_log.append(f"   Receptor height: {receptor_height} m")

        # 7. Worker thread
        self.text_log.append("\n--- Starting calculation in background thread ---")
        self.text_log.append("UI will remain responsive during calculation.")

        from opensymos.core.calculation_worker import CalculationWorker
        from qgis.PyQt.QtCore import QThread

        self.calculation_worker = CalculationWorker(
            sources=sources,
            receptors=receptors,
            dem=terrain,
            wind_rose=wind_rose,
            calculation_type=calculation_type,
            pollutant=pollutant,
            receptor_height=receptor_height,
            limit_value=limit_value,
        )

        self.calculation_thread = QThread()
        self.calculation_worker.moveToThread(self.calculation_thread)

        self.calculation_thread.started.connect(self.calculation_worker.run)
        self.calculation_worker.finished.connect(self.calculation_finished)
        self.calculation_worker.finished.connect(self.calculation_thread.quit)
        self.calculation_worker.finished.connect(self.calculation_worker.deleteLater)
        self.calculation_thread.finished.connect(self.calculation_thread.deleteLater)
        self.calculation_worker.progress.connect(self.update_calculation_progress)
        self.calculation_worker.log.connect(self.text_log.append)

        self.calculation_thread.start()
        self.text_log.append("Calculation thread started.")

    def update_calculation_progress(self, percent):
        """Update progress bar during calculation."""
        self.progress_bar.setValue(percent)

    def abort_calculation(self):
        """Abort running calculation."""
        if not hasattr(self, "calculation_worker") or not self.calculation_worker:
            return

        reply = QMessageBox.question(
            self,
            "Abort Calculation",
            "Do you really want to abort the calculation?\n\n"
            "Partial results will not be saved.",
            QMessageBox.Yes | QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            self.text_log.append("🛑 Aborting calculation by user request...")
            self.calculation_worker.abort()
            self.btn_abort.setEnabled(False)

    def calculation_finished(self, results=None):
        """Called when calculation finishes."""
        self.btn_calculate.setEnabled(True)
        self.big_calc_button.setEnabled(True)
        self.btn_validate.setEnabled(True)
        self.btn_abort.setEnabled(False)

        if hasattr(self, "calculation_worker") and self.calculation_worker.aborted:
            self.lbl_status.setText("Status: Calculation aborted")
            self.text_log.append("Calculation aborted by user.")
            self.progress_bar.setValue(0)
            return

        if results is None:
            self.lbl_status.setText("Status: Calculation failed")
            self.text_log.append("❌ Calculation failed - no results generated.")
            self.progress_bar.setValue(0)

            QMessageBox.critical(
                self,
                "Calculation Failed",
                "Calculation failed to produce results.\n\n"
                "Please check the log for details.",
            )

        elif results == "dummy_result":
            self.lbl_status.setText("Status: Test complete")
            self.text_log.append("✅ Test calculation completed successfully!")
            self.progress_bar.setValue(100)

            QMessageBox.information(
                self,
                "Test Complete",
                "Test calculation completed successfully!\n\n"
                "This was a simulation - real calculation will produce actual results.",
            )

        else:
            self.lbl_status.setText("Status: Calculation complete")
            self.text_log.append("✅ Calculation completed successfully!")

            layer_name = f"{self.combo_concentration_type.currentText()} Results"
            layer = results.add_to_qgis_project(layer_name)

            if layer:
                self.text_log.append(f"✓ Result layer '{layer_name}' added to map.")

            stats = results.get_statistics()
            self.text_log.append("📊 Statistics:")
            self.text_log.append(f"   • Points: {stats['count']}")
            self.text_log.append(f"   • Min: {stats['min']:.3f} μg/m³")
            self.text_log.append(f"   • Max: {stats['max']:.3f} μg/m³")
            self.text_log.append(f"   • Mean: {stats['mean']:.3f} μg/m³")

            QMessageBox.information(
                self,
                "Calculation Complete",
                f"✅ Calculation completed successfully!\n\n"
                f"📊 Statistics:\n"
                f"• Points: {stats['count']}\n"
                f"• Min: {stats['min']:.3f} μg/m³\n"
                f"• Max: {stats['max']:.3f} μg/m³\n"
                f"• Mean: {stats['mean']:.3f} μg/m³\n\n"
                f"Results added to map as '{layer_name}'.",
            )


if __name__ == "__main__":
    from qgis.PyQt.QtWidgets import QApplication

    app = QApplication(sys.argv)
    dialog = MainDialog()
    dialog.show()
    sys.exit(app.exec_())