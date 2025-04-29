import serial
import time
import random
import json

COM_PORT = "COM3"  # Set to your virtual COM pair
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
        ser = serial.Serial(COM_PORT, BAUDRATE, timeout=1)
        print(f"Writing fake IoT data to {COM_PORT}...")

        while True:
            data = generate_data()
            line = json.dumps(data) + "\n"
            ser.write(line.encode("utf-8"))
            print(f"Sent: {line.strip()}")
            time.sleep(2)

    except serial.SerialException as e:
        print(f"Serial error: {e}")

if __name__ == "__main__":
    main()
