"""Create one SVG floor plan per IFC building storey."""

from __future__ import annotations

import shutil
import subprocess
import xml.etree.ElementTree as ET
import re
from pathlib import Path

import ifcopenshell

IFC_CONVERT = r"C:\Program Files\IfcConvert\IfcConvert.exe"


IFC_FILE = Path(
    r"C:\Users\timmc\OneDrive - Danmarks Tekniske Universitet\Skrivebord\3626D-A\BIM\01\26-01-D-ARCH.ifc"
)
OUTPUT_DIR = Path("floorplans")
THREADS = 7
SCALE = "1:100"
SVG_UNIT_MM = 10
BORDER_INSET_MM = 10
BORDER_STROKE_MM = 0.25


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
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    skipped: list[str] = []

    for index, storey in enumerate(model.by_type("IfcBuildingStorey"), start=1):
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
