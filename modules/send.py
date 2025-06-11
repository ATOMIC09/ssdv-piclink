import serial
import time

START_BYTE = 0x7E
END_BYTE = 0x7F
ACK = 0x06
MAX_RETRIES = 3
CHUNK_SIZE = 256
TIMEOUT = 2.0

def send_ssdv_packets(input_file, port, baudrate):
    with serial.Serial(port, baudrate, timeout=TIMEOUT) as ser, open(input_file, "rb") as in_file:
        seq = 0
        total_packets = 0
        successful_packets = 0

        # Get file size for progress tracking
        in_file.seek(0, 2)  # Seek to end
        file_size = in_file.tell()
        in_file.seek(0)     # Seek back to beginning
        total_expected_packets = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE
        
        print(f"File size: {file_size} bytes, Expected packets: {total_expected_packets}")

        while True:
            chunk = in_file.read(CHUNK_SIZE)
            if not chunk:
                break

            total_packets += 1
            # Frame: START_BYTE + seq + payload + END_BYTE
            framed = bytes([START_BYTE, seq]) + chunk + bytes([END_BYTE])

            packet_sent = False
            for attempt in range(MAX_RETRIES):
                # Clear any stale data in the buffer before sending
                ser.reset_input_buffer()
                
                ser.write(framed)
                print(f"Sent packet {total_packets}/{total_expected_packets}, seq {seq} (attempt {attempt + 1}, {len(chunk)} bytes)")
                
                # Wait a bit for the data to be transmitted
                time.sleep(0.01)
                
                # Read ACK with timeout - read byte by byte to avoid partial reads
                ack_received = False
                start_time = time.time()
                
                while time.time() - start_time < TIMEOUT:
                    if ser.in_waiting >= 2:
                        response = ser.read(2)
                        if len(response) == 2 and response[0] == ACK and response[1] == seq:
                            print(f"✓ ACK received for seq {seq}")
                            ack_received = True
                            packet_sent = True
                            successful_packets += 1
                            break
                        else:
                            print(f"Invalid ACK: expected {ACK:02x}{seq:02x}, got {response.hex() if response else 'None'}")
                    time.sleep(0.01)
                
                if ack_received:
                    break
                else:
                    print(f"Timeout waiting for ACK for seq {seq}")
                    time.sleep(0.1)  # Brief delay before retry
                    
            if not packet_sent:
                print(f"❌ Failed to send seq {seq} after {MAX_RETRIES} retries")
                print(f"Successfully sent: {successful_packets}/{total_packets} packets")
                return False

            seq = (seq + 1) % 256
            time.sleep(0.01)  # Small delay between packets

        print(f"✅ All {total_packets} packets sent successfully")
        print(f"Final success rate: {successful_packets}/{total_packets}")
        return True
