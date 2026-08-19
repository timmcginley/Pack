"""Create one SVG floor plan per IFC building storey."""

from __future__ import annotations

import shutil
import subprocess
import xml.etree.ElementTree as ET
import re
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
from ifcopenshell.util.element import get_decomposition
from ifcopenshell.util.placement import get_local_placement
from ifcopenshell.util.unit import calculate_unit_scale

IFC_CONVERT = r"C:\Program Files\IfcConvert\IfcConvert.exe"

IFC_FILE = Path(
    r"C:\Users\timmc\OneDrive - Danmarks Tekniske Universitet\Skrivebord\3626D-A\BIM\01\26-01-D-ARCH.ifc"
)
OUTPUT_DIR = Path("floorplans")
THREADS = 7
SCALE = "1:100"
STOREY_TO_EXPORT = "basement"  # Set to None to export every storey.
SVG_UNIT_MM = 10
BORDER_INSET_MM = 10
BORDER_STROKE_MM = 0.25
BOUND_TYPES = {
    "IfcWall",
    "IfcWallStandardCase",
    "IfcWindow",
    "IfcDoor",
    "IfcOpeningElement",
    "IfcSpace",
    "IfcSlab",
    "IfcColumn",
    "IfcBeam",
}


def safe_filename(name: str | None, fallback: str) -> str:
    value = name or fallback
    return "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in value
    )


def find_ifc_convert(path: str | None) -> str:
    if path:
        return path
    if executable := shutil.which("IfcConvert"):
        return executable
    raise FileNotFoundError(
        "IfcConvert was not found. Install the IfcOpenShell command-line tools "
        "or pass its location with --ifc-convert."
    )


def svg_bounds(root: ET.Element) -> tuple[float, float, float, float]:
    number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
    coordinates: list[float] = []
    geometry_tags = {"path", "polyline", "polygon", "line", "rect", "circle", "ellipse", "text"}

    def collect(element: ET.Element, inside_defs: bool = False) -> None:
        local_name = element.tag.rsplit("}", 1)[-1]
        inside_defs = inside_defs or local_name == "defs"
        if not inside_defs and local_name in geometry_tags and element.get("id") != "inset-border":
            for attribute in ("d", "points", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "rx", "ry"):
                coordinates.extend(float(value) for value in re.findall(number, element.get(attribute, "")))
        for child in element:
            collect(child, inside_defs)

    collect(root)
    if len(coordinates) < 2:
        raise ValueError("SVG has no drawable geometry")
    return (
        min(coordinates[0::2]),
        min(coordinates[1::2]),
        max(coordinates[0::2]),
        max(coordinates[1::2]),
    )


def storey_world_bounds(storey, settings) -> tuple[float, float, float, float]:
    points: list[tuple[float, float]] = []
    for element in get_decomposition(storey):
        if not any(element.is_a(element_type) for element_type in BOUND_TYPES):
            continue
        try:
            shape = ifcopenshell.geom.create_shape(settings, element)
        except RuntimeError:
            continue
        vertices = shape.geometry.verts
        points.extend(zip(vertices[0::3], vertices[1::3]))
    if not points:
        raise ValueError(f"Storey {storey.Name!r} has no geometry bounds")
    return min(x for x, _ in points), min(y for _, y in points), max(x for x, _ in points), max(y for _, y in points)


def grid_axis_points(axis, grid, unit_scale: float) -> list[tuple[float, float]]:
    curve = axis.AxisCurve
    if not curve.is_a("IfcPolyline"):
        raise ValueError(f"Unsupported grid axis curve: {curve.is_a()}")
    matrix = get_local_placement(grid.ObjectPlacement)
    points = []
    for point in curve.Points:
        x = point.Coordinates[0] * unit_scale
        y = point.Coordinates[1] * unit_scale
        points.append((
            (matrix[0, 0] * x + matrix[0, 1] * y + matrix[0, 3] * unit_scale),
            (matrix[1, 0] * x + matrix[1, 1] * y + matrix[1, 3] * unit_scale),
        ))
    return points


