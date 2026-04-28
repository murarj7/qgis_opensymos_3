"""
Module for receptor representation in SYMOS dispersion model.
Each receptor (calculation point) is represented by a Receptor object.
"""
from qgis.core import QgsGeometry, QgsPointXY

class Receptor:
    """
    Represents a single receptor point where concentrations are calculated.
    
    Receptors can come from:
    - Imported point layer
    - Generated regular grid
    - Generated around features
    """
    
    def __init__(self, receptor_id, x, y):
        """
        Initialize a receptor with basic position.
        
        Args:
            receptor_id: int/str - unique identifier
            x: float - x coordinate in CRS units (meters)
            y: float - y coordinate in CRS units (meters)
        """
        self.id = receptor_id
        self.x = x
        self.y = y
        
        # Will be set later
        self.z = None                # Terrain elevation from DEM [m]
        self.height_above = None     # Height above terrain [m] (user input)
        
        # Optional: for receptors from generated grids
        self.grid_info = None        # For debugging: 'regular', 'around', etc.
    
    @classmethod
    def from_point_geometry(cls, receptor_id, point_geom, height_above=0):
        """
        Create receptor from a point geometry (e.g., imported layer).
        
        Args:
            receptor_id: int/str - unique identifier
            point_geom: QgsGeometry - point geometry
            height_above: float - height above terrain [m] (default 0)
        
        Returns:
            Receptor object
        """
        if point_geom.type() != 0:  # 0 = Point
            raise ValueError(f"Geometry is not a point (type: {point_geom.type()})")
        
        point = point_geom.asPoint()
        receptor = cls(receptor_id, point.x(), point.y())
        receptor.height_above = height_above
        return receptor
    
    @classmethod
    def from_grid(cls, receptor_id, x, y, grid_type="regular"):
        """
        Create receptor from grid generation.
        
        Args:
            receptor_id: int/str - unique identifier
            x: float - x coordinate
            y: float - y coordinate
            grid_type: str - 'regular', 'around', etc.
        
        Returns:
            Receptor object
        """
        receptor = cls(receptor_id, x, y)
        receptor.grid_info = grid_type
        return receptor
    
    def set_elevation(self, z):
        """
        Set terrain elevation from DEM.
        
        Args:
            z: float - elevation in meters
        """
        self.z = z
    
    def set_height_above(self, height):
        """
        Set height above terrain (from user input).
        
        Args:
            height: float - height above terrain [m]
        """
        self.height_above = height
    
    def get_total_height(self):
        """
        Get total receptor height (terrain elevation + height above).
        
        Returns:
            float: total height [m] or None if not set
        """
        if self.z is None or self.height_above is None:
            return None
        return self.z + self.height_above
    
    def get_geometry(self):
        """
        Get QGIS point geometry for this receptor.
        
        Returns:
            QgsGeometry: point geometry
        """
        return QgsGeometry.fromPointXY(QgsPointXY(self.x, self.y))
    
    def validate(self):
        """
        Basic validation of receptor parameters.
        
        Returns:
            tuple: (is_valid, error_message)
        """
        if self.x is None or self.y is None:
            return False, "Receptor coordinates not set"
        
        if self.z is None:
            return False, "Receptor elevation (z) not set from DEM"
        
        if self.height_above is None:
            return False, "Receptor height above terrain not set"
        
        return True, "OK"
    
    def __repr__(self):
        """String representation for debugging."""
        return (f"Receptor(id={self.id}, x={self.x:.1f}, y={self.y:.1f}, "
                f"z={self.z:.1f}, h_above={self.height_above})")