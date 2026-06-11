# Fit Selection In Frame (SketchUp Ruby)
#
# This script perfectly frames the active camera around the selected
# objects by projecting their exact 3D vertices into the camera's
# 2D view space, calculating the required physical distance
# based on the camera's true Field of View (FOV).

require 'sketchup.rb'

module HD
  module FitSelectionInFrame

    # ==========================================
    # USER SETTINGS
    # ==========================================
    # The safe frame margin amount is represented as a percentage.
    # 0   = The object touches the exact edge of the render frame.
    # 15  = (Default) The object takes up 85% of the frame with a 15% margin around it.
    # 50  = The object takes up 50% of the frame, leaving a massive margin.
    MARGIN_PERCENTAGE = 15.0
    # ==========================================

    extend self

    # Geom::Vector3d has no scalar multiply (* is cross product), so roll our own.
    def scaled(vector, s)
      Geom::Vector3d.new(vector.x * s, vector.y * s, vector.z * s)
    end

    # -------------------------------------------------------------
    # RESTORE PREVIOUS CAMERA
    # -------------------------------------------------------------
    # SketchUp does not record scripted camera changes, so neither Ctrl+Z nor
    # Camera > Previous can undo the fit. Instead, the camera state is
    # remembered before every fit and a second menu item jumps back to it.
    def remember_camera(cam)
      @previous_camera = {
        eye: cam.eye,
        target: cam.target,
        up: cam.up,
        perspective: cam.perspective?,
        fov: cam.perspective? ? cam.fov : nil,
        height: cam.perspective? ? nil : cam.height,
        aspect_ratio: cam.aspect_ratio
      }
    end

    def restore_previous_camera
      if @previous_camera.nil?
        UI.messagebox("No camera move to restore yet.\n" \
                      "Run \"Fit Selection In Frame\" first.")
        return
      end
      view = Sketchup.active_model.active_view
      cam = view.camera
      prev = @previous_camera
      cam.perspective = prev[:perspective]
      cam.set(prev[:eye], prev[:target], prev[:up])
      cam.aspect_ratio = prev[:aspect_ratio] if prev[:aspect_ratio] > 0.0
      if prev[:perspective]
        cam.fov = prev[:fov]
      else
        cam.height = prev[:height]
      end
      view.invalidate
    end

    # -------------------------------------------------------------
    # COLLECT ALL WORLD-SPACE VERTICES
    # -------------------------------------------------------------
    # Faces and Edges contribute exact vertex positions (Edges cover arcs,
    # circles and curves - in SketchUp those are chains of edges). Groups and
    # ComponentInstances recurse with an accumulated transformation.
    # Anything else (Image, Text, Dimension, SectionPlane, construction
    # geometry, plugin entities...) falls back to its bounding box corners,
    # mirroring the other DCC ports' "bulletproof fallback".
    def collect_world_points(entity, transformation, points)
      case entity
      when Sketchup::Face, Sketchup::Edge
        entity.vertices.each do |v|
          points << v.position.transform(transformation)
        end
      when Sketchup::Group
        t = transformation * entity.transformation
        entity.entities.each { |e| collect_world_points(e, t, points) }
      when Sketchup::ComponentInstance
        t = transformation * entity.transformation
        entity.definition.entities.each { |e| collect_world_points(e, t, points) }
      else
        begin
          bounds = entity.bounds
          if bounds.valid?
            (0..7).each do |i|
              points << bounds.corner(i).transform(transformation)
            end
          end
        rescue StandardError
          # Entity exposes no usable bounds - skip it silently.
        end
      end
    end

    def fit_selection_in_frame
      model = Sketchup.active_model
      view = model.active_view
      cam = view.camera

      # -------------------------------------------------------------
      # 1. VALIDATE THE ENVIRONMENT
      # -------------------------------------------------------------
      # (A SketchUp view always has a camera, so no "no camera" check is needed.)
      sel = model.selection
      if sel.empty?
        UI.messagebox("Please select at least one object to fit into the camera view.")
        return
      end

      # -------------------------------------------------------------
      # 2. COLLECT ALL WORLD-SPACE VERTICES
      # -------------------------------------------------------------
      all_verts_world = []
      identity = Geom::Transformation.new
      sel.each { |e| collect_world_points(e, identity, all_verts_world) }

      if all_verts_world.empty?
        UI.messagebox("No valid geometry points found to fit.")
        return
      end

      # -------------------------------------------------------------
      # 3. PROJECT WORLD VERTICES INTO CAMERA-LOCAL SPACE
      # -------------------------------------------------------------
      # Build an orthonormal camera frame with backward = -forward, so
      # vertices in front of the lens get NEGATIVE local Z. This matches the
      # Max/Maya/Blender/C4D ports and keeps the fitting core identical.
      eye = cam.eye
      forward = (cam.target - eye).normalize
      right = (forward * cam.up).normalize     # * is cross product
      true_up = (right * forward).normalize    # re-orthogonalized up
      backward = forward.reverse

      local_verts = all_verts_world.map do |p|
        d = p - eye
        [d % right, d % true_up, d % backward]  # % is dot product
      end

      # The frame aspect: an explicit camera aspect ratio wins, otherwise the
      # live viewport is the frame ("aspect ratio safe" in SketchUp terms).
      aspect = cam.aspect_ratio
      aspect = view.vpwidth.to_f / view.vpheight.to_f if aspect <= 0.0

      # Remember the current camera so the user can jump back via
      # Extensions > Fit Selection In Frame - Restore Previous Camera.
      remember_camera(cam)

      if cam.perspective?
        # -------------------------------------------------------------
        # 4. DETERMINE CAMERA FIELD OF VIEW (FOV)
        # -------------------------------------------------------------
        # cam.fov is in degrees; fov_is_height? says which axis it measures.
        fov_rad = cam.fov * Math::PI / 180.0
        if cam.fov_is_height?
          tan_v = Math.tan(fov_rad / 2.0)
          tan_h = tan_v * aspect
        else
          tan_h = Math.tan(fov_rad / 2.0)
          tan_v = tan_h / aspect
        end
        fit_perspective(view, cam, eye, right, true_up, backward, forward,
                        local_verts, tan_h, tan_v)
      else
        fit_parallel(view, cam, eye, right, true_up, backward, forward,
                     local_verts, aspect)
      end
    end

    # Inverse Screen Percentage margin model, identical to the other ports.
    def margin_scale_factor
      if MARGIN_PERCENTAGE > 50.0
        UI.messagebox("WARNING: A margin greater than 50% pushes the camera very far away.\n" \
                      "The object may disappear into SketchUp's view clipping at extreme distances.")
      end
      occupancy = 100.0 - MARGIN_PERCENTAGE
      occupancy = 0.1 if occupancy < 0.1
      100.0 / occupancy
    end

    # -------------------------------------------------------------
    # 5. ITERATIVE SCREEN-SPACE CENTERING AND SCALING (perspective)
    # -------------------------------------------------------------
    def fit_perspective(view, cam, eye, right, true_up, backward, forward,
                        local_verts, tan_h, tan_v)
      scale_factor = margin_scale_factor

      xs = local_verts.map { |v| v[0] }
      ys = local_verts.map { |v| v[1] }
      zs = local_verts.map { |v| v[2] }

      current_offset_x = (xs.min + xs.max) / 2.0
      current_offset_y = (ys.min + ys.max) / 2.0
      center_z = (zs.min + zs.max) / 2.0

      best_offset_z = -Float::INFINITY

      # Iterate up to 10 times to balance the X/Y optical center with the Z depth.
      10.times do
        max_required_offset_z = -Float::INFINITY

        local_verts.each do |x, y, z|
          dx = (x - current_offset_x).abs * scale_factor
          dy = (y - current_offset_y).abs * scale_factor

          min_depth_h = dx > 0.0001 ? dx / tan_h : 0.0
          min_depth_v = dy > 0.0001 ? dy / tan_v : 0.0

          required_offset_z = z + [min_depth_h, min_depth_v].max
          if required_offset_z > max_required_offset_z
            max_required_offset_z = required_offset_z
          end
        end

        # Failsafe for zero-volume selections.
        if max_required_offset_z.infinite? || max_required_offset_z.nan?
          max_required_offset_z = zs.max + 10.0
        end

        best_offset_z = max_required_offset_z

        screenspace_xs = []
        screenspace_ys = []

        local_verts.each do |x, y, z|
          depth = best_offset_z - z
          depth = 0.0001 if depth < 0.0001

          screenspace_xs << (x - current_offset_x) / (depth * tan_h)
          screenspace_ys << (y - current_offset_y) / (depth * tan_v)
        end

        optical_center_x = (screenspace_xs.min + screenspace_xs.max) / 2.0
        optical_center_y = (screenspace_ys.min + screenspace_ys.max) / 2.0

        physical_shift_x = optical_center_x * (best_offset_z - center_z) * tan_h
        physical_shift_y = optical_center_y * (best_offset_z - center_z) * tan_v

        current_offset_x += physical_shift_x
        current_offset_y += physical_shift_y

        break if physical_shift_x.abs < 0.001 && physical_shift_y.abs < 0.001
      end

      # -------------------------------------------------------------
      # 6. APPLY THE NEW CAMERA
      # -------------------------------------------------------------
      new_eye = eye + scaled(right, current_offset_x) +
                scaled(true_up, current_offset_y) +
                scaled(backward, best_offset_z)

      # The target sits on the new optical axis at the selection's depth
      # center (SketchUp's eye->target distance is its native equivalent of
      # target distance; this keeps later orbits pivoting around the object).
      new_targ_dist = best_offset_z - center_z
      new_targ_dist = 10.0 if new_targ_dist < 0.1
      new_target = new_eye + scaled(forward, new_targ_dist)

      # Modify the live camera in place: this preserves FOV, aspect ratio and
      # every other camera property. (SketchUp does not record scripted camera
      # moves, so "Restore Previous Camera" is the way back, not Ctrl+Z or
      # Camera > Previous.)
      cam.set(new_eye, new_target, cam.up)
      view.invalidate
    end

    # -------------------------------------------------------------
    # PARALLEL PROJECTION FIT
    # -------------------------------------------------------------
    # No iteration needed: orthographic projection has no perspective
    # distortion, so the geometric center IS the optical center. Fitting
    # means centering the camera in the view plane and setting the view
    # height, not moving the camera back.
    def fit_parallel(view, cam, eye, right, true_up, backward, forward,
                     local_verts, aspect)
      scale_factor = margin_scale_factor

      xs = local_verts.map { |v| v[0] }
      ys = local_verts.map { |v| v[1] }
      zs = local_verts.map { |v| v[2] }

      center_x = (xs.min + xs.max) / 2.0
      center_y = (ys.min + ys.max) / 2.0
      center_z = (zs.min + zs.max) / 2.0

      # Distance does not affect framing in parallel projection, but geometry
      # behind the eye can clip - if any vertex is behind (local z > 0), slide
      # the eye back until everything is in front, with 10% depth padding.
      offset_z = 0.0
      if zs.max > 0.0
        padding = (zs.max - zs.min) * 0.1
        padding = 1.0 if padding < 1.0
        offset_z = zs.max + padding
      end

      extent_x = xs.max - xs.min
      extent_y = ys.max - ys.min
      height = [extent_y, extent_x / aspect].max * scale_factor
      height = 0.1 if height < 0.1

      new_eye = eye + scaled(right, center_x) +
                scaled(true_up, center_y) +
                scaled(backward, offset_z)

      new_targ_dist = offset_z - center_z
      new_targ_dist = 10.0 if new_targ_dist < 0.1
      new_target = new_eye + scaled(forward, new_targ_dist)

      # Modify the live camera in place (see the note in fit_perspective).
      cam.set(new_eye, new_target, cam.up)
      cam.height = height
      view.invalidate
    end

  end
end

unless file_loaded?(__FILE__)
  menu = UI.menu("Extensions")
  menu.add_item("Fit Selection In Frame") {
    HD::FitSelectionInFrame.fit_selection_in_frame
  }
  menu.add_item("Fit Selection In Frame - Restore Previous Camera") {
    HD::FitSelectionInFrame.restore_previous_camera
  }
  file_loaded(__FILE__)
end
