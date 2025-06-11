#!/usr/bin/env python3
"""
Robust SSDV packet receiver for satellite-to-ground communication.
Designed for unreliable medium with error detection and recovery.
"""

import serial
import time
import struct
import logging
from typing import Optional, Dict, Set
from collections import defaultdict

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SSDVReceiver:
    """Reliable SSDV packet receiver with error recovery."""
    
    # Protocol constants (must match transmitter)
    FRAME_START = b'\x55\xAA'  # Sync pattern
    FRAME_END = b'\xAA\x55'    # End pattern
    MAX_PAYLOAD_SIZE = 255     # SSDV packet size (max for single byte length field)
    RECEIVE_TIMEOUT = 30.0     # Timeout for receiving packets
    SYNC_TIMEOUT = 10.0        # Timeout for initial sync
    BATCH_SIZE = 100           # Number of packets per batch (must match transmitter)
    
    # Control bytes
    ACK = b'\x06'              # Acknowledgment
    NAK = b'\x15'              # Negative acknowledgment
    
    def __init__(self, port: str, baud: int = 9600):
        """Initialize receiver with serial port configuration."""
        self.port = port
        self.baud = baud
        self.serial_conn: Optional[serial.Serial] = None
        self.packet_buffer: Dict[int, bytes] = {}  # Store packets by sequence number
        self.received_sequences: Set[int] = set()
        self.expected_sequence = 0
        self.current_batch_start = 0
        self.current_batch_packets = set()
        self.output_file_handle = None
        self.stats = {
            'packets_received': 0,
            'packets_valid': 0,
            'packets_duplicate': 0,
            'packets_corrupted': 0,
            'bytes_received': 0,
            'batches_processed': 0,
            'batches_acked': 0
        }
    
    def connect(self) -> bool:
        """Establish serial connection."""
        try:
            logger.info(f"CONNECTING: Attempting to connect to {self.port} at {self.baud} baud")
            
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1.0
            )
            
            # Flush buffers
            self.serial_conn.reset_input_buffer()
            self.serial_conn.reset_output_buffer()
            
            logger.info(f"CONNECTION SUCCESS: Connected to {self.port} at {self.baud} baud")
            logger.debug(f"SERIAL CONFIG: 8N1, timeout=1.0s")
            return True
            
        except serial.SerialException as e:
            logger.error(f"CONNECTION FAILED: Failed to connect to {self.port} - {e}")
            return False
    
    def disconnect(self):
        """Close serial connection."""
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
            logger.info("Serial connection closed")
    
    def calculate_checksum(self, data: bytes) -> bytes:
        """Calculate CRC16 checksum for data integrity validation."""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return struct.pack('<H', crc)
    
    def send_batch_ack(self, batch_start: int, batch_end: int, missing_packets: list = None):
        """Send batch acknowledgment or negative acknowledgment with missing packet list."""
        if not self.serial_conn:
            return
        
        current_time = time.strftime('%H:%M:%S.%f')[:-3]
        
        try:
            if missing_packets:
                # Send NAK with missing packet list
                response = (self.NAK + 
                          bytes([batch_start & 0xFF, batch_end & 0xFF, len(missing_packets)]) + 
                          bytes(missing_packets))
                logger.warning(f"[{current_time}] SENDING NAK: batch {batch_start}-{batch_end}, missing {len(missing_packets)} packets: {missing_packets}")
            else:
                # Send ACK for complete batch
                response = self.ACK + bytes([batch_start & 0xFF, batch_end & 0xFF])
                logger.info(f"[{current_time}] SENDING ACK: batch {batch_start}-{batch_end} complete - all packets received")
            
            self.serial_conn.write(response)
            self.serial_conn.flush()
            
            logger.debug(f"[{current_time}] RESPONSE SENT: {len(response)} bytes transmitted")
            
        except serial.SerialException as e:
            logger.error(f"[{current_time}] SERIAL ERROR: Failed to send batch acknowledgment - {e}")
    
    def open_output_file(self, output_file: str) -> bool:
        """Open output file for instant writing."""
        try:
            self.output_file_handle = open(output_file, 'wb')
            logger.info(f"Opened output file {output_file} for instant writing")
            return True
        except Exception as e:
            logger.error(f"Failed to open output file {output_file}: {e}")
            return False
    
    def close_output_file(self):
        """Close output file."""
        if self.output_file_handle:
            self.output_file_handle.close()
            self.output_file_handle = None
    
    def write_packet_instantly(self, sequence: int, payload: bytes):
        """Write packet data to file instantly."""
        if self.output_file_handle:
            try:
                # Store current position
                current_pos = self.output_file_handle.tell()
                
                # Calculate position for this packet (assuming sequential writing)
                # For out-of-order packets, we might need a more sophisticated approach
                packet_pos = sequence * self.MAX_PAYLOAD_SIZE
                
                # Seek to correct position and write
                self.output_file_handle.seek(packet_pos)
                self.output_file_handle.write(payload)
                self.output_file_handle.flush()
                
                logger.debug(f"Wrote packet {sequence} instantly to file at position {packet_pos}")
                
            except Exception as e:
                logger.error(f"Failed to write packet {sequence} instantly: {e}")
    
    def send_ack(self, sequence: int, positive: bool = True):
        """Send acknowledgment or negative acknowledgment."""
        if not self.serial_conn:
            return
        
        try:
            control_byte = self.ACK if positive else self.NAK
            response = control_byte + bytes([sequence & 0xFF])
            self.serial_conn.write(response)
            self.serial_conn.flush()
            
            logger.debug(f"Sent {'ACK' if positive else 'NAK'} for packet {sequence}")
            
        except serial.SerialException as e:
            logger.error(f"Failed to send acknowledgment: {e}")
    
    def find_frame_in_buffer(self, buffer: bytearray) -> Optional[tuple]:
        """Find and extract a complete frame from the buffer."""
        start_pos = buffer.find(self.FRAME_START)
        if start_pos == -1:
            return None
        
        # Look for frame end after the start
        search_start = start_pos + len(self.FRAME_START)
        end_pos = buffer.find(self.FRAME_END, search_start)
        
        if end_pos == -1:
            return None
        
        # Extract frame data (excluding start and end markers)
        frame_data = buffer[start_pos + len(self.FRAME_START):end_pos]
        frame_length = end_pos + len(self.FRAME_END) - start_pos
        
        return frame_data, start_pos, frame_length
    
    def validate_packet(self, frame_data: bytes) -> Optional[tuple]:
        """Validate packet structure and checksum."""
        # Minimum packet size: SEQ(1) + LEN(1) + CRC(2) = 4 bytes
        if len(frame_data) < 4:
            logger.debug(f"VALIDATION FAILED: Packet too short ({len(frame_data)} bytes < 4 minimum)")
            return None
        
        try:
            # Extract packet components
            sequence = frame_data[0]
            payload_length = frame_data[1]
            
            # Check if we have enough data for the payload and CRC
            expected_total_length = 2 + payload_length + 2  # header + payload + CRC
            if len(frame_data) != expected_total_length:
                logger.debug(f"VALIDATION FAILED: Packet length mismatch for seq={sequence} - expected {expected_total_length}, got {len(frame_data)}")
                return None
            
            # Extract payload and checksum
            payload = frame_data[2:2 + payload_length]
            received_crc = frame_data[2 + payload_length:2 + payload_length + 2]
            
            # Validate checksum
            packet_data = frame_data[:2 + payload_length]  # SEQ + LEN + PAYLOAD
            calculated_crc = self.calculate_checksum(packet_data)
            
            if received_crc != calculated_crc:
                logger.warning(f"VALIDATION FAILED: Checksum mismatch for seq={sequence} - received={received_crc.hex()}, calculated={calculated_crc.hex()}")
                return None
            
            logger.debug(f"VALIDATION SUCCESS: seq={sequence}, payload_len={payload_length}, checksum_ok=True")
            return sequence, payload
            
        except Exception as e:
            logger.error(f"VALIDATION ERROR: Packet validation exception - {e}")
            return None
    
    def process_packet(self, sequence: int, payload: bytes) -> bool:
        """Process a valid packet with batch handling and instant writing."""
        self.stats['packets_received'] += 1
        
        # Detailed logging for packet reception
        current_time = time.strftime('%H:%M:%S.%f')[:-3]  # Include milliseconds
        logger.info(f"[{current_time}] PACKET RECEIVED: seq={sequence}, size={len(payload)} bytes, total_received={self.stats['packets_received']}")
        
        # Check for end-of-transmission marker
        if sequence == 255 and payload == b'EOT':
            logger.info(f"[{current_time}] END-OF-TRANSMISSION marker received (seq={sequence})")
            self.process_current_batch()  # Process any remaining batch
            return False  # Signal end of transmission
        
        # Check for duplicate packet
        if sequence in self.received_sequences:
            self.stats['packets_duplicate'] += 1
            logger.warning(f"[{current_time}] DUPLICATE PACKET: seq={sequence} - already received, ignoring")
            return True
        
        # Store packet and write instantly
        self.packet_buffer[sequence] = payload
        self.received_sequences.add(sequence)
        self.current_batch_packets.add(sequence)
        self.stats['packets_valid'] += 1
        self.stats['bytes_received'] += len(payload)
        
        # Write packet data instantly
        self.write_packet_instantly(sequence, payload)
        
        # Calculate progress statistics
        total_packets = len(self.received_sequences)
        progress_pct = (self.stats['bytes_received'] / (total_packets * self.MAX_PAYLOAD_SIZE)) * 100 if total_packets > 0 else 0
        
        logger.info(f"[{current_time}] PACKET PROCESSED: seq={sequence}, payload={len(payload)}B, total_valid={self.stats['packets_valid']}, bytes_total={self.stats['bytes_received']}, progress={progress_pct:.1f}%")
        
        # Check if we need to process a batch
        batch_num = sequence // self.BATCH_SIZE
        expected_batch_start = batch_num * self.BATCH_SIZE
        
        # If this is a new batch, process the previous one
        if expected_batch_start != self.current_batch_start and self.current_batch_packets:
            logger.info(f"[{current_time}] BATCH TRANSITION: switching from batch {self.current_batch_start//self.BATCH_SIZE} to {batch_num}")
            self.process_current_batch()
            self.current_batch_start = expected_batch_start
            self.current_batch_packets = {sequence}
        
        # Check if current batch is complete
        expected_packets_in_batch = set(range(self.current_batch_start, 
                                            min(self.current_batch_start + self.BATCH_SIZE, 256)))
        
        # For the last batch, only expect packets that were actually sent
        if self.current_batch_start + self.BATCH_SIZE >= 256:
            # Find the highest sequence we've seen to determine batch end
            max_seq = max(self.received_sequences) if self.received_sequences else sequence
            expected_packets_in_batch = set(range(self.current_batch_start, max_seq + 1))
        
        # If we have all expected packets for this batch, send ACK
        received_in_batch = self.current_batch_packets & expected_packets_in_batch
        batch_progress = len(received_in_batch)
        batch_expected = len(expected_packets_in_batch)
        
        logger.debug(f"[{current_time}] BATCH STATUS: batch={self.current_batch_start//self.BATCH_SIZE}, received={batch_progress}/{batch_expected} packets")
        
        if len(received_in_batch) >= self.BATCH_SIZE or (sequence >= 255):
            logger.info(f"[{current_time}] BATCH COMPLETE: triggering batch processing for batch {self.current_batch_start//self.BATCH_SIZE}")
            self.process_current_batch()
        
        return True
    
    def process_current_batch(self):
        """Process the current batch and send appropriate ACK/NAK."""
        if not self.current_batch_packets:
            return
        
        batch_start = self.current_batch_start
        batch_end = min(self.current_batch_start + self.BATCH_SIZE - 1, 255)
        
        # Find missing packets in the current batch
        expected_packets = set(range(batch_start, batch_end + 1))
        missing_packets = []
        
        for seq in expected_packets:
            if seq not in self.current_batch_packets:
                missing_packets.append(seq)
        
        self.stats['batches_processed'] += 1
        
        if missing_packets:
            # Send NAK with missing packet list
            self.send_batch_ack(batch_start, batch_end, missing_packets)
            logger.warning(f"Batch {batch_start}-{batch_end} incomplete, missing {len(missing_packets)} packets")
        else:
            # Send ACK for complete batch
            self.send_batch_ack(batch_start, batch_end)
            self.stats['batches_acked'] += 1
            logger.info(f"Batch {batch_start}-{batch_end} complete, sent ACK")
        
        # Move to next batch
        self.current_batch_start = batch_end + 1
        self.current_batch_packets = set()
    
    def wait_for_sync(self) -> bool:
        """Wait for initial synchronization with transmitter."""
        logger.info("Waiting for synchronization...")
        
        start_time = time.time()
        buffer = bytearray()
        
        while time.time() - start_time < self.SYNC_TIMEOUT:
            if not self.serial_conn:
                return False
                
            if self.serial_conn.in_waiting > 0:
                data = self.serial_conn.read(self.serial_conn.in_waiting)
                buffer.extend(data)
                
                # Look for start pattern
                if self.FRAME_START in buffer:
                    logger.info("Synchronization achieved")
                    return True
                
                # Keep buffer size manageable
                if len(buffer) > 1024:
                    buffer = buffer[-512:]  # Keep last 512 bytes
            
            time.sleep(0.1)
        
        logger.error("Synchronization timeout")
        return False
    
    def receive_ssdv_file(self, output_file: str) -> bool:
        """Receive complete SSDV file with batch handling and instant writing."""
        if not self.connect():
            return False
        
        # Open output file for instant writing
        if not self.open_output_file(output_file):
            self.disconnect()
            return False
        
        try:
            # Wait for initial synchronization
            if not self.wait_for_sync():
                return False
            
            logger.info(f"=== STARTING SSDV RECEPTION ===")
            logger.info(f"Output file: {output_file}")
            logger.info(f"Serial port: {self.port} @ {self.baud} baud")
            logger.info(f"Batch size: {self.BATCH_SIZE} packets")
            logger.info(f"Receive timeout: {self.RECEIVE_TIMEOUT}s")
            
            buffer = bytearray()
            last_activity = time.time()
            frames_processed = 0
            
            while True:
                current_time = time.strftime('%H:%M:%S.%f')[:-3]
                
                # Check for timeout
                if time.time() - last_activity > self.RECEIVE_TIMEOUT:
                    logger.warning(f"[{current_time}] TIMEOUT: No activity for {self.RECEIVE_TIMEOUT}s, ending reception")
                    break
                
                # Read data from serial port
                if self.serial_conn.in_waiting > 0:
                    data = self.serial_conn.read(self.serial_conn.in_waiting)
                    buffer.extend(data)
                    last_activity = time.time()
                    
                    logger.debug(f"[{current_time}] SERIAL DATA: received {len(data)} bytes, buffer size now {len(buffer)} bytes")
                    
                    # Process all complete frames in buffer
                    while True:
                        frame_result = self.find_frame_in_buffer(buffer)
                        if not frame_result:
                            break
                        
                        frame_data, start_pos, frame_length = frame_result
                        frames_processed += 1
                        
                        logger.debug(f"[{current_time}] FRAME FOUND: #{frames_processed}, start_pos={start_pos}, length={frame_length}, data_size={len(frame_data)}")
                        
                        # Remove processed frame from buffer
                        del buffer[:start_pos + frame_length]
                        
                        # Validate and process packet
                        packet_result = self.validate_packet(frame_data)
                        if packet_result:
                            sequence, payload = packet_result
                            logger.info(f"[{current_time}] FRAME VALIDATED: seq={sequence}, payload_size={len(payload)}")
                            
                            if not self.process_packet(sequence, payload):
                                # End of transmission received
                                logger.info(f"[{current_time}] === RECEPTION COMPLETED ===")
                                logger.info(f"Total frames processed: {frames_processed}")
                                self.finalize_output_file(output_file)
                                self.print_statistics()
                                return True
                        else:
                            self.stats['packets_corrupted'] += 1
                            logger.warning(f"[{current_time}] FRAME REJECTED: corrupted packet discarded (frame #{frames_processed})")
                
                time.sleep(0.01)  # Small delay to prevent busy waiting
            
            # Finalize received data even if transmission was incomplete
            logger.info("Finalizing received data (transmission may be incomplete)")
            self.finalize_output_file(output_file)
            self.print_statistics()
            return len(self.packet_buffer) > 0
            
        except Exception as e:
            logger.error(f"Reception error: {e}")
            return False
        finally:
            self.close_output_file()
            self.disconnect()
    
    def finalize_output_file(self, output_file: str):
        """Finalize the output file by ensuring all received data is properly written."""
        try:
            # Close the instant-write file handle
            self.close_output_file()
            
            # Reopen for final cleanup and gap filling
            with open(output_file, 'r+b') as f:
                # Fill any gaps with zero bytes or handle missing packets
                if self.packet_buffer:
                    min_seq = min(self.packet_buffer.keys())
                    max_seq = max(self.packet_buffer.keys())
                    
                    for seq in range(min_seq, max_seq + 1):
                        if seq not in self.packet_buffer:
                            # Write zeros for missing packets
                            f.seek(seq * self.MAX_PAYLOAD_SIZE)
                            f.write(b'\x00' * self.MAX_PAYLOAD_SIZE)
                    
                    # Truncate file to actual data size
                    actual_size = (max_seq + 1) * self.MAX_PAYLOAD_SIZE
                    # Find the last non-zero byte
                    f.seek(0, 2)  # Go to end
                    file_size = f.tell()
                    
                    # Truncate trailing zeros
                    for pos in range(file_size - 1, -1, -1):
                        f.seek(pos)
                        if f.read(1) != b'\x00':
                            f.truncate(pos + 1)
                            break
                    
            logger.info(f"Finalized {len(self.packet_buffer)} packets in {output_file}")
            
            # Report missing packets
            if self.packet_buffer:
                min_seq = min(self.packet_buffer.keys())
                max_seq = max(self.packet_buffer.keys())
                missing = []
                
                for seq in range(min_seq, max_seq + 1):
                    if seq not in self.packet_buffer:
                        missing.append(seq)
                
                if missing:
                    logger.warning(f"Missing packets: {missing}")
                else:
                    logger.info("All packets received in sequence")
                    
        except Exception as e:
            logger.error(f"Failed to finalize output file: {e}")
    
    def print_statistics(self):
        """Print reception statistics."""
        logger.info("=== Reception Statistics ===")
        logger.info(f"Packets received: {self.stats['packets_received']}")
        logger.info(f"Valid packets: {self.stats['packets_valid']}")
        logger.info(f"Duplicate packets: {self.stats['packets_duplicate']}")
        logger.info(f"Corrupted packets: {self.stats['packets_corrupted']}")
        logger.info(f"Bytes received: {self.stats['bytes_received']}")
        logger.info(f"Batches processed: {self.stats['batches_processed']}")
        logger.info(f"Batches acknowledged: {self.stats['batches_acked']}")
        
        if self.stats['packets_received'] > 0:
            error_rate = (self.stats['packets_corrupted'] / self.stats['packets_received']) * 100
            logger.info(f"Packet error rate: {error_rate:.1f}%")
        
        if self.stats['batches_processed'] > 0:
            batch_success_rate = (self.stats['batches_acked'] / self.stats['batches_processed']) * 100
            logger.info(f"Batch success rate: {batch_success_rate:.1f}%")


def main():
    """Command line interface for SSDV receiver."""
    import argparse
    
    parser = argparse.ArgumentParser(description="SSDV Satellite Receiver")
    parser.add_argument("--ssdv", required=True, help="Output SSDV file")
    parser.add_argument("--port", required=True, help="Serial port (e.g., /dev/ttyUSB0)")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default: 9600)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    receiver = SSDVReceiver(args.port, args.baud)
    success = receiver.receive_ssdv_file(args.ssdv)
    
    exit(0 if success else 1)


if __name__ == "__main__":
    main()
