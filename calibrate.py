#!/usr/bin/env python3
"""
Invisible Spatial Switch - Calibration Utility
Serves a live MJPEG stream over HTTP showing defined spatial zones overlayed on the Kinect depth frame.
"""

import json
import logging
import time
import cv2
import freenect
import numpy as np
from flask import Flask, Response

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

app = Flask(__name__)
CONFIG_PATH = "config.json"


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def get_depth_frame():
    """Fetch depth map from Kinect v1 using libfreenect."""
    depth, _ = freenect.sync_get_depth()
    if depth is None:
        return None
    return depth


def generate_calibration_frames():
    config = load_config()
    web_cfg = config.get("web", {})
    zones = config.get("zones", {})

    while True:
        depth = get_depth_frame()
        if depth is None:
            time.sleep(0.03)
            continue

        # Normalize depth to 8-bit image for visual clarity (0 to 255)
        # Depth values typically range from ~500mm to ~4000mm
        depth_clipped = np.clip(depth, 500, 2000)
        depth_vis = (
            (depth_clipped - 500) / (2000 - 500) * 255
        ).astype(np.uint8)
        frame_bgr = cv2.applyColorMap(depth_vis, cv2.COLORMAP_JET)

        for name, zone in zones.items():
            x_min, x_max = zone["x_min"], zone["x_max"]
            y_min, y_max = zone["y_min"], zone["y_max"]
            z_min, z_max = zone["z_min"], zone["z_max"]
            p_thresh = zone.get("pixel_threshold", 100)

            # Crop sub-region
            crop = depth[y_min:y_max, x_min:x_max]
            active_mask = (crop >= z_min) & (crop <= z_max)
            active_count = np.sum(active_mask)

            # Determine box color: Green if active threshold reached, Yellow otherwise
            box_color = (
                (0, 255, 0) if active_count >= p_thresh else (0, 255, 255)
            )

            # Draw bounding box
            cv2.rectangle(
                frame_bgr, (x_min, y_min), (x_max, y_max), box_color, 2
            )

            # Render zone label and detection status
            label = f"{name} ({zone['type']})"
            stats = f"Px: {active_count}/{p_thresh} Z:[{z_min}-{z_max}]"

            cv2.putText(
                frame_bgr,
                label,
                (x_min, max(y_min - 15, 15)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (255, 255, 255),
                1,
            )
            cv2.putText(
                frame_bgr,
                stats,
                (x_min, y_max + 15),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.35,
                box_color,
                1,
            )

        # Encode frame to JPEG format
        _, jpeg = cv2.imencode(".jpg", frame_bgr)
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
        )
        time.sleep(0.03)


@app.route("/")
def video_feed():
    return Response(
        generate_calibration_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


if __name__ == "__main__":
    cfg = load_config()
    host = cfg.get("web", {}).get("host", "0.0.0.0")
    port = cfg.get("web", {}).get("port", 8080)
    logging.info(
        f"Starting Calibration Web Server at http://{host}:{port}"
    )
    app.run(host=host, port=port, debug=False, threaded=True)
