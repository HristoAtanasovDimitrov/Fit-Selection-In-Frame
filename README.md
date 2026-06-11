# Fit Selection In Frame

A highly precise, computationally accurate Python script with versions for **Autodesk 3ds Max**, **Blender**, **Autodesk Maya**, and **Maxon Cinema 4D** that perfectly frames the active camera around selected objects by projecting their exact 3D vertices into the camera's 2D view space.

Unlike standard bounding-box tools, these scripts use **Frustum Culling** and **Iterative Optical Centering** to guarantee that the geometry perfectly touches the edges of the frame, avoiding perspective-distortion off-centering.

## Features
- **Perfect Optical Centering**: Identifies the 2D visual center to correct for perspective camera distortion (meaning the object physically looks centered on your screen, even if one side is closer to the lens than the other).
- **Geometric Precision**: Evaluates the actual mesh vertices of your selection rather than a rough rectangular bounds block.
- **Inverse Screen Percentage Margin**: A mathematically scaled padding model. Set the margin to `0%` to touch the exact pixels of the frame edge, `50%` to occupy exactly half the screen, or `99%` to shrink the object to a tiny speck in the distance.
- **Aspect Ratio Safe**: Calculates the slope of the view frustum (cone) by verifying both the Render Output Aspect Ratio and the active Viewport size, ensuring it never clips regardless of standard UI window sizing.
- **Bulletproof Fallbacks**: Safely handles non-geometry objects (Lights, Splines, Empties, Helpers) by falling back to their basic bounding boxes without crashing. In **Maya**, this fallback also covers plugin shapes that expose no polygon mesh — such as **VRayProxy** render proxies — by framing their true world-space bounds (via `exactWorldBoundingBox`) instead of an inaccurate node bounding box.

---

## Installation

There are separate scripts depending on your 3D software. You do not need to restart your software to use or update them.

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

## Usage

1. **Activate a Camera View**: Ensure the viewport you are actively looking through is a physical or standard camera (e.g., Press `C` in 3ds Max, `Numpad 0` in Blender, look through a camera in Maya, or look through a Camera object in Cinema 4D).
2. **Select Objects**: Select the mesh(es) you want to fit on screen.
3. **Run the Script**. The camera's physical position (and target depth) will seamlessly transition to perfect optical framing. You can freely use `CTRL+Z` to undo the movement instantly.

## Adjusting the Margin

Open the respective script (`Fit-Selection-In-Frame_(3ds Max).py` or `Fit-Selection-In-Frame_(Blender).py`) in any text editor. At the very top, you will see a simple configuration block:

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
