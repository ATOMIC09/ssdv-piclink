import serial
import time

START_BYTE = 0x7E
END_BYTE = 0x7F
ACK = b'\x06'
MAX_RETRIES = 3
CHUNK_SIZE = 256

def send_ssdv_packets(input_file, port, baudrate):
    with serial.Serial(port, baudrate, timeout=2) as ser, open(input_file, "rb") as in_file:
        seq = 0

        while True:
            chunk = in_file.read(CHUNK_SIZE)
            if not chunk:
                break

            framed = bytes([START_BYTE, seq]) + chunk + bytes([END_BYTE])

            for attempt in range(MAX_RETRIES):
                ser.write(framed)
                ack = ser.read(1)

                if ack == ACK:
                    print(f"Sent seq {seq}")
                    break
                else:
                    print(f"Retrying seq {seq}, attempt {attempt + 1}")
            else:
                print(f"Failed to send seq {seq} after {MAX_RETRIES} retries")
                return

            seq = (seq + 1) % 256
            time.sleep(0.05)  # Small delay between packets