def add_grid_axes(svg_path: Path, model, storey, settings) -> None:
    namespace = "http://www.w3.org/2000/svg"
    ET.register_namespace("", namespace)
    tree = ET.parse(svg_path)
    root = tree.getroot()
    output_min_x, output_min_y, output_max_x, output_max_y = svg_bounds(root)
    world_min_x, world_min_y, world_max_x, world_max_y = storey_world_bounds(storey, settings)
    unit_scale = calculate_unit_scale(model)
    grids = [
        grid
        for grid in model.by_type("IfcGrid")
        if any(
            relation.RelatingStructure == storey
            for relation in (getattr(grid, "ContainedInStructure", ()) or ())
        )
    ]
    if not grids:
        return

    def project(point: tuple[float, float]) -> tuple[float, float]:
        x, y = point
        return (
            output_min_x + (x - world_min_x) * (output_max_x - output_min_x) / (world_max_x - world_min_x),
            output_max_y - (y - world_min_y) * (output_max_y - output_min_y) / (world_max_y - world_min_y),
        )

    group = ET.Element(f"{{{namespace}}}g", {"id": "ifc-grid-axes"})
    for grid in grids:
        for axis in list(grid.UAxes or []) + list(grid.VAxes or []):
            try:
                points = grid_axis_points(axis, grid, unit_scale)
            except ValueError:
                continue
            if len(points) < 2:
                continue
            x1, y1 = project(points[0])
            x2, y2 = project(points[-1])
            line = ET.SubElement(group, f"{{{namespace}}}line", {
                "x1": f"{x1:g}", "y1": f"{y1:g}", "x2": f"{x2:g}", "y2": f"{y2:g}",
                "stroke": "#b00000", "stroke-width": "0.08", "stroke-dasharray": "0.3 0.2",
                "data-global-id": str(axis.AxisCurve.id()),
            })
            label_x, label_y = project(points[len(points) // 2])
            label = ET.SubElement(group, f"{{{namespace}}}text", {
                "x": f"{label_x:g}", "y": f"{label_y:g}", "fill": "#b00000",
                "font-size": "0.8", "text-anchor": "middle",
            })
            label.text = str(axis.AxisTag or "")
    root.append(group)
    for element in root.iter():
        element.attrib = {name: str(value) for name, value in element.attrib.items()}
    tree.write(str(svg_path), encoding="utf-8", xml_declaration=True)


def add_inset_border(svg_path: Path, inset_mm: float = BORDER_INSET_MM) -> None:
    """Add a 1 cm inset black border to an SVG document."""
    namespace = "http://www.w3.org/2000/svg"
    inset_units = inset_mm / SVG_UNIT_MM
    stroke_units = BORDER_STROKE_MM / SVG_UNIT_MM
    ET.register_namespace("", namespace)
    tree = ET.parse(svg_path)
    root = tree.getroot()
    view_box = root.get("viewBox")
    border_x = border_y = 0.0
    border_width = border_height = 0.0
    if view_box:
        values = view_box.replace(",", " ").split()
        if len(values) != 4:
            raise ValueError(f"SVG viewBox must have four values: {svg_path}")
        min_x, min_y, width, height = map(float, values)
        border_x, border_y = min_x + inset_units, min_y + inset_units
        border_width, border_height = width - inset_units * 2, height - inset_units * 2
    else:
        number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
        coordinates: list[float] = []
        geometry_tags = {"path", "polyline", "polygon", "line", "rect", "circle", "ellipse", "text"}

        def collect(element: ET.Element, inside_defs: bool = False) -> None:
            local_name = element.tag.rsplit("}", 1)[-1]
            inside_defs = inside_defs or local_name == "defs"
            if not inside_defs and local_name in geometry_tags:
                for attribute in ("d", "points", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "rx", "ry"):
                    coordinates.extend(float(value) for value in re.findall(number, element.get(attribute, "")))
            for child in element:
                collect(child, inside_defs)

        collect(root)
        if len(coordinates) < 2:
            raise ValueError(f"SVG has no drawable geometry: {svg_path}")
        min_x, max_x = min(coordinates[0::2]), max(coordinates[0::2])
        min_y, max_y = min(coordinates[1::2]), max(coordinates[1::2])
        width, height = max_x - min_x, max_y - min_y
        root.set("viewBox", f"{min_x - inset_units:g} {min_y - inset_units:g} {width + inset_units * 2:g} {height + inset_units * 2:g}")
        root.set("width", f"{(width + inset_units * 2) * SVG_UNIT_MM:g}mm")
        root.set("height", f"{(height + inset_units * 2) * SVG_UNIT_MM:g}mm")
        border_x, border_y = min_x, min_y
        border_width, border_height = width, height
    if width <= inset_units * 2 or height <= inset_units * 2:
        raise ValueError(f"SVG is too small for a {inset_mm:g} mm inset: {svg_path}")

    border_tag = f"{{{namespace}}}rect"
    for element in root.findall(border_tag):
        if element.get("id") == "inset-border":
            root.remove(element)

    border = ET.Element(
        border_tag,
        {
            "id": "inset-border",
            "x": str(border_x),
            "y": str(border_y),
            "width": str(border_width),
            "height": str(border_height),
            "fill": "none",
            "stroke": "black",
            "stroke-width": str(stroke_units),
        },
    )
    root.append(border)
    tree.write(svg_path, encoding="utf-8", xml_declaration=True)


def export_floor_plans(
    ifc_path: Path,
    output_dir: Path,
    ifc_convert: str | None = None,
    threads: int = 1,
) -> list[Path]:
    """Use IfcConvert to export one SVG floor plan for every building storey."""
    model = ifcopenshell.open(str(ifc_path))
    converter = find_ifc_convert(ifc_convert)
    geometry_settings = ifcopenshell.geom.settings()
    geometry_settings.set(geometry_settings.USE_WORLD_COORDS, True)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    skipped: list[str] = []

    for index, storey in enumerate(model.by_type("IfcBuildingStorey"), start=1):
        if STOREY_TO_EXPORT is not None and storey.Name != STOREY_TO_EXPORT:
            continue
        output_path = output_dir / f"{index:02d}_{safe_filename(storey.Name, 'storey')}.svg"
        command = [
            converter,
            "--yes",
            "--plan",
            "--model",
            "--print-space-names",
            "--print-space-areas",
            "--door-arcs",
            "--scale",
            SCALE,
            "--use-element-names",
            "--use-element-guids",
            "--include+",
            "attribute",
            "GlobalId",
            storey.GlobalId,
            "--threads",
            str(threads),
            str(ifc_path),
            str(output_path),
        ]
        try:
            subprocess.run(command, check=True)
            add_grid_axes(output_path, model, storey, geometry_settings)
            add_inset_border(output_path)
        except subprocess.CalledProcessError:
            if output_path.exists():
                output_path.unlink()
            skipped.append(storey.Name or f"storey {index}")
            continue
        outputs.append(output_path)
    if skipped:
        print(f"Skipped storeys without convertible geometry: {', '.join(skipped)}")
    return outputs


def main() -> None:
    outputs = export_floor_plans(
        IFC_FILE,
        OUTPUT_DIR,
        IFC_CONVERT,
        THREADS,
    )
    print(f"Exported {len(outputs)} floor plan(s) to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
