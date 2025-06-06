# ANPR VIP Alert System with Telegram Notifications

## Overview

This application monitors Dahua ANPR (Automatic Number Plate Recognition) cameras for license plate detections. When a detected plate matches an entry in a predefined VIP list, the system sends a notification message, including an image of the detected vehicle, to a specified Telegram chat.

## Features

- Real-time license plate detection by integrating with Dahua camera event streams.
- VIP list management via a simple CSV file.
- Customizable Telegram notifications with vehicle image, plate details, owner information, and timestamp.
- Threaded camera connections for handling multiple cameras simultaneously.
- Configurable via an INI file.

## Project Structure

- `src/`: Contains the Python source code.
  - `main.py`: Main application entry point, orchestrates all modules.
  - `camera_handler.py`: Connects to Dahua cameras, subscribes to event streams (`snapManager.cgi`), parses multipart responses to extract plate data and images.
  - `vip_manager.py`: Loads and manages the VIP list from `data/vip_list.csv`.
  - `telegram_notifier.py`: Handles sending formatted messages (text and image) via the Telegram Bot API.
  - `config_loader.py`: Utility to load settings from `config.ini`.
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
    # Optional: Add username and password if your cameras require authentication
    # username = admin
    # password = yourpassword

    [telegram]
    bot_token = YOUR_TELEGRAM_BOT_TOKEN_HERE ; Replace with your actual Telegram Bot Token
    default_test_chat_id = YOUR_DEFAULT_TEST_CHAT_ID_HERE ; Optional: For testing notifications

    [files]
    vip_list_csv = data/vip_list.csv ; Path to your VIP list

    [app]
    log_file = anpr_app.log
    log_level = INFO ; (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    detection_fetch_interval_seconds = 1.0 ; How often the main loop checks the detection queue
    status_log_interval_minutes = 60 ; Set to 0 to disable periodic status log
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
- Press `Ctrl+C` to stop the application gracefully.

## Camera API Dependency (Dahua)

This application is specifically designed to work with Dahua ANPR cameras that support the `snapManager.cgi` event stream API (often part of Dahua HTTP API v2.x or v3.x).
- It expects the camera to provide a `multipart/x-mixed-replace` stream.
- This stream should contain `text/plain` parts with event metadata (including license plate, timestamp) and `image/jpeg` parts with the corresponding snapshot.
- The primary event code used for ANPR is `TrafficJunction`.

## Troubleshooting

- **No Detections:**
  - Check camera IP addresses in `config.ini`.
  - Verify cameras are online and accessible from the machine running the script.
  - Ensure the `Events` parameter in `src/camera_handler.py` (within `CameraConnection` class) includes `TrafficJunction` and matches your camera's event codes.
  - Check `anpr_app.log` for connection errors or event parsing issues.
- **No Telegram Notifications:**
  - Ensure `bot_token` in `config.ini` is correct.
  - Verify the `chat_id` in your `vip_list.csv` (or `default_test_chat_id` for testing) is valid.
  - The machine running the script must have internet access to reach the Telegram API.
- **Log Files:**
  - Main application log: `anpr_app.log` (or as configured).
  - Critical startup errors (if logging isn't up): `startup_error.log`.

---
*This system is intended for monitoring and notification purposes. Ensure compliance with local privacy regulations.*