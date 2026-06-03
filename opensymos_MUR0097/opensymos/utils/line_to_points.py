"""
Module for converting line sources to point sources with emission redistribution.
Each generated point represents a segment of the original line and receives
a proportional share of the TOTAL line emission.

Expected input:
- line geometry layer
- attribute with TOTAL emission for the whole line feature, default: "emission" [g/s]

Output:
- point layer with original attributes copied
- added attributes:
    * orig_line_id
    * segment_id
    * dist_along
    * segment_length
    * point_emission
"""

from qgis.core import (
    QgsWkbTypes,
    QgsVectorLayer,
    QgsFeature,
    QgsField,
    QgsFields
)
from qgis.PyQt.QtCore import QVariant


class LineToPointConverter:
    """Class for converting line sources to point sources with emission redistribution."""

    def __init__(self):
        """Converter initialization."""
        pass

    def convert(self, line_layer, spacing, emission_field="emission", id_field=None):
        """
        Converts line layer to points along lines and redistributes TOTAL line emissions
        to generated points.

        Args:
            line_layer: QgsVectorLayer - input line layer
            spacing: float - point spacing in layer units (typically meters)
            emission_field: str - attribute name with TOTAL line emission [g/s]
            id_field: str or None - optional field to use as original line ID;
                                    if None, feature.id() is used

        Returns:
            QgsVectorLayer - point layer or None on error
        """
        if not self._validate_inputs(line_layer, spacing, emission_field, id_field):
            return None

        point_layer = self._create_output_layer(line_layer)

        if point_layer is None:
            print("Error: Failed to create output layer")
            return None

        dp = point_layer.dataProvider()
        new_features = []
        global_segment_id = 1

        for line_feature in line_layer.getFeatures():
            try:
                line_geom = line_feature.geometry()
                if line_geom is None or line_geom.isEmpty():
                    continue

                total_length = line_geom.length()
                if total_length <= 0:
                    continue

                total_emission = self._safe_float(line_feature[emission_field])
                if total_emission is None:
                    print(
                        f"Warning: Feature {line_feature.id()} has invalid "
                        f"'{emission_field}', skipping"
                    )
                    continue

                original_id = line_feature[id_field] if id_field else line_feature.id()
                segments = self._generate_segments(total_length, spacing)

                emitted_so_far = 0.0

                for idx, segment in enumerate(segments):
                    dist_along = segment["center"]
                    segment_length = segment["length"]

                    point_geom = self._interpolate_point_geometry(line_geom, dist_along)
                    if point_geom is None:
                        continue

                    if segment_length <= 0:
                        continue

                    # Redistribute TOTAL line emission proportionally by represented segment length.
                    # For the last segment, use the remaining emission to avoid tiny floating-point drift.
                    if idx == len(segments) - 1:
                        point_emission = total_emission - emitted_so_far
                    else:
                        point_emission = total_emission * (segment_length / total_length)
                        emitted_so_far += point_emission

                    new_feature = QgsFeature(point_layer.fields())
                    new_feature.setGeometry(point_geom)

                    attrs = []

                    # Copy original attributes first
                    for field in line_layer.fields():
                        attrs.append(line_feature[field.name()])

                    # Append new attributes
                    attrs.extend([
                        str(original_id),              # orig_line_id
                        global_segment_id,             # segment_id
                        float(dist_along),             # dist_along
                        float(segment_length),         # segment_length
                        float(point_emission)          # point_emission
                    ])

                    new_feature.setAttributes(attrs)
                    new_features.append(new_feature)

                    global_segment_id += 1

            except Exception as e:
                print(f"Warning: Failed to process feature {line_feature.id()}: {e}")

        if new_features:
            dp.addFeatures(new_features)
            point_layer.updateExtents()

        point_layer.setName(f"{line_layer.name()}_points_{spacing}m")

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

        if layer.geometryType() != QgsWkbTypes.LineGeometry:
            print("Error: Layer is not line geometry")
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

    def _create_output_layer(self, line_layer):
        """
        Create memory point layer with copied original attributes and added fields.
        """
        try:
            crs_authid = line_layer.crs().authid()
            point_layer = QgsVectorLayer(
                f"Point?crs={crs_authid}",
                f"{line_layer.name()}_points",
                "memory"
            )

            dp = point_layer.dataProvider()
            output_fields = QgsFields()

            # Copy all original fields
            for field in line_layer.fields():
                output_fields.append(field)

            # Add new fields
            output_fields.append(QgsField("orig_line_id", QVariant.String))
            output_fields.append(QgsField("segment_id", QVariant.Int))
            output_fields.append(QgsField("dist_along", QVariant.Double))
            output_fields.append(QgsField("segment_length", QVariant.Double))
            output_fields.append(QgsField("point_emission", QVariant.Double))

            dp.addAttributes(output_fields)
            point_layer.updateFields()

            return point_layer

        except Exception as e:
            print(f"Error creating output layer: {e}")
            return None

    def _generate_segments(self, total_length, spacing):
        """
        Generate non-overlapping line segments and their point positions.

        Each output point is placed at the center of its represented segment.
        The last segment gets only the real remaining length, so the sum of
        segment_length values is always equal to total_length.

        Example for spacing=3 and line length=10:
            centers: 1.5, 4.5, 7.5, 9.5
            lengths: 3.0, 3.0, 3.0, 1.0
        """
        segments = []
        start = 0.0

        while start < total_length:
            end = min(start + spacing, total_length)
            length = end - start

            if length > 0:
                center = (start + end) / 2.0
                segments.append({
                    "start": start,
                    "end": end,
                    "center": center,
                    "length": length
                })

            start += spacing

        return segments

    def _interpolate_point_geometry(self, line_geom, distance):
        """
        Interpolate point geometry at distance along line.
        Supports single and multipart lines through QgsGeometry.interpolate().
        """
        try:
            pt_geom = line_geom.interpolate(distance)
            if pt_geom is None or pt_geom.isEmpty():
                return None
            return pt_geom
        except Exception as e:
            print(f"Warning: Interpolation failed at distance {distance}: {e}")
            return None

    def _safe_float(self, value):
        """Convert value to float safely."""
        try:
            if value is None:
                return None
            return float(value)
        except Exception:
            return None
