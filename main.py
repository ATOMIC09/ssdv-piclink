import argparse
from modules.encode_decode import encode_image, decode_ssdv
from modules.transmitter import FileTransmitter
from modules.receiver import FileReceiver
from modules.convert_to_baseline import convert_to_baseline

def main():
    parser = argparse.ArgumentParser(description="SSDV Transfer Tool CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # convert command
    convert_parser = subparsers.add_parser("convert", help="Convert image to baseline JPEG with proper size")
    convert_parser.add_argument("--image", required=True, help="Input JPEG image file")
    convert_parser.add_argument("--output", required=True, help="Output converted JPEG file")

    # encode command
    encode_parser = subparsers.add_parser("encode", help="Encode JPEG to SSDV")
    encode_parser.add_argument("--image", required=True, help="Input JPEG image file")
    encode_parser.add_argument("--ssdv", required=True, help="Output SSDV file")

    # decode command
    decode_parser = subparsers.add_parser("decode", help="Decode SSDV to JPEG")
    decode_parser.add_argument("--ssdv", required=True, help="Input SSDV file")
    decode_parser.add_argument("--output", required=True, help="Output JPEG image file")

    # send command
    send_parser = subparsers.add_parser("send", help="Send SSDV packets over serial")
    send_parser.add_argument("--ssdv", required=True, help="SSDV file to send")
    send_parser.add_argument("--port", required=True, help="Serial port")
    send_parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default 9600)")

    # recv command
    recv_parser = subparsers.add_parser("recv", help="Receive SSDV packets over serial")
    recv_parser.add_argument("--port", required=True, help="Serial port")
    recv_parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default 9600)")
    recv_parser.add_argument("--output-dir", default=".", help="Directory to save received files")

    args = parser.parse_args()

    if args.command == "encode":
        encode_image(args.image, args.ssdv)
        print(f"Encoded {args.image} to {args.ssdv}")

    elif args.command == "decode":
        decode_ssdv(args.ssdv, args.output)
        print(f"Decoded {args.ssdv} to {args.output}")

    elif args.command == "convert":
        convert_to_baseline(args.image, args.output)
        print(f"Converted {args.image} to baseline JPEG {args.output}")

    elif args.command == "send":
        print(f"Sending {args.ssdv} over {args.port} at {args.baud} baud")
        transmitter = FileTransmitter(args.port, args.baud)
        result = transmitter.send_file(args.ssdv)
        if result:
            print(f"Successfully sent {args.ssdv}")
        else:
            print(f"Failed to send {args.ssdv}")
            return 1

    elif args.command == "recv":
        print(f"Receiving SSDV file on {args.port} at {args.baud} baud")
        receiver = FileReceiver(args.port, args.baud, args.output_dir)
        result = receiver.receive_file()
        if result:
            print(f"Successfully received SSDV file")
        else:
            print(f"Failed to receive SSDV file")
            return 1


if __name__ == "__main__":
    main()
