from flask import Flask, request, Response
import werkzeug.utils # For secure_filename
import json
import logging
import os
import csv
from datetime import datetime # <-- NEW IMPORT
import atexit # <-- NEW IMPORT
from telegram_notifier import TelegramNotifier # <-- NEW IMPORT

app = Flask(__name__)

# --- Define VIP CSV Path ---
VIP_CSV_PATH = 'C:/anprju/data/vip_list.csv'
# For local testing if C: drive is not appropriate or for non-Windows:
# VIP_CSV_PATH = 'vip_list.csv'

# --- Initialize Telegram Notifier ---
# Ensure the TELEGRAM_BOT_TOKEN environment variable is set in your execution environment
bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")

# Initialize telegram_sender, it will be None if bot_token is not found
if bot_token:
    telegram_sender = TelegramNotifier(bot_token)
    if hasattr(telegram_sender, 'shutdown') and callable(telegram_sender.shutdown):
        atexit.register(telegram_sender.shutdown)
        app.logger_name = app.name # to ensure app.logger is configured before this point
        app.logger.info("TelegramNotifier shutdown method registered with atexit.")
    else:
        app.logger_name = app.name
        app.logger.warning("TelegramNotifier instance does not have a callable 'shutdown' method. Cannot register with atexit.")
else:
    telegram_sender = None # Explicitly set to None if no token
    app.logger_name = app.name
    app.logger.warning("TELEGRAM_BOT_TOKEN environment variable not set. Telegram notifications will be disabled globally.")


def format_timestamp_from_realutc(real_utc_str):
    """Converts a RealUTC string (epoch seconds) to a formatted datetime string."""
    if not real_utc_str:
        return "N/A"
    try:
        # Camera's RealUTC is often an epoch timestamp.
        # Displaying it in local server time or a specific target timezone might be desired.
        # Here, we simply format it. The interpretation (UTC, local) depends on camera settings.
        return datetime.fromtimestamp(int(real_utc_str)).strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        app.logger.error(f"Could not parse RealUTC '{real_utc_str}' into an integer for timestamp.")
        return "Invalid Timestamp"
    except Exception as e:
        app.logger.error(f"Error formatting RealUTC '{real_utc_str}': {e}", exc_info=True)
        return "Error Timestamp"

def find_vip_by_plate(plate_number_to_check, event_details_dict, scene_image_bytes=None):
    """
    Checks if a given plate number is in the VIP list.
    If VIP, constructs and sends a Telegram notification with an image if available.
    `event_details_dict` is the specific event object, e.g., Events[0].
    """
    if not plate_number_to_check:
        app.logger.debug("No plate number provided to find_vip_by_plate.")
        return False

    is_vip_found = False
    try:
        if not os.path.exists(VIP_CSV_PATH):
            app.logger.error(f"VIP CSV file not found at configured path: {VIP_CSV_PATH}")
            return False

        with open(VIP_CSV_PATH, mode='r', newline='', encoding='utf-8-sig') as csvfile:
            reader = csv.DictReader(csvfile)
            if 'plate_number' not in reader.fieldnames:
                app.logger.error(f"'plate_number' column not found in VIP CSV. Headers: {reader.fieldnames}")
                return False

            for row in reader:
                vip_plate = row.get('plate_number', '').strip()
                if not vip_plate:
                    app.logger.warning(f"Skipping empty plate_number in VIP list row: {row}")
                    continue

                if vip_plate.lower() == plate_number_to_check.lower():
                    is_vip_found = True
                    owner_name = row.get('owner_name', 'N/A')
                    vehicle_type = row.get('type', 'N/A')
                    chat_id_to_notify = row.get('chat_id', '').strip()

                    log_msg_vip = f"VIP DETECTED: Plate: {plate_number_to_check}, Owner: {owner_name}, Type: {vehicle_type}, Target ChatID: '{chat_id_to_notify}'"
                    app.logger.info(log_msg_vip)
                    print(log_msg_vip) # For immediate console visibility

                    if telegram_sender and chat_id_to_notify:
                        # Ensure event_details_dict is the actual event object for timestamp
                        formatted_timestamp = format_timestamp_from_realutc(event_details_dict.get('RealUTC'))

                        caption = (
                            f"✨ VIP Vehicle Detected! ✨\n"
                            f"🚗 Plate: {plate_number_to_check}\n"
                            f"👤 Owner: {owner_name}\n"
                            f"🏠 House: {row.get('house_number', 'N/A')}\n"
                            f"🏷️ Type: {vehicle_type}\n"
                            f"⏰ Time: {formatted_timestamp}"
                            # Consider adding camera identifier if available in event_details_dict
                            # f"\n📹 Camera: {event_details_dict.get('MachineAddress', 'N/A')}"
                        )

                        app.logger.debug(f"Attempting to send Telegram notification to Chat ID: {chat_id_to_notify}")

                        image_filename = f"{plate_number_to_check.replace(' ','_')}_{event_details_dict.get('RealUTC', 'event')}.jpg"

                        send_success = telegram_sender.send_notification_with_image(
                            chat_id_to_notify,
                            caption,
                            scene_image_bytes, # This can be None
                            image_filename=image_filename
                        )
                        if send_success:
                            app.logger.info(f"Telegram notification sent for VIP {plate_number_to_check} to {chat_id_to_notify}.")
                        else:
                            app.logger.warning(f"Failed to send Telegram notification for VIP {plate_number_to_check} to {chat_id_to_notify}.")
                    elif not telegram_sender:
                        app.logger.warning("Telegram_sender is not initialized (token missing?). Cannot send VIP notification.")
                    elif not chat_id_to_notify:
                        app.logger.warning(f"No chat_id configured for VIP {plate_number_to_check} in CSV. Cannot send notification.")
                    break

            if not is_vip_found:
                app.logger.info(f"Plate '{plate_number_to_check}' not found in VIP list.")
                print(f"Plate '{plate_number_to_check}' not found in VIP list.")
            return is_vip_found

    except FileNotFoundError:
        app.logger.error(f"VIP CSV file not found at path: {VIP_CSV_PATH}")
    except Exception as e:
        app.logger.error(f"Error in find_vip_by_plate ('{VIP_CSV_PATH}'): {e}", exc_info=True)
    return False

