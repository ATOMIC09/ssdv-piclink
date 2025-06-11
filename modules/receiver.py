#!/usr/bin/env python3
"""
Simple file receiver over serial port.
Receives files in chunks with basic error detection and acknowledgment.
"""

import serial
import time
import struct
import hashlib
import logging
from pathlib import Path
from typing import Optional

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class FileReceiver:
    """Simple file receiver for serial communication."""
    
    # Protocol constants (must match transmitter)
    CHUNK_SIZE = 4096          # Size of each data chunk
    START_MARKER = b'START'    # Start of transmission marker
    END_MARKER = b'END'        # End of transmission marker
    ACK = b'ACK'               # Acknowledgment
    NACK = b'NACK'             # Negative acknowledgment
    TIMEOUT = 10.0             # Receive timeout in seconds
    
    def __init__(self, port: str, baud: int = 9600, output_dir: str = "."):
        """Initialize receiver with serial port settings."""
        self.port = port
        self.baud = baud
        self.output_dir = Path(output_dir)
        self.serial_conn: Optional[serial.Serial] = None
        self.stats = {
            'bytes_received': 0,
            'chunks_received': 0,
            'errors': 0,
            'start_time': 0,
            'end_time': 0
        }
    
    def connect(self) -> bool:
        """Connect to serial port."""
        try:
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1.0,  # Shorter timeout for more responsive reading
                write_timeout=1.0,
                inter_byte_timeout=None,  # Disable inter-byte timeout
                xonxoff=False,  # Disable software flow control
                rtscts=False,   # Disable hardware flow control (enable if your hardware supports it)
                dsrdtr=False    # Disable hardware flow control (enable if your hardware supports it)
            )
            
            # Clear buffers
            self.serial_conn.reset_input_buffer()
            self.serial_conn.reset_output_buffer()
            
            logger.info(f"Connected to {self.port} at {self.baud} baud")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to {self.port}: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from serial port."""
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
            logger.info("Serial connection closed")
    
    def calculate_checksum(self, data: bytes) -> bytes:
        """Calculate MD5 checksum for data."""
        return hashlib.md5(data).digest()
    
    def send_ack(self):
        """Send acknowledgment."""
        if self.serial_conn:
            self.serial_conn.write(self.ACK)
            self.serial_conn.flush()
    
    def send_nack(self):
        """Send negative acknowledgment."""
        if self.serial_conn:
            self.serial_conn.write(self.NACK)
            self.serial_conn.flush()
    
    def receive_exact(self, size: int) -> Optional[bytes]:
        """Receive exact number of bytes."""
        if not self.serial_conn:
            return None
            
        data = b''
        start_time = time.time()
        
        # First try to read the entire block at once
        chunk = self.serial_conn.read(size)
        if len(chunk) == size:
            return chunk
        
        # If we didn't get all the data, append what we got and continue reading
        data += chunk
        
        while len(data) < size:
            if time.time() - start_time > self.TIMEOUT:
                logger.error(f"Timeout receiving {size} bytes (got {len(data)} bytes)")
                return None
            
            remaining = size - len(data)
            chunk = self.serial_conn.read(remaining)
            
            if not chunk:  # If no data was received, sleep briefly to avoid CPU spin
                time.sleep(0.01)
                continue
            
            data += chunk
        
        return data
    
    def receive_chunk(self) -> Optional[tuple[int, bytes]]:
        """Receive a single chunk."""
        if not self.serial_conn:
            return None
        
        receive_start = time.time()
        
        try:
            # Read chunk header: chunk_id(4) + data_length(4)
            header = self.receive_exact(8)
            if not header:
                logger.debug("PACKET TIMEOUT: Failed to receive packet header")
                return None
            
            chunk_id, data_length = struct.unpack('<II', header)
            
            # Validate data length
            if data_length > self.CHUNK_SIZE:
                logger.error(f"PACKET ERROR: Invalid chunk size {data_length} > {self.CHUNK_SIZE} for chunk_id={chunk_id}")
                self.send_nack()
                self.stats['errors'] += 1
                return None
            
            # Read data and checksum
            data = self.receive_exact(data_length)
            if not data:
                logger.error(f"PACKET ERROR: Failed to receive data for chunk_id={chunk_id}")
                self.send_nack()
                self.stats['errors'] += 1
                return None
            
            checksum = self.receive_exact(16)  # MD5 is 16 bytes
            if not checksum:
                logger.error(f"PACKET ERROR: Failed to receive checksum for chunk_id={chunk_id}")
                self.send_nack()
                self.stats['errors'] += 1
                return None
            
            # Verify checksum
            expected_checksum = self.calculate_checksum(data)
            if checksum != expected_checksum:
                logger.error(f"CHECKSUM ERROR: chunk_id={chunk_id}, data_size={len(data)}B")
                self.send_nack()
                self.stats['errors'] += 1
                return None
            
            receive_time = time.time() - receive_start
            packet_size = 8 + data_length + 16  # header + data + checksum
            
            # Send acknowledgment
            self.send_ack()
            logger.debug(f"PACKET RECEIVED: chunk_id={chunk_id}, data_size={len(data)}B, "
                        f"packet_size={packet_size}B, receive_time={receive_time:.3f}s")
            
            return chunk_id, data
            
        except Exception as e:
            receive_time = time.time() - receive_start
            logger.error(f"PACKET EXCEPTION: error={e}, receive_time={receive_time:.3f}s")
            self.send_nack()
            self.stats['errors'] += 1
            return None
    
    def wait_for_start(self) -> Optional[tuple[str, int]]:
        """Wait for transmission start marker."""
        if not self.serial_conn:
            return None
        
        logger.info("Waiting for transmission start...")
        
        try:
            # Look for start marker
            buffer = b''
            while True:
                byte = self.serial_conn.read(1)
                if not byte:
                    continue
                
                buffer += byte
                
                # Keep buffer manageable
                if len(buffer) > 100:
                    buffer = buffer[-50:]
                
                # Check for start marker
                if self.START_MARKER in buffer:
                    # Found start marker, read filename and file size
                    marker_pos = buffer.find(self.START_MARKER)
                    remaining_header = buffer[marker_pos + len(self.START_MARKER):]
                    
                    # Read filename length
                    while len(remaining_header) < 4:
                        byte = self.serial_conn.read(1)
                        if byte:
                            remaining_header += byte
                    
                    filename_length = struct.unpack('<I', remaining_header[:4])[0]
                    remaining_header = remaining_header[4:]
                    
                    # Read filename
                    while len(remaining_header) < filename_length:
                        byte = self.serial_conn.read(1)
                        if byte:
                            remaining_header += byte
                    
                    filename = remaining_header[:filename_length].decode('utf-8')
                    remaining_header = remaining_header[filename_length:]
                    
                    # Read file size
                    while len(remaining_header) < 8:
                        byte = self.serial_conn.read(1)
                        if byte:
                            remaining_header += byte
                    
                    file_size = struct.unpack('<Q', remaining_header[:8])[0]
                    
                    logger.info(f"HANDSHAKE: Receiving file '{filename}' ({file_size:,} bytes)")
                    
                    # Send acknowledgment
                    self.send_ack()
                    
                    return filename, file_size
                    
        except Exception as e:
            logger.error(f"Error waiting for start: {e}")
            return None
    
    def receive_file(self) -> bool:
        """Receive complete file over serial port."""
        if not self.connect():
            return False
        
        try:
            # Wait for transmission start
            start_info = self.wait_for_start()
            if not start_info:
                logger.error("Failed to receive start marker")
                return False
            
            filename, file_size = start_info
            output_path = self.output_dir / filename
            
            # Ensure output directory exists
            self.output_dir.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"Starting file reception: {output_path}")
            self.stats['start_time'] = time.time()
            
            expected_chunk_id = 0
            packets_received = 0
            last_log_time = time.time()
            
            with open(output_path, 'wb') as f:
                while True:
                    # Receive chunk - the END marker will be detected when chunk reception fails
                    chunk_result = self.receive_chunk()
                    if not chunk_result:
                        # When chunk reception fails, try to read END marker
                        logger.debug("CHUNK FAILED: Attempting to read END marker")
                        end_marker = self.serial_conn.read(len(self.END_MARKER))
                        if end_marker == self.END_MARKER:
                            logger.info(f"END MARKER: Received end of transmission marker")
                            self.send_ack()
                            break
                        else:
                            logger.error("RECEPTION FAILED: Failed to receive chunk and no END marker found")
                            return False
                    
                    chunk_id, data = chunk_result
                    packets_received += 1
                    
                    # Check sequence (simple check - could be more robust)
                    if chunk_id != expected_chunk_id:
                        logger.warning(f"SEQUENCE WARNING: got chunk_id={chunk_id}, expected={expected_chunk_id}")
                    
                    # Write data to file
                    f.write(data)
                    self.stats['bytes_received'] += len(data)
                    self.stats['chunks_received'] += 1
                    
                    # Detailed progress update
                    current_time = time.time()
                    progress = (self.stats['bytes_received'] / file_size) * 100 if file_size > 0 else 0
                    elapsed = current_time - self.stats['start_time']
                    current_rate = self.stats['bytes_received'] / elapsed if elapsed > 0 else 0
                    packets_per_sec = packets_received / elapsed if elapsed > 0 else 0
                    eta = ((file_size - self.stats['bytes_received']) / current_rate) if current_rate > 0 else 0
                    
                    # Log every 10 packets or every 2 seconds, whichever comes first
                    if expected_chunk_id % 10 == 0 or (current_time - last_log_time) >= 2.0:
                        logger.info(f"PROGRESS: packet={packets_received}, chunk_id={chunk_id}, "
                                  f"progress={progress:.1f}%, bytes={self.stats['bytes_received']:,}/{file_size:,}, "
                                  f"rate={current_rate:.0f}B/s, packet_rate={packets_per_sec:.1f}pkt/s, "
                                  f"errors={self.stats['errors']}, eta={eta:.1f}s")
                        last_log_time = current_time
                    
                    expected_chunk_id += 1
            
            self.stats['end_time'] = time.time()
            
            # Verify file size
            received_size = output_path.stat().st_size
            if received_size == file_size:
                logger.info(f"FILE COMPLETE: Successfully received {output_path} ({received_size:,} bytes)")
                self.print_stats()
                return True
            else:
                logger.error(f"FILE SIZE MISMATCH: expected {file_size:,} bytes, got {received_size:,} bytes")
                return False
                
        except Exception as e:
            logger.error(f"Reception error: {e}")
            return False
        finally:
            self.disconnect()
    
    def print_stats(self):
        """Print reception statistics."""
        duration = self.stats['end_time'] - self.stats['start_time']
        rate = self.stats['bytes_received'] / duration if duration > 0 else 0
        packet_rate = self.stats['chunks_received'] / duration if duration > 0 else 0
        error_rate = (self.stats['errors'] / (self.stats['chunks_received'] + self.stats['errors']) * 100) if (self.stats['chunks_received'] + self.stats['errors']) > 0 else 0
        
        logger.info("=" * 50)
        logger.info("RECEPTION STATISTICS")
        logger.info("=" * 50)
        logger.info(f"File transfer:")
        logger.info(f"  • Bytes received: {self.stats['bytes_received']:,} bytes")
        logger.info(f"  • Packets received: {self.stats['chunks_received']:,} packets")
        logger.info(f"  • Packet size: {self.CHUNK_SIZE:,} bytes")
        logger.info(f"  • Total errors: {self.stats['errors']:,}")
        logger.info(f"  • Error rate: {error_rate:.1f}%")
        logger.info(f"Performance:")
        logger.info(f"  • Duration: {duration:.2f} seconds")
        logger.info(f"  • Transfer rate: {rate:.0f} bytes/second ({rate/1024:.1f} KB/s)")
        logger.info(f"  • Packet rate: {packet_rate:.1f} packets/second")
        logger.info(f"  • Protocol overhead: {((self.stats['chunks_received'] * 24) / self.stats['bytes_received'] * 100):.1f}% (headers + checksums)")
        logger.info(f"Protocol efficiency:")
        logger.info(f"  • Data bytes: {self.stats['bytes_received']:,}")
        logger.info(f"  • Protocol overhead: {self.stats['chunks_received'] * 24:,} bytes")
        logger.info(f"  • Total received: {self.stats['bytes_received'] + (self.stats['chunks_received'] * 24):,} bytes")
        logger.info("=" * 50)


def main():
    """Command line interface for file receiver."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Receive file over serial port")
    parser.add_argument("port", help="Serial port (e.g., /dev/ttyUSB0)")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default: 9600)")
    parser.add_argument("--output", "-o", default=".", help="Output directory (default: current)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    receiver = FileReceiver(args.port, args.baud, args.output)
    success = receiver.receive_file()
    
    exit(0 if success else 1)


if __name__ == "__main__":
    main()
