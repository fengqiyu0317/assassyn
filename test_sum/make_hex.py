import sys
import struct

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 make_hex.py <binary_file>", file=sys.stderr)
        sys.exit(1)

    filename = sys.argv[1]
    with open(filename, "rb") as f:
        content = f.read()

    # Pad to 4 bytes
    while len(content) % 4 != 0:
        content += b'\x00'

    for i in range(0, len(content), 4):
        instr = struct.unpack("<I", content[i:i+4])[0]
        print(f"0x{instr:08x}")

if __name__ == "__main__":
    main()
