# SSDV-PicLink

SSDV-PicLink is a Python-based tool for encoding, transmitting, receiving, and decoding SSDV (Slow Scan Digital Video) image files. It provides a complete pipeline for sending images over serial connections, which is particularly useful for applications like high-altitude balloons, amateur radio, and other projects requiring reliable image transmission over limited bandwidth channels.

## Features

- Convert progressive JPEG images to baseline format compatible with SSDV
- Encode JPEG images to SSDV format
- Decode SSDV files back to JPEG images
- Send SSDV files over serial connections with error detection and retransmission
- Receive and reconstruct SSDV files from serial connections
- Detailed statistics on transmission performance

## Requirements

- Python 3
- ImageMagick (for image conversion)
- SSDV command-line tool (included in repository)

## Installation

Clone this repository to your local machine:

```bash
git clone https://github.com/ATOMIC09/ssdv-piclink.git
cd ssdv-piclink
```

Make sure the SSDV binary is executable:

```bash
chmod +x ./ssdv
```

Install required packages:

```bash
sudo apt install graphicsmagick-imagemagick-compat
```

## Usage

### Convert Image to Baseline JPEG

Converts a JPEG image to baseline format with dimensions that are multiples of 16 (required for SSDV encoding):

```bash
python3 main.py convert --image <input_image.jpg> --output <baseline_image.jpg>
```

### Encode JPEG to SSDV

Encodes a baseline JPEG image to SSDV format:

```bash
python3 main.py encode --image <baseline_image.jpg> --ssdv <encoded.ssdv>
```

### Receive SSDV Files

Listens on a serial port for incoming SSDV file transmissions:

```bash
python3 main.py recv --port /dev/ttyS0 --output-dir ./output
```

### Send SSDV Files

Sends an SSDV file over a serial connection:

```bash
python3 main.py send --ssdv <encoded.ssdv> --port /dev/ttyS1
```

### Decode SSDV to JPEG

Converts an SSDV file back to a JPEG image:

```bash
python3 main.py decode --ssdv <encoded.ssdv> --output decoded_image.jpg
```

## Transmission Protocol

The tool uses a custom reliable transmission protocol with the following features:

- Chunked file transfer with configurable chunk size
- MD5 checksums for data integrity verification
- Automatic retransmission of corrupted or lost packets
- Acknowledgment-based flow control
- Detailed statistics and progress reporting

## Connection Diagram

```
+-------------+                                    +-------------+
| Sender      |                                    | Receiver    |
+-------------+                                    +-------------+
      |                                                  |
      |  1. START + filename + filesize                  |
      |------------------------------------------------->|
      |                                                  |
      |                     ACK                          |
      |<-------------------------------------------------|
      |                                                  |
      |  2. Chunk_ID + Data_Length + Data + MD5          |
      |------------------------------------------------->|
      |                                                  | Verify 
      |                     ACK                          | Checksum
      |<-------------------------------------------------|
      |                                                  |
      |  3. Chunk_ID + Data_Length + Data + MD5          |
      |------------------------------------------------->|
      |                                                  | Verify
      |                     NACK (if corrupted)          | Checksum
      |<-------------------------------------------------|
      |                                                  |
      |  3. Chunk_ID + Data_Length + Data + MD5 (retry)  |
      |------------------------------------------------->|
      |                                                  | Verify
      |                     ACK                          | Checksum
      |<-------------------------------------------------|
      |                                                  |
      |           ...more chunks...                      |
      |                                                  |
      |  4. END marker                                   |
      |------------------------------------------------->|
      |                                                  |
      |                     ACK                          |
      |<-------------------------------------------------|
      |                                                  |
```

## Known Bugs
- END marker is not sent after the last chunk, which may cause the receiver to wait until a timeout occurs before closing the connection.

## Directory Structure

```
ssdv-piclink/
├── main.py                      # Main script for SSDV operations
├── ssdv                         # SSDV command-line tool
├── modules/
│   ├── convert_to_baseline.py   # Module for converting images to baseline JPEG
│   ├── encode_decode.py         # Module for encoding and decoding SSDV files
│   ├── receiver.py              # Module for receiving SSDV files
│   └── transmitter.py           # Module for sending SSDV files
├── LICENSE                      # License file
└── README.md                    # Project documentation
```

## License

This project is licensed under the terms of the included LICENSE file.

## Example Workflow

1. Convert a progressive JPEG to baseline format:
   ```bash
   python3 main.py convert --image progressive.jpg --output baseline.jpg
   ```

2. Encode the baseline JPEG to SSDV format:
   ```bash
   python3 main.py encode --image baseline.jpg --ssdv forsend.ssdv
   ```

3. On the receiving end, start the receiver:
   ```bash
   python3 main.py recv --port /dev/pts/10 --output-dir output
   ```

4. On the sending end, transmit the SSDV file:
   ```bash
   python3 main.py send --ssdv forsend.ssdv --port /dev/pts/9
   ```

5. Decode the received SSDV file back to JPEG:
   ```bash
   python3 main.py decode --ssdv forsend.ssdv --output final.jpg
   ```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