def check_and_process_event(json_data, image_file_storage=None):
    try:
        if isinstance(json_data, dict) and \
           'Events' in json_data and \
           isinstance(json_data['Events'], list) and \
           len(json_data['Events']) > 0:

            first_event = json_data['Events'][0] # This is the event_details_dict for find_vip_by_plate
            if isinstance(first_event, dict) and first_event.get('Code') == "TrafficJunction":
                app.logger.info("Processing TrafficJunction event.")

                plate_number = None
                if 'TrafficCar' in first_event and isinstance(first_event['TrafficCar'], dict):
                    plate_number = first_event['TrafficCar'].get('PlateNumber')

                if not plate_number and 'Object' in first_event and isinstance(first_event['Object'], dict):
                    plate_number = first_event['Object'].get('Text')

                if plate_number:
                    plate_number = plate_number.strip().upper() # Normalize plate
                    app.logger.info(f"Extracted license plate: '{plate_number}'")
                    print(f"Extracted license plate: '{plate_number}'")

                    scene_image_bytes = None
                    if image_file_storage:
                        try:
                            image_file_storage.stream.seek(0)
                            scene_image_bytes = image_file_storage.read()
                            app.logger.info(f"Read {len(scene_image_bytes)} bytes from image part '{image_file_storage.name}'.")
                        except Exception as e:
                            app.logger.error(f"Error reading bytes from image FileStorage '{image_file_storage.name}': {e}", exc_info=True)
                    else:
                        app.logger.info("No associated image FileStorage provided for this event.")

                    find_vip_by_plate(plate_number, first_event, scene_image_bytes)
                else:
                    app.logger.warning("TrafficJunction event: PlateNumber/Object.Text not found or empty.")
            else:
                app.logger.debug(f"Event code is not TrafficJunction ('{first_event.get('Code')}') or event structure invalid.")
        else:
            app.logger.debug(f"JSON data invalid for TrafficJunction. Keys: {list(json_data.keys()) if isinstance(json_data, dict) else 'Not a dict'}")
    except Exception as e:
        app.logger.error(f"Error in check_and_process_event: {e}", exc_info=True)

