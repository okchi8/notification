import logging
import requests
from requests.auth import HTTPDigestAuth
from requests.exceptions import RequestException
import threading
import time
from queue import Queue, Empty
from datetime import datetime # Ensure datetime is imported

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

        # Load gate alarm channel index
        self.gate_alarm_channel_index = -1 # Default to invalid/not configured
        if self.config and self.config.has_section('camera_gate_alarm_channels'):
            try:
                # Ensure self.camera_ip is used as the key, and provide a string fallback for getint conversion
                channel_str = self.config.get('camera_gate_alarm_channels', self.camera_ip, fallback='-1')
                self.gate_alarm_channel_index = int(channel_str)
                self.logger.info(f"Gate alarm output channel index for {self.camera_ip} configured to: {self.gate_alarm_channel_index}")
            except ValueError:
                self.logger.error(f"Invalid gate alarm channel index for {self.camera_ip}: '{channel_str}'. Must be an integer. Using -1.")
                self.gate_alarm_channel_index = -1
            except Exception as e_conf: # Catch any other config parsing error for this key
                self.logger.error(f"Error reading gate_alarm_channel_index for {self.camera_ip}: {e_conf}. Using -1.")
                self.gate_alarm_channel_index = -1
        else:
            self.logger.warning("[camera_gate_alarm_channels] section not found in config. Gate check will use default (inactive / index -1).")


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

    def is_gate_alarm_active(self) -> bool:
        """
        Checks if the configured gate alarm output channel is currently active for this camera.
        Returns True if active, False otherwise (or if not configured/error).
        """
        if self.gate_alarm_channel_index < 0:
            self.logger.debug(f"Gate alarm check skipped for {self.camera_ip}: channel index not configured or invalid ({self.gate_alarm_channel_index}).")
            return False

        default_duration = 2.0
        default_interval = 0.5
        duration = default_duration
        interval = default_interval

        if self.config and self.config.has_section('gate_check'):
            duration = self.config.getfloat('gate_check', 'vip_gate_check_duration_seconds', fallback=default_duration)
            interval = self.config.getfloat('gate_check', 'vip_gate_check_interval_seconds', fallback=default_interval)
            self.logger.debug(f"Using gate_check settings: duration={duration}s, interval={interval}s")
        else:
            self.logger.warning(f"[gate_check] section not found in config. Using defaults: duration={duration}s, interval={interval}s")

        alarm_state_url = f"http://{self.camera_ip}/cgi-bin/alarm.cgi?action=getOutState"
        auth_object = None
        if self.cam_username and self.cam_password:
            auth_object = HTTPDigestAuth(self.cam_username, self.cam_password)

        start_time = time.monotonic()
        poll_attempt = 0
        while (time.monotonic() - start_time) < duration:
            poll_attempt += 1
            self.logger.debug(f"Polling gate alarm for {self.camera_ip} (attempt {poll_attempt}). Elapsed: {time.monotonic() - start_time:.2f}s / {duration}s")

            current_poll_is_active = False
            try:
                with requests.get(alarm_state_url, auth=auth_object, timeout=5) as resp:
                    resp.raise_for_status()
                    content = resp.text.strip()
                    self.logger.debug(f"Raw response from getOutState (attempt {poll_attempt}) for {self.camera_ip}: '{content}'")
                    if content.startswith("result="):
                        try:
                            value_str = content.split('=')[1]
                            alarm_state_value = int(value_str)
                            mask = (1 << self.gate_alarm_channel_index)
                            current_poll_is_active = (alarm_state_value & mask) != 0
                            self.logger.debug(f"Gate alarm (attempt {poll_attempt}) for {self.camera_ip} is {'ACTIVE' if current_poll_is_active else 'INACTIVE'} (raw: {alarm_state_value}, mask: {mask}, channel: {self.gate_alarm_channel_index})")
                        except (IndexError, ValueError) as e_parse:
                            self.logger.error(f"Error parsing getOutState response (attempt {poll_attempt}) for {self.camera_ip}: '{content}'. Error: {e_parse}")
                            # Keep current_poll_is_active as False
                    else:
                        self.logger.error(f"Unexpected response format (attempt {poll_attempt}) from getOutState for {self.camera_ip}: '{content}'")
                        # Keep current_poll_is_active as False
            except RequestException as e:
                self.logger.error(f"RequestException (attempt {poll_attempt}) while checking alarm state for {self.camera_ip}: {e}")
                # Keep current_poll_is_active as False
            except Exception as e_gen:
                self.logger.error(f"Generic exception (attempt {poll_attempt}) while checking alarm state for {self.camera_ip}: {e_gen}", exc_info=True)
                # Keep current_poll_is_active as False

            if current_poll_is_active:
                self.logger.info(f"Gate alarm ACTIVE for {self.camera_ip} detected on attempt {poll_attempt} within {time.monotonic() - start_time:.2f}s.")
                return True

            # Check if it's worth sleeping before the next poll
            if (time.monotonic() - start_time + interval) < duration:
                self.logger.debug(f"Gate alarm inactive on attempt {poll_attempt}, sleeping for {interval}s.")
                time.sleep(interval)
            else:
                # Not enough time for another full interval sleep, or time is up
                self.logger.debug(f"Gate alarm inactive on attempt {poll_attempt}. Time nearly up, will do final check or exit.")
                # Loop condition will handle exit if time is up

        self.logger.info(f"Gate alarm for {self.camera_ip} remained INACTIVE throughout the {duration}s polling window ({poll_attempt} attempts).")
        return False

    def run(self):
        self.logger.info(f"Starting connection thread for {self.camera_ip}")
        while not self.stop_event.is_set():
            try:
                base_url = f"http://{self.camera_ip}{self.cgi_path}"
                query_string = "action=attachFileProc&channel=1&heartbeat=15&Flags[0]=Event&Events=%5BTrafficJunction%5D"
                full_url = f"{base_url}?{query_string}"

                self.logger.info(f"Attempting to connect to (manually built URL): {full_url}")

                auth_object = None
                if self.cam_username and self.cam_password:
                    auth_object = HTTPDigestAuth(self.cam_username, self.cam_password)
                    self.logger.debug("HTTPDigestAuth object created for this request.")

                with requests.get(full_url,
                                  auth=auth_object,
                                  params=None,
                                  stream=True,
                                  timeout=(10, 30)) as resp:

                    resp.raise_for_status()
                    self.logger.info(f"Successfully connected to {self.camera_ip} (status {resp.status_code}). Streaming events...")

                    content_type_header = resp.headers.get('Content-Type', '')
                    boundary = None
                    if 'boundary=' in content_type_header:
                        boundary = content_type_header.split('boundary=')[1].strip()

                    if not boundary:
                        self.logger.error("No boundary string found in Content-Type header. Cannot parse multipart stream.")
                        self.stop_event.wait(30); continue

                    buffer = b''; expected_boundary = b'--' + boundary.encode('utf-8'); current_event_data = None

                    for chunk in resp.iter_content(chunk_size=4096):
                        if self.stop_event.is_set(): break
                        buffer += chunk

                        while True:
                            start_boundary_pos = buffer.find(expected_boundary)
                            if start_boundary_pos == -1:
                                if len(buffer) > 2 * len(expected_boundary) and self.logger.isEnabledFor(logging.DEBUG):
                                     self.logger.debug(f"Waiting for more data. Buffer does not contain full boundary. Buffer head: {buffer[:100]}")
                                break

                            if buffer.startswith(expected_boundary + b'--'):
                                self.logger.info("End of multipart stream detected by final boundary."); buffer = b''; current_event_data = None; break

                            header_start_offset = start_boundary_pos + len(expected_boundary) + len(b'\r\n')
                            end_of_headers_pos = buffer.find(b'\r\n\r\n', header_start_offset)
                            if end_of_headers_pos == -1:
                                if self.logger.isEnabledFor(logging.DEBUG): self.logger.debug(f"Waiting for more data. Buffer does not contain full headers."); break

                            header_section_bytes = buffer[header_start_offset:end_of_headers_pos]
                            headers_str = header_section_bytes.decode('utf-8', errors='ignore')
                            part_content_type = None; part_content_length = None
                            for header_line in headers_str.split('\r\n'):
                                if header_line.lower().startswith('content-type:'): part_content_type = header_line.split(':', 1)[1].strip()
                                elif header_line.lower().startswith('content-length:'):
                                    try: part_content_length = int(header_line.split(':', 1)[1].strip())
                                    except ValueError: self.logger.warning(f"Could not parse C-L: {header_line.split(':', 1)[1].strip()}"); part_content_length = None

                            body_start_offset = end_of_headers_pos + len(b'\r\n\r\n')
                            part_body_defined_this_iteration = False
                            part_body = b'' # Initialize part_body

                            if part_content_length is not None:
                                if len(buffer) >= body_start_offset + part_content_length:
                                    part_body = buffer[body_start_offset : body_start_offset + part_content_length]
                                    buffer = buffer[body_start_offset + part_content_length:]
                                    part_body_defined_this_iteration = True
                                    # Do NOT break here, proceed to process this part
                                else:
                                    if self.logger.isEnabledFor(logging.DEBUG):
                                        self.logger.debug(
                                            f"Waiting for more data. Body incomplete (Content-Length: {part_content_length}). "
                                            f"Have {len(buffer) - body_start_offset} bytes for current part. Buffer size: {len(buffer)}"
                                        )
                                    break # Break inner loop to fetch more data
                            else: # part_content_length is None
                                next_boundary_pos = buffer.find(expected_boundary, body_start_offset)
                                if next_boundary_pos != -1:
                                    part_body = buffer[body_start_offset:next_boundary_pos]
                                    buffer = buffer[next_boundary_pos:]
                                    part_body_defined_this_iteration = True
                                    # Do NOT break here, proceed to process this part
                                else:
                                    if self.logger.isEnabledFor(logging.DEBUG):
                                        self.logger.debug(f"Waiting for more data (no C-L and no next boundary found). Buffer head: {buffer[body_start_offset:body_start_offset+100]}")
                                    break # Break inner loop to fetch more data

                            if not part_body_defined_this_iteration:
                                # This safeguard break should ideally not be hit if logic above is correct,
                                # but ensures we don't loop infinitely if part_body isn't defined.
                                self.logger.debug("part_body was not defined in this iteration, breaking to get more data.")
                                break

                            if part_content_type == 'text/plain':
                                text_content = part_body.decode('utf-8', errors='ignore').strip()
                                if "Heartbeat" in text_content: self.logger.debug(f"Received heartbeat from {self.camera_ip}"); current_event_data = None
                                else:
                                    parsed_text_event = self._parse_event_text_part(text_content)
                                    self.logger.debug(f"Parsed text event: {parsed_text_event}")
                                    if parsed_text_event.get("Events[0].EventBaseInfo.Code") == "TrafficJunction": current_event_data = parsed_text_event
                                    else: self.logger.debug(f"Non-TrafficJunction event: {parsed_text_event.get('Events[0].EventBaseInfo.Code')}"); current_event_data = None
                            elif part_content_type == 'image/jpeg':
                                if current_event_data:
                                    self.logger.info(f"Received image data ({len(part_body)} bytes) for event: {current_event_data.get('Events[0].TrafficCar.PlateNumber', 'N/A')}")
                                    plate_number = current_event_data.get("Events[0].TrafficCar.PlateNumber", "UNKNOWN_PLATE")

                                    # MODIFIED TIMESTAMP LOGIC
                                    event_time = datetime.now()
                                    self.logger.info(f"Using current system time for event: {event_time.strftime('%Y-%m-%d %H:%M:%S.%f')}")

                                    self.event_queue.put(DetectionEvent(plate_number, event_time, self.camera_ip, part_body, current_event_data)); current_event_data = None
                                else: self.logger.warning("Received image data but no preceding 'TrafficJunction' event data. Discarding.")
                            else: self.logger.debug(f"Skipping part with unhandled Content-Type: {part_content_type}"); current_event_data = None
                            # This checks if the *remaining* buffer starts with the end-of-stream marker
                            if buffer.startswith(expected_boundary + b'--'):
                                self.logger.info("End of multipart stream detected after part processing (final boundary found).")
                                break # Break from the inner while True loop

                        # This check is for the outer loop, after processing all parts found in the current chunk or after breaking from inner loop
                        if self.stop_event.is_set():
                            self.logger.info("Stop event set, exiting connection loop.")
                            break # Break from the for chunk in resp.iter_content()

                    # This message is logged if the stream ends naturally (e.g. server closes connection)
                    # OR if the stop_event caused the chunk iteration to break.
                    if not self.stop_event.is_set(): # Only log natural end if not explicitly stopped
                        self.logger.info(f"Stream ended from {self.camera_ip}. Will attempt to reconnect if not stopping.")
               except RequestException as e: self.logger.error(f"RequestException for {self.camera_ip}: {e}. Retrying in 30s."); self.stop_event.wait(30)
               except Exception as e: self.logger.critical(f"Unhandled exception in connection thread for {self.camera_ip}: {e}", exc_info=True); self.stop_event.wait(60)
           self.logger.info(f"Connection thread for {self.camera_ip} fully stopped.")
       def stop(self): self.logger.info(f"Stopping connection thread for {self.camera_ip}"); self.stop_event.set()

