#!/usr/bin/env python3
"""
Invisible Spatial Switch - Core Daemon
Processes depth frames from Kinect, tracks spatial zones (switch, slider, color),
and syncs bidirectional state via MQTT.
"""

import argparse
import json
import logging
import math
import sys
import time
import cv2
import freenect
import numpy as np
import paho.mqtt.client as mqtt
from flask import Flask, Response

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

app = Flask(__name__)
GLOBAL_DEPTH_FRAME = None


class SpatialSwitchEngine:

    def __init__(self, config_path="config.json"):
        with open(config_path, "r") as f:
            self.config = json.load(f)

        self.zones = self.config.get("zones", {})
        self.mqtt_cfg = self.config.get("mqtt", {})
        self.base_topic = self.mqtt_cfg.get(
            "base_topic", "invisible-spatial-switch"
        )

        # Zone state and interaction tracking
        self.states = {}
        self.zone_data = {}

        for name, zone in self.zones.items():
            z_type = zone.get("type", "switch")
            if z_type == "switch":
                mode = zone.get("mode", "toggle")
                pressed = zone.get("pressed", "ON/OFF")
                tokens = pressed.split("/")
                initial_state = tokens[0] if len(tokens) > 0 else "OFF"
                self.states[name] = initial_state
            elif z_type == "slider":
                self.states[name] = str(zone.get("min_value", 0))
            elif z_type == "color":
                self.states[name] = (
                    "0,0,100"
                    if zone.get("color_system") == "hsb"
                    else "255,255,255"
                )

            self.zone_data[name] = {
                "active": False,
                "last_action_time": 0,
                "history": [],
            }

        self.init_mqtt()

    def init_mqtt(self):
        self.client = mqtt.Client()
        self.client.on_connect = self.on_mqtt_connect
        self.client.on_message = self.on_mqtt_message

        try:
            self.client.connect(
                self.mqtt_cfg.get("broker", "localhost"),
                self.mqtt_cfg.get("port", 1883),
                self.mqtt_cfg.get("keepalive", 60),
            )
            self.client.loop_start()
        except Exception as e:
            logging.error(f"MQTT connection error: {e}")

    def on_mqtt_connect(self, client, userdata, flags, rc):
        logging.info(
            f"Connected to MQTT Broker with result code {rc}"
        )
        for name in self.zones.keys():
            state_topic = f"{self.base_topic}/{name}/state"
            client.subscribe(state_topic)
            logging.info(f"Subscribed to state updates: {state_topic}")

    def on_mqtt_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode("utf-8").strip()

        # Parse external state synchronization updates from Home Assistant / openHAB
        for name in self.zones.keys():
            state_topic = f"{self.base_topic}/{name}/state"
            if topic == state_topic:
                if self.states[name] != payload:
                    logging.info(
                        f"External state sync received for '{name}': {payload}"
                    )
                    self.states[name] = payload

    def send_command(self, zone_name, command_payload):
        cmd_topic = f"{self.base_topic}/{zone_name}/command"
        logging.info(
            f"Publishing Command -> Topic: {cmd_topic} | Payload: {command_payload}"
        )
        self.client.publish(cmd_topic, command_payload)

    def process_frame(self, depth):
        global GLOBAL_DEPTH_FRAME
        GLOBAL_DEPTH_FRAME = depth
        current_time = time.time()

        for name, zone in self.zones.items():
            z_type = zone.get("type", "switch")
            x_min, x_max = zone["x_min"], zone["x_max"]
            y_min, y_max = zone["y_min"], zone["y_max"]
            z_min, z_max = zone["z_min"], zone["z_max"]
            p_thresh = zone.get("pixel_threshold", 100)

            crop = depth[y_min:y_max, x_min:x_max]
            mask = (crop >= z_min) & (crop <= z_max)
            active_count = np.sum(mask)

            is_triggered = active_count >= p_thresh
            z_data = self.zone_data[name]

            if z_type == "switch":
                self.handle_switch_zone(
                    name, zone, is_triggered, current_time
                )
            elif z_type == "slider":
                self.handle_slider_zone(
                    name, zone, mask, is_triggered, current_time
                )
            elif z_type == "color":
                self.handle_color_zone(
                    name, zone, mask, is_triggered, current_time
                )

            z_data["active"] = is_triggered

    def handle_switch_zone(self, name, zone, is_triggered, current_time):
        z_data = self.zone_data[name]
        mode = zone.get("mode", "toggle")
        pressed = zone.get("pressed", "ON/OFF")
        tokens = pressed.split("/")

        if mode == "toggle":
            debounce = zone.get("debounce", 0.8)
            if is_triggered and not z_data["active"]:
                if current_time - z_data["last_action_time"] > debounce:
                    z_data["last_action_time"] = current_time
                    if len(tokens) == 2:
                        next_state = (
                            tokens[0]
                            if self.states[name] == tokens[1]
                            else tokens[1]
                        )
                    else:
                        next_state = tokens[0]
                    self.states[name] = next_state
                    self.send_command(name, next_state)

        elif mode == "hold":
            # Sends token[0] while hand is detected, token[1] upon release
            if is_triggered and not z_data["active"]:
                cmd = tokens[0] if len(tokens) > 0 else "UP"
                self.send_command(name, cmd)
            elif not is_triggered and z_data["active"]:
                cmd = tokens[1] if len(tokens) > 1 else "STOP"
                self.send_command(name, cmd)

        elif mode == "pulse":
            if is_triggered and not z_data["active"]:
                cmd = tokens[0] if len(tokens) > 0 else "PULSE"
                self.send_command(name, cmd)

    def handle_slider_zone(
        self, name, zone, mask, is_triggered, current_time
    ):
        if not is_triggered:
            return

        direction = zone.get("direction", "horizontal")
        min_v = zone.get("min_value", 0)
        max_v = zone.get("max_value", 100)

        # Calculate centroid of active depth pixels
        y_indices, x_indices = np.where(mask)
        if len(x_indices) == 0:
            return

        if direction == "horizontal":
            rel_pos = np.mean(x_indices) / mask.shape[1]
        else:
            rel_pos = 1.0 - (np.mean(y_indices) / mask.shape[0])

        calculated_value = int(min_v + rel_pos * (max_v - min_v))
        calculated_value = max(min_v, min(max_v, calculated_value))

        # Throttle slider MQTT updates to every 150ms
        z_data = self.zone_data[name]
        if current_time - z_data["last_action_time"] > 0.15:
            if str(calculated_value) != self.states[name]:
                self.states[name] = str(calculated_value)
                z_data["last_action_time"] = current_time
                self.send_command(name, str(calculated_value))

    def handle_color_zone(
        self, name, zone, mask, is_triggered, current_time
    ):
        if not is_triggered:
            return

        z_data = self.zone_data[name]
        if current_time - z_data["last_action_time"] < 0.2:
            return

        y_indices, x_indices = np.where(mask)
        if len(x_indices) == 0:
            return

        # Calculate normalized coordinates (-1 to 1) relative to box center
        cx = (np.mean(x_indices) / mask.shape[1]) - 0.5
        cy = (np.mean(y_indices) / mask.shape[0]) - 0.5

        if zone.get("h_flip", False):
            cx = -cx
        if zone.get("v_flip", False):
            cy = -cy

        # Determine polar angle (hue)
        angle_rad = math.atan2(cy, cx)
        angle_deg = (math.degrees(angle_rad) + zone.get("degree_offset", 0)) % 360

        color_sys = zone.get("color_system", "hsb")
        if color_sys == "hsb":
            # HSB Format: Hue (0-360), Saturation (100%), Brightness (100%)
            payload = f"{int(angle_deg)},100,100"
        else:
            # RGB Color Wheel Mapping
            hsv_pixel = np.uint8([[[int(angle_deg / 2), 255, 255]]])
            rgb_pixel = cv2.cvtColor(hsv_pixel, cv2.COLOR_HSV2BGR)[0][0]
            payload = f"{rgb_pixel[2]},{rgb_pixel[1]},{rgb_pixel[0]}"

        if payload != self.states[name]:
            self.states[name] = payload
            z_data["last_action_time"] = current_time
            self.send_command(name, payload)


