"""
Module for generating receptors around features using buffer and difference.
"""
import processing
from qgis.core import QgsWkbTypes, QgsProject, QgsVectorLayer, QgsField, QgsFeature, QgsProcessingFeedback
from qgis.PyQt.QtCore import QVariant

class SilentFeedback(QgsProcessingFeedback):
    def reportError(self, error, fatalError=False):
        pass

class AroundFeaturesGenerator:
    """Class for generating receptors around features."""
    
    def __init__(self):
        """Generator initialization."""
        pass
    
    def generate(self, features_layer, dem_layer, min_distance, max_distance, spacing, height_above_terrain):
        """
        Generates receptors around features in the ring between min and max distance.
        
        Args:
            features_layer: QgsVectorLayer - input layer with features (point/line/polygon)
            dem_layer: QgsRasterLayer - digital elevation model
            min_distance: float - minimum distance from features (m)
            max_distance: float - maximum distance from features (m)
            spacing: float - point spacing in meters
            height_above_terrain: float - height of receptors above terrain (m)
            
        Returns:
            QgsVectorLayer - point layer with elevation attribute or None on error
        """
        print(f"\n=== AROUND FEATURES GENERATOR ===")
        print(f"Features layer: {features_layer.name()}")
        print(f"DEM layer: {dem_layer.name()}")
        print(f"Min distance: {min_distance}m")
        print(f"Max distance: {max_distance}m")
        print(f"Spacing: {spacing}m")
        print(f"Height above terrain: {height_above_terrain}m")
        
        # 1. Input validation
        if not self._validate_inputs(features_layer, dem_layer, min_distance, max_distance, spacing):
            print("Validation failed")
            return None
        
        # 2. Create MIN buffer
        print("Creating MIN buffer...")
        buffer_min = self._create_buffer(features_layer, min_distance)
        if not buffer_min:
            print("Failed to create MIN buffer")
            return None
        
        # 3. Create MAX buffer
        print("Creating MAX buffer...")
        buffer_max = self._create_buffer(features_layer, max_distance)
        if not buffer_max:
            print("Failed to create MAX buffer")
            return None
        
        # 4. Create point grid based on MAX buffer extent
        print("Creating point grid...")
        grid_layer = self._create_grid(buffer_max, spacing)
        if not grid_layer:
            print("Failed to create grid")
            return None
        
        print(f"Grid created, point count: {grid_layer.featureCount()}")
        
        # 5. First, keep only points within MAX buffer
        print("Keeping points within MAX buffer...")
        points_in_max = self._extract_within_max(grid_layer, buffer_max)
        if not points_in_max:
            print("No points within MAX buffer")
            return None
        
        print(f"Points within MAX buffer: {points_in_max.featureCount()}")
        
        # 6. Difference - remove points inside MIN buffer
        print("Removing points inside MIN buffer...")
        ring_points = self._apply_difference(points_in_max, buffer_min)
        if not ring_points:
            print("Difference failed or no points left")
            return None
        
        print(f"Final points in ring ({min_distance}-{max_distance}m): {ring_points.featureCount()}")
        
        # 7. Sample DEM values at points
        print("Sampling DEM values...")
        sampled_layer = self._sample_raster(ring_points, dem_layer)
        if not sampled_layer:
            print("Failed to sample raster")
            return None
        
        # 7b. Check if we have any points left after sampling
        if sampled_layer.featureCount() == 0:
            print("ERROR: No points remain after DEM sampling. All points are outside DEM extent.")
            return None
        
        # 8. Calculate final elevation (DEM value + height above terrain)
        print("Calculating final elevation...")
        result_layer = self._calculate_elevation(sampled_layer, height_above_terrain)
        if not result_layer:
            print("Failed to calculate elevation")
            return None
        
        print(f"Final point count: {result_layer.featureCount()}")
        print("=== GENERATOR FINISHED ===\n")
        
        print("Cleaning up attributes...")
        result_layer = self._clean_attributes(result_layer, ['elevation'])

        result_layer.setName(f"around_features_{min_distance}-{max_distance}m")
        return result_layer    

    def _clean_attributes(self, layer, keep_fields):
        """Remove all attributes except the ones we want to keep."""
        try:
            # Get current fields
            fields = layer.fields()
            keep_indices = []
            
            # Find indices of fields we want to keep
            for field_name in keep_fields:
                idx = fields.indexOf(field_name)
                if idx >= 0:
                    keep_indices.append(idx)
            
            # If we only want to keep elevation and it exists
            if keep_indices:
                result = processing.run("native:retainfields", {
                    'INPUT': layer,
                    'FIELDS': keep_fields,
                    'OUTPUT': 'memory:'
                })
                return result['OUTPUT']
            else:
                return layer
                
        except Exception as e:
            print(f"ERROR cleaning attributes: {e}")
            return layer  # Return original if cleaning fails
    
    def _validate_inputs(self, features_layer, dem_layer, min_distance, max_distance, spacing):
        """Check input parameters."""
        if not features_layer:
            print("Error: No features layer provided")
            return False
        
        if not dem_layer:
            print("Error: No DEM layer provided")
            return False
        
        if dem_layer.type() != 1:  # 1 = RasterLayer
            print("Error: DEM layer is not a raster")
            return False
        
        if min_distance < 0:
            print("Error: Min distance must be non-negative")
            return False
        
        if max_distance <= min_distance:
            print("Error: Max distance must be greater than min distance")
            return False
        
        if spacing <= 0:
            print("Error: Spacing must be greater than 0")
            return False
        
        # Check CRS
        if dem_layer.crs().mapUnits() != 0:  # 0 = meters
            print("Error: DEM must be in metric CRS")
            return False
        
        return True
    
    def _create_buffer(self, input_layer, distance):
        """Create buffer around features."""
        try:
            result = processing.run("native:buffer", {
                'INPUT': input_layer,
                'DISTANCE': distance,
                'SEGMENTS': 20,
                'DISSOLVE': True,  # Dissolve to avoid overlapping buffers
                'OUTPUT': 'memory:'
            })
            
            buffer_layer = result['OUTPUT']
            print(f"Buffer created at {distance}m, feature count: {buffer_layer.featureCount()}")
            return buffer_layer
            
        except Exception as e:
            print(f"ERROR creating buffer: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _create_grid(self, buffer_layer, spacing):
        """Create point grid based on buffer extent."""
        try:
            extent = buffer_layer.extent()
            print(f"Grid extent: xmin={extent.xMinimum()}, ymin={extent.yMinimum()}, "
                  f"xmax={extent.xMaximum()}, ymax={extent.yMaximum()}")
            
            result = processing.run("native:creategrid", {
                'TYPE': 0,  # 0 = Point
                'EXTENT': extent,
                'HSPACING': spacing,
                'VSPACING': spacing,
                'HOVERLAY': 0,
                'VOVERLAY': 0,
                'CRS': buffer_layer.crs(),
                'OUTPUT': 'memory:'
            })
            
            grid_layer = result['OUTPUT']
            print(f"Grid created, point count: {grid_layer.featureCount()}")
            return grid_layer
            
        except Exception as e:
            print(f"ERROR creating grid: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _extract_within_max(self, points_layer, buffer_max):
        """Extract points within MAX buffer."""
        try:
            feedback = SilentFeedback()
            result = processing.run("native:extractbylocation", {
                'INPUT': points_layer,
                'PREDICATE': [0],  # 0 = within
                'INTERSECT': buffer_max,
                'OUTPUT': 'memory:'
            }, feedback=feedback)
            
            extracted = result['OUTPUT']
            print(f"Extracted within MAX buffer: {extracted.featureCount()} points")
            return extracted
            
        except Exception as e:
            print(f"ERROR extracting within MAX buffer: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _apply_difference(self, points_layer, buffer_min):
        """Remove points inside MIN buffer."""
        try:
            feedback = SilentFeedback()
            result = processing.run("native:difference", {
                'INPUT': points_layer,
                'OVERLAY': buffer_min,
                'OUTPUT': 'memory:'
            }, feedback=feedback)
            
            diff_layer = result['OUTPUT']
            print(f"Difference applied, points remaining: {diff_layer.featureCount()}")
            return diff_layer
            
        except Exception as e:
            print(f"ERROR applying difference: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _sample_raster(self, point_layer, dem_layer):
        """Sample DEM values at points and remove points outside DEM."""
        try:
            result = processing.run("native:rastersampling", {
                'INPUT': point_layer,
                'RASTERCOPY': dem_layer,
                'COLUMN_PREFIX': 'dem_',
                'OUTPUT': 'memory:'
            })
            
            sampled = result['OUTPUT']
            
            # Find the DEM field name
            field_names = [field.name() for field in sampled.fields()]
            dem_field = None
            for name in field_names:
                if name.startswith('dem_'):
                    dem_field = name
                    break
            
            print(f"DEM field detected: {dem_field}")
            self.dem_field_name = dem_field
            
            # Remove points with NULL values (outside DEM)
            if dem_field:
                # Count before
                before_count = sampled.featureCount()
                
                # Extract only points with valid DEM values
                extracted = processing.run("native:extractbyexpression", {
                    'INPUT': sampled,
                    'EXPRESSION': f'"{dem_field}" IS NOT NULL',
                    'OUTPUT': 'memory:'
                })['OUTPUT']
                
                after_count = extracted.featureCount()
                print(f"Removed {before_count - after_count} points outside DEM")
                
                return extracted
            
            return sampled
            
        except Exception as e:
            print(f"ERROR sampling raster: {e}")
            import traceback
            traceback.print_exc()
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
                'FIELD_TYPE': 0,  # 0 = Float
                'FIELD_LENGTH': 10,
                'FIELD_PRECISION': 2,
                'FORMULA': f'"{self.dem_field_name}" + {height_above_terrain}',
                'OUTPUT': 'memory:'
            })
            
            return result['OUTPUT']
            
        except Exception as e:
            print(f"ERROR calculating elevation: {e}")
            import traceback
            traceback.print_exc()
            return None
