"""
Fit Selection In Frame (Cinema 4D Python)

This script perfectly frames the active camera around the selected
objects by projecting their exact 3D vertices into the camera's
2D view space, calculating the required physical distance
based on the camera's true Field of View (FOV).
""" 

import math
import c4d
from c4d import utils, gui

# ==========================================
# USER SETTINGS
# ==========================================
# The safe frame margin amount is represented as a percentage.
# 0   = The object touches the exact edge of the render frame.
# 15  = (Default) The object takes up 85% of the frame with a 15% margin around it.
# 50  = The object takes up 50% of the frame, leaving a massive margin.
MARGIN_PERCENTAGE = 15
# ==========================================


def collect_world_points(op):
    """Return a list of world-space c4d.Vector points for the evaluated
    (deformed / polygonized) geometry of `op`, or None if it has no points.

    Uses Current State To Object (the C4D analog of snapshotAsMesh) so that
    parametric primitives, generators and deformers are all resolved. The clone
    keeps its full hierarchy because generators (Sweep, Cloner, Loft, Array...)
    need their child inputs to produce geometry. The clone's own matrix is reset
    to identity so the baked result root carries no local transform; op.GetMg()
    then re-applies the full world transform exactly once in walk().
    """
    clone = op.GetClone(c4d.COPYFLAGS_0)  # full clone incl. children (generators need them)
    if clone is None:
        return None
    # Reset to identity so walk()'s `mg * (local_ml * p)` doesn't double-apply
    # op's own local matrix (the baked root's GetMl would otherwise equal it).
    clone.SetMl(c4d.Matrix())

    temp = c4d.documents.BaseDocument()
    temp.InsertObject(clone)
    res = utils.SendModelingCommand(
        command=c4d.MCOMMAND_CURRENTSTATETOOBJECT,
        list=[clone],
        mode=c4d.MODELINGCOMMANDMODE_ALL,
        bc=c4d.BaseContainer(),
        doc=temp,
    )
    # CSTO returns a list of result roots (usually one, but some generators
    # produce several); fall back to the clone itself if the command failed.
    roots = res if isinstance(res, list) and len(res) > 0 else [clone]

    mg = op.GetMg()
    pts = []

    def walk(node, parent_ml):
        # Matrix of this node relative to the baked result root.
        local_ml = parent_ml * node.GetMl()
        if node.IsInstanceOf(c4d.Opoint):
            for p in node.GetAllPoints():
                pts.append(mg * (local_ml * p))
        child = node.GetDown()
        while child:
            walk(child, local_ml)
            child = child.GetNext()

    for root in roots:
        walk(root, c4d.Matrix())

    # Free the throwaway document so repeated calls don't leak scene graphs.
    c4d.documents.KillDocument(temp)
    return pts if pts else None


