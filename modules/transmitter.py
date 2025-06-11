#!/usr/bin/env python3
"""
Simple file transmitter over serial port.
Sends files in chunks with basic error detection and acknowledgment.
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


class FileTransmitter:
    """Simple file transmitter for serial communication."""
    
    # Protocol constants
    CHUNK_SIZE = 4096          # Size of each data chunk
    START_MARKER = b'START'    # Start of transmission marker
    END_MARKER = b'END'        # End of transmission marker  
    ACK = b'ACK'               # Acknowledgment
    NACK = b'NACK'             # Negative acknowledgment
    TIMEOUT = 5.0              # ACK timeout in seconds
    MAX_RETRIES = 3            # Maximum retry attempts
    
    def __init__(self, port: str, baud: int = 9600):
        """Initialize transmitter with serial port settings."""
        self.port = port
        self.baud = baud
        self.serial_conn: Optional[serial.Serial] = None
        self.stats = {
            'bytes_sent': 0,
            'chunks_sent': 0,
            'retries': 0,
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
    
    def send_chunk(self, chunk_id: int, data: bytes) -> bool:
        """Send a single chunk with acknowledgment."""
        if not self.serial_conn:
            return False
        
        # Create packet: chunk_id(4) + data_length(4) + data + checksum(16)
        packet = struct.pack('<I', chunk_id)  # Chunk ID
        packet += struct.pack('<I', len(data))  # Data length
        packet += data  # Actual data
        packet += self.calculate_checksum(data)  # Checksum
        
        packet_size = len(packet)
        send_time = time.time()
        
        for attempt in range(self.MAX_RETRIES):
            try:
                # Send packet all at once for better performance
                bytes_written = self.serial_conn.write(packet)
                self.serial_conn.flush()
                
                if bytes_written != packet_size:
                    logger.warning(f"PARTIAL WRITE: chunk_id={chunk_id}, wrote {bytes_written}/{packet_size} bytes")
                
                if attempt == 0:
                    logger.debug(f"PACKET SENT: chunk_id={chunk_id}, data_size={len(data)}B, packet_size={packet_size}B")
                else:
                    logger.info(f"PACKET RETRY: chunk_id={chunk_id}, data_size={len(data)}B, attempt={attempt + 1}")
                
                # Wait for acknowledgment
                ack_start = time.time()
                response = self.serial_conn.read(4)
                ack_time = time.time() - ack_start
                
                if response == self.ACK:
                    response_time = time.time() - send_time
                    logger.debug(f"PACKET ACK: chunk_id={chunk_id}, ack_time={ack_time:.3f}s, total_time={response_time:.3f}s")
                    if attempt > 0:
                        self.stats['retries'] += attempt
                        logger.info(f"RETRY SUCCESS: chunk_id={chunk_id} succeeded after {attempt + 1} attempts")
                    return True
                elif response == self.NACK:
                    logger.warning(f"PACKET NACK: chunk_id={chunk_id} rejected by receiver, retrying... (attempt {attempt + 1}/{self.MAX_RETRIES})")
                    self.stats['retries'] += 1
                elif not response:
                    logger.warning(f"PACKET TIMEOUT: chunk_id={chunk_id} no response after {ack_time:.3f}s, retrying... (attempt {attempt + 1}/{self.MAX_RETRIES})")
                    self.stats['retries'] += 1
                else:
                    logger.warning(f"PACKET UNKNOWN RESPONSE: chunk_id={chunk_id}, response={response!r}, retrying... (attempt {attempt + 1}/{self.MAX_RETRIES})")
                    self.stats['retries'] += 1
                
            except Exception as e:
                logger.error(f"PACKET ERROR: chunk_id={chunk_id}, attempt={attempt + 1}, error={e}")
                self.stats['retries'] += 1
            
            # Shorter delay between retries
            time.sleep(0.05)
        
        logger.error(f"PACKET FAILED: chunk_id={chunk_id} failed after {self.MAX_RETRIES} attempts")
        return False
    
    def send_file(self, file_path: str) -> bool:
        """Send complete file over serial port."""
        file_path = Path(file_path)
        
        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return False
        
        if not self.connect():
            return False
        
        try:
            file_size = file_path.stat().st_size
            logger.info(f"Starting transmission of {file_path.name} ({file_size} bytes)")
            
            self.stats['start_time'] = time.time()
            
            # Send start marker with filename and file size
            filename_bytes = file_path.name.encode('utf-8')
            start_packet = self.START_MARKER
            start_packet += struct.pack('<I', len(filename_bytes))  # Filename length
            start_packet += filename_bytes  # Filename
            start_packet += struct.pack('<Q', file_size)  # File size
            
            logger.info(f"HANDSHAKE: Sending start packet (size={len(start_packet)}B)")
            self.serial_conn.write(start_packet)
            self.serial_conn.flush()
            
            # Wait for start acknowledgment
            handshake_start = time.time()
            response = self.serial_conn.read(4)
            handshake_time = time.time() - handshake_start
            
            if response != self.ACK:
                logger.error(f"HANDSHAKE FAILED: Receiver did not acknowledge start (response={response}, time={handshake_time:.3f}s)")
                return False
            
            logger.info(f"HANDSHAKE SUCCESS: Receiver ready (response_time={handshake_time:.3f}s)")
            
            # Send file in chunks
            chunk_id = 0
            packets_sent = 0
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(self.CHUNK_SIZE)
                    if not chunk:
                        break
                    
                    if self.send_chunk(chunk_id, chunk):
                        self.stats['bytes_sent'] += len(chunk)
                        self.stats['chunks_sent'] += 1
                        packets_sent += 1
                        
                        # Detailed progress update
                        progress = (self.stats['bytes_sent'] / file_size) * 100
                        elapsed = time.time() - self.stats['start_time']
                        current_rate = self.stats['bytes_sent'] / elapsed if elapsed > 0 else 0
                        packets_per_sec = packets_sent / elapsed if elapsed > 0 else 0
                        eta = ((file_size - self.stats['bytes_sent']) / current_rate) if current_rate > 0 else 0
                        
                        if chunk_id % 10 == 0:  # Update every 10 chunks instead of 5
                            logger.info(f"PROGRESS: packet={packets_sent}, chunk_id={chunk_id}, "
                                      f"progress={progress:.1f}%, bytes={self.stats['bytes_sent']}/{file_size}, "
                                      f"rate={current_rate:.0f}B/s, packet_rate={packets_per_sec:.1f}pkt/s, "
                                      f"retries={self.stats['retries']}, eta={eta:.1f}s")
                        
                        chunk_id += 1
                    else:
                        logger.error(f"TRANSMISSION FAILED: Failed to send chunk {chunk_id}")
                        return False
            
            # Send end marker
            logger.info(f"FINALIZING: Sending end marker (total_packets={packets_sent})")
            self.serial_conn.write(self.END_MARKER)
            self.serial_conn.flush()
            
            # Wait for final acknowledgment
            final_start = time.time()
            response = self.serial_conn.read(4)
            final_time = time.time() - final_start
            
            if response == self.ACK:
                self.stats['end_time'] = time.time()
                logger.info(f"END ACKNOWLEDGED: Transmission complete (response_time={final_time:.3f}s)")
                self.print_stats()
                logger.info("FILE TRANSMISSION COMPLETED SUCCESSFULLY")
                return True
            else:
                logger.error(f"END FAILED: Receiver did not acknowledge end (response={response}, time={final_time:.3f}s)")
                return False
                
        except Exception as e:
            logger.error(f"Transmission error: {e}")
            return False
        finally:
            self.disconnect()
    
    def print_stats(self):
        """Print transmission statistics."""
        duration = self.stats['end_time'] - self.stats['start_time']
        rate = self.stats['bytes_sent'] / duration if duration > 0 else 0
        packet_rate = self.stats['chunks_sent'] / duration if duration > 0 else 0
        efficiency = ((self.stats['chunks_sent'] * 100) / (self.stats['chunks_sent'] + self.stats['retries'])) if (self.stats['chunks_sent'] + self.stats['retries']) > 0 else 0
        
        logger.info("=" * 50)
        logger.info("TRANSMISSION STATISTICS")
        logger.info("=" * 50)
        logger.info(f"File transfer:")
        logger.info(f"  • Bytes sent: {self.stats['bytes_sent']:,} bytes")
        logger.info(f"  • Packets sent: {self.stats['chunks_sent']:,} packets")
        logger.info(f"  • Packet size: {self.CHUNK_SIZE:,} bytes")
        logger.info(f"  • Total retries: {self.stats['retries']:,}")
        logger.info(f"  • Success rate: {efficiency:.1f}%")
        logger.info(f"Performance:")
        logger.info(f"  • Duration: {duration:.2f} seconds")
        logger.info(f"  • Transfer rate: {rate:.0f} bytes/second ({rate/1024:.1f} KB/s)")
        logger.info(f"  • Packet rate: {packet_rate:.1f} packets/second")
        logger.info(f"  • Overhead: {((self.stats['chunks_sent'] * 24) / self.stats['bytes_sent'] * 100):.1f}% (headers + checksums)")
        logger.info(f"Protocol efficiency:")
        logger.info(f"  • Data bytes: {self.stats['bytes_sent']:,}")
        logger.info(f"  • Protocol overhead: {self.stats['chunks_sent'] * 24:,} bytes")
        logger.info(f"  • Total transmitted: {self.stats['bytes_sent'] + (self.stats['chunks_sent'] * 24):,} bytes")
        logger.info("=" * 50)


def main():
    """Command line interface for file transmitter."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Send file over serial port")
    parser.add_argument("port", help="Serial port (e.g., /dev/ttyUSB0)")
    parser.add_argument("file", help="File to transmit")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default: 9600)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    transmitter = FileTransmitter(args.port, args.baud)
    success = transmitter.send_file(args.file)
    
    exit(0 if success else 1)


if __name__ == "__main__":
    main()
