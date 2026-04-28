from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer, QgsMapLayer, QgsWkbTypes
from qgis.PyQt.QtCore import QObject
from qgis.PyQt.QtWidgets import QMessageBox

class LayerManager(QObject):
    """Manages QGIS layers for the plugin."""
    
    @staticmethod
    def get_all_raster_layers():
        """Get all raster layers in the current project."""
        layers = QgsProject.instance().mapLayers().values()
        raster_layers = []
        
        for layer in layers:
            if isinstance(layer, QgsRasterLayer):
                raster_layers.append(layer)
                
        return raster_layers
    
    @staticmethod
    def get_all_vector_layers():
        """Get all vector layers in the current project."""
        layers = QgsProject.instance().mapLayers().values()
        vector_layers = []
        
        for layer in layers:
            if isinstance(layer, QgsVectorLayer):
                vector_layers.append(layer)
                
        return vector_layers
    
    @staticmethod
    def get_raster_info(layer):
        """Get information about a raster layer."""
        if not layer or not layer.isValid():
            return None
            
        # Get CRS information
        crs = layer.crs()
        crs_authid = crs.authid() if crs.isValid() else "Unknown"
        crs_description = crs.description() if crs.isValid() else "No coordinate system"
        
        info = {
            'name': layer.name(),
            'id': layer.id(),
            'crs': crs_authid,
            'crs_description': crs_description,
            'extent': layer.extent().toString(),
            'width': layer.width(),
            'height': layer.height(),
            'band_count': layer.bandCount(),
            'data_type': "Unknown",
            'pixel_size': "Unknown"
        }
        
        # Try to get pixel size
        try:
            if layer.rasterType() in [QgsRasterLayer.GrayOrUndefined, 
                                       QgsRasterLayer.Multiband]:
                pixel_size = layer.rasterUnitsPerPixelX()
                info['pixel_size'] = f"{pixel_size:.2f} m"
        except:
            info['pixel_size'] = "Unknown"
            
        return info
    
    @staticmethod
    def get_vector_info(layer):
        """Get information about a vector layer."""
        if not layer or not layer.isValid():
            return None
            
        # Get CRS information
        crs = layer.crs()
        crs_authid = crs.authid() if crs.isValid() else "Unknown"
        crs_description = crs.description() if crs.isValid() else "No coordinate system"
        
        # Get geometry type
        geom_type = layer.geometryType()
        if geom_type == QgsWkbTypes.PointGeometry:
            geom_name = "Point"
        elif geom_type == QgsWkbTypes.LineGeometry:
            geom_name = "Line"
        elif geom_type == QgsWkbTypes.PolygonGeometry:
            geom_name = "Polygon"
        else:
            geom_name = "Unknown"
        
        # Get field names
        field_names = [field.name() for field in layer.fields()]
        
        info = {
            'name': layer.name(),
            'id': layer.id(),
            'crs': crs_authid,
            'crs_description': crs_description,
            'extent': layer.extent().toString(),
            'feature_count': layer.featureCount(),
            'geometry_type': geom_type,
            'geometry_type_name': geom_name,
            'fields': field_names
        }
        
        return info
    
    @staticmethod
    def get_layer_by_name(name):
        """Get layer by its name."""
        layers = QgsProject.instance().mapLayers().values()
        for layer in layers:
            if layer.name() == name:
                return layer
        return None
    
    @staticmethod
    def load_raster_from_file(file_path):
        """Load a raster layer from file."""
        if not file_path:
            return None
            
        # Create layer name from filename
        import os
        layer_name = os.path.splitext(os.path.basename(file_path))[0]
        
        # Create raster layer
        layer = QgsRasterLayer(file_path, layer_name)
        
        if not layer.isValid():
            return None
            
        # Add to project
        QgsProject.instance().addMapLayer(layer)
        
        return layer