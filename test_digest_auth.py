import requests
from requests.auth import HTTPDigestAuth
import logging

# Configure basic logging for this test script
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Camera details (hardcoded for this simple test)
CAMERA_IP = "192.168.1.106" # User confirmed curl works with this IP
USERNAME = "admin"
PASSWORD = "123OKChi@" # User confirmed credentials are correct

# The URL that curl successfully accessed (parameters URL-encoded as curl did)
# Note: requests will typically handle URL encoding of params if given as a dict,
# but for exact replication of the curl working URL structure:
# Events=[TrafficJunction] was Events=%5BTrafficJunction%5D in successful curl
# Flags[0]=Event was Flags[0]=Event (no encoding needed for [0] by curl's --data-urlencode)

# Let's construct params as a dict and let requests handle encoding, which is standard.
# The successful curl GET request was:
# /cgi-bin/snapManager.cgi?action=attachFileProc&channel=1&heartbeat=15&Flags[0]=Event&Events=%5bTrafficJunction%5d
# The %5b and %5d are URL encodings for [ and ].
# requests params dictionary will handle this correctly for reserved characters.

url = f"http://{CAMERA_IP}/cgi-bin/snapManager.cgi"
params = {
    "action": "attachFileProc",
    "channel": 1,
    "heartbeat": 15,
    "Flags[0]": "Event", # requests might need help with dict keys like this.
                         # It's often better to construct the query string for such keys.
    "Events": "[TrafficJunction]" # requests will URL-encode the brackets
}

# Alternative: construct query string part manually for problematic keys
# base_url = f"http://{CAMERA_IP}/cgi-bin/snapManager.cgi"
# query_string = "action=attachFileProc&channel=1&heartbeat=15&Flags[0]=Event&Events=[TrafficJunction]"
# full_url = f"{base_url}?{query_string}"
# For this test, let's use the simpler params dict first. If that fails due to Flags[0], we can try full_url.

logger.info(f"Attempting to connect to {url} with params {params} using HTTPDigestAuth.")

try:
    with requests.Session() as session:
        session.auth = HTTPDigestAuth(USERNAME, PASSWORD)

        # First attempt (let requests build the full URL with params)
        # Using a timeout similar to what's in CameraConnection
        response = session.get(url, params=params, stream=True, timeout=(10, 30))

        logger.info(f"Initial response status code: {response.status_code}")
        # logger.info(f"Initial response headers: {response.headers}")

        # If the first response was 401, requests with HTTPDigestAuth should automatically
        # handle the challenge and send a second request with the Authorization header.
        # The `response` object here would be from the *second* request if auth was successful.

        if response.status_code == 200:
            logger.info("SUCCESS! Connected and authenticated successfully (HTTP 200 OK).")
            logger.info(f"Response Content-Type: {response.headers.get('Content-Type')}")

            # Try to read a bit of the stream
            stream_content_preview = ""
            stream_bytes_preview = b""
            try:
                for i, chunk in enumerate(response.iter_content(chunk_size=1024)):
                    if i < 2: # Read first couple of chunks only for preview
                        logger.info(f"Received chunk {i+1} of length {len(chunk)}")
                        stream_bytes_preview += chunk
                    else:
                        break
                if stream_bytes_preview:
                    # Attempt to decode as utf-8, ignoring errors for non-text parts
                    stream_content_preview = stream_bytes_preview.decode('utf-8', errors='ignore')
                    logger.info(f"Preview of stream content (first ~2KB):\n{stream_content_preview[:500]}")
                else:
                    logger.info("No content chunks received from stream in preview.")
            except Exception as e_stream:
                logger.error(f"Error reading stream: {e_stream}")
            finally:
                response.close() # Ensure stream is closed

        elif response.status_code == 401:
            logger.error("FAILURE! Still received 401 Unauthorized even with HTTPDigestAuth.")
            logger.error(f"Response headers: {response.headers}")
        else:
            logger.error(f"FAILURE! Received unexpected status code: {response.status_code}")
            logger.error(f"Response text: {response.text[:500]}") # Show beginning of response text

except requests.exceptions.RequestException as e:
    logger.error(f"RequestException during connection: {e}", exc_info=True)
except Exception as e_global:
    logger.error(f"An unexpected error occurred: {e_global}", exc_info=True)
