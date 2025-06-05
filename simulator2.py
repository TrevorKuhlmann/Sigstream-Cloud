import requests
import time
import random
import os
import json
from dotenv import load_dotenv

# Load .env file if available
load_dotenv()


DEVICE_ID = os.getenv("SIM_DEVICE_ID", "dev-001")



API_URL = "https://sigstreamcloud.com/device-data"
HEADERS = {"X-API-Key": "mysecretapikey123"}  # Custom header
# If you have a token, you can uncomment the next line and comment the above HEADERS line

# HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
HEADERS = {"Authorization": "Bearer mysecretapikey123"}
def generate_fake_data():
    return {
        "device_id": DEVICE_ID,
        "data": json.dumps({
            "temperature": 25.0,
            "voltage": 227.8,
            "signal_strength": 61
        }),
        "timestamp": int(time.time())
    }

def send_data():
    payload = generate_fake_data()
    try:
        response = requests.post(API_URL, json=payload, headers=HEADERS)
        if response.status_code == 200:
            print("✅ Data sent successfully:", payload)
        else:
            print(f"❌ Failed to send data. Status: {response.status_code}, Response: {response.text}")
    except Exception as e:
        print("🚨 Error sending data:", e)

if __name__ == "__main__":
    while True:
        send_data()
        time.sleep(10)
