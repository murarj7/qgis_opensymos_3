"""
Module for managing collection of calculation results and exporting to QGIS layers.
"""
from qgis.core import (QgsVectorLayer, QgsField, QgsFeature, QgsGeometry,
                       QgsPointXY, QgsProject, QgsWkbTypes, QgsCoordinateReferenceSystem)
from qgis.PyQt.QtCore import QVariant
from .result import Result

class ResultsCollection:
    """
    Collection of calculation results with export capabilities.
    
    Provides methods for:
    - Adding results from calculations
    - Creating QGIS vector layers from results
    - Exporting to shapefile/GML (via QGIS)
    - Basic statistics
    """
    
    def __init__(self):
        """Initialize empty results collection."""
        self.results = []          # List of Result objects
        self.crs = None            # Coordinate reference system
        self.pollutant = None       # Pollutant name
        self.calculation_type = None # Type of calculation performed
    
    def add_result(self, result):
        """
        Add a single result to collection.
        
        Args:
            result: Result object
        """
        if not isinstance(result, Result):
            raise TypeError("Expected Result object")
        self.results.append(result)
    
    def add_results(self, results_list):
        """
        Add multiple results at once.
        
        Args:
            results_list: list of Result objects
        """
        for r in results_list:
            self.add_result(r)
    
    def set_metadata(self, crs, pollutant, calculation_type):
        """
        Set metadata for the results collection.
        
        Args:
            crs: QgsCoordinateReferenceSystem - CRS of the results
            pollutant: str - pollutant name
            calculation_type: int - Result.TYPE_ constant
        """
        self.crs = crs
        self.pollutant = pollutant
        self.calculation_type = calculation_type
    
    def get_results(self):
        """
        Get all results.
        
        Returns:
            list: Result objects
        """
        return self.results
    
    def count(self):
        """
        Get number of results.
        
        Returns:
            int: number of results
        """
        return len(self.results)
    
    def is_empty(self):
        """
        Check if collection is empty.
        
        Returns:
            bool: True if no results
        """
        return len(self.results) == 0
    
    def get_statistics(self):
        """
        Calculate basic statistics from results.
        
        Returns:
            dict: statistics or None if collection empty
        """
        if self.is_empty():
            return None
        
        stats = {
            'count': self.count(),
            'min': float('inf'),
            'max': float('-inf'),
            'mean': 0.0,
            'sum': 0.0
        }
        
        values = []
        for r in self.results:
            if r.result_type == Result.TYPE_MAX_SHORT_TERM:
                val = r.max_total
            elif r.result_type == Result.TYPE_ANNUAL_AVERAGE:
                val = r.annual_average
            elif r.result_type == Result.TYPE_EXCEEDANCE_TIME:
                val = r.exceedance_time
            else:
                continue
            
            if val is not None:
                values.append(val)
                stats['min'] = min(stats['min'], val)
                stats['max'] = max(stats['max'], val)
                stats['sum'] += val
        
        if values:
            stats['mean'] = stats['sum'] / len(values)
        else:
            stats['min'] = stats['max'] = stats['mean'] = stats['sum'] = 0
        
        return stats
    
    def create_qgis_layer(self, layer_name="Calculation Results"):
        """
        Create a QGIS memory layer from results.
        
        Args:
            layer_name: str - name for the layer
        
        Returns:
            QgsVectorLayer: memory layer with results or None if no results
        """
        if self.is_empty():
            print("No results to create layer")
            return None
        
        if self.crs is None:
            print("Warning: No CRS set for results, using default")
            self.crs = QgsCoordinateReferenceSystem("EPSG:5514")  # Default to JTSK
        
        # Create memory layer
        layer = QgsVectorLayer(
            f"Point?crs={self.crs.authid()}",
            layer_name,
            "memory"
        )
        provider = layer.dataProvider()
        
        # Add fields based on calculation type
        fields = self._create_fields()
        provider.addAttributes(fields)
        layer.updateFields()
        
        # Add features
        features = self._create_features()
        provider.addFeatures(features)
        
        # Update extent
        layer.updateExtents()
        
        return layer
    
    def _create_fields(self):
        """
        Create field definitions based on calculation type.
        
        Returns:
            list: QgsField objects
        """
        fields = [
            QgsField("id", QVariant.Int),
            QgsField("x", QVariant.Double),
            QgsField("y", QVariant.Double)
        ]
        
        if self.calculation_type == Result.TYPE_MAX_SHORT_TERM:
            # Add 11 concentration fields
            for name in Result.CONCENTRATION_NAMES:
                fields.append(QgsField(name, QVariant.Double))
            fields.append(QgsField("c_max", QVariant.Double))
            fields.append(QgsField("max_stability_class", QVariant.Int))
            fields.append(QgsField("max_wind_speed", QVariant.Double))
            fields.append(QgsField("max_wind_direction", QVariant.Int))
        
        elif self.calculation_type == Result.TYPE_ANNUAL_AVERAGE:
            fields.append(QgsField("c_average", QVariant.Double))
        
        elif self.calculation_type == Result.TYPE_EXCEEDANCE_TIME:
            fields.append(QgsField("time_hours", QVariant.Double))
        
        # Add pollutant info as field (optional)
        if self.pollutant:
            fields.append(QgsField("pollutant", QVariant.String))
        
        return fields
    
    def _create_features(self):
        """
        Create QGIS features from results.
        
        Returns:
            list: QgsFeature objects
        """
        features = []
        
        for r in self.results:
            f = QgsFeature()
            
            # Set geometry
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(r.x, r.y)))
            
            # Set attributes based on result type
            attrs = [r.id, r.x, r.y]
            
            if r.result_type == Result.TYPE_MAX_SHORT_TERM:
                if r.max_values:
                    attrs.extend(r.max_values)
                else:
                    attrs.extend([None] * 11)
                attrs.append(r.max_total)
                attrs.append(r.max_stability)
                attrs.append(r.max_wind_speed)
                attrs.append(r.max_direction)
            
            elif r.result_type == Result.TYPE_ANNUAL_AVERAGE:
                attrs.append(r.annual_average)
            
            elif r.result_type == Result.TYPE_EXCEEDANCE_TIME:
                attrs.append(r.exceedance_time)
            
            # Add pollutant if field exists
            if self.pollutant:
                attrs.append(self.pollutant)
            
            f.setAttributes(attrs)
            features.append(f)
        
        return features
    
    def add_to_qgis_project(self, layer_name="Calculation Results"):
        """
        Create layer and add it to current QGIS project.
        
        Args:
            layer_name: str - name for the layer
        
        Returns:
            QgsVectorLayer: the added layer or None if failed
        """
        layer = self.create_qgis_layer(layer_name)
        if layer:
            QgsProject.instance().addMapLayer(layer)
            print(f"Added layer '{layer_name}' with {self.count()} points")
        return layer
    
    def export_to_shapefile(self, filepath, layer_name="results"):
        """
        Export results to shapefile.
        
        Args:
            filepath: str - full path for the shapefile
            layer_name: str - layer name
        
        Returns:
            bool: True if successful
        """
        layer = self.create_qgis_layer(layer_name)
        if not layer:
            return False
        
        # Save to file
        error = QgsVectorFileWriter.writeAsVectorFormat(
            layer, filepath, "UTF-8", self.crs, "ESRI Shapefile"
        )
        
        if error[0] == QgsVectorFileWriter.NoError:
            print(f"Results exported to: {filepath}")
            return True
        else:
            print(f"Export failed: {error}")
            return False
    
    def clear(self):
        """Remove all results."""
        self.results.clear()
    
    def __repr__(self):
        """String representation."""
        return (f"ResultsCollection({self.count()} points, "
                f"type={self.calculation_type}, pollutant={self.pollutant})")