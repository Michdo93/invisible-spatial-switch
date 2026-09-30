# invisible-spatial-switch

Turn plain walls into invisible, interactive spatial touch interfaces using an **Xbox 360 Kinect v1** and a **Raspberry Pi** or Ubuntu server.

Define virtual touch zones, sliders, and color wheels on physical surfaces without hardware modification. All touch actions are broadcast to MQTT for seamless integration with **openHAB**, **Home Assistant**, or **Node-RED**.

---

## Features

- **Spatial Depth Zones:** Individual 3D bounding boxes ($X, Y, Z_{\text{min}}, Z_{\text{max}}$) per zone to compensate for wall angles or projector trapezoid distortion.
- **Multiple Switch Types:**
  - `switch`: Supports `toggle`, `hold` (e.g., roller shutter movement until released), and `pulse` modes with custom MQTT payloads (e.g., `ON/OFF`, `UP/STOP`, `RING`).
  - `slider`: Linear tracking (horizontal or vertical) mapping depth points to custom numerical ranges ($0-100$).
  - `color`: 360° circular color selection outputting `HSB` or `RGB` strings with horizontal/vertical mirroring and degree offsets.
- **Bi-directional MQTT Synchronization:** Publishes commands to `<base_topic>/<zone>/command` and subscribes to `<base_topic>/<zone>/state` to maintain state parity across openHAB items or Home Assistant entities.
- **Headless & Web GUI Support:** Built-in web server streams MJPEG depth video with interactive overlays over HTTP for headless Raspberry Pi configurations.

---

## Hardware Requirements

- **Xbox 360 Kinect v1** (Model 1414) + USB/AC Adapter (12V).
- **Raspberry Pi 3 / 4 / 5** or standard Ubuntu Server.

---

## Installation

```bash
# Update package repositories
sudo apt update
sudo apt install -y python3-pip libfreenect-dev

# Clone repository
git clone [https://github.com/your-user/invisible-spatial-switch.git](https://github.com/your-user/invisible-spatial-switch.git)
cd invisible-spatial-switch

# Install Python dependencies
pip3 install -r requirements.txt
```

---

## Calibration & Setup

1. Edit `config.json` to define your zones and set your MQTT broker address.
2. Run the calibration utility:
   ```bash
   python3 calibrate.py
   ```
3. Open a browser and navigate to `http://<your-raspberry-pi-ip>:8080`.
4. Observe the live depth stream. Mount painter's tape on your physical wall directly matching the bounding boxes displayed on screen.

---

## Execution

### Run with Live Web Monitoring GUI

```bash
python3 main.py
```

Access the live interface with active state readouts at `http://<your-raspberry-pi-ip>:8080`.

### Run in Headless Mode (Optimized for Production/Systemd)

```bash
python3 main.py --headless
```

---

## MQTT Communication Structure

* **Base Topic:** `invisible-spatial-switch`
* **Command Topic:** `invisible-spatial-switch/<zone_name>/command`
* **State Topic:** `invisible-spatial-switch/<zone_name>/state`

### Integration Example for openHAB

```openhab
// Switch Item
Switch Light_Switch "Kitchen Light" { mqtt=">[broker:invisible-spatial-switch/Light_Switch/command:command:*:default], <[broker:invisible-spatial-switch/Light_Switch/state:state:default]" }

// Rollershutter Item
Rollershutter Shutter "Window Shutter" { mqtt=">[broker:invisible-spatial-switch/Roller_Shutter_Up/command:command:*:default]" }

// Dimmer Item
Dimmer Kitchen_Dimmer "Dimmer" { mqtt=">[broker:invisible-spatial-switch/Dimmer_Slider/command:command:*:default]" }
```
