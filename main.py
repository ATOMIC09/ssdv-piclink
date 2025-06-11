import argparse
from modules.encode_decode import encode_image, decode_ssdv
from modules.send import send_ssdv_packets
from modules.receive import receive_ssdv_packets
from modules.convert_to_baseline import convert_to_baseline

def main():
    parser = argparse.ArgumentParser(description="SSDV Transfer Tool CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

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
    send_parser.add_argument("--ssdv", required=True, help="Input SSDV file")
    send_parser.add_argument("--port", required=True, help="Serial port")
    send_parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default 9600)")

    # recv command
    recv_parser = subparsers.add_parser("recv", help="Receive SSDV packets over serial")
    recv_parser.add_argument("--ssdv", required=True, help="Output SSDV file")
    recv_parser.add_argument("--port", required=True, help="Serial port")
    recv_parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default 9600)")

    # convert command
    convert_parser = subparsers.add_parser("convert", help="Convert image to baseline JPEG with proper size")
    convert_parser.add_argument("--image", required=True, help="Input JPEG image file")
    convert_parser.add_argument("--output", required=True, help="Output converted JPEG file")

    args = parser.parse_args()

    if args.command == "encode":
        encode_image(args.image, args.ssdv)
        print(f"Encoded {args.image} to {args.ssdv}")

    elif args.command == "decode":
        decode_ssdv(args.ssdv, args.output)
        print(f"Decoded {args.ssdv} to {args.output}")

    elif args.command == "send":
        send_ssdv_packets(args.ssdv, args.port, args.baud)
        print(f"Sent {args.ssdv} over {args.port} at {args.baud} baud")

    elif args.command == "recv":
        receive_ssdv_packets(args.ssdv, args.port, args.baud)
        print(f"Received SSDV packets on {args.port} saved to {args.ssdv}")

    elif args.command == "convert":
        convert_to_baseline(args.image, args.output)
        print(f"Converted {args.image} to baseline JPEG {args.output}")

if __name__ == "__main__":
    main()
