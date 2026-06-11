"""
Fit Selection In Frame (Maya Python)

This script perfectly frames the active camera around the selected
objects by projecting their exact 3D vertices into the camera's
2D view space, calculating the required physical distance
based on the camera's true Field of View (FOV).
""" 

import math
import maya.api.OpenMaya as om
import maya.api.OpenMayaUI as omui  # M3dView lives here, NOT in OpenMaya
import maya.cmds as cmds

# ==========================================
# USER SETTINGS
# ==========================================
# The safe frame margin amount is represented as a percentage.
# 0   = The object touches the exact edge of the render frame.
# 15  = (Default) The object takes up 85% of the frame with a 15% margin around it.
# 50  = The object takes up 50% of the frame, leaving a massive margin.
MARGIN_PERCENTAGE = 15
# ==========================================


def fit_selection_in_frame():

    # -------------------------------------------------------------
    # 1. VALIDATE THE ENVIRONMENT
    # -------------------------------------------------------------
    # The active 3D view's camera is the one the focused viewport looks
    # through (the default 'persp' is accepted, like the Max/Blender ports).
    # M3dView is in OpenMayaUI (omui), not OpenMaya (om).
    try:
        view = omui.M3dView.active3dView()
        cam_dag = view.getCamera()  # MDagPath to the active view's camera
    except Exception:
        cmds.confirmDialog(title="Fit Camera",
                           message="No active viewport camera found.\nActivate a camera viewport before running this tool.",
                           button=["OK"])
        return

    sel_list = om.MGlobal.getActiveSelectionList()
    if sel_list.length() == 0:
        cmds.confirmDialog(title="Fit Camera",
                           message="Please select at least one object to fit into the camera view.",
                           button=["OK"])
        return

    # Resolve both the camera shape and its parent transform.
    # getCamera() may return either the transform or the shape, so normalise to
    # the SHAPE first (used for FOV / attributes), then derive the TRANSFORM
    # (used for the move) by stepping up one level.
    cam_shape_dag = om.MDagPath(cam_dag)
    if cam_shape_dag.apiType() != om.MFn.kCamera:
        cam_shape_dag.extendToShape()
    cam_shape_name = cam_shape_dag.fullPathName()
    cam_transform_dag = om.MDagPath(cam_shape_dag)
    cam_transform_dag.pop()  # step up from shape to transform
    cam_transform_name = cam_transform_dag.fullPathName()

    # -------------------------------------------------------------
    # 2. COLLECT ALL WORLD-SPACE VERTICES
    # -------------------------------------------------------------
    all_verts_world = []

    for i in range(sel_list.length()):
        # MSelectionList can contain non-DAG items (materials, render layers,
        # etc.). Skip anything without a DAG path instead of aborting the loop.
        try:
            dag = sel_list.getDagPath(i)
        except (TypeError, RuntimeError):
            continue

        # Skip the camera itself (whether the shape or its transform was selected).
        if dag.fullPathName() in (cam_shape_name, cam_transform_name):
            continue

        # MFnMesh.getPoints(kWorld) returns the deformer-evaluated geometry in
        # world space directly, so there is no temporary mesh to clean up.
        is_mesh = False
        try:
            shape_dag = om.MDagPath(dag)
            if shape_dag.apiType() != om.MFn.kMesh:
                shape_dag.extendToShape()
            if shape_dag.hasFn(om.MFn.kMesh):
                mesh_fn = om.MFnMesh(shape_dag)
                all_verts_world.extend(mesh_fn.getPoints(om.MSpace.kWorld))
                is_mesh = True
        except Exception:
            is_mesh = False

        if not is_mesh:
            # FALLBACK: lights, locators, NURBS, and plugin shapes such as
            # VRayProxy have no polygon mesh. cmds.exactWorldBoundingBox queries
            # the drawn world-space bounds and is reliable for plugin shapes,
            # whereas MFnDagNode.boundingBox reports wrong extents for them.
            try:
                xmin, ymin, zmin, xmax, ymax, zmax = cmds.exactWorldBoundingBox(dag.fullPathName())
                all_verts_world.extend([
                    om.MPoint(xmin, ymin, zmin), om.MPoint(xmax, ymin, zmin),
                    om.MPoint(xmin, ymax, zmin), om.MPoint(xmax, ymax, zmin),
                    om.MPoint(xmin, ymin, zmax), om.MPoint(xmax, ymin, zmax),
                    om.MPoint(xmin, ymax, zmax), om.MPoint(xmax, ymax, zmax),
                ])
            except Exception:
                pass

    if not all_verts_world:
        cmds.confirmDialog(title="Fit Camera",
                           message="No valid geometry points found to fit.",
                           button=["OK"])
        return

    # -------------------------------------------------------------
    # 3. PROJECT WORLD VERTICES INTO CAMERA-LOCAL SPACE
    # -------------------------------------------------------------
    # Local +X = right, +Y = up, +Z = backward (the camera looks down -Z),
    # matching the convention used by the Max and Blender ports.
    cam_world_mtx = cam_transform_dag.inclusiveMatrix()
    cam_inv = cam_world_mtx.inverse()
    local_verts = [p * cam_inv for p in all_verts_world]

    # -------------------------------------------------------------
    # 4. DETERMINE CAMERA FIELD OF VIEW (FOV)
    # -------------------------------------------------------------
    # Maya stores focal length (mm) and film aperture (inches). The horizontal
    # half-FOV tangent is (aperture_mm / 2) / focal = (aperture_in * 25.4) / (2 * focal).
    cam_fn = om.MFnCamera(cam_shape_dag)
    focal = cam_fn.focalLength
    h_aperture_in = cam_fn.horizontalFilmAperture
    tan_h = (h_aperture_in * 25.4) / (2.0 * focal)

    # Vertical slope comes from the render aspect ratio, mirroring the Max port,
    # so all three ports behave consistently regardless of Maya's filmFit mode.
    render_w = cmds.getAttr("defaultResolution.width")
    render_h = cmds.getAttr("defaultResolution.height")
    render_aspect = float(render_w) / float(render_h)
    tan_v = tan_h / render_aspect

    # -------------------------------------------------------------
    # 5. ITERATIVE SCREEN-SPACE CENTERING AND SCALING
    # -------------------------------------------------------------
    # Initial guess: camera at the flat 3D center of the selection.
    current_offset_x = (min(v.x for v in local_verts) + max(v.x for v in local_verts)) / 2.0
    current_offset_y = (min(v.y for v in local_verts) + max(v.y for v in local_verts)) / 2.0
    center_z = (min(v.z for v in local_verts) + max(v.z for v in local_verts)) / 2.0

    if MARGIN_PERCENTAGE > 50.0:
        cmds.warning("Fit Camera: a margin above 50% pushes the camera very far away. "
                     "You may need to raise the camera's Far Clip Plane so the object stays visible.")

    occupancy = 100.0 - MARGIN_PERCENTAGE
    if occupancy < 0.1:
        occupancy = 0.1
    scale_factor = 100.0 / occupancy

    best_offset_z = -float('inf')

    # Iterate up to 10 times to balance the X/Y optical center with the Z depth.
    for iteration in range(10):
        max_required_offset_z = -float('inf')

        for v in local_verts:
            dx = abs(v.x - current_offset_x) * scale_factor
            dy = abs(v.y - current_offset_y) * scale_factor

            min_depth_h = (dx / tan_h) if dx > 0.0001 else 0.0
            min_depth_v = (dy / tan_v) if dy > 0.0001 else 0.0

            required_d = max(min_depth_h, min_depth_v)
            required_offset_z = v.z + required_d

            if required_offset_z > max_required_offset_z:
                max_required_offset_z = required_offset_z

        # Failsafe for zero-volume selections.
        if math.isinf(max_required_offset_z) or math.isnan(max_required_offset_z):
            max_required_offset_z = max(v.z for v in local_verts) + 10.0

        best_offset_z = max_required_offset_z

        screenspace_xs = []
        screenspace_ys = []

        for v in local_verts:
            depth = best_offset_z - v.z
            if depth < 0.0001:
                depth = 0.0001

            sx = (v.x - current_offset_x) / (depth * tan_h)
            sy = (v.y - current_offset_y) / (depth * tan_v)

            screenspace_xs.append(sx)
            screenspace_ys.append(sy)

        min_sx, max_sx = min(screenspace_xs), max(screenspace_xs)
        min_sy, max_sy = min(screenspace_ys), max(screenspace_ys)

        optical_center_x = (min_sx + max_sx) / 2.0
        optical_center_y = (min_sy + max_sy) / 2.0

        physical_shift_x = optical_center_x * (best_offset_z - center_z) * tan_h
        physical_shift_y = optical_center_y * (best_offset_z - center_z) * tan_v

        current_offset_x += physical_shift_x
        current_offset_y += physical_shift_y

        if abs(physical_shift_x) < 0.001 and abs(physical_shift_y) < 0.001:
            break

    # -------------------------------------------------------------
    # 6. APPLY NEW TRANSFORMATION (single undo chunk)
    # -------------------------------------------------------------
    # The camera's world-space local axes are rows 0-2 of its world matrix;
    # row 3 is its current world position.
    right    = om.MVector(cam_world_mtx.getElement(0, 0), cam_world_mtx.getElement(0, 1), cam_world_mtx.getElement(0, 2))
    up       = om.MVector(cam_world_mtx.getElement(1, 0), cam_world_mtx.getElement(1, 1), cam_world_mtx.getElement(1, 2))
    backward = om.MVector(cam_world_mtx.getElement(2, 0), cam_world_mtx.getElement(2, 1), cam_world_mtx.getElement(2, 2))
    orig_pos = om.MVector(cam_world_mtx.getElement(3, 0), cam_world_mtx.getElement(3, 1), cam_world_mtx.getElement(3, 2))

    new_pos = orig_pos + (right * current_offset_x) + (up * current_offset_y) + (backward * best_offset_z)

    new_targ_dist = best_offset_z - center_z
    if new_targ_dist < 0.1:
        new_targ_dist = 10.0

    cmds.undoInfo(openChunk=True, chunkName="Fit Camera Screen Space")
    try:
        cmds.xform(cam_transform_name, worldSpace=True,
                   translation=[new_pos.x, new_pos.y, new_pos.z])

        # centerOfInterest = Maya's equivalent of Max's target distance.
        if cmds.attributeQuery("centerOfInterest", node=cam_shape_name, exists=True):
            cmds.setAttr(cam_shape_name + ".centerOfInterest", new_targ_dist)

        # focusDistance = depth-of-field focus, mirroring the Blender port.
        if cmds.attributeQuery("focusDistance", node=cam_shape_name, exists=True):
            cmds.setAttr(cam_shape_name + ".focusDistance", new_targ_dist)
    finally:
        cmds.undoInfo(closeChunk=True)


if __name__ == "__main__":
    fit_selection_in_frame()
