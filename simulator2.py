import requests
import time
import random

# Your Render endpoint (adjust if needed)
url = "https://sigstreamcloud.com/data"

# Replace this with the token you generated
token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

headers = {
    "Authorization": f"Bearer {token}"
}

# Simulate sending device data
def send_data():
    payload = {
        "device_id": "dev-001",  # Must be a claimed device
        "data": {
            "voltage": round(random.uniform(210.0, 240.0), 2),
            "temperature": round(random.uniform(18.0, 30.0), 2)
        },
        "timestamp": int(time.time())
    }

    response = requests.post(url, json=payload, headers=headers)
    print(f"Status: {response.status_code}, Response: {response.text}")

# Run once
send_data()

# Or simulate sending continuously:
# while True:
#     send_data()
#     time.sleep(5)
