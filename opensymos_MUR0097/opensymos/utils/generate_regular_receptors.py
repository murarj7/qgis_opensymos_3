"""
Module for generating regular grid of receptors with elevation from DEM + height above terrain.
"""
import processing
from qgis.core import QgsWkbTypes, QgsProject, QgsVectorLayer, QgsField, QgsFeature
from qgis.PyQt.QtCore import QVariant

class RegularReceptorGenerator:
    """Class for generating regular grid of receptors with elevation."""
    
    def __init__(self):
        """Generator initialization."""
        pass
    
    def generate(self, extent_layer, dem_layer, spacing, height_above_terrain):
        """
        Generates regular grid of receptors with elevation from DEM + height above terrain.
        
        Args:
            extent_layer: QgsVectorLayer - layer defining the extent (any geometry)
            dem_layer: QgsRasterLayer - digital elevation model
            spacing: float - point spacing in meters
            height_above_terrain: float - height of receptors above terrain (m)
            
        Returns:
            QgsVectorLayer - point layer with elevation attribute or None on error
        """
        print(f"\n=== REGULAR RECEPTOR GENERATOR ===")
        print(f"Extent layer: {extent_layer.name()}")
        print(f"DEM layer: {dem_layer.name()}")
        print(f"Spacing: {spacing}m")
        print(f"Height above terrain: {height_above_terrain}m")
        
        #METRIC CHECK
        if dem_layer.crs().mapUnits() != 0:  # 0 = meters
            print("Error: DEM must be in metric CRS")
            return None
        
        # 1. Input validation
        if not self._validate_inputs(extent_layer, dem_layer, spacing):
            print("Validation failed")
            return None
        
        # 2. Create point grid based on extent layer
        print("Creating point grid...")
        grid_layer = self._create_grid(extent_layer, spacing)
        if not grid_layer:
            print("Failed to create grid")
            return None
        
        print(f"Grid created, point count: {grid_layer.featureCount()}")
        
        # 3. Sample raster values (get elevation from DEM)
        print("Sampling DEM values...")
        sampled_layer = self._sample_raster(grid_layer, dem_layer)
        if not sampled_layer:
            print("Failed to sample raster")
            return None
        
        print(f"Sampled, point count: {sampled_layer.featureCount()}")
        
        # 4. Calculate final elevation (DEM value + height above terrain)
        print("Calculating final elevation...")
        result_layer = self._calculate_elevation(sampled_layer, height_above_terrain)
        if not result_layer:
            print("Failed to calculate elevation")
            return None
        
        print(f"Final point count: {result_layer.featureCount()}")
        print("=== GENERATOR FINISHED ===\n")
        
        result_layer.setName(f"receptors_grid_{spacing}m")
        return result_layer
    
    def _validate_inputs(self, extent_layer, dem_layer, spacing):
        """Check input parameters."""
        if not extent_layer:
            print("Error: No extent layer provided")
            return False
        
        if not dem_layer:
            print("Error: No DEM layer provided")
            return False
        
        if dem_layer.type() != 1:  # 1 = RasterLayer
            print("Error: DEM layer is not a raster")
            return False
        
        if spacing <= 0:
            print("Error: Spacing must be greater than 0")
            return False
        
        return True
    
    def _create_grid(self, extent_layer, spacing):
        """Create point grid based on extent layer."""
        try:
            extent = extent_layer.extent()
            print(f"Extent: xmin={extent.xMinimum()}, ymin={extent.yMinimum()}, "
                  f"xmax={extent.xMaximum()}, ymax={extent.yMaximum()}")
            
            result = processing.run("native:creategrid", {
                'TYPE': 0,  # 0 = Point
                'EXTENT': extent,
                'HSPACING': spacing,
                'VSPACING': spacing,
                'HOVERLAY': 0,
                'VOVERLAY': 0,
                'CRS': extent_layer.crs(),
                'OUTPUT': 'memory:'
            })
            
            return result['OUTPUT']
            
        except Exception as e:
            print(f"ERROR creating grid: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _sample_raster(self, grid_layer, dem_layer):
        """Sample DEM values at grid points."""
        try:
            result = processing.run("native:rastersampling", {
                'INPUT': grid_layer,
                'RASTERCOPY': dem_layer,
                'COLUMN_PREFIX': 'dem_',
                'OUTPUT': 'memory:'
            })
            
            sampled = result['OUTPUT']
            
            field_names = [field.name() for field in sampled.fields()]
            dem_field = None
            for name in field_names:
                if name.startswith('dem_'):
                    dem_field = name
                    break
            
            print(f"DEM field detected: {dem_field}")
            
            self.dem_field_name = dem_field
            
            return sampled
            
        except Exception as e:
            print(f"ERROR sampling raster: {e}")
            return None

    def _calculate_elevation(self, sampled_layer, height_above_terrain):
        """Calculate final elevation (DEM value + height above terrain)."""
        try:
            if not hasattr(self, 'dem_field_name') or not self.dem_field_name:
                print("ERROR: No DEM field name available")
                return None
                
            print(f"Using field: {self.dem_field_name}")
            
            result = processing.run("native:fieldcalculator", {
                'INPUT': sampled_layer,
                'FIELD_NAME': 'elevation',
                'FIELD_TYPE': 0,
                'FIELD_LENGTH': 10,
                'FIELD_PRECISION': 2,
                'FORMULA': f'"{self.dem_field_name}" + {height_above_terrain}',
                'OUTPUT': 'memory:'
            })
            
            return result['OUTPUT']
            
        except Exception as e:
            print(f"ERROR calculating elevation: {e}")
            return None