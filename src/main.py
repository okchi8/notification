from config_loader import load_config
import logging

def setup_logging(log_file, log_level_str):
   numeric_level = getattr(logging, log_level_str.upper(), None)
   if not isinstance(numeric_level, int):
       raise ValueError(f'Invalid log level: {log_level_str}')

   logging.basicConfig(level=numeric_level,
                       format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                       handlers=[
                           logging.FileHandler(log_file),
                           logging.StreamHandler() # Also log to console
                       ])
   logging.info("Logging configured.")


if __name__ == '__main__':
    try:
        # Adjust path to config.ini assuming src/main.py is the entry point
        # and config.ini is in the parent directory.
        config = load_config('config.ini')

        log_file = config.get('app', 'log_file', fallback='anpr_app.log')
        log_level = config.get('app', 'log_level', fallback='INFO')
        setup_logging(log_file, log_level)

        logging.info("Application starting...")
        logging.info("Camera IPs: %s", config.get('cameras', 'ips'))
        logging.info("Telegram Bot Token: %s", config.get('telegram', 'bot_token'))
        logging.info("VIP List CSV Path: %s", config.get('files', 'vip_list_csv'))
        # The rest of the application logic will go here
        logging.info("Application finished (placeholder).")

    except FileNotFoundError as e:
        print(f"FATAL ERROR: {e}. Please ensure 'config.ini' exists in the root directory.")
    except ValueError as e:
        print(f"FATAL ERROR in configuration: {e}")
    except Exception as e:
        # Fallback for any other unexpected error during startup
        print(f"An unexpected error occurred during startup: {e}")
