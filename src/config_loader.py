import configparser
import os

def load_config(config_file_path='config.ini'):
    """Loads configuration from the INI file."""
    if not os.path.exists(config_file_path):
        raise FileNotFoundError(f"Configuration file not found: {config_file_path}")

    config = configparser.ConfigParser()
    config.read(config_file_path)
    return config

if __name__ == '__main__':
    # Example usage:
    try:
        config = load_config('../config.ini') # Adjust path if running directly for testing
        print("Camera IPs:", config.get('cameras', 'ips').split(','))
        print("Telegram Bot Token:", config.get('telegram', 'bot_token'))
        print("VIP List CSV Path:", config.get('files', 'vip_list_csv'))
        print("Log File:", config.get('app', 'log_file'))
        print("Log Level:", config.get('app', 'log_level'))
    except FileNotFoundError as e:
        print(e)
    except Exception as e:
        print(f"Error loading or parsing config: {e}")
