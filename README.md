# ANPR VIP Alert System with Telegram Notifications

## Overview

This application monitors Dahua ANPR (Automatic Number Plate Recognition) cameras for license plate detections. When a detected plate matches an entry in a predefined VIP list, and if the associated camera's gate alarm output is active, the system sends a notification message, including a watermarked image of the detected vehicle, to a specified Telegram chat.

## Features

- Real-time license plate detection by integrating with Dahua camera event streams.
- VIP list management via a simple CSV file.
- Customizable Telegram notifications with vehicle image, plate details, owner information.
- **Conditional notifications**: Only sends alerts if a camera's specified gate alarm output channel is active.
- **Image watermarking**: Adds a "GRRA-Chemor,PK" watermark to notification images.
- **Real-time event processing with current system timestamps for notifications.**
- Threaded camera connections for handling multiple cameras simultaneously.
- Configurable via an INI file.

## Project Structure

- `src/`: Contains the Python source code.
  - `main.py`: Main application entry point, orchestrates all modules.
  - `camera_handler.py`: Connects to Dahua cameras, subscribes to event streams (`snapManager.cgi`), parses multipart responses to extract plate data and images, and checks gate alarm status.
  - `vip_manager.py`: Loads and manages the VIP list from `data/vip_list.csv`.
  - `telegram_notifier.py`: Handles sending formatted messages (text and image) via the Telegram Bot API.
  - `config_loader.py`: Utility to load settings from `config.ini`.
  - `image_utils.py`: Utility for image processing, including adding watermarks.
- `data/`: Directory for data files.
  - `vip_list.csv`: CSV file for the VIP list. **Must include headers:** `plate_number,owner_name,house_number,land_number,chat_id,type`.
- `config.ini`: Configuration file for all application settings.
- `requirements.txt`: Lists Python dependencies.
- `anpr_app.log`: Default log file for application events and errors. (Configurable in `config.ini`)
- `startup_error.log`: Fallback log for critical errors during startup if main logging isn't initialized.

## Setup and Installation

1.  **Clone the Repository:**
    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```

2.  **Create and Configure `config.ini`:**
    - Copy `config.ini.example` to `config.ini` if an example is provided, otherwise create `config.ini` manually in the project root.
    - Edit `config.ini` with your specific settings:

    ```ini
    [cameras]
    ips = 192.168.1.106, 192.168.1.107 ; Comma-separated IP addresses of your Dahua cameras
    username = admin
    password = your_camera_password

    [telegram]
    bot_token = YOUR_TELEGRAM_BOT_TOKEN_HERE ; Replace with your actual Telegram Bot Token
    default_test_chat_id = YOUR_DEFAULT_TEST_CHAT_ID_HERE ; Optional: For testing notifications

    [files]
    vip_list_csv = data/vip_list.csv ; Path to your VIP list

    [app]
    log_file = anpr_app.log
    log_level = INFO ; (DEBUG, INFO, WARNING, ERROR, CRITICAL). Set to DEBUG for verbose troubleshooting.
    detection_fetch_interval_seconds = 1.0 ; How often the main loop checks the detection queue
    status_log_interval_minutes = 60 ; Set to 0 to disable periodic status log

    [camera_directions]
    ; Maps camera IP to a descriptive direction (e.g., IN, OUT, North Gate IN)
    ; This text is used in the notification message.
    ; Example:
    ; 192.168.1.106 = IN
    ; 192.168.1.107 = IN
    ; 192.168.1.108 = OUT

    [camera_gate_alarm_channels]
    ; Maps camera IP to the index of its alarm output channel that signals gate opening.
    ; Index is typically 0 for the first alarm output.
    ; If a camera's IP is not listed here, or if its value is < 0,
    ; the gate alarm check will be skipped/default to inactive for that camera, and no notification will be sent.
    ; Example:
    ; 192.168.1.106 = 0
    ; 192.168.1.107 = 0
    ; 192.168.1.108 = 0
    ```

3.  **Prepare VIP List (`data/vip_list.csv`):**
    - Ensure `data/vip_list.csv` exists or create it.
    - The first row **must** be the header: `plate_number,owner_name,house_number,land_number,chat_id,type`
    - Populate with your VIP data. Example:
      ```csv
      plate_number,owner_name,house_number,land_number,chat_id,type
      ANR9163,OKChi,32,C2,814158826,Residence
      AHH6386,OKChi,32,C2,814158826,Visitor
      ```

4.  **Install Dependencies:**
    - It's recommended to use a virtual environment.
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```
    - Install required packages:
    ```bash
    pip install -r requirements.txt
    ```