class CameraHandler:
    def __init__(self, camera_ips, app_config=None):
        self.camera_ips = camera_ips; self.app_config = app_config; self.detection_queue = Queue(); self.connections = []
        self.logger = logging.getLogger("CameraHandler")
        for ip in self.camera_ips: self.connections.append(CameraConnection(ip, self.detection_queue, self.app_config))

    def check_gate_alarm_for_ip(self, target_ip: str) -> bool:
        for conn in self.connections:
            if conn.camera_ip == target_ip:
                if conn.is_alive(): return conn.is_gate_alarm_active()
                else: self.logger.warning(f"Attempted to check gate alarm for non-running camera thread: {target_ip}"); return False
        self.logger.warning(f"No active CameraConnection found for IP {target_ip} to check gate alarm state."); return False

    def start_monitoring(self):
        self.logger.info("Starting all camera monitoring threads...")
        for conn in self.connections: conn.start()
        self.logger.info(f"{len(self.connections)} camera threads started.")

    def stop_monitoring(self):
        self.logger.info("Stopping all camera monitoring threads...")
        for conn in self.connections: conn.stop()
        for conn in self.connections: conn.join(timeout=10);            if conn.is_alive(): self.logger.warning(f"Thread for {conn.camera_ip} did not terminate in time.")
        self.logger.info("All camera threads stopped.")

    def get_new_detections(self, max_items=10, timeout=0.1):
        detections = []
        try: detections.append(self.detection_queue.get(block=True, timeout=timeout))
        except Empty: return detections
        for _ in range(max_items - 1):
            try: detections.append(self.detection_queue.get(block=False))
            except Empty: break
        return detections

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG,format='%(asctime)s - %(name)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',handlers=[logging.StreamHandler()])
    logger = logging.getLogger(__name__)
    class MockConfig:
        def __init__(self):
            self.sections_data = {
                'cameras': {'username': 'admin', 'password': '123OKChi@'},
                'camera_gate_alarm_channels': {'192.168.1.106': '0'}
            }
        def has_section(self, section): return section in self.sections_data
        def get(self, section, key, fallback=None): return self.sections_data.get(section, {}).get(key, fallback)
        def items(self, section): return self.sections_data.get(section, {}).items()

    mock_config_instance = MockConfig()
    camera_test_ips = ["192.168.1.106"]

    logger.info(f"Starting CameraHandler standalone test with IPs: {camera_test_ips}")
    handler = CameraHandler(camera_test_ips, app_config=mock_config_instance)

    if handler.connections:
        test_conn_obj = handler.connections[0]
        time.sleep(0.1)
        logger.info(f"Standalone test: Initial check of gate alarm for {test_conn_obj.camera_ip} (channel {test_conn_obj.gate_alarm_channel_index})...")
        alarm_status = test_conn_obj.is_gate_alarm_active()
        logger.info(f"Standalone test: Gate alarm status for {test_conn_obj.camera_ip}: {alarm_status}")

    handler.start_monitoring()
    try:
        for i in range(20):
            if i == 5 and handler.connections :
                logger.info(f"Standalone test: Mid-run check of gate alarm for {handler.connections[0].camera_ip}")
                alarm_status_again = handler.connections[0].is_gate_alarm_active()
                logger.info(f"Standalone test (mid-run): Gate alarm status for {handler.connections[0].camera_ip}: {alarm_status_again}")

            new_detections = handler.get_new_detections(timeout=0.5) # Shorter timeout for test loop
            if new_detections: logger.info(f"MAIN STANDALONE TEST: Got Detections: {new_detections}")
            else: logger.debug("MAIN STANDALONE TEST: No new detections in this cycle.")
            time.sleep(0.5)

    except KeyboardInterrupt: logger.info("MAIN STANDALONE TEST: Keyboard interrupt received.")
    finally: logger.info("MAIN STANDALONE TEST: Shutting down CameraHandler..."); handler.stop_monitoring(); logger.info("MAIN STANDALONE TEST: Test finished.")
