import os # Added
from config_loader import load_config, prepare_user_file # Modified import, get_app_data_dir is used via config.app_data_dir
from camera_handler import CameraHandler
import logging
import time
from datetime import datetime, timedelta
from vip_manager import VIPManager
from telegram_notifier import TelegramNotifier
from image_utils import add_watermark

# Imports for simulation (should be commented out for production)
# from PIL import Image, ImageDraw
# from io import BytesIO
# from camera_handler import DetectionEvent as SimDetectionEvent

def setup_logging(log_file, log_level_str):
    numeric_level = getattr(logging, log_level_str.upper(), None)
    if not isinstance(numeric_level, int):
        # Before logging is fully set up, this might go to stderr or be lost if called very early by other modules
        # For now, print is a fallback.
        print(f"CRITICAL: Invalid log level string: {log_level_str}. Cannot configure logging.")
        # Or raise ValueError, but logging is critical for app health.
        # Defaulting to INFO if level is bad, or re-raise. For now, let it pass to see if error is caught later.
        # However, the getLogger().setLevel will fail.
        # It's better to raise here or have a hardcoded default.
        raise ValueError(f'Invalid log level: {log_level_str}')


    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s'))
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s'))

    logger = logging.getLogger() # Get root logger
    logger.setLevel(numeric_level)

    # Clear any existing handlers from a previous run (e.g. if this function is called again)
    if logger.hasHandlers():
        logger.handlers.clear()

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    # This first log message will go to the configured handlers.
    logging.info(f"Logging configured. Level: {log_level_str}. Log file: {log_file}")

def format_telegram_message(vip_details, detection_event, direction="N/A"):
    plate = vip_details.get('plate_number', 'N/A')
    owner_name = vip_details.get('owner_name', 'N/A')
    house_number = vip_details.get('house_number', 'N/A')
    land_number = vip_details.get('land_number', 'N/A')
    vehicle_type = vip_details.get('type', 'N/A')

    event_time_str = "N/A"
    if isinstance(detection_event.timestamp, datetime):
        try:
            original_event_time = detection_event.timestamp
            if original_event_time.tzinfo is None:
                logging.warning(f"Timestamp for plate {vip_details.get('plate_number', 'N/A')} was naive: {original_event_time}. Attempting to assume it's UTC+8.")
                try:
                    import pytz
                    utc8_tz = pytz.timezone('Etc/GMT-8')
                    original_event_time = utc8_tz.localize(original_event_time)
                    logging.info(f"Successfully localized naive timestamp to UTC+8 using pytz: {original_event_time}")
                except ImportError:
                    logging.error("pytz library not found. Cannot reliably localize naive timestamp if provided. Time adjustment for naive timestamps will be skipped, treating as local.")
                    pass
            adjusted_event_time_utc_equivalent = original_event_time - timedelta(hours=8)
            final_display_time_local = adjusted_event_time_utc_equivalent.astimezone()
            event_time_str = final_display_time_local.strftime('%Y-%m-%d %H:%M:%S')
        except Exception as e:
            logging.error(f"Error formatting or converting timestamp {detection_event.timestamp}: {e}", exc_info=True)
            if hasattr(detection_event.timestamp, 'tzinfo') and detection_event.timestamp.tzinfo is not None:
                event_time_str = detection_event.timestamp.strftime('%Y-%m-%d %H:%M:%S %Z%z')
            else:
                event_time_str = detection_event.timestamp.strftime('%Y-%m-%d %H:%M:%S (Original, Timezone Unknown)')
    else:
        event_time_str = str(detection_event.timestamp)

    title = "🟢 GRRA Notification:"
    direction_keyword_text = str(direction).upper()
    display_direction = str(direction)
    direction_emoji = "↔️"
    if "IN" in direction_keyword_text: direction_emoji = "➡️🚪"
    elif "OUT" in direction_keyword_text: direction_emoji = "🚪⬅️"
    status_line = f"{vehicle_type} {direction_emoji} {display_direction}"
    separator = "------------------------"
    plate_line = f"🚗 Plate: {plate}"
    owner_line = f"👤 Owner: {owner_name}"
    house_line = f"🏠 House: {house_number}"
    land_line = f"🏗️ Land: {land_number}"
    time_line = f"⏰ Time: {event_time_str}"
    message = (
        f"{title}\n{status_line}\n{separator}\n{plate_line}\n"
        f"{owner_line}\n{house_line}\n{land_line}\n{time_line}"
    )
    return message

