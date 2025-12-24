import struct
import os

def generate_hex(bin_path, hex_path):
    if not os.path.exists(bin_path):
        print(f"Error: {bin_path} not found")
        return

    with open(bin_path, "rb") as f:
        content = f.read()
    
    # Pad to 4 bytes
    while len(content) % 4 != 0:
        content += b"\x00"
        
    with open(hex_path, "w") as f:
        for i in range(0, len(content), 4):
            instr = struct.unpack("<I", content[i:i+4])[0]
            f.write(f"0x{instr:08x}\n")
    print(f"Generated {hex_path}")

benchmarks = [
    ("benchmarks/multiply/multiply.bin", "benchmarks/multiply/multiply.hex"),
    ("benchmarks/vvadd/vvadd.bin", "benchmarks/vvadd/vvadd.hex"),
    ("benchmarks/add_while/test.bin", "benchmarks/add_while/test.hex")
]

for bin_file, hex_file in benchmarks:
    generate_hex(bin_file, hex_file)
