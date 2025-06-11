import serial
import time

START_BYTE = 0x7E
END_BYTE = 0x7F
ACK = 0x06
CHUNK_SIZE = 256  # Add this constant

def receive_ssdv_packets(output_file, port, baudrate):
    buffer = bytearray()
    expected_seq = 0  # Start from 0 instead of -1
    last_written_seq = -1  # Track the last sequence we actually wrote to file
    corruption_count = 0
    max_corruption = 10  # Reset buffer after too many corrupted packets
    
    with serial.Serial(port, baudrate, timeout=1) as ser, open(output_file, "wb") as out_file:
        print(f"Starting to receive packets, expecting seq {expected_seq}")
        
        while True:
            # Read available data
            data = ser.read(ser.in_waiting or 1)
            if not data:
                continue
                
            buffer.extend(data)
            
            # Limit buffer size to prevent memory issues
            if len(buffer) > 2048:
                # Keep only the last 1024 bytes
                buffer = buffer[-1024:]
                corruption_count += 1
                print(f"Buffer overflow, truncated (corruption count: {corruption_count})")
            
            # Process all complete packets in buffer
            packets_processed = 0
            while packets_processed < 10:  # Limit processing per iteration
                try:
                    # Find start byte
                    if START_BYTE not in buffer:
                        break
                        
                    start_idx = buffer.index(START_BYTE)
                    
                    # Remove any data before start byte
                    if start_idx > 0:
                        print(f"Discarding {start_idx} bytes before START_BYTE")
                        buffer = buffer[start_idx:]
                        start_idx = 0
                    
                    # Need minimum packet size: START + SEQ + END (+ at least some payload)
                    if len(buffer) < 4:
                        break
                        
                    # Find end byte after start
                    try:
                        end_idx = buffer.index(END_BYTE, start_idx + 2)  # At least START + SEQ before END
                    except ValueError:
                        # No end byte found, check if buffer is getting too long
                        if len(buffer) > 512:  # Max reasonable packet size
                            print("No END_BYTE found in large buffer, discarding data")
                            buffer = buffer[1:]  # Remove first byte and try again
                            corruption_count += 1
                        break
                    
                    # Extract packet
                    packet = buffer[start_idx:end_idx + 1]
                    buffer = buffer[end_idx + 1:]
                    packets_processed += 1
                    
                    # Enhanced packet validation
                    if not validate_packet(packet):
                        corruption_count += 1
                        if corruption_count > max_corruption:
                            print("Too many corrupted packets, clearing buffer")
                            buffer.clear()
                            corruption_count = 0
                        continue
                    
                    seq = packet[1]
                    payload = packet[2:-1]  # Everything between seq and end byte
                    
                    # Additional validation: reasonable payload size
                    if len(payload) > CHUNK_SIZE + 10:  # Allow some tolerance
                        print(f"Payload too large ({len(payload)} bytes), likely corrupted")
                        corruption_count += 1
                        continue
                    
                    print(f"Received valid packet seq {seq} (expecting {expected_seq}, payload: {len(payload)} bytes)")
                    
                    # Reset corruption counter on valid packet
                    corruption_count = 0
                    
                    # Check if this is the expected sequence number
                    if seq == expected_seq:
                        # This is the packet we're waiting for
                        out_file.write(payload)
                        out_file.flush()
                        last_written_seq = seq
                        print(f"✓ Wrote seq {seq} to file ({len(payload)} bytes)")
                        
                        # Send ACK
                        ack_response = bytes([ACK, seq])
                        ser.write(ack_response)
                        
                        # Move to next expected sequence
                        expected_seq = (expected_seq + 1) % 256
                        
                    elif seq == last_written_seq:
                        # This is a retransmission of the packet we just processed
                        # ACK it but don't write to file again
                        print(f"Retransmission of seq {seq} (just processed), sending ACK")
                        ack_response = bytes([ACK, seq])
                        ser.write(ack_response)
                        
                    elif is_recent_packet(seq, last_written_seq):
                        # This is a retransmission of a recently processed packet
                        print(f"Retransmission of recent seq {seq}, sending ACK")
                        ack_response = bytes([ACK, seq])
                        ser.write(ack_response)
                        
                    else:
                        # Out of order packet - ignore and don't ACK
                        print(f"Out of order seq {seq} (expecting {expected_seq}), ignoring")
                        
                except Exception as e:
                    print(f"Error processing packet: {e}")
                    corruption_count += 1
                    # Try to recover by removing one byte from buffer
                    if len(buffer) > 0:
                        buffer = buffer[1:]
                    break

def is_recent_packet(seq, last_written_seq):
    """Check if a sequence number is a recent retransmission (within last 10 packets)"""
    if last_written_seq == -1:
        return False
    
    # Handle sequence number wraparound
    if last_written_seq >= seq:
        # Normal case or wraparound
        diff = last_written_seq - seq
        if diff <= 10:  # Within last 10 packets
            return True
        # Check wraparound case: seq might be near 255, last_written near 0
        wraparound_diff = (256 - seq) + last_written_seq
        return wraparound_diff <= 10
    else:
        # seq > last_written_seq, check if it's a wraparound retransmission
        wraparound_diff = (256 - last_written_seq) + seq
        return wraparound_diff >= 246  # Within last 10 packets considering wraparound

def validate_packet(packet):
    """Validate packet structure and integrity"""
    if len(packet) < 4:  # START + SEQ + at least 1 payload byte + END
        print(f"Invalid packet length: {len(packet)}")
        return False
    
    if packet[0] != START_BYTE:
        print(f"Invalid START_BYTE: {packet[0]:02x}")
        return False
    
    if packet[-1] != END_BYTE:
        print(f"Invalid END_BYTE: {packet[-1]:02x}")
        return False
    
    seq = packet[1]
    if seq > 255:  # Sequence number should be 0-255
        print(f"Invalid sequence number: {seq}")
        return False
    
    return True