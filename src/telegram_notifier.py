import logging
import telegram
from io import BytesIO
import asyncio
import re # For markdown escape
from datetime import datetime # Added for standalone test
import time # For standalone test delay

def escape_markdown_v2(text: str) -> str:
    # Escape reserved characters for MarkdownV2
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    # In the replacement string, \1 refers to the matched group (the character itself).
    # We need to prepend it with a literal backslash. In Python string literals,
    # a backslash also needs to be escaped, so \\\\1 becomes \\ and then the \1.
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

class TelegramNotifier:
    def __init__(self, bot_token):
        self.bot_token = bot_token
        generic_placeholder = "YOUR_TELEGRAM_BOT_TOKEN_HERE"
        # This specific token check might be too rigid if the token changes legitimately.
        # Consider a more robust way if token can be valid but different from this hardcoded "real" one.
        # For now, following the plan's logic.
        real_token_from_config = "7573502667:AAFDP0N6H9k_tjrSByKK1DRjivj9Z66Ono8"

        if self.bot_token and self.bot_token != generic_placeholder and not self.bot_token.endswith("_PLACEHOLDER"):
            try:
                # Prioritize the known real token if it matches, otherwise try to init with whatever is given (if not placeholder)
                if self.bot_token == real_token_from_config:
                    self.bot = telegram.Bot(token=self.bot_token)
                    logging.info("Telegram Bot object initialized successfully with known token.")
                else:
                    logging.warning(f"Telegram bot token ('{self.bot_token[:20]}...') is present but differs from the primary expected one. Attempting initialization.")
                    self.bot = telegram.Bot(token=self.bot_token) # Attempt to init with the different token
                    logging.info("Telegram Bot object initialized successfully with a different valid token.")
            except Exception as e:
                self.bot = None
                logging.error(f"Failed to initialize Telegram Bot object with token '{self.bot_token[:20]}...': {e}. Notifications will be disabled.", exc_info=True)
        else:
            self.bot = None
            logging.warning("Telegram bot token is not configured or is a known placeholder. Telegram notifications will be disabled.")

    async def _async_send_text_notification(self, chat_id, message_text_unescaped):
        if not self.bot:
            logging.warning(f"Telegram bot not initialized. Cannot send text message to {chat_id}: {str(message_text_unescaped)[:100]}...")
            return True
        if not chat_id or str(chat_id).strip() == "YOUR_DEFAULT_TEST_CHAT_ID_HERE" or not str(chat_id).strip():
             logging.warning(f"Invalid or placeholder chat_id: '{chat_id}'. Cannot send Telegram message.")
             return False

        message_text_escaped = escape_markdown_v2(str(message_text_unescaped)) # Ensure it's a string
        try:
            sent_message = await self.bot.send_message(chat_id=str(chat_id).strip(), text=message_text_escaped, parse_mode="MarkdownV2")
            logging.info(f"Successfully sent Telegram text notification to {chat_id}. Message ID: {sent_message.message_id if sent_message else 'N/A'}")
            return True
        except telegram.error.BadRequest as e:
            logging.error(f"Failed to send Telegram text message to {chat_id} due to BadRequest: {e.message} (escaped text: {message_text_escaped[:100]})", exc_info=True)
        except telegram.error.TelegramError as e: # More generic PTB error
            logging.error(f"Failed to send Telegram text message to {chat_id} due to TelegramError: {e.message}", exc_info=True)
        except Exception as e: # Catch-all for other unexpected errors
            logging.error(f"An unexpected error occurred while sending Telegram text message to {chat_id}: {e}", exc_info=True)
        return False

    async def _async_send_notification_with_image(self, chat_id, caption_unescaped, image_data, image_filename="plate.jpg"):
        if not self.bot:
            logging.warning(f"Telegram bot not initialized. Cannot send image notification to {chat_id}.")
            return True
        if not chat_id or str(chat_id).strip() == "YOUR_DEFAULT_TEST_CHAT_ID_HERE" or not str(chat_id).strip():
             logging.warning(f"Invalid or placeholder chat_id: '{chat_id}'. Cannot send Telegram image message.")
             return False

        caption_escaped = escape_markdown_v2(str(caption_unescaped)) # Ensure it's a string
        if not image_data:
            logging.warning(f"No image data provided for notification to {chat_id}. Sending text only.")
            # Call the async helper, not the public sync wrapper, to avoid nested asyncio.run()
            return await self._async_send_text_notification(chat_id, caption_unescaped)

        try:
            photo_file = BytesIO(image_data)
            photo_file.name = image_filename
            sent_message = await self.bot.send_photo(
                chat_id=str(chat_id).strip(),
                photo=photo_file,
                caption=caption_escaped,
                parse_mode="MarkdownV2"
            )
            logging.info(f"Successfully sent Telegram notification with image to {chat_id}. Message ID: {sent_message.message_id if sent_message else 'N/A'}")
            return True
        except telegram.error.BadRequest as e:
            logging.error(f"Failed to send Telegram image message to {chat_id} due to BadRequest: {e.message} (escaped caption: {caption_escaped[:100]})", exc_info=True)
        except telegram.error.NetworkError as e: # Specific error for network issues
            logging.error(f"Failed to send Telegram image message to {chat_id} due to NetworkError: {e.message}", exc_info=True)
        except telegram.error.TelegramError as e: # More generic PTB error
            logging.error(f"Failed to send Telegram image message to {chat_id} due to TelegramError: {e.message}", exc_info=True)
        except Exception as e: # Catch-all for other unexpected errors
            logging.error(f"An unexpected error occurred while sending Telegram image to {chat_id}: {e}", exc_info=True)
        return False

    # Synchronous Wrappers
    def send_text_notification(self, chat_id, message_text_unescaped):
        try:
            return asyncio.run(self._async_send_text_notification(chat_id, message_text_unescaped))
        except RuntimeError as e:
            logging.error(f"RuntimeError in sync send_text_notification: {e}. This can happen with nested asyncio.run calls or if event loop is closed/already running.", exc_info=True)
            return False
        except Exception as e_gen:
            logging.error(f"Generic error in sync send_text_notification wrapper: {e_gen}", exc_info=True)
            return False

    def send_notification_with_image(self, chat_id, caption_unescaped, image_data, image_filename="plate.jpg"):
        try:
            return asyncio.run(self._async_send_notification_with_image(chat_id, caption_unescaped, image_data, image_filename))
        except RuntimeError as e:
            logging.error(f"RuntimeError in sync send_notification_with_image: {e}. This can happen with nested asyncio.run calls or if event loop is closed/already running.", exc_info=True)
            return False
        except Exception as e_gen:
            logging.error(f"Generic error in sync send_notification_with_image wrapper: {e_gen}", exc_info=True)
            return False

