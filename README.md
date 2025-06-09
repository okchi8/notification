# ANPR Notification System

This application monitors ANPR cameras, checks detected license plates against a VIP list, and sends Telegram notifications.

## Project Structure

- `config.ini`: Configuration file for camera IPs, Telegram bot token, file paths, etc.
- `src/`: Contains the Python source code.
  - `src/main.py`: The main entry point for the application.
  - `src/config_loader.py`: Module for loading settings from `config.ini`.
- `data/`: Directory for data files.
  - `data/vip_list.csv`: CSV file containing the VIP list (PlateNumber,Name,HouseNumber,Lane,ChatID,Type).
- `anpr_app.log`: Log file for the application.

## Setup

1.  **Clone the repository.**
2.  **Create `config.ini`:** Copy `config.ini.example` (if provided) or create `config.ini` manually.
    - Fill in your camera IPs.
    - Add your Telegram Bot Token.
    - Specify the path to your VIP list CSV if different from the default `data/vip_list.csv`.
3.  **Prepare `data/vip_list.csv`:** Ensure your VIP list is in this file with the correct headers.
4.  **Install dependencies:** (A `requirements.txt` will be added later)
    ```bash
    pip install ...
    ```
5.  **Run the application:**
    ```bash
    python src/main.py
    ```