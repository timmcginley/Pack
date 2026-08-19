"""Create one SVG floor plan per IFC building storey."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import ifcopenshell

IFC_CONVERT = r"C:\Program Files\IfcConvert\IfcConvert.exe"


IFC_FILE = Path(
    r"C:\Users\timmc\OneDrive - Danmarks Tekniske Universitet\Skrivebord\3626D-A\BIM\01\26-01-D-ARCH.ifc"
)
OUTPUT_DIR = Path("floorplans")
THREADS = 7
SCALE = "1:100"


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
