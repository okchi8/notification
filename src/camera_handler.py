import logging
import requests
from requests.auth import HTTPDigestAuth
from requests.exceptions import RequestException
import threading
import time
from queue import Queue, Empty
from datetime import datetime # For timestamp parsing

# Define a simple data structure for detections
class DetectionEvent:
    def __init__(self, plate_number, timestamp, camera_ip, image_data, event_details=None):
        self.plate_number = plate_number
        self.timestamp = timestamp # Should be datetime object
        self.camera_ip = camera_ip
        self.image_data = image_data # Bytes
        self.event_details = event_details if event_details else {} # Full parsed event

    def __repr__(self):
        return (f"DetectionEvent(plate='{self.plate_number}', ts='{self.timestamp}', "
                f"cam='{self.camera_ip}', img_size='{len(self.image_data) if self.image_data else 0}')")

class CameraConnection(threading.Thread):
    def __init__(self, camera_ip, event_queue, config=None): # Pass full app config
        super().__init__(daemon=True)
        self.camera_ip = camera_ip
        self.event_queue = event_queue
        self.config = config
        self.stop_event = threading.Event()
        self.logger = logging.getLogger(f"CameraConnection.{self.camera_ip}")

        self.cgi_path = "/cgi-bin/snapManager.cgi"
        # self.params dictionary is intentionally REMOVED. URL will be built manually.

        self.cam_username = None
        self.cam_password = None
        if self.config and self.config.has_section('cameras'):
            retrieved_username = self.config.get('cameras', 'username', fallback=None)
            retrieved_password = self.config.get('cameras', 'password', fallback=None)

            if retrieved_username and retrieved_password:
                self.cam_username = retrieved_username
                self.cam_password = retrieved_password
                self.logger.info(f"Credentials loaded for user: {self.cam_username}. Will use HTTPDigestAuth per request.")
            else:
                self.logger.info("Camera username/password not found in config. HTTP auth will not be used.")
        else:
            self.logger.info("No [cameras] section in config. HTTP auth will not be used.")

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
                # Manually construct the full URL with query string
                # Ensuring Events=[TrafficJunction] becomes Events=%5BTrafficJunction%5D
                base_url = f"http://{self.camera_ip}{self.cgi_path}"
                query_string = "action=attachFileProc&channel=1&heartbeat=15&Flags[0]=Event&Events=%5BTrafficJunction%5D"
                full_url = f"{base_url}?{query_string}"

                # This log line is CRITICAL for verifying the change
                self.logger.info(f"Attempting to connect to (manually built URL): {full_url}")

                auth_object = None
                if self.cam_username and self.cam_password:
                    auth_object = HTTPDigestAuth(self.cam_username, self.cam_password)
                    self.logger.debug("HTTPDigestAuth object created for this request.")

                with requests.get(full_url, # Use the manually constructed full_url
                                  auth=auth_object,
                                  params=None, # PARAMS MUST BE NONE HERE
                                  stream=True,
                                  timeout=(10, 30)) as resp:

                    resp.raise_for_status()
                    self.logger.info(f"Successfully connected to {self.camera_ip} (status {resp.status_code}). Streaming events...")

                    content_type_header = resp.headers.get('Content-Type', '')
                    boundary = None
                    if 'boundary=' in content_type_header:
                         # Ensure boundary is treated as bytes, as stream content is bytes
                        boundary = content_type_header.split('boundary=')[1].strip().encode('utf-8')

                    if not boundary:
                        self.logger.error("No boundary string found in Content-Type header. Cannot parse multipart stream.")
                        self.stop_event.wait(30)
                        continue

                    buffer = b''
                    expected_boundary_line = b'--' + boundary # This is now bytes
                    current_event_data = None

                    for chunk in resp.iter_content(chunk_size=4096): # Adjusted chunk size
                        if self.stop_event.is_set():
                            break
                        buffer += chunk

                        while True:
                            start_boundary_pos = buffer.find(expected_boundary_line)
                            if start_boundary_pos == -1:
                                if len(buffer) > 2 * len(expected_boundary_line):
                                     self.logger.debug(f"No start boundary found yet in buffer of size {len(buffer)}. Buffer head: {buffer[:100]}")
                                break

                            if start_boundary_pos > 0:
                                self.logger.warning(f"Skipping {start_boundary_pos} bytes of unexpected data before boundary.")
                                buffer = buffer[start_boundary_pos:]

                            if buffer.startswith(expected_boundary_line + b'--'):
                                self.logger.info("End of multipart stream detected by final boundary marker.")
                                buffer = b''
                                break

                            boundary_plus_crlf_len = len(expected_boundary_line) + 2
                            if len(buffer) < boundary_plus_crlf_len: break

                            headers_end_pos = buffer.find(b'\r\n\r\n', boundary_plus_crlf_len)
                            if headers_end_pos == -1: break

                            header_section = buffer[boundary_plus_crlf_len : headers_end_pos]
                            headers_str = header_section.decode('utf-8', errors='ignore')

                            part_content_type = None
                            part_content_length = None
                            for header_line in headers_str.split('\r\n'):
                                if header_line.lower().startswith('content-type:'):
                                    part_content_type = header_line.split(':', 1)[1].strip()
                                elif header_line.lower().startswith('content-length:'):
                                    part_content_length = int(header_line.split(':', 1)[1].strip())

                            if part_content_length is None:
                                self.logger.error("Part Content-Length is missing. Skipping part.")
                                next_boundary_search_start = headers_end_pos + 4
                                next_boundary_pos = buffer.find(expected_boundary_line, next_boundary_search_start)
                                buffer = buffer[next_boundary_pos:] if next_boundary_pos != -1 else b''
                                current_event_data = None
                                continue

                            body_start_pos = headers_end_pos + 4
                            body_end_pos = body_start_pos + part_content_length

                            if len(buffer) < body_end_pos: break

                            part_body = buffer[body_start_pos:body_end_pos]

                            buffer_advancement_pos = body_end_pos
                            if buffer[buffer_advancement_pos:buffer_advancement_pos+2] == b'\r\n':
                                buffer_advancement_pos +=2

                            buffer = buffer[buffer_advancement_pos:]

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
                                    else: current_event_data = None
                            elif part_content_type == 'image/jpeg':
                                if current_event_data:
                                    plate = current_event_data.get("Events[0].TrafficCar.PlateNumber", "UNKNOWN_PLATE")
                                    self.logger.info(f"Received image data ({len(part_body)} bytes) for event: {plate}")
                                    timestamp_str = current_event_data.get("Events[0].PTS", "0.0")
                                    try:
                                        timestamp_val = float(timestamp_str) / 1000.0
                                        event_time = datetime.fromtimestamp(timestamp_val)
                                    except ValueError:
                                        self.logger.warning(f"Could not parse PTS '{timestamp_str}'. Using current time.")
                                        event_time = datetime.now()

                                    detection = DetectionEvent(plate_number=plate, timestamp=event_time, camera_ip=self.camera_ip, image_data=part_body, event_details=current_event_data)
                                    self.event_queue.put(detection)
                                    current_event_data = None
                                else: self.logger.warning("Received image data but no preceding event data. Discarding.")
                            else:
                                self.logger.debug(f"Skipping part with Content-Type: {part_content_type}")
                                current_event_data = None

                    if self.stop_event.is_set():
                        self.logger.info("Stop event set, exiting connection loop.")
                        break

                    if resp.raw.closed and not buffer:
                         self.logger.info(f"Stream closed by server {self.camera_ip} and buffer empty. Reconnecting...")
                         break

                    self.logger.info(f"Stream from {self.camera_ip} iter_content exhausted or stream naturally ended. Reconnecting...")

            except RequestException as e:
                self.logger.error(f"RequestException for {self.camera_ip}: {e}.")
                self.stop_event.wait(30)
            except Exception as e:
                self.logger.critical(f"Unhandled exception in connection thread for {self.camera_ip}: {e}", exc_info=True)
                self.stop_event.wait(60)

        self.logger.info(f"Connection thread for {self.camera_ip} fully stopped.")

    def stop(self):
        self.logger.info(f"Stopping connection thread for {self.camera_ip}")
        self.stop_event.set()

