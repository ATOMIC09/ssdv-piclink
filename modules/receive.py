import serial

START_BYTE = 0x7E
END_BYTE = 0x7F
ACK = b'\x06'

def receive_ssdv_packets(output_file, port, baudrate):
    buffer = bytearray()

    with serial.Serial(port, baudrate, timeout=1) as ser, open(output_file, "wb") as out_file:
        while True:
            byte = ser.read(1)
            if not byte:
                continue

            buffer += byte

            # Look for a complete framed packet
            if buffer and buffer[0] != START_BYTE:
                buffer.clear()
                continue

            if START_BYTE in buffer and END_BYTE in buffer:
                try:
                    start_index = buffer.index(START_BYTE)
                    end_index = buffer.index(END_BYTE, start_index + 1)

                    packet = buffer[start_index:end_index + 1]
                    buffer = buffer[end_index + 1:]  # Remove processed part

                    if len(packet) < 4:
                        continue  # Invalid packet

                    seq = packet[1]
                    payload = packet[2:-1]

                    out_file.write(payload)
                    out_file.flush()
                    ser.write(ACK)

                    print(f"Received seq {seq}")
                except ValueError:
                    # End byte not found yet, continue accumulating
                    continue
