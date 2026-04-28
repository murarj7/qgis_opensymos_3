"""
Module for converting polygon sources to point sources with emission redistribution.
Each generated point represents a clipped grid cell inside the polygon and receives
a proportional share of the TOTAL polygon emission.

Expected input:
- polygon geometry layer
- attribute with TOTAL emission for the whole polygon feature, default: "emission" [g/s]

Output:
- point layer with original attributes copied
- added attributes:
    * orig_area_id
    * cell_id
    * cell_area
    * point_emission
"""

from qgis.core import (
    QgsWkbTypes,
    QgsVectorLayer,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsRectangle,
    QgsPointXY
)
from qgis.PyQt.QtCore import QVariant


class PolygonToPointConverter:
    """Class for converting polygon sources to point sources with emission redistribution."""

    def __init__(self):
        """Converter initialization."""
        pass

    def convert(self, polygon_layer, spacing, emission_field="emission", id_field=None):
        """
        Converts polygon layer to points using a regular square grid clipped by each polygon.
        TOTAL polygon emission is redistributed proportionally by clipped cell area.

        Args:
            polygon_layer: QgsVectorLayer - input polygon layer
            spacing: float - grid spacing / cell size in layer units (typically meters)
            emission_field: str - attribute name with TOTAL polygon emission [g/s]
            id_field: str or None - optional field to use as original polygon ID;
                                    if None, feature.id() is used

        Returns:
            QgsVectorLayer - point layer or None on error
        """
        if not self._validate_inputs(polygon_layer, spacing, emission_field, id_field):
            return None

        point_layer = self._create_output_layer(polygon_layer)
        if point_layer is None:
            print("Error: Failed to create output layer")
            return None

        dp = point_layer.dataProvider()
        new_features = []
        global_cell_id = 1

        for poly_feature in polygon_layer.getFeatures():
            try:
                poly_geom = poly_feature.geometry()
                if poly_geom is None or poly_geom.isEmpty():
                    continue

                total_area = poly_geom.area()
                if total_area <= 0:
                    continue

                total_emission = self._safe_float(poly_feature[emission_field])
                if total_emission is None:
                    print(
                        f"Warning: Feature {poly_feature.id()} has invalid "
                        f"'{emission_field}', skipping"
                    )
                    continue

                original_id = poly_feature[id_field] if id_field else poly_feature.id()

                feature_cells = self._generate_clipped_cells(poly_geom, spacing)

                # Small polygon fallback: one centroid point with full emission
                if not feature_cells:
                    centroid_geom = poly_geom.centroid()
                    if centroid_geom is not None and not centroid_geom.isEmpty():
                        new_feature = QgsFeature(point_layer.fields())
                        new_feature.setGeometry(centroid_geom)

                        attrs = []
                        for field in polygon_layer.fields():
                            attrs.append(poly_feature[field.name()])

                        attrs.extend([
                            str(original_id),          # orig_area_id
                            global_cell_id,            # cell_id
                            float(total_area),         # cell_area
                            float(total_emission)      # point_emission
                        ])

                        new_feature.setAttributes(attrs)
                        new_features.append(new_feature)
                        global_cell_id += 1

                    continue

                for clipped_geom in feature_cells:
                    cell_area = clipped_geom.area()
                    if cell_area <= 0:
                        continue

                    point_geom = clipped_geom.centroid()
                    if point_geom is None or point_geom.isEmpty():
                        continue

                    point_emission = total_emission * (cell_area / total_area)

                    new_feature = QgsFeature(point_layer.fields())
                    new_feature.setGeometry(point_geom)

                    attrs = []
                    for field in polygon_layer.fields():
                        attrs.append(poly_feature[field.name()])

                    attrs.extend([
                        str(original_id),          # orig_area_id
                        global_cell_id,            # cell_id
                        float(cell_area),          # cell_area
                        float(point_emission)      # point_emission
                    ])

                    new_feature.setAttributes(attrs)
                    new_features.append(new_feature)
                    global_cell_id += 1

            except Exception as e:
                print(f"Warning: Failed to process feature {poly_feature.id()}: {e}")

        if new_features:
            dp.addFeatures(new_features)
            point_layer.updateExtents()

        point_layer.setName(f"{polygon_layer.name()}_points_{spacing}m")

        print(
            f"Generated {point_layer.featureCount()} points "
            f"with redistributed total emissions"
        )
        return point_layer

    def _validate_inputs(self, layer, spacing, emission_field, id_field):
        """Check input parameters."""
        if not layer:
            print("Error: No layer provided")
            return False

        if layer.geometryType() != QgsWkbTypes.PolygonGeometry:
            print("Error: Layer is not polygon geometry")
            return False

        if spacing <= 0:
            print("Error: Spacing must be greater than 0")
            return False

        field_names = [f.name() for f in layer.fields()]

        if emission_field not in field_names:
            print(f"Error: Emission field '{emission_field}' not found in layer")
            return False

        if id_field is not None and id_field not in field_names:
            print(f"Error: ID field '{id_field}' not found in layer")
            return False

        return True

    def _create_output_layer(self, polygon_layer):
        """
        Create memory point layer with copied original attributes and added fields.
        """
        try:
            crs_authid = polygon_layer.crs().authid()
            point_layer = QgsVectorLayer(
                f"Point?crs={crs_authid}",
                f"{polygon_layer.name()}_points",
                "memory"
            )

            dp = point_layer.dataProvider()
            output_fields = QgsFields()

            # Copy all original fields
            for field in polygon_layer.fields():
                output_fields.append(field)

            # Add new fields
            output_fields.append(QgsField("orig_area_id", QVariant.String))
            output_fields.append(QgsField("cell_id", QVariant.Int))
            output_fields.append(QgsField("cell_area", QVariant.Double))
            output_fields.append(QgsField("point_emission", QVariant.Double))

            dp.addAttributes(output_fields)
            point_layer.updateFields()

            return point_layer

        except Exception as e:
            print(f"Error creating output layer: {e}")
            return None

    def _generate_clipped_cells(self, polygon_geom, spacing):
        """
        Generate square cells over polygon extent, clip them by polygon,
        and return non-empty clipped geometries.
        """
        clipped_cells = []

        bbox = polygon_geom.boundingBox()

        x = bbox.xMinimum()
        while x < bbox.xMaximum():
            y = bbox.yMinimum()
            while y < bbox.yMaximum():
                cell_rect = QgsRectangle(
                    x,
                    y,
                    min(x + spacing, bbox.xMaximum()),
                    min(y + spacing, bbox.yMaximum())
                )

                cell_geom = QgsGeometry.fromRect(cell_rect)

                # quick reject
                if not polygon_geom.boundingBoxIntersects(cell_rect):
                    y += spacing
                    continue

                # intersection
                try:
                    clipped = polygon_geom.intersection(cell_geom)
                    if clipped is not None and not clipped.isEmpty() and clipped.area() > 0:
                        clipped_cells.append(clipped)
                except Exception:
                    pass

                y += spacing
            x += spacing

        return clipped_cells

    def _safe_float(self, value):
        """Convert value to float safely."""
        try:
            if value is None:
                return None
            return float(value)
        except Exception:
            return None