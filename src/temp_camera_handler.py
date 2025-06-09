import logging
import requests
from requests.auth import HTTPDigestAuth
from requests.exceptions import RequestException
import threading
import time
from queue import Queue, Empty
from datetime import datetime

# Define a simple data structure for detections
class DetectionEvent:
    def __init__(self, plate_number, timestamp, camera_ip, image_data, event_details=None):
        self.plate_number = plate_number
        self.timestamp = timestamp # Should be datetime object
        self.camera_ip = camera_ip
        self.image_data = image_data # Bytes
        self.event_details = event_details if event_details else {}

    def __repr__(self):
        return (f"DetectionEvent(plate='{self.plate_number}', ts='{self.timestamp}', "
                f"cam='{self.camera_ip}', img_size='{len(self.image_data) if self.image_data else 0}')")

class CameraConnection(threading.Thread):
    def __init__(self, camera_ip, event_queue, config=None): # Pass full app config
        super().__init__(daemon=True)
        self.camera_ip = camera_ip
        self.event_queue = event_queue
        self.config = config # This is the main ConfigParser object from main.py
        self.stop_event = threading.Event()
        self.logger = logging.getLogger(f"CameraConnection.{self.camera_ip}")

        self.cgi_path = "/cgi-bin/snapManager.cgi"
        # self.params dictionary is intentionally REMOVED. URL will be built manually.

        self.cam_username = None
        self.cam_password = None
        # Load credentials from the passed config object
        if self.config and self.config.has_section('cameras'):
            retrieved_username = self.config.get('cameras', 'username', fallback=None)
            retrieved_password = self.config.get('cameras', 'password', fallback=None)

            if retrieved_username and retrieved_password:
                self.cam_username = retrieved_username
                self.cam_password = retrieved_password
                self.logger.info(f"Credentials loaded for user '{self.cam_username}'. HTTPDigestAuth will be used per request.")
            else:
                self.logger.info("Camera username/password not found in config. HTTP auth will not be used.")
        else:
            self.logger.info("No [cameras] section in config or no config provided. HTTP auth will not be used.")

    def _parse_event_text_part(self, text_part_content):
        details = {}
        try:
            for line in text_part_content.splitlines():
                if '=' in line:
                    key, value = line.split('=', 1)
                    details[key.strip()] = value.strip()
        except Exception as e:
            self.logger.error(f"Error parsing event text part: {e}. Content: '{text_part_content[:200]}'")
        return details

    def run(self):
        self.logger.info(f"Starting connection thread for {self.camera_ip}")
        while not self.stop_event.is_set():
            try:
                base_url = f"http://{self.camera_ip}{self.cgi_path}"
                # Manually construct query string with URL-encoded brackets for Events parameter
                query_string = "action=attachFileProc&channel=1&heartbeat=15&Flags[0]=Event&Events=%5BTrafficJunction%5D"
                full_url = f"{base_url}?{query_string}"

                self.logger.info(f"Attempting to connect to (manually built URL): {full_url}")

                auth_object = None
                if self.cam_username and self.cam_password:
                    auth_object = HTTPDigestAuth(self.cam_username, self.cam_password)
                    self.logger.debug("HTTPDigestAuth object created for this request.")

                # Using requests.get directly for each attempt
                with requests.get(full_url,
                                  auth=auth_object,
                                  params=None, # Params are already in full_url
                                  stream=True,
                                  timeout=(10, 30)) as resp: # connect timeout, read timeout (30s total for read)

                    resp.raise_for_status()
                    self.logger.info(f"Successfully connected to {self.camera_ip} (status {resp.status_code}). Streaming events...")

                    content_type_header = resp.headers.get('Content-Type', '')
                    boundary = None
                    if 'boundary=' in content_type_header:
                        boundary = content_type_header.split('boundary=')[1].strip()

                    if not boundary:
                        self.logger.error("No boundary string found in Content-Type header. Cannot parse multipart stream.")
                        self.stop_event.wait(30)
                        continue

                    buffer = b''
                    expected_boundary = b'--' + boundary.encode('utf-8')
                    current_event_data = None

                    for chunk in resp.iter_content(chunk_size=4096):
                        if self.stop_event.is_set():
                            break
                        buffer += chunk

                        while True:
                            start_boundary_pos = buffer.find(expected_boundary)
                            if start_boundary_pos == -1:
                                if len(buffer) > 2 * len(expected_boundary) and self.logger.isEnabledFor(logging.DEBUG):
                                     self.logger.debug(f"Waiting for more data. Buffer does not contain full boundary. Buffer head: {buffer[:100]}")
                                break

                            if buffer.startswith(expected_boundary + b'--'):
                                self.logger.info("End of multipart stream detected by final boundary marker.")
                                buffer = b''
                                current_event_data = None
                                break

                            header_start_offset = start_boundary_pos + len(expected_boundary) + len(b'\r\n')

                            end_of_headers_pos = buffer.find(b'\r\n\r\n', header_start_offset)
                            if end_of_headers_pos == -1:
                                if self.logger.isEnabledFor(logging.DEBUG):
                                    self.logger.debug(f"Waiting for more data. Buffer does not contain full headers. Buffer from boundary: {buffer[start_boundary_pos:start_boundary_pos+200]}")
                                break

                            header_section_bytes = buffer[header_start_offset:end_of_headers_pos]
                            headers_str = header_section_bytes.decode('utf-8', errors='ignore')

                            part_content_type = None
                            part_content_length = None
                            for header_line in headers_str.split('\r\n'):
                                if header_line.lower().startswith('content-type:'):
                                    part_content_type = header_line.split(':', 1)[1].strip()
                                elif header_line.lower().startswith('content-length:'):
                                    try:
                                        part_content_length = int(header_line.split(':', 1)[1].strip())
                                    except ValueError:
                                        self.logger.warning(f"Could not parse Content-Length: {header_line.split(':', 1)[1].strip()}")
                                        part_content_length = None

                            body_start_offset = end_of_headers_pos + len(b'\r\n\r\n')
                            next_boundary_pos = buffer.find(expected_boundary, body_start_offset)

                            if next_boundary_pos == -1:
                                if part_content_length is not None:
                                    if len(buffer) >= body_start_offset + part_content_length:
                                        part_body = buffer[body_start_offset : body_start_offset + part_content_length]
                                        buffer = buffer[body_start_offset + part_content_length:]
                                    else:
                                        if self.logger.isEnabledFor(logging.DEBUG):
                                            self.logger.debug(f"Waiting for more data. Body incomplete based on Content-Length. Have {len(buffer)-body_start_offset}, need {part_content_length}")
                                        break
                                else:
                                    if self.logger.isEnabledFor(logging.DEBUG):
                                        self.logger.debug(f"Waiting for more data (no C-L). Next boundary not found. Buffer from body start: {buffer[body_start_offset:body_start_offset+200]}")
                                    break
                            else:
                                part_body = buffer[body_start_offset:next_boundary_pos]
                                buffer = buffer[next_boundary_pos:]

                            if part_content_type == 'text/plain':
                                text_content = part_body.decode('utf-8', errors='ignore').strip()
                                if "Heartbeat" in text_content:
                                    self.logger.debug(f"Received heartbeat from {self.camera_ip}")
                                    current_event_data = None
                                else:
                                    parsed_text_event = self._parse_event_text_part(text_content)
                                    self.logger.debug(f"Parsed text event: {parsed_text_event}")
                                    if parsed_text_event.get("Events[0].EventBaseInfo.Code") == "TrafficJunction":
                                        current_event_data = parsed_text_event
                                    else:
                                        self.logger.debug(f"Received non-TrafficJunction text event: {parsed_text_event.get('Events[0].EventBaseInfo.Code')}")
                                        current_event_data = None
                            elif part_content_type == 'image/jpeg':
                                if current_event_data:
                                    self.logger.info(f"Received image data ({len(part_body)} bytes) for event: {current_event_data.get('Events[0].TrafficCar.PlateNumber', 'N/A')}")
                                    plate_number = current_event_data.get("Events[0].TrafficCar.PlateNumber", "UNKNOWN_PLATE")
                                    timestamp_str = current_event_data.get("Events[0].PTS", "0.0")
                                    try:
                                        timestamp_val = float(timestamp_str) / 1000.0
                                        event_time = datetime.fromtimestamp(timestamp_val)
                                    except ValueError:
                                        self.logger.warning(f"Could not parse PTS timestamp: {timestamp_str}. Using current time.")
                                        event_time = datetime.now()

                                    detection = DetectionEvent(
                                        plate_number=plate_number,
                                        timestamp=event_time,
                                        camera_ip=self.camera_ip,
                                        image_data=part_body,
                                        event_details=current_event_data
                                    )
                                    self.event_queue.put(detection)
                                    current_event_data = None
                                else:
                                    self.logger.warning("Received image data but no preceding 'TrafficJunction' event data. Discarding.")
                            else:
                                self.logger.debug(f"Skipping part with unhandled Content-Type: {part_content_type}")
                                current_event_data = None

                        if buffer.startswith(expected_boundary + b'--'):
                            self.logger.info("End of multipart stream detected by final boundary after part processing.")
                            break

                    if self.stop_event.is_set():
                        self.logger.info("Stop event set, exiting connection loop.")
                        break
                    self.logger.info(f"Stream ended from {self.camera_ip}. Will attempt to reconnect if not stopping.")

            except RequestException as e:
                self.logger.error(f"RequestException for {self.camera_ip}: {e}. Retrying in 30s.")
                self.stop_event.wait(30)
            except Exception as e:
                self.logger.critical(f"Unhandled exception in connection thread for {self.camera_ip}: {e}", exc_info=True)
                self.stop_event.wait(60)

        self.logger.info(f"Connection thread for {self.camera_ip} fully stopped.")

    def stop(self):
        self.logger.info(f"Stopping connection thread for {self.camera_ip}")
        self.stop_event.set()

