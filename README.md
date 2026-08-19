# Pack

Run the Python wrapper to export one SVG floor plan per `IfcBuildingStorey` using the IfcOpenShell `IfcConvert` engine:

```powershell
python main.py
```

The model path, output folder, converter path, and thread count are hard-coded at the top of `main.py`. Set `IFC_CONVERT` to the full path of `IfcConvert.exe` if it is not on `PATH`. The wrapper includes walls, windows, doors, openings, grid axes, door arcs, and space names.