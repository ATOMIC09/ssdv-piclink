#!/usr/bin/env python3
"""
Robust SSDV packet transmitter for satellite-to-ground communication.
Designed for unreliable medium with error detection and recovery.
"""

import serial
import time
import struct
import hashlib
import logging
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SSDVTransmitter:
    """Reliable SSDV packet transmitter with error recovery."""
    
    # Protocol constants
    FRAME_START = b'\x55\xAA'  # Sync pattern
    FRAME_END = b'\xAA\x55'    # End pattern
    MAX_PAYLOAD_SIZE = 255     # SSDV packet size (max for single byte length field)
    MAX_RETRIES = 5            # Maximum retransmission attempts
    ACK_TIMEOUT = 25.0         # Acknowledgment timeout in seconds (increased for batch ACK)
    INTER_PACKET_DELAY = 0.1   # Delay between packets
    BATCH_SIZE = 100           # Number of packets to send before expecting ACK
    
    # Control bytes
    ACK = b'\x06'              # Acknowledgment
    NAK = b'\x15'              # Negative acknowledgment
    
    def __init__(self, port: str, baud: int = 9600):
        """Initialize transmitter with serial port configuration."""
        self.port = port
        self.baud = baud
        self.serial_conn: Optional[serial.Serial] = None
        self.stats = {
            'packets_sent': 0,
            'packets_acked': 0,
            'retransmissions': 0,
            'failed_packets': 0,
            'batches_sent': 0,
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
                timeout=self.ACK_TIMEOUT,
                write_timeout=1.0
            )
            
            # Flush buffers
            self.serial_conn.reset_input_buffer()
            self.serial_conn.reset_output_buffer()
            
            logger.info(f"CONNECTION SUCCESS: Connected to {self.port} at {self.baud} baud")
            logger.debug(f"SERIAL CONFIG: 8N1, ACK_timeout={self.ACK_TIMEOUT}s, write_timeout=1.0s")
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
        """Calculate CRC16 checksum for data integrity."""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return struct.pack('<H', crc)
    
    def create_packet(self, sequence: int, payload: bytes) -> bytes:
        """Create a framed packet with error detection."""
        # Packet structure: START(2) + SEQ(1) + LEN(1) + PAYLOAD(n) + CRC(2) + END(2)
        seq_byte = sequence & 0xFF
        length = len(payload)
        
        # Validate payload size
        if length > self.MAX_PAYLOAD_SIZE:
            raise ValueError(f"Payload size {length} exceeds maximum {self.MAX_PAYLOAD_SIZE}")
        
        # Create packet header and payload
        packet_data = struct.pack('BB', seq_byte, length) + payload
        checksum = self.calculate_checksum(packet_data)
        
        # Frame the packet
        packet = (self.FRAME_START + 
                 packet_data + 
                 checksum + 
                 self.FRAME_END)
        
        return packet
    
    def wait_for_batch_ack(self, batch_start: int, batch_end: int) -> tuple:
        """Wait for batch acknowledgment from receiver."""
        if not self.serial_conn:
            return False, []
            
        start_time = time.time()
        response_buffer = bytearray()
        current_time = time.strftime('%H:%M:%S.%f')[:-3]
        
        logger.info(f"[{current_time}] WAITING FOR BATCH ACK: batch {batch_start}-{batch_end}, timeout={self.ACK_TIMEOUT}s")
        
        while time.time() - start_time < self.ACK_TIMEOUT:
            if self.serial_conn.in_waiting > 0:
                data = self.serial_conn.read(self.serial_conn.in_waiting)
                response_buffer.extend(data)
                
                logger.debug(f"[{current_time}] ACK DATA RECEIVED: {len(data)} bytes, buffer_size={len(response_buffer)}")
                
                # Look for batch ACK pattern: ACK + batch_start + batch_end
                expected_ack = self.ACK + bytes([batch_start & 0xFF, batch_end & 0xFF])
                if expected_ack in response_buffer:
                    logger.info(f"[{current_time}] BATCH ACK RECEIVED: batch {batch_start}-{batch_end} acknowledged successfully")
                    return True, []
                
                # Check for NAK with missing packet list
                nak_start = response_buffer.find(self.NAK)
                if nak_start != -1:
                    # NAK format: NAK + batch_start + batch_end + missing_count + [missing_packets...]
                    if len(response_buffer) >= nak_start + 4:
                        missing_count = response_buffer[nak_start + 3]
                        if len(response_buffer) >= nak_start + 4 + missing_count:
                            missing_packets = list(response_buffer[nak_start + 4:nak_start + 4 + missing_count])
                            logger.warning(f"[{current_time}] BATCH NAK RECEIVED: batch {batch_start}-{batch_end}, missing {missing_count} packets: {missing_packets}")
                            return False, missing_packets
            
            time.sleep(0.01)
        
        logger.warning(f"[{current_time}] BATCH ACK TIMEOUT: No response for batch {batch_start}-{batch_end} after {self.ACK_TIMEOUT}s")
        return False, []
    
    def send_packet_no_ack(self, sequence: int, payload: bytes) -> bool:
        """Send a single packet without waiting for ACK."""
        if not self.serial_conn:
            return False
        
        packet = self.create_packet(sequence, payload)
        current_time = time.strftime('%H:%M:%S.%f')[:-3]  # Include milliseconds
        
        try:
            self.serial_conn.write(packet)
            self.serial_conn.flush()
            self.stats['packets_sent'] += 1
            
            logger.info(f"[{current_time}] PACKET SENT: seq={sequence}, payload_size={len(payload)}B, packet_size={len(packet)}B, total_sent={self.stats['packets_sent']}")
            logger.debug(f"[{current_time}] PACKET DETAILS: seq={sequence}, payload_hex={payload[:8].hex()}{'...' if len(payload) > 8 else ''}")
            
            return True
        except serial.SerialException as e:
            logger.error(f"[{current_time}] SERIAL ERROR: Failed to send packet seq={sequence} - {e}")
            return False
    
    def wait_for_ack(self, sequence: int) -> bool:
        """Wait for acknowledgment from receiver."""
        if not self.serial_conn:
            return False
            
        start_time = time.time()
        response_buffer = bytearray()
        
        while time.time() - start_time < self.ACK_TIMEOUT:
            if self.serial_conn.in_waiting > 0:
                data = self.serial_conn.read(self.serial_conn.in_waiting)
                response_buffer.extend(data)
                
                # Look for ACK pattern: ACK + sequence number
                expected_ack = self.ACK + bytes([sequence & 0xFF])
                if expected_ack in response_buffer:
                    return True
                
                # Check for NAK
                expected_nak = self.NAK + bytes([sequence & 0xFF])
                if expected_nak in response_buffer:
                    logger.warning(f"Received NAK for packet {sequence}")
                    return False
            
            time.sleep(0.01)  # Small delay to prevent busy waiting
        
        logger.warning(f"Timeout waiting for ACK for packet {sequence}")
        return False
    
    def send_packet(self, sequence: int, payload: bytes) -> bool:
        """Send a single packet with retransmission logic."""
        if not self.serial_conn:
            return False
        
        packet = self.create_packet(sequence, payload)
        
        for attempt in range(self.MAX_RETRIES):
            try:
                # Send packet
                self.serial_conn.write(packet)
                self.serial_conn.flush()
                self.stats['packets_sent'] += 1
                
                logger.debug(f"Sent packet {sequence}, attempt {attempt + 1}")
                
                # Wait for acknowledgment
                if self.wait_for_ack(sequence):
                    self.stats['packets_acked'] += 1
                    logger.info(f"Packet {sequence} acknowledged")
                    return True
                else:
                    if attempt < self.MAX_RETRIES - 1:
                        self.stats['retransmissions'] += 1
                        logger.warning(f"Retransmitting packet {sequence} (attempt {attempt + 2})")
                        time.sleep(0.5)  # Wait before retry
            
            except serial.SerialException as e:
                logger.error(f"Serial error sending packet {sequence}: {e}")
                break
        
        self.stats['failed_packets'] += 1
        logger.error(f"Failed to send packet {sequence} after {self.MAX_RETRIES} attempts")
        return False
    
    def send_ssdv_file(self, ssdv_file: str, output_log: str = None) -> bool:
        """Send complete SSDV file with batch transmission and instant logging."""
        if not self.connect():
            return False
        
        log_file = None
        if output_log:
            try:
                log_file = open(output_log, 'w')
                log_file.write("# SSDV Transmission Log\n")
                log_file.write("# Format: timestamp,sequence,payload_size,status\n")
                log_file.flush()
            except Exception as e:
                logger.error(f"Failed to open log file {output_log}: {e}")
        
        try:
            with open(ssdv_file, 'rb') as f:
                # Get file size for progress tracking
                f.seek(0, 2)
                file_size = f.tell()
                f.seek(0)
                
                logger.info(f"=== STARTING SSDV TRANSMISSION ===")
                logger.info(f"Input file: {ssdv_file} ({file_size} bytes)")
                logger.info(f"Serial port: {self.port} @ {self.baud} baud")
                logger.info(f"Batch size: {self.BATCH_SIZE} packets")
                logger.info(f"Max payload per packet: {self.MAX_PAYLOAD_SIZE} bytes")
                logger.info(f"Inter-packet delay: {self.INTER_PACKET_DELAY}s")
                logger.info(f"ACK timeout: {self.ACK_TIMEOUT}s")
                
                sequence = 0
                bytes_sent = 0
                batch_packets = []
                batch_start = 0
                start_time = time.time()
                
                while True:
                    # Read SSDV packet
                    chunk = f.read(self.MAX_PAYLOAD_SIZE)
                    if not chunk:
                        logger.info(f"FILE READ COMPLETE: End of file reached at sequence {sequence}")
                        break
                    
                    current_time = time.strftime('%H:%M:%S.%f')[:-3]
                    
                    # Send packet without waiting for individual ACK
                    if self.send_packet_no_ack(sequence, chunk):
                        batch_packets.append((sequence, chunk))
                        bytes_sent += len(chunk)
                        
                        # Log transmission instantly
                        if log_file:
                            timestamp = time.time()
                            log_file.write(f"{timestamp},{sequence},{len(chunk)},sent\n")
                            log_file.flush()
                        
                        progress = (bytes_sent / file_size) * 100
                        elapsed = time.time() - start_time
                        rate = bytes_sent / elapsed if elapsed > 0 else 0
                        
                        logger.info(f"[{current_time}] TRANSMISSION PROGRESS: seq={sequence}, bytes={len(chunk)}, total_bytes={bytes_sent}/{file_size}, progress={progress:.1f}%, rate={rate:.0f}B/s")
                        
                        sequence = (sequence + 1) % 256
                        time.sleep(self.INTER_PACKET_DELAY)
                        
                        # Check if we've sent a full batch
                        if len(batch_packets) >= self.BATCH_SIZE:
                            logger.info(f"[{current_time}] BATCH READY: {len(batch_packets)} packets ready for batch processing (seq {batch_start}-{sequence-1})")
                            if not self.process_batch(batch_packets, batch_start, log_file):
                                logger.error(f"Batch transmission failed at packets {batch_start}-{sequence-1}")
                                return False
                            batch_packets = []
                            batch_start = sequence
                    else:
                        logger.error(f"Failed to send packet {sequence}")
                        return False
                
                # Process remaining packets in final batch
                if batch_packets:
                    logger.info(f"FINAL BATCH: Processing remaining {len(batch_packets)} packets")
                    if not self.process_batch(batch_packets, batch_start, log_file):
                        logger.error("Final batch transmission failed")
                        return False
                
                # Send end-of-transmission marker
                current_time = time.strftime('%H:%M:%S.%f')[:-3]
                eot_packet = self.create_packet(255, b'EOT')
                self.serial_conn.write(eot_packet)
                
                logger.info(f"[{current_time}] END-OF-TRANSMISSION: EOT marker sent (seq=255)")
                
                if log_file:
                    timestamp = time.time()
                    log_file.write(f"{timestamp},255,3,eot_sent\n")
                    log_file.flush()
                
                total_time = time.time() - start_time
                avg_rate = bytes_sent / total_time if total_time > 0 else 0
                
                logger.info(f"=== TRANSMISSION COMPLETED SUCCESSFULLY ===")
                logger.info(f"Total time: {total_time:.2f}s")
                logger.info(f"Average rate: {avg_rate:.0f} bytes/second")
                self.print_statistics()
                return True
                
        except FileNotFoundError:
            logger.error(f"SSDV file not found: {ssdv_file}")
            return False
        except Exception as e:
            logger.error(f"Transmission error: {e}")
            return False
        finally:
            if log_file:
                log_file.close()
            self.disconnect()
    
    def process_batch(self, batch_packets: list, batch_start: int, log_file) -> bool:
        """Process a batch of packets with ACK/NAK handling."""
        if not batch_packets:
            return True
        
        batch_end = batch_packets[-1][0]  # Last sequence number in batch
        self.stats['batches_sent'] += 1
        current_time = time.strftime('%H:%M:%S.%f')[:-3]
        
        logger.info(f"[{current_time}] BATCH PROCESSING: batch {batch_start//self.BATCH_SIZE}, packets {batch_start}-{batch_end} ({len(batch_packets)} packets)")
        
        for attempt in range(self.MAX_RETRIES):
            attempt_time = time.strftime('%H:%M:%S.%f')[:-3]
            
            # Wait for batch acknowledgment
            logger.debug(f"[{attempt_time}] BATCH ATTEMPT {attempt + 1}/{self.MAX_RETRIES}: waiting for ACK/NAK")
            ack_received, missing_packets = self.wait_for_batch_ack(batch_start, batch_end)
            
            if ack_received:
                self.stats['batches_acked'] += 1
                self.stats['packets_acked'] += len(batch_packets)
                logger.info(f"[{attempt_time}] BATCH SUCCESS: batch {batch_start}-{batch_end} acknowledged on attempt {attempt + 1}")
                
                if log_file:
                    timestamp = time.time()
                    log_file.write(f"{timestamp},{batch_start}-{batch_end},batch,ack_received\n")
                    log_file.flush()
                
                return True
            
            elif missing_packets:
                # Retransmit only missing packets
                logger.warning(f"[{attempt_time}] PARTIAL BATCH FAILURE: retransmitting {len(missing_packets)} missing packets: {missing_packets}")
                self.stats['retransmissions'] += len(missing_packets)
                
                for missing_seq in missing_packets:
                    # Find the packet data for this sequence
                    for seq, payload in batch_packets:
                        if seq == missing_seq:
                            logger.info(f"[{attempt_time}] RETRANSMITTING: seq={missing_seq}, size={len(payload)}B")
                            if not self.send_packet_no_ack(seq, payload):
                                logger.error(f"Failed to retransmit packet {seq}")
                                return False
                            
                            if log_file:
                                timestamp = time.time()
                                log_file.write(f"{timestamp},{seq},{len(payload)},retransmitted\n")
                                log_file.flush()
                            break
                
                time.sleep(0.5)  # Wait before next attempt
            else:
                # No response, retransmit entire batch
                if attempt < self.MAX_RETRIES - 1:
                    logger.warning(f"[{attempt_time}] FULL BATCH FAILURE: no response, retransmitting entire batch (attempt {attempt + 2})")
                    self.stats['retransmissions'] += len(batch_packets)
                    
                    for seq, payload in batch_packets:
                        logger.debug(f"[{attempt_time}] BATCH RETRANSMIT: seq={seq}, size={len(payload)}B")
                        if not self.send_packet_no_ack(seq, payload):
                            logger.error(f"Failed to retransmit packet {seq}")
                            return False
                        
                        if log_file:
                            timestamp = time.time()
                            log_file.write(f"{timestamp},{seq},{len(payload)},batch_retransmitted\n")
                            log_file.flush()
                        
                        time.sleep(self.INTER_PACKET_DELAY)
                    
                    time.sleep(1.0)  # Wait before next attempt
        
        # All retries failed
        self.stats['failed_packets'] += len(batch_packets)
        failure_time = time.strftime('%H:%M:%S.%f')[:-3]
        logger.error(f"[{failure_time}] BATCH FINAL FAILURE: Failed to transmit batch {batch_start}-{batch_end} after {self.MAX_RETRIES} attempts")
        return False
    
    def print_statistics(self):
        """Print transmission statistics."""
        logger.info("=== Transmission Statistics ===")
        logger.info(f"Packets sent: {self.stats['packets_sent']}")
        logger.info(f"Packets acknowledged: {self.stats['packets_acked']}")
        logger.info(f"Batches sent: {self.stats['batches_sent']}")
        logger.info(f"Batches acknowledged: {self.stats['batches_acked']}")
        logger.info(f"Retransmissions: {self.stats['retransmissions']}")
        logger.info(f"Failed packets: {self.stats['failed_packets']}")
        
        if self.stats['packets_sent'] > 0:
            success_rate = (self.stats['packets_acked'] / self.stats['packets_sent']) * 100
            logger.info(f"Packet success rate: {success_rate:.1f}%")
        
        if self.stats['batches_sent'] > 0:
            batch_success_rate = (self.stats['batches_acked'] / self.stats['batches_sent']) * 100
            logger.info(f"Batch success rate: {batch_success_rate:.1f}%")


def main():
    """Command line interface for SSDV transmitter."""
    import argparse
    
    parser = argparse.ArgumentParser(description="SSDV Satellite Transmitter")
    parser.add_argument("--ssdv", required=True, help="Input SSDV file")
    parser.add_argument("--port", required=True, help="Serial port (e.g., /dev/ttyUSB0)")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default: 9600)")
    parser.add_argument("--log", help="Output log file for transmission records")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    transmitter = SSDVTransmitter(args.port, args.baud)
    success = transmitter.send_ssdv_file(args.ssdv, args.log)
    
    exit(0 if success else 1)


if __name__ == "__main__":
    main()