def fit_selection_in_frame():

    # -------------------------------------------------------------
    # 1. VALIDATE THE ENVIRONMENT
    # -------------------------------------------------------------
    doc = c4d.documents.GetActiveDocument()
    bd = doc.GetRenderBaseDraw()
    cam = bd.GetSceneCamera(doc) if bd else None
    if cam is None:
        gui.MessageDialog("No active scene camera found.\n"
                          "Look through a Camera object (not the default editor "
                          "camera) before running this tool.")
        return

    # Top-level selected objects only. collect_world_points() clones each with
    # its full hierarchy and recurses, so we must NOT pull in unselected
    # children here (GETACTIVEOBJECTFLAGS_CHILDREN) - for a Cloner/Sweep that
    # would add the source template at its own position, skewing the framing.
    sel = doc.GetActiveObjects(c4d.GETACTIVEOBJECTFLAGS_0)
    if not sel:
        gui.MessageDialog("Please select at least one object to fit into the "
                          "camera view.")
        return

    # -------------------------------------------------------------
    # 2. COLLECT ALL WORLD-SPACE VERTICES
    # -------------------------------------------------------------
    all_verts_world = []

    for op in sel:
        if op == cam:
            continue  # never fit the camera to its own geometry

        pts = collect_world_points(op)
        if pts:
            all_verts_world.extend(pts)
        else:
            # FALLBACK: lights, nulls, cameras and anything with no polygon
            # output. Use the object's local bounding box (center GetMp + half
            # extent GetRad) transformed to world space by its global matrix.
            mg = op.GetMg()
            mp = op.GetMp()
            rad = op.GetRad()
            for sx in (-1.0, 1.0):
                for sy in (-1.0, 1.0):
                    for sz in (-1.0, 1.0):
                        corner = c4d.Vector(mp.x + sx * rad.x,
                                            mp.y + sy * rad.y,
                                            mp.z + sz * rad.z)
                        all_verts_world.append(mg * corner)

    if not all_verts_world:
        gui.MessageDialog("No valid geometry points found to fit.")
        return

    # -------------------------------------------------------------
    # 3. PROJECT WORLD VERTICES INTO CAMERA-LOCAL SPACE
    # -------------------------------------------------------------
    # C4D cameras look down +Z. We define the local frame with backward = -v3
    # so vertices in front of the lens get NEGATIVE local Z, matching the
    # Max/Maya/Blender ports and letting steps 4-5 stay identical.
    cam_mg = cam.GetMg()
    right = cam_mg.v1
    up = cam_mg.v2
    backward = -cam_mg.v3
    campos = cam_mg.off

    cam_frame = c4d.Matrix(campos, right, up, backward)
    cam_inv = ~cam_frame  # world -> camera-local
    local_verts = [cam_inv * v for v in all_verts_world]

    # -------------------------------------------------------------
    # 4. DETERMINE CAMERA FIELD OF VIEW (FOV)
    # -------------------------------------------------------------
    # CAMERAOBJECT_FOV is the horizontal field of view, in radians.
    fov_h = cam[c4d.CAMERAOBJECT_FOV]
    if not fov_h:
        gui.MessageDialog("Camera has no usable horizontal FOV. Assuming 45 "
                          "degrees.")
        fov_h = math.radians(45.0)
    tan_h = math.tan(fov_h / 2.0)

    # Vertical slope from the render aspect ratio, mirroring the Max/Maya ports.
    rd = doc.GetActiveRenderData()
    render_aspect = float(rd[c4d.RDATA_XRES]) / float(rd[c4d.RDATA_YRES])
    tan_v = tan_h / render_aspect

    # -------------------------------------------------------------
    # 5. ITERATIVE SCREEN-SPACE CENTERING AND SCALING
    # -------------------------------------------------------------
    current_offset_x = (min(v.x for v in local_verts) + max(v.x for v in local_verts)) / 2.0
    current_offset_y = (min(v.y for v in local_verts) + max(v.y for v in local_verts)) / 2.0
    center_z = (min(v.z for v in local_verts) + max(v.z for v in local_verts)) / 2.0

    if MARGIN_PERCENTAGE > 50.0:
        gui.MessageDialog("WARNING: A margin greater than 50% pushes the camera "
                          "very far away. You may need to increase the camera's "
                          "Far Clipping limit so the object stays visible.")

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
    # 6. APPLY NEW TRANSFORMATION (single undo block)
    # -------------------------------------------------------------
    new_pos = campos + (right * current_offset_x) + (up * current_offset_y) + (backward * best_offset_z)

    new_targ_dist = best_offset_z - center_z
    if new_targ_dist < 0.1:
        new_targ_dist = 10.0

    doc.StartUndo()
    try:
        doc.AddUndo(c4d.UNDOTYPE_CHANGE, cam)

        # Move the camera: replace the position column, keep orientation.
        mg = cam.GetMg()
        mg.off = new_pos
        cam.SetMg(mg)

        # Focus distance = C4D's equivalent of Max's target distance.
        cam[c4d.CAMERAOBJECT_TARGETDISTANCE] = new_targ_dist

        # If a Target tag drives the camera's orientation, move the linked
        # target onto the new optical axis at the depth center so the tag's
        # re-orientation preserves the framing (parallels the Max port).
        target_tag = cam.GetTag(c4d.Ttargetexpression)
        if target_tag is not None:
            target = target_tag[c4d.TARGETEXPRESSIONTAG_LINK]
            if target is not None:
                doc.AddUndo(c4d.UNDOTYPE_CHANGE, target)
                target_pos = campos + (right * current_offset_x) + (up * current_offset_y) + (backward * center_z)
                tmg = target.GetMg()
                tmg.off = target_pos
                target.SetMg(tmg)
    finally:
        doc.EndUndo()

    c4d.EventAdd()


if __name__ == "__main__":
    fit_selection_in_frame()