@app.route('/event_listener', methods=['POST'])
def event_listener():
    app.logger.info(f"Request on /event_listener from {request.remote_addr}. Headers: {request.headers}")
    content_type_header = request.headers.get('Content-Type', '').lower()

    parsed_json_data = None
    image_file_storage_for_event = None

    if 'multipart/form-data' in content_type_header or 'multipart/x-mixed-replace' in content_type_header:
        app.logger.info(f"Processing multipart request (Content-Type: {content_type_header})")
        try:
            # Prioritize JSON from file parts if specific, else from form fields
            if 'json_event_data' in request.files and request.files['json_event_data'].content_type == 'application/json':
                file_storage = request.files['json_event_data']
                try:
                    json_str = file_storage.read().decode('utf-8')
                    parsed_json_data = json.loads(json_str)
                    app.logger.info(f"Parsed JSON from file part '{file_storage.name}'.")
                except Exception as e:
                    app.logger.error(f"Error processing JSON file part '{file_storage.name}': {e}", exc_info=True)

            if not parsed_json_data: # If not found as a specific file part, check form fields
                for key, value in request.form.items():
                    try:
                        parsed_json_data = json.loads(value)
                        app.logger.info(f"Parsed JSON from form field '{key}'.")
                        break # Found JSON in form, use this one
                    except json.JSONDecodeError:
                        app.logger.debug(f"Form field '{key}' is not JSON.")

            # Identify the first image part for the event (simplistic: assumes one event, one image or first image is primary)
            for key, file_storage in request.files.items():
                if 'image' in file_storage.content_type:
                    image_file_storage_for_event = file_storage
                    app.logger.info(f"Identified image part '{file_storage.name}' for potential use.")
                    # Optional: Save image for debugging (ensure path exists and is writable)
                    # try:
                    #     debug_image_dir = '/tmp/received_images'
                    #     if not os.path.exists(debug_image_dir): os.makedirs(debug_image_dir)
                    #     sf_name = werkzeug.utils.secure_filename(file_storage.filename or f"{key}_debug.jpg")
                    #     file_storage.save(os.path.join(debug_image_dir, sf_name))
                    #     file_storage.stream.seek(0) # Reset stream if saved
                    #     app.logger.debug(f"Debug image saved: {sf_name}")
                    # except Exception as e_img_save: app.logger.error(f"Debug save error: {e_img_save}")
                    break # Use first image found

            if parsed_json_data:
                check_and_process_event(parsed_json_data, image_file_storage_for_event)
            else:
                 app.logger.info("No processable JSON data found in multipart request.")
            return "OK", 200
        except Exception as e:
            app.logger.error(f"General error processing multipart request: {e}", exc_info=True)
            return "Error processing multipart request", 500

    elif 'application/json' in content_type_header:
        try:
            data = request.get_json()
            app.logger.info("Received plain JSON data.")
            # print(f"--- Plain JSON Data ---\n{json.dumps(data, indent=2)}\n--- End JSON ---")
            check_and_process_event(data, image_file_storage=None)
            return "OK", 200
        except Exception as e:
            app.logger.error(f"Error processing plain JSON request: {e}", exc_info=True)
            return "Error processing JSON request", 400
    else:
        body_snippet = "Unable to retrieve body snippet."
        try: body_snippet = request.get_data(as_text=True, cache=False)[:200]
        except:
            try: body_snippet = request.get_data(cache=False)[:200].hex()
            except: pass
        app.logger.warning(f"Unsupported Content-Type: {content_type_header}. Snippet: {body_snippet}")
        return f"Unsupported Content-Type: {content_type_header}", 415

if __name__ == '__main__':
    # Configure Flask's built-in logger more explicitly
    # This ensures that when run directly (not via gunicorn/wsgi), logs are visible.
    # When using gunicorn, it typically handles its own logging and Flask might inherit some settings.
    if not app.debug: # Avoid adding handlers if Flask's debug mode might have already set them up
        log_handler = logging.StreamHandler()
        log_level_env = os.environ.get('FLASK_LOG_LEVEL', 'INFO').upper()
        actual_log_level = getattr(logging, log_level_env, logging.INFO)

        log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')
        log_handler.setFormatter(log_formatter)

        # Configure app.logger
        app.logger.handlers.clear() # Clear any default handlers if necessary
        app.logger.addHandler(log_handler)
        app.logger.setLevel(actual_log_level)

        # Configure root logger similarly if you want other libraries (like telegram_notifier) to also log at this level
        # logging.getLogger().handlers.clear()
        # logging.getLogger().addHandler(log_handler)
        # logging.getLogger().setLevel(actual_log_level)

        app.logger.info(f"Flask logger initialized. Level: {log_level_env}. Handler: {log_handler}")

    app.logger.info(f"Starting HTTP listener on 0.0.0.0:5000. VIP CSV Path: {VIP_CSV_PATH}")
    if not bot_token: # Re-check here as app.logger might not have been configured when first global warning was issued
        app.logger.warning("Reminder: TELEGRAM_BOT_TOKEN is not set. Telegram features disabled.")
    elif not telegram_sender:
         app.logger.warning("Reminder: Telegram_sender failed to initialize. Telegram features disabled.")

    app.run(host='0.0.0.0', port=5000, debug=False) # debug=False for production/stable testing