## Running the Application

- Ensure `config.ini` and `data/vip_list.csv` are correctly set up.
- Run the main script from the project root directory:
  ```bash
  python src/main.py
  ```
- The application will start, attempt to connect to cameras, and log its activities.
- Timestamps in notifications are based on the PC's system time when an event is processed by the application.
- Press `Ctrl+C` to stop the application gracefully.

## Notification Format

When a VIP is detected and the gate alarm is active, a Telegram notification is sent with the following format:

```
🟢 GRRA Notification:
<Vehicle Type> <Direction Emoji & Text>
------------------------
🚗 Plate: <PLATE_NUMBER>
👤 Owner: <OWNER_NAME>
🏠 House: <HOUSE_NUMBER>
🏗️ Land: <LAND_NUMBER>
⏰ Time: <YYYY-MM-DD HH:MM:SS>
(Image with "GRRA-Chemor,PK" watermark attached)
```

## Camera API Dependency (Dahua)

This application is specifically designed to work with Dahua ANPR cameras that support the `snapManager.cgi` event stream API and the `alarm.cgi?action=getOutState` API for checking alarm output states.
- Event Stream (`snapManager.cgi`): Expects a `multipart/x-mixed-replace` stream containing `text/plain` parts for event metadata (plate, timestamp via PTS field) and `image/jpeg` parts for snapshots. The primary event code used for ANPR is `TrafficJunction`.
- Alarm Output Check (`alarm.cgi`): Used to query the status of digital alarm outputs.

## Troubleshooting

- **No Detections:**
  - Check camera IP addresses, username, and password in `config.ini`.
  - Verify cameras are online and accessible (ping, web interface).
  - Ensure the `Events` parameter in `src/camera_handler.py` (within `CameraConnection` class) includes `TrafficJunction`.
  - Check `anpr_app.log` (set `log_level=DEBUG` in `config.ini` for more detail) for connection errors (e.g., timeouts, authentication failures like 401) or event parsing issues.
- **No Telegram Notifications (or missing for some events):**
  - Ensure `bot_token` in `config.ini` is correct and the bot has permissions for the target chat IDs.
  - Verify `chat_id` in `vip_list.csv` is correct for the VIP.
  - **Gate Alarm Logic**: Check `anpr_app.log` (with `log_level=DEBUG`). Notifications are only sent if the camera's configured gate alarm output is active. Logs will show "Gate alarm is INACTIVE..." if this condition is not met.
  - Ensure `[camera_gate_alarm_channels]` in `config.ini` is correctly set up for each camera IP and that the channel index corresponds to your camera's gate trigger mechanism.
  - The machine running the script must have internet access.
- **Watermark Issues:**
  - Check DEBUG logs from `image_utils.py` (enable `log_level=DEBUG` in `config.ini`). These logs show font loading attempts, chosen font, calculated sizes, and placement coordinates.
  - Ensure a common system font (Arial, Verdana, DejaVuSans) is available on the system running the script. If not, Pillow's default font will be used, which may have limited quality for rotated/scaled text. Consider installing one of these fonts if issues persist.
- **Timestamps**: Timestamps in notifications are generated using `datetime.now()` by the application when an event is processed from the camera's stream. This means they reflect the processing time on the PC, not necessarily the exact detection time from the camera's internal clock if there are network delays.
- **Log Files:**
  - Main application log: `anpr_app.log` (or as configured).
  - Critical startup errors (if logging isn't up): `startup_error.log`.

---
*This system is intended for monitoring and notification purposes. Ensure compliance with local privacy regulations.*