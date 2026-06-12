# Fit Selection In Frame

A precise, computationally accurate script with versions for **Autodesk 3ds Max**, **Blender**, **Autodesk Maya**, **Maxon Cinema 4D**, **Trimble SketchUp**, **SideFX Houdini**, and **Rhinoceros 3D** that perfectly frames the active camera around selected objects by projecting their exact 3D vertices into the camera's 2D view space.

Unlike standard bounding-box tools, these scripts use **Frustum Culling** and **Iterative Optical Centering** to guarantee that the geometry perfectly touches the edges of the frame, avoiding perspective-distortion off-centering.

## Features
- **Perfect Optical Centering**: Identifies the 2D visual center to correct for perspective camera distortion (meaning the object physically looks centered on your screen, even if one side is closer to the lens than the other).
- **Geometric Precision**: Evaluates the actual mesh vertices of your selection rather than a rough rectangular bounds block.
- **Inverse Screen Percentage Margin**: A mathematically scaled padding model. Set the margin to `0%` to touch the exact pixels of the frame edge, `50%` to occupy exactly half the screen, or `99%` to shrink the object to a tiny speck in the distance.
- **Aspect Ratio Safe**: Calculates the slope of the view frustum (cone) by verifying both the Render Output Aspect Ratio and the active Viewport size, ensuring it never clips regardless of standard UI window sizing.
- **Bulletproof Fallbacks**: Safely handles non-geometry objects (Lights, Splines, Empties, Helpers) by falling back to their basic bounding boxes without crashing. In **Maya**, this fallback also covers plugin shapes that expose no polygon mesh - such as **VRayProxy** render proxies - by framing their true world-space bounds (via `exactWorldBoundingBox`) instead of an inaccurate node bounding box.

---

## Installation

There are separate scripts depending on your 3D software. For 3ds Max, Blender, Maya, Cinema 4D, Houdini and Rhino you do not need to restart your software to use or update them.

### For 3ds Max
1. Download or clone `Fit-Selection-In-Frame_(3ds Max).py` to your local drive.
2. Open **3ds Max**.
3. Go to **Scripting > Run Script...**
4. Select the `Fit-Selection-In-Frame_(3ds Max).py` file.

### For Blender
1. Download or clone `Fit-Selection-In-Frame_(Blender).py` to your local drive.
2. Open **Blender**.
3. Go to the **Scripting** workspace.
4. Open the `Fit-Selection-In-Frame_(Blender).py` file and click **Run Script** (the play icon).

### For Maya
1. Download or clone `Fit-Selection-In-Frame_(Maya).py` to your local drive.
2. Open **Maya**.
3. Open the **Script Editor** (bottom-right icon or **Windows > General Editors > Script Editor**).
4. In a **Python** tab, open the `Fit-Selection-In-Frame_(Maya).py` file and click **Execute** (the double-play icon).

### For Cinema 4D
1. Download or clone `Fit-Selection-In-Frame_(Cinema 4D).py` to your local drive.
2. Open **Cinema 4D**.
3. Open the **Script Manager** (**Extensions > Script Manager**, or **Shift+F11**).
4. Open the `Fit-Selection-In-Frame_(Cinema 4D).py` file and click **Execute**.

### For SketchUp
1. Download or clone `Fit-Selection-In-Frame_(SketchUp).rb` to your local drive.
2. Copy it into your SketchUp **Plugins** folder:
   - **Windows**: `%APPDATA%\SketchUp\SketchUp <version>\SketchUp\Plugins`
   - **Mac**: `~/Library/Application Support/SketchUp <version>/SketchUp/Plugins`
3. Restart SketchUp (or load the file once via **Window > Ruby Console**).
4. Run it from **Extensions > Fit Selection In Frame**. You can bind a keyboard shortcut to it under **Window > Preferences > Shortcuts**.

### For Houdini
1. Download or clone `Fit-Selection-In-Frame_(Houdini).py` to your local drive.
2. Open **Houdini**.
3. Go to **Windows > Python Source Editor**, paste the contents of the file (or open it), and click **Apply** to run it once.
4. For a permanent toolbar button: right-click an empty area of any shelf, choose **New Tool...**, paste the script into the **Script** tab (language: Python), and give it a name like *Fit Selection In Frame*. You can bind a keyboard shortcut in the tool's **Hotkeys** tab.

### For Rhino
1. Download or clone `Fit-Selection-In-Frame_(Rhino).py` to your local drive. The script works in both **Rhino 7** (IronPython) and **Rhino 8** (Python 3).
2. **Rhino 7**: run `EditPythonScript`, open the file, and press **F5** (or use `_-RunPythonScript` with the file path).
3. **Rhino 8**: run `ScriptEditor`, open the file, and click **Run**.
4. For a permanent toolbar button or alias, use the macro: `! _-RunPythonScript "C:\path\to\Fit-Selection-In-Frame_(Rhino).py"`

## Usage

1. **Activate a Camera View**: Ensure the viewport you are actively looking through is a physical or standard camera (e.g., Press `C` in 3ds Max, `Numpad 0` in Blender, look through a camera in Maya, look through a Camera object in Cinema 4D, or lock the viewport to a camera in Houdini; in SketchUp and Rhino the active view is always a camera, so no extra step is needed).
2. **Select Objects**: Select the mesh(es) you want to fit on screen.
3. **Run the Script**. The camera's physical position (and target depth) will seamlessly transition to perfect optical framing. You can freely use `CTRL+Z` to undo the movement instantly.

> **SketchUp note**: SketchUp cannot undo scripted camera moves - neither Ctrl+Z nor **Camera > Previous** applies. Use **Extensions > Fit Selection In Frame - Restore Previous Camera** to jump back to the pre-fit view instead. SketchUp's **Parallel Projection** mode is fully supported (the tool sets the view height instead of moving the camera back). Running the tool while in **Two-Point Perspective** returns the view to standard perspective, exactly as orbiting does.

> **Houdini note**: both Perspective and Orthographic camera projections are supported (orthographic fits adjust the camera's **Ortho Width** instead of moving it back). The camera's **Focus Distance** parameter is updated to the selection's depth center. Cameras driven by look-at/CHOP constraints are moved as plain transforms - constraint targets are not relocated.

> **Rhino note**: camera moves are restored with Rhino's **UndoView** command, not Ctrl+Z. Parallel-projection viewports (Top/Front/Right) are fully supported - the tool adjusts the view rectangle instead of moving the camera back. Two-point perspective is treated as plain perspective.

## Adjusting the Margin

Open the respective script (e.g. `Fit-Selection-In-Frame_(3ds Max).py` or `Fit-Selection-In-Frame_(SketchUp).rb`) in any text editor. At the very top, you will see a simple configuration block:

```python
# ==========================================
# USER SETTINGS
# ==========================================
MARGIN_PERCENTAGE = 15
```

The script uses **Inverse Screen Percentage** logic.
- `0`: The geometry perfectly brushes the extreme edges of the render frame.
- `15`: The object occupies exactly 85% of the frame, leaving a standard 15% margin around it.
- `50`: The object occupies exactly 50% of the center of the frame.
- `99`: The object occupies a tiny 1% footprint in the center.

> **Warning**: Setting the margin greater than 50% means the camera is physically being pushed extremely far away to force the object to look tiny. You may need to increase your Camera's physical `Clip End` or `Far Clipping Plane` limit within your 3D software to ensure the object doesn't vanish from the viewport depths!
