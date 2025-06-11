import serial

def receive_ssdv_packets(output_ssdv, port, baud):
    buffer = bytearray()
    with open(output_ssdv, "wb") as f, serial.Serial(port, baud, timeout=1) as ser:
        while True:
            byte = ser.read(1)
            if not byte:
                continue
            buffer += byte
            if buffer.startswith(b'\x7E') and buffer.endswith(b'\x7F'):
                seq = buffer[1]
                payload = buffer[2:-1]
                f.write(payload)
                ser.write(b'\x06')
                print(f"Received seq {seq}")
                buffer.clear()