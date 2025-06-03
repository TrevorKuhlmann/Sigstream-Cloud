
import requests
import time
import random
import os
from dotenv import load_dotenv

# Load .env file if available
load_dotenv()

API_URL = os.getenv("SIGSTREAM_API_URL", "https://sigstreamcloud.com/data")
DEVICE_ID = os.getenv("SIM_DEVICE_ID", "dev-001")
TOKEN = os.getenv("SIGSTREAM_API_TOKEN", "mysecretapikey123")

HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}

def generate_fake_data():
    return {
        "device_id": DEVICE_ID,
        "data": {
            "temperature": round(random.uniform(20.0, 30.0), 2),
            "voltage": round(random.uniform(220.0, 240.0), 1),
            "signal_strength": random.randint(60, 100)
        },
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
