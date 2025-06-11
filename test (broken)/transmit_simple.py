#!/usr/bin/env python3
"""
Simple SSDV packet transmitter without ACK checking for high-speed transmission.
Designed for reliable communication channels where error recovery is not needed.
"""

import serial
import time
import struct
import logging
import argparse
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SSDVTransmitterSimple:
    """Simple SSDV packet transmitter without error recovery."""
    
    # Protocol constants
    FRAME_START = b'\x55\xAA'  # Sync pattern
    FRAME_END = b'\xAA\x55'    # End pattern
    MAX_PAYLOAD_SIZE = 255     # SSDV packet size (max for single byte length field)
    INTER_PACKET_DELAY = 0.01  # Minimal delay between packets (10ms)
    
    def __init__(self, port: str, baud: int = 9600):
        """Initialize transmitter with serial port configuration."""
        self.port = port
        self.baud = baud
        self.serial_conn: Optional[serial.Serial] = None
        self.stats = {
            'packets_sent': 0,
            'bytes_sent': 0,
            'transmission_time': 0.0
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
    
    def send_packet(self, sequence: int, payload: bytes) -> bool:
        """Send a single packet without waiting for ACK."""
        if not self.serial_conn:
            return False
        
        packet = self.create_packet(sequence, payload)
        current_time = time.strftime('%H:%M:%S.%f')[:-3]
        
        try:
            self.serial_conn.write(packet)
            self.serial_conn.flush()
            self.stats['packets_sent'] += 1
            self.stats['bytes_sent'] += len(payload)
            
            logger.debug(f"[{current_time}] PACKET SENT: seq={sequence}, payload_size={len(payload)}B, packet_size={len(packet)}B")
            
            return True
        except serial.SerialException as e:
            logger.error(f"[{current_time}] SERIAL ERROR: Failed to send packet seq={sequence} - {e}")
            return False
    
    def send_ssdv_file(self, ssdv_file: str, output_log: str = None) -> bool:
        """Send complete SSDV file with simple sequential transmission."""
        if not self.connect():
            return False
        
        log_file = None
        if output_log:
            try:
                log_file = open(output_log, 'w')
                log_file.write("# Simple SSDV Transmission Log\n")
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
                
                logger.info(f"=== STARTING SIMPLE SSDV TRANSMISSION ===")
                logger.info(f"Input file: {ssdv_file} ({file_size} bytes)")
                logger.info(f"Serial port: {self.port} @ {self.baud} baud")
                logger.info(f"Max payload per packet: {self.MAX_PAYLOAD_SIZE} bytes")
                logger.info(f"Inter-packet delay: {self.INTER_PACKET_DELAY}s")
                
                sequence = 0
                bytes_sent = 0
                start_time = time.time()
                
                while True:
                    # Read SSDV packet
                    chunk = f.read(self.MAX_PAYLOAD_SIZE)
                    if not chunk:
                        logger.info(f"FILE READ COMPLETE: End of file reached at sequence {sequence}")
                        break
                    
                    current_time = time.strftime('%H:%M:%S.%f')[:-3]
                    
                    # Send packet
                    if self.send_packet(sequence, chunk):
                        bytes_sent += len(chunk)
                        
                        # Log transmission instantly
                        if log_file:
                            timestamp = time.time()
                            log_file.write(f"{timestamp},{sequence},{len(chunk)},sent\n")
                            log_file.flush()
                        
                        progress = (bytes_sent / file_size) * 100
                        elapsed = time.time() - start_time
                        rate = bytes_sent / elapsed if elapsed > 0 else 0
                        
                        if sequence % 50 == 0 or sequence < 10:  # Log every 50 packets or first 10
                            logger.info(f"[{current_time}] PROGRESS: seq={sequence}, bytes={len(chunk)}, total_bytes={bytes_sent}/{file_size}, progress={progress:.1f}%, rate={rate:.0f}B/s")
                        
                        sequence = (sequence + 1) % 256
                        
                        # Small delay between packets
                        if self.INTER_PACKET_DELAY > 0:
                            time.sleep(self.INTER_PACKET_DELAY)
                    else:
                        logger.error(f"Failed to send packet {sequence}")
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
                
                # Calculate final statistics
                total_time = time.time() - start_time
                self.stats['transmission_time'] = total_time
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
    
    def print_statistics(self):
        """Print transmission statistics."""
        logger.info("=== Simple Transmission Statistics ===")
        logger.info(f"Packets sent: {self.stats['packets_sent']}")
        logger.info(f"Bytes sent: {self.stats['bytes_sent']}")
        logger.info(f"Transmission time: {self.stats['transmission_time']:.2f}s")
        
        if self.stats['transmission_time'] > 0:
            throughput = self.stats['bytes_sent'] / self.stats['transmission_time']
            packet_rate = self.stats['packets_sent'] / self.stats['transmission_time']
            logger.info(f"Throughput: {throughput:.0f} bytes/second")
            logger.info(f"Packet rate: {packet_rate:.1f} packets/second")

def main():
    """Command line interface for simple SSDV transmitter."""
    parser = argparse.ArgumentParser(description="Simple SSDV packet transmitter (no ACK)")
    parser.add_argument("port", help="Serial port (e.g., /dev/ttyUSB0, COM3)")
    parser.add_argument("ssdv", help="Input SSDV file to transmit")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default: 9600)")
    parser.add_argument("--delay", type=float, default=0.01, help="Inter-packet delay in seconds (default: 0.01)")
    parser.add_argument("--log", help="Output transmission log file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    transmitter = SSDVTransmitterSimple(args.port, args.baud)
    transmitter.INTER_PACKET_DELAY = args.delay
    
    success = transmitter.send_ssdv_file(args.ssdv, args.log)
    
    exit(0 if success else 1)

if __name__ == "__main__":
    main()