# Standalone test block
if __name__ == '__main__':
    from PIL import Image, ImageDraw

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s')

    test_bot_token = "YOUR_TOKEN_FALLBACK"
    test_chat_id = "YOUR_CHAT_ID_FALLBACK"
    try:
        import configparser
        import os
        current_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(current_dir, '..', 'config.ini')
        if os.path.exists(config_path):
            config = configparser.ConfigParser()
            config.read(config_path)
            test_bot_token = config.get('telegram', 'bot_token', fallback=test_bot_token)
            test_chat_id = config.get('telegram', 'default_test_chat_id', fallback=test_chat_id)
            logging.info(f"Loaded token ('{test_bot_token[:20]}...') and chat_id ('{test_chat_id}') from config.ini for sync testing.")
        else:
            logging.warning(f"config.ini not found at {config_path} for sync test. Using hardcoded/env fallbacks if any.")
            if test_bot_token == "YOUR_TOKEN_FALLBACK":
                test_bot_token = "7573502667:AAFDP0N6H9k_tjrSByKK1DRjivj9Z66Ono8"
            if test_chat_id == "YOUR_CHAT_ID_FALLBACK":
                test_chat_id = "814158826"
    except Exception as e:
        logging.warning(f"Could not load config.ini for sync testing: {e}. Using hardcoded test values if not overridden by ENV.")
        test_bot_token = os.environ.get("TELEGRAM_TEST_TOKEN", "7573502667:AAFDP0N6H9k_tjrSByKK1DRjivj9Z66Ono8")
        test_chat_id = os.environ.get("TELEGRAM_TEST_CHAT_ID", "814158826")

    logging.info(f"Sync Test: Attempting to initialize TelegramNotifier with token: '{test_bot_token[:20]}...'")
    notifier = TelegramNotifier(test_bot_token)

    if notifier.bot:
        logging.info(f"Sync Test: Notifier initialized. Attempting to send messages to chat_id: '{test_chat_id}'")

        if test_chat_id and test_chat_id == "814158826":

            simple_text = "ANPR Bot Sync Test (Wrapper): Simple text. Did it arrive?"
            logging.info(f"--- Sync Test 1: Sending Simple Text to {test_chat_id} ---")
            success1 = notifier.send_text_notification(test_chat_id, simple_text)
            if success1: logging.info("Sync Test 1: Simple text message sent successfully.")
            else: logging.error("Sync Test 1: Failed to send simple text message.")
            time.sleep(1)

            plate, owner_name, house_number, land_number = "SYNCWRAP", "Sync User", "S01", "Y1"
            event_time_dt, vehicle_type, direction, camera_ip_test = datetime.now(), "Sync Test Type", "OUT", "127.0.0.3"
            event_time = event_time_dt.strftime('%Y-%m-%d %H:%M:%S')
            title = "🟢 *GRRA Notification (Sync Wrap Test):*"
            status_line = f" *{vehicle_type}* 🚪⬅️ {direction}"
            separator = "------------------------"
            plate_line, owner_line = f"🚗 Plate: {plate}", f"👤 Owner: {owner_name}"
            house_line, land_line = f"🏠 House: {house_number}", f"🏗️ Land: {land_number}"
            time_line, camera_line = f"⏰ Time: {event_time}", f"📷 Camera: {camera_ip_test}"
            formatted_caption = f"{title}\n{status_line}\n{separator}\n{plate_line}\n{owner_line}\n{house_line}\n{land_line}\n{time_line}\n{camera_line}"

            logging.info(f"--- Sync Test 2: Sending Formatted Text to {test_chat_id} ---")
            success2 = notifier.send_text_notification(test_chat_id, formatted_caption)
            if success2: logging.info("Sync Test 2: Formatted text message sent successfully.")
            else: logging.error("Sync Test 2: Failed to send formatted text message.")
            time.sleep(1)

            logging.info(f"--- Sync Test 3: Sending Image with Caption to {test_chat_id} ---")
            dummy_image_data = None
            try:
                img = Image.new('RGB', (320, 160), color = (128, 200, 200))
                d = ImageDraw.Draw(img); d.text((10,10), f"PLATE: {plate}", fill=(0,0,0)); d.text((10,40), "SYNC WRAP TEST", fill=(0,0,0))
                d.text((10,70), f"CAM: {camera_ip_test} @ {event_time_dt.strftime('%H:%M:%S')}", fill=(0,0,0))
                dummy_image_bytes = BytesIO(); img.save(dummy_image_bytes, format='JPEG'); dummy_image_data = dummy_image_bytes.getvalue()
            except Exception as e_img: logging.error(f"Error creating dummy image for sync test: {e_img}")

            if dummy_image_data:
                success3 = notifier.send_notification_with_image(test_chat_id, formatted_caption, dummy_image_data, "sync_wrap_test.jpg")
                if success3: logging.info("Sync Test 3: Message with image sent successfully.")
                else: logging.error("Sync Test 3: Failed to send message with image.")
            else: logging.info("Skipping sync send_notification_with_image test (no dummy image).")
        else:
            logging.warning(f"Sync Test: Chat ID ('{test_chat_id}') is placeholder or not '{ '814158826' }'. Skipping actual send tests.") # Note: Corrected placeholder string in log
    else:
        logging.warning("Sync Test: Telegram bot could not be initialized. Test send skipped.")
