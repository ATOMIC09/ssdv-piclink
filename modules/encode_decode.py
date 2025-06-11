import subprocess

def encode_image(input_jpg, output_ssdv):
    cmd = [
        "./ssdv", "-e",
        "-c", "CUBESA",
        "-i", "1",
        "-q", "7",
        "-l", "256",
        input_jpg, output_ssdv
    ]
    subprocess.run(cmd, check=True)

def decode_ssdv(input_ssdv, output_jpg):
    cmd = ["./ssdv", "-d", "-l", "256", input_ssdv, output_jpg]
    subprocess.run(cmd, check=True)