import configparser
import os
import shutil
import sys
import logging # Added for logging within the module

# Initialize a logger for this module if not already configured by main app
# This helps if functions here are called before main app logging is set up
logger = logging.getLogger(__name__)
if not logger.handlers: # Avoid adding multiple handlers if already configured
    _handler = logging.StreamHandler()
    _formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    _handler.setFormatter(_formatter)
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO) # Default level for this module's logger

def get_app_data_dir():
    """
    Determines the application-specific data directory based on the OS.
    Creates the directory if it doesn't exist.
    """
    app_name_base = "ANPR_Notifier_Data"
    app_name = f".{app_name_base}" if os.name != 'nt' else app_name_base
    app_data_dir = os.path.join(os.path.expanduser("~"), app_name)

    try:
        os.makedirs(app_data_dir, exist_ok=True)
        logger.debug(f"Application data directory is: {app_data_dir}")
    except OSError as e:
        logger.error(f"Failed to create application data directory '{app_data_dir}': {e}", exc_info=True)
        raise
    return app_data_dir

def get_bundled_file_path(relative_path):
    """
    Get the absolute path to a bundled file (e.g., templates)
    whether running as a script or as a PyInstaller frozen bundle.
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        bundle_dir = sys._MEIPASS
        logger.debug(f"Running in PyInstaller bundle. MEIPASS: {bundle_dir}")
    else:
        # Assumes config_loader.py is in 'src/', so project root is one level up.
        bundle_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        logger.debug(f"Running as script. Project root for bundled files: {bundle_dir}")
    return os.path.join(bundle_dir, relative_path)

def prepare_user_file(user_data_dir, filename_in_user_dir, template_relative_path):
    """
    Ensures a user-specific file exists in user_data_dir.
    If not, copies it from the template path (relative to bundle/project root).
    filename_in_user_dir can include subdirectories relative to user_data_dir.
    Returns the full path to the user file, or None if it could not be prepared.
    """
    user_file_path = os.path.join(user_data_dir, filename_in_user_dir)
    user_file_subdir = os.path.dirname(user_file_path)

    if user_file_subdir and not os.path.exists(user_file_subdir):
        try:
            os.makedirs(user_file_subdir, exist_ok=True)
            logger.debug(f"Created subdirectory for user file: {user_file_subdir}")
        except OSError as e:
            logger.error(f"Failed to create subdirectory '{user_file_subdir}' for user file: {e}", exc_info=True)
            return None

    if not os.path.exists(user_file_path):
        logger.info(f"User file '{user_file_path}' not found. Attempting to copy from template.")
        template_path_in_bundle = get_bundled_file_path(template_relative_path)

        if os.path.exists(template_path_in_bundle):
            try:
                shutil.copy2(template_path_in_bundle, user_file_path)
                logger.info(f"Copied template '{template_path_in_bundle}' to '{user_file_path}'.")
            except Exception as e:
                logger.error(f"Error copying template '{template_path_in_bundle}' to '{user_file_path}': {e}", exc_info=True)
                return None
        else:
            logger.warning(f"Template file '{template_path_in_bundle}' (from relative path '{template_relative_path}') not found. Cannot create user file '{user_file_path}'.")
            return None

    logger.debug(f"User file ready at: {user_file_path}")
    return user_file_path

def load_config(config_file_name='config.ini'):
    """
    Loads configuration from the INI file located in the user's app data directory.
    If the config file doesn't exist, it's copied from 'config.ini.example' (template).
    """
    app_data_dir = get_app_data_dir()

    # Template 'config.ini.example' is assumed to be at the project root (or bundled root)
    config_path = prepare_user_file(app_data_dir, config_file_name, "config.ini.example")

    if not config_path:
        critical_error_msg = f"Configuration file '{config_file_name}' could not be prepared in '{app_data_dir}'. Application cannot start."
        logger.critical(critical_error_msg)
        raise FileNotFoundError(critical_error_msg)

    config = configparser.ConfigParser()
    read_files = config.read(config_path)
    if not read_files: # config.read returns a list of successfully read files
        error_msg = f"Configuration file '{config_path}' was found/copied but could not be read or is empty."
        logger.error(error_msg)
        # This could indicate an issue with the template or an empty/corrupted user file.
        # For robustness, one might delete the problematic user file and retry prepare_user_file once,
        # or raise a more specific error.
        raise configparser.Error(error_msg) # Or a custom exception

    config.app_data_dir = app_data_dir # Store for access by other modules

    logger.info(f"Configuration loaded from: {config_path}")
    return config

if __name__ == '__main__':
    logger.info("Running config_loader.py standalone test...")
    try:
        # Ensure template files exist for testing (relative to where this test is run from)
        # This assumes the script is run from within the 'src' directory for these paths to work.
        # Or, adjust paths if running from project root. Let's assume project root.
        if not os.path.exists("config.ini.example"):
            with open("config.ini.example", "w") as f:
                f.write("[app]\nlog_level=INFO\nlog_file=test_app.log\n[files]\nvip_list_csv=data/test_vip_list.csv\n")
            logger.info("Created dummy config.ini.example for testing in project root.")

        data_dir_example = "data"
        if not os.path.exists(data_dir_example):
            os.makedirs(data_dir_example)
            logger.info(f"Created '{data_dir_example}' directory in project root.")

        vip_example_path = os.path.join(data_dir_example, "vip_list.csv.example")
        if not os.path.exists(vip_example_path):
             with open(vip_example_path, "w") as f:
                f.write("plate_number,owner_name\nTESTPLATE,TestOwner\n")
             logger.info(f"Created dummy '{vip_example_path}' for testing.")

        config = load_config()
        print(f"Config loaded. App data dir: {config.app_data_dir}")
        print(f"Log Level from config: {config.get('app', 'log_level', fallback='NOT_FOUND')}")
        print(f"Log File from config (relative to app_data_dir): {config.get('app', 'log_file', fallback='NOT_FOUND')}")

        # Test prepare_user_file for vip_list.csv
        # filename_in_user_dir includes 'data' subdirectory. template_relative_path also includes 'data'.
        user_vip_list_path = prepare_user_file(
            config.app_data_dir,
            config.get('files', 'vip_list_csv', fallback=os.path.join("data", "vip_list.csv")),
            config.get('files', 'vip_list_csv', fallback=os.path.join("data", "vip_list.csv")) + ".example" # Construct template name
        )
        if user_vip_list_path and os.path.exists(user_vip_list_path):
            print(f"User VIP list prepared at: {user_vip_list_path}")
            with open(user_vip_list_path, 'r') as f_vip:
                print(f"Content of user VIP list:\n{f_vip.read()}")
        else:
            print(f"Failed to prepare user VIP list. Path: {user_vip_list_path}")

    except Exception as e:
        logger.error(f"Error during standalone test: {e}", exc_info=True)
        print(f"Error during standalone test: {e}")