class CameraHandler:
    def __init__(self, camera_ips, app_config=None): # app_config is the main ConfigParser object
        self.camera_ips = camera_ips
        self.app_config = app_config # Storing the ConfigParser object
        self.detection_queue = Queue()
        self.connections = []
        self.logger = logging.getLogger("CameraHandler")

        for ip in self.camera_ips:
            # Pass the app_config to CameraConnection
            conn = CameraConnection(ip, self.detection_queue, self.app_config)
            self.connections.append(conn)

    def start_monitoring(self):
        self.logger.info("Starting all camera monitoring threads...")
        for conn in self.connections:
            conn.start()
        self.logger.info(f"{len(self.connections)} camera threads started.")

    def stop_monitoring(self):
        self.logger.info("Stopping all camera monitoring threads...")
        for conn in self.connections:
            conn.stop()
        for conn in self.connections:
            conn.join(timeout=10)
            if conn.is_alive():
                self.logger.warning(f"Thread for {conn.camera_ip} did not terminate in time.")
        self.logger.info("All camera threads stopped.")

    def get_new_detections(self, max_items=10, timeout=0.1):
        detections = []
        try: # Try to get first item with blocking
            detections.append(self.detection_queue.get(block=True, timeout=timeout))
            # Try to get more items without further blocking
            for _ in range(max_items - 1):
                try: detections.append(self.detection_queue.get(block=False))
                except Empty: break
        except Empty: pass # No items even after initial timeout
        return detections

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
                        handlers=[logging.StreamHandler()])
    logger = logging.getLogger(__name__)

    # MockConfig for standalone testing of camera_handler.py
    # This allows testing without needing config.ini in a parent directory.
    class MockConfig:
        def __init__(self):
            self.sections_data = {
                'cameras': {
                    'username': 'admin',
                    'password': '123OKChi@' # Ensure this is the correct password
                }
            }
        def has_section(self, section):
            return section in self.sections_data

        def get(self, section, key, fallback=None):
            return self.sections_data.get(section, {}).get(key, fallback)

        def items(self, section): # Added for completeness, though not strictly used by current CameraConnection
            return self.sections_data.get(section, {}).items()

    mock_config_instance = MockConfig()

    # Test with a specific IP, e.g., one that worked with test_digest_auth.py
    camera_test_ips = ["192.168.1.106"]

    logger.info(f"Starting CameraHandler standalone test with IPs: {camera_test_ips}")
    logger.warning("This test requires a Dahua camera simulator or a real, accessible camera at the specified IP.")

    handler = CameraHandler(camera_test_ips, app_config=mock_config_instance)
    handler.start_monitoring()

    try:
        for i in range(120): # Run for a while (e.g., 2 minutes)
            new_detections = handler.get_new_detections(timeout=1.0) # Check queue every second
            if new_detections:
                for det in new_detections:
                    logger.info(f"MAIN STANDALONE TEST: Got Detection: {det}")
                    # Example: Save image if received
                    # if det.image_data:
                    #     try:
                    #         with open(f"{det.plate_number}_{det.camera_ip.replace('.', '_')}_{int(time.time())}.jpg", "wb") as f:
                    #             f.write(det.image_data)
                    #         logger.info(f"Saved image for {det.plate_number}")
                    #     except Exception as e_img_save:
                    #         logger.error(f"Error saving image: {e_img_save}")
            else:
                logger.debug("MAIN STANDALONE TEST: No new detections in this cycle.")

    except KeyboardInterrupt:
        logger.info("MAIN STANDALONE TEST: Keyboard interrupt received.")
    finally:
        logger.info("MAIN STANDALONE TEST: Shutting down CameraHandler...")
        handler.stop_monitoring()
        logger.info("MAIN STANDALONE TEST: Test finished.")