class CameraHandler:
    def __init__(self, camera_ips, app_config=None):
        self.camera_ips = camera_ips
        self.app_config = app_config
        self.detection_queue = Queue()
        self.connections = []
        self.logger = logging.getLogger("CameraHandler")

        for ip in self.camera_ips:
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
        try:
            detections.append(self.detection_queue.get(block=True, timeout=timeout))
            for _ in range(max_items - 1):
                try: detections.append(self.detection_queue.get(block=False))
                except Empty: break
        except Empty: pass
        return detections

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
                        handlers=[logging.StreamHandler()])
    logger = logging.getLogger(__name__)

    class MockConfig:
        def has_section(self, section):
            return section == 'cameras'
        def get(self, section, key, fallback=None):
            if section == 'cameras':
                if key == 'username': return 'admin'
                if key == 'password': return '123OKChi@'
            return fallback

    mock_config = MockConfig()
    camera_test_ips = ["192.168.1.106"]

    logger.info(f"Starting CameraHandler standalone test with IPs: {camera_test_ips}")
    logger.warning("This test requires a Dahua camera simulator or a real, accessible camera at the specified IP.")

    handler = CameraHandler(camera_test_ips, app_config=mock_config)
    handler.start_monitoring()

    try:
        for i in range(120):
            new_detections = handler.get_new_detections(timeout=1.0)
            if new_detections:
                for det in new_detections:
                    logger.info(f"MAIN STANDALONE TEST: Got Detection: {det}")
            else:
                logger.debug("MAIN STANDALONE TEST: No new detections in this cycle.")

    except KeyboardInterrupt:
        logger.info("MAIN STANDALONE TEST: Keyboard interrupt received.")
    finally:
        logger.info("MAIN STANDALONE TEST: Shutting down CameraHandler...")
        handler.stop_monitoring()
        logger.info("MAIN STANDALONE TEST: Test finished.")