def generate_mjpeg_stream(engine):
    while True:
        if GLOBAL_DEPTH_FRAME is None:
            time.sleep(0.03)
            continue

        depth = GLOBAL_DEPTH_FRAME
        depth_clipped = np.clip(depth, 500, 2000)
        depth_vis = (
            (depth_clipped - 500) / (2000 - 500) * 255
        ).astype(np.uint8)
        frame_bgr = cv2.applyColorMap(depth_vis, cv2.COLORMAP_JET)

        for name, zone in engine.zones.items():
            x_min, x_max = zone["x_min"], zone["x_max"]
            y_min, y_max = zone["y_min"], zone["y_max"]
            is_active = engine.zone_data[name]["active"]

            color = (0, 255, 0) if is_active else (255, 100, 0)
            cv2.rectangle(frame_bgr, (x_min, y_min), (x_max, y_max), color, 2)
            cv2.putText(
                frame_bgr,
                f"{name}: {engine.states[name]}",
                (x_min, max(y_min - 8, 12)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (255, 255, 255),
                1,
            )

        _, jpeg = cv2.imencode(".jpg", frame_bgr)
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
        )
        time.sleep(0.03)


@app.route("/")
def stream():
    return Response(
        generate_mjpeg_stream(app.engine_ref),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


def main():
    parser = argparse.ArgumentParser(
        description="Invisible Spatial Switch Core Engine"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without streaming web GUI server",
    )
    parser.add_argument(
        "--config", default="config.json", help="Path to config file"
    )
    args = parser.parse_args()

    engine = SpatialSwitchEngine(config_path=args.config)

    if not args.headless:
        app.engine_ref = engine
        web_cfg = engine.config.get("web", {})
        host = web_cfg.get("host", "0.0.0.0")
        port = web_cfg.get("port", 8080)

        import threading

        server_thread = threading.Thread(
            target=lambda: app.run(
                host=host, port=port, debug=False, use_reloader=False
            ),
            daemon=True,
        )
        server_thread.start()
        logging.info(
            f"Live Web GUI streaming at http://{host}:{port}"
        )

    logging.info("Core Engine running. Press Ctrl+C to stop.")
    try:
        while True:
            depth, _ = freenect.sync_get_depth()
            if depth is not None:
                engine.process_frame(depth)
            time.sleep(0.02)
    except KeyboardInterrupt:
        logging.info("Shutting down engine...")


if __name__ == "__main__":
    main()
