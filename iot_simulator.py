import serial
import time
import random
import json

COM_PORT = "COM3"         # Adjust to match your virtual COM pair
BAUDRATE = 9600
DEVICE_ID = "dev-001"

def generate_data():
    return {
        "device_id": DEVICE_ID,
        "temp": round(random.uniform(20, 30), 2),
        "voltage": round(random.uniform(3.3, 4.2), 2),
        "humidity": round(random.uniform(30, 60), 1)
    }

def main():
    try:
        # Open and hold the port
        with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser:
            print(f"[SIMULATOR] Writing fake IoT data to {COM_PORT}...")

            while True:
                data = generate_data()
                line = json.dumps(data) + "\n"
                ser.write(line.encode("utf-8"))
                print(f"[SIMULATOR] Sent: {line.strip()}")
                time.sleep(2)

    except serial.SerialException as e:
        print(f"[SIMULATOR ERROR] Could not open {COM_PORT}: {e}")

if __name__ == "__main__":
    main()
