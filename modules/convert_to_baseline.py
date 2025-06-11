import subprocess

def convert_to_baseline(input_jpg, output_jpg):
    # Get dimensions using identify (requires ImageMagick)
    identify_cmd = ["identify", "-format", "%w %h", input_jpg]
    result = subprocess.run(identify_cmd, capture_output=True, text=True, check=True)
    width, height = map(int, result.stdout.strip().split())

    new_width = (width + 15) // 16 * 16
    new_height = (height + 15) // 16 * 16

    if (new_width, new_height) != (width, height):
        print(f"Resizing image from {width}x{height} to {new_width}x{new_height}")
        resize_cmd = [
            "convert", input_jpg,
            "-resize", f"{new_width}x{new_height}!",
            "-quality", "100",
            "-interlace", "none",
            output_jpg
        ]
    else:
        resize_cmd = [
            "convert", input_jpg,
            "-quality", "100",
            "-interlace", "none",
            output_jpg
        ]

    subprocess.run(resize_cmd, check=True)