def run_main_loop(config, cam_handler, vip_manager, telegram_notifier, camera_direction_map):
    detection_fetch_interval = config.getfloat('app', 'detection_fetch_interval_seconds', fallback=1.0)
    status_log_interval_minutes = config.getint('app', 'status_log_interval_minutes', fallback=60)
    last_status_log_time = datetime.now()

    logging.info(f"Starting main processing loop. Detection fetch interval: {detection_fetch_interval}s.")
    if status_log_interval_minutes > 0:
        logging.info(f"Status log interval: {status_log_interval_minutes} minutes.")

    cam_handler.start_monitoring()

    try:
        while True:
            detections = cam_handler.get_new_detections(max_items=5, timeout=detection_fetch_interval)

            if detections:
                for det_event in detections:
                    logging.info(f"Processing event: Plate='{det_event.plate_number}', CamIP='{det_event.camera_ip}', Timestamp='{det_event.timestamp}', ImgSize={len(det_event.image_data) if det_event.image_data else 0}")

                    vip_details = vip_manager.get_vip_details(det_event.plate_number)

                    if vip_details:
                        logging.info(f"VIP DETECTED: Plate='{det_event.plate_number}', Name='{vip_details.get('owner_name', 'N/A')}', Type='{vip_details.get('type', 'N/A')}'. Gate alarm check is bypassed for VIP notification.")
                        direction = camera_direction_map.get(det_event.camera_ip, "N/A")
                        logging.debug(f"Determined direction for cam {det_event.camera_ip} as {direction} for VIP plate {det_event.plate_number}")
                        message_caption = format_telegram_message(vip_details, det_event, direction)
                        chat_id_to_notify = vip_details.get('chat_id')

                        if chat_id_to_notify:
                            image_to_send = det_event.image_data
                            if det_event.image_data:
                                logging.info(f"Original image size for VIP plate {det_event.plate_number}: {len(det_event.image_data)} bytes.")
                                logging.debug(f"Attempting to add watermark to image for VIP plate {det_event.plate_number}")
                                watermarked_image_data = add_watermark(det_event.image_data, "GRRA-Chemor,PK")
                                if watermarked_image_data:
                                    logging.info(f"Watermarked image size for VIP plate {det_event.plate_number}: {len(watermarked_image_data)} bytes.")
                                    if watermarked_image_data == det_event.image_data and len(det_event.image_data) > 0:
                                        logging.warning(f"Watermark may not have been applied or returned original for VIP plate {det_event.plate_number}.")
                                    image_to_send = watermarked_image_data
                                else:
                                    logging.warning(f"Watermarking returned None for VIP plate {det_event.plate_number}. Using original image data.")
                            else:
                                logging.warning(f"No image data available for VIP plate {det_event.plate_number} to watermark.")

                            logging.info(f"TIMESTAMP (VIP Notif): Before calling send_notification_with_image for {det_event.plate_number}: {datetime.now()}")
                            success = telegram_notifier.send_notification_with_image(chat_id_to_notify, message_caption, image_to_send)
                            logging.info(f"TIMESTAMP (VIP Notif): After calling send_notification_with_image for {det_event.plate_number}: {datetime.now()}")

                            if success:
                                logging.info(f"VIP Notification with image sent for {det_event.plate_number} to {chat_id_to_notify}.")
                            else:
                                logging.warning(f"Failed to send VIP notification for {det_event.plate_number} to {chat_id_to_notify}.")
                        else:
                            logging.warning(f"No chat_id for VIP {det_event.plate_number}. Notification cannot be sent.")
                    else:
                        logging.info(f"Plate '{det_event.plate_number}' is not on the VIP list.")
                        pass
            else:
                logging.debug(f"No new detections from queue in this cycle (timeout: {detection_fetch_interval}s).")

            if status_log_interval_minutes > 0 and (datetime.now() - last_status_log_time) >= timedelta(minutes=status_log_interval_minutes):
                active_cam_threads = sum(1 for conn_thread in cam_handler.connections if conn_thread.is_alive())
                logging.info(f"Application still running. Active camera connections: {active_cam_threads}/{len(cam_handler.connections)}. VIPs loaded: {len(vip_manager.vip_data)}.")
                last_status_log_time = datetime.now()

    except KeyboardInterrupt:
        logging.info("KeyboardInterrupt received. Shutting down application...")
    except Exception as e:
        logging.critical(f"An unexpected error in main loop: {e}", exc_info=True)
    finally:
        logging.info("Stopping camera monitoring (from run_main_loop finally block)...")
        if 'cam_handler' in locals() and cam_handler:
            cam_handler.stop_monitoring()
        logging.info("Application main loop ended.")

