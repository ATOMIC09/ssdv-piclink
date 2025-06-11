import serial, time

def send_ssdv_packets(ssdv_file, port, baud):
    with open(ssdv_file, "rb") as f, serial.Serial(port, baud, timeout=1) as ser:
        seq = 0
        while True:
            chunk = f.read(256)
            if not chunk:
                break
            framed = b'\x7E' + seq.to_bytes(1, 'big') + chunk + b'\x7F'
            for _ in range(3):
                ser.write(framed)
                if ser.read(1) == b'\x06':
                    print(f"Sent seq {seq}")
                    break
                else:
                    print(f"Retrying seq {seq}")
            else:
                print(f"Failed to send seq {seq}")
                break
            seq = (seq + 1) % 256