if __name__ == '__main__':
    cam_handler = None
    telegram_notifier = None
    # app_data_dir will be defined here after load_config()
    try:
        # config.ini will be sought in user's app data dir by load_config
        config = load_config('config.ini')

        app_data_dir = config.app_data_dir

        log_file_name_from_config = config.get('app', 'log_file', fallback='anpr_app.log')
        log_file_path = os.path.join(app_data_dir, log_file_name_from_config) # Corrected variable name

        log_level_str = config.get('app', 'log_level', fallback='INFO') # Corrected variable name
        setup_logging(log_file_path, log_level_str)

        logging.info("===================================================")
        logging.info(f"      ANPR Notification Application Starting     ")
        logging.info(f"      User Data Directory: {app_data_dir}      ")
        if log_level_str == "DEBUG":
            logging.info("                (DEBUG LOGGING ENABLED)          ")
        logging.info("===================================================")

        camera_ips_str = config.get('cameras', 'ips')
        if not camera_ips_str:
            logging.critical("Camera IPs not found in config.ini. Exiting.")
            exit(1)
        camera_ips = [ip.strip() for ip in camera_ips_str.split(',')]

        # --- Modify vip_csv_path handling ---
        # vip_list_filename_in_config is relative to app_data_dir/data
        vip_list_filename_in_config = config.get('files', 'vip_list_csv', fallback=os.path.join('data', 'vip_list.csv'))
        # template_relative_path is relative to project/bundle root
        vip_list_template_relative_path = os.path.join('data', 'vip_list.csv.example')

        # prepare_user_file expects filename_in_user_dir to be relative to app_data_dir
        # So, vip_list_filename_in_config should already be like "data/vip_list.csv"
        vip_csv_path_in_user_dir = prepare_user_file(
            app_data_dir,
            vip_list_filename_in_config,
            vip_list_template_relative_path
        )

        if not vip_csv_path_in_user_dir:
            logging.critical(f"VIP list CSV ('{vip_list_filename_in_config}') could not be prepared in user data directory '{app_data_dir}'. Exiting.")
            exit(1)

        logging.info(f"Using VIP list from: {vip_csv_path_in_user_dir}")
        # --- End vip_csv_path handling ---

        bot_token = config.get('telegram', 'bot_token')
        camera_direction_map = {}
        if config.has_section('camera_directions'):
            for ip, direction in config.items('camera_directions'):
                camera_direction_map[ip.strip()] = direction.strip().upper()
            logging.info(f"Loaded camera directions: {camera_direction_map}")
        else:
            logging.warning("[camera_directions] section not found in config.ini.")

        logging.info(f"Camera IPs to monitor: {camera_ips}")

        is_placeholder_token = not bot_token or "YOUR_TELEGRAM_BOT_TOKEN_HERE" in bot_token or bot_token.endswith("_PLACEHOLDER") or len(bot_token) < 20
        logging.info(f"Telegram Bot Token is {'SET' if not is_placeholder_token else 'NOT SET or placeholder'}")

        vip_manager = VIPManager(vip_csv_path_in_user_dir)
        if not vip_manager.vip_data:
            logging.warning(f"VIP list at '{vip_csv_path_in_user_dir}' is empty or failed to load. Check CSV path and format if this is unexpected.")

        telegram_notifier = TelegramNotifier(bot_token)
        if not telegram_notifier.bot and not is_placeholder_token :
             logging.warning("TelegramNotifier bot object may not have initialized correctly (e.g. bad token) despite token being set. Notifications might be disabled.")

        cam_handler = CameraHandler(camera_ips, app_config=config)

        run_main_loop(config, cam_handler, vip_manager, telegram_notifier, camera_direction_map)

    except FileNotFoundError as e:
        print(f"FATAL STARTUP ERROR (FileNotFound): {e}. Please ensure necessary files/templates exist.")
        if logging.getLogger().hasHandlers(): # Check if logging was set up
            logging.critical(f"FATAL STARTUP ERROR: {e}", exc_info=True)
    except ValueError as e:
        print(f"FATAL STARTUP ERROR (ValueError in config/setup): {e}")
        if logging.getLogger().hasHandlers():
            logging.critical(f"FATAL STARTUP ERROR (ValueError in config/setup): {e}", exc_info=True)
    except Exception as e:
        print(f"AN UNEXPECTED FATAL STARTUP ERROR: {e}")
        if logging.getLogger().hasHandlers():
            logging.critical("An unexpected FATAL STARTUP ERROR occurred.", exc_info=True)
    finally:
        if logging.getLogger().hasHandlers(): # Only log if logging was set up
            logging.info("Initiating application shutdown sequence (from __main__ finally block)...")

            if cam_handler and hasattr(cam_handler, 'stop_monitoring'):
                logging.info("Stopping camera monitoring (from __main__ finally block)...")
                cam_handler.stop_monitoring()
            else:
                logging.info("Camera handler (cam_handler) not available or not initialized for shutdown in __main__ finally.")

            if telegram_notifier and hasattr(telegram_notifier, 'shutdown'):
                logging.info("Shutting down TelegramNotifier (from __main__ finally block)...")
                telegram_notifier.shutdown()
            else:
                logging.info("Telegram notifier (telegram_notifier) not available or not initialized for shutdown in __main__ finally.")

            logging.info("Application shutdown sequence complete.")
        else: # If logging wasn't even set up, print to console
            print("Application shutdown sequence initiated (logging not configured).")
            if cam_handler: print("Attempting to stop camera handler...")
            if telegram_notifier: print("Attempting to shutdown telegram notifier...")
            print("Application shutdown sequence complete.")
