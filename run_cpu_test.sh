#!/bin/bash

# run_cpu_test.sh - Automated script to compile C programs and run RV32I CPU simulation
# Usage: ./run_cpu_test.sh <c_file> [run_simulation]

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check arguments
if [ $# -lt 1 ]; then
    echo -e "${RED}Usage: $0 <c_file> [run_simulation]${NC}"
    echo -e "  c_file: Path to C source file"
    echo -e "  run_simulation: 'yes' to run simulation after compilation (default: yes)"
    echo ""
    echo "Example:"
    echo "  $0 my_test.c          # Compile and run"
    echo "  $0 my_test.c yes      # Compile and run"
    echo "  $0 my_test.c no       # Compile only"
    exit 1
fi

C_FILE="$1"
RUN_SIM="${2:-yes}"

# Validate C file exists
if [ ! -f "$C_FILE" ]; then
    echo -e "${RED}Error: C file '$C_FILE' not found!${NC}"
    exit 1
fi

# Get absolute path, directory and basename
C_FILE_ABS=$(cd "$(dirname "$C_FILE")" && pwd)/$(basename "$C_FILE")
C_DIR=$(cd "$(dirname "$C_FILE")" && pwd)
C_BASENAME=$(basename "$C_FILE" .c)
WORK_DIR="$C_DIR/$C_BASENAME"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}RV32I CPU Test Automation Script${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${YELLOW}Input file:${NC} $C_FILE"
echo -e "${YELLOW}Work directory:${NC} $WORK_DIR"
echo ""

# Check if RISC-V toolchain is available
if ! command -v riscv64-unknown-elf-gcc &> /dev/null; then
    echo -e "${RED}Error: riscv64-unknown-elf-gcc not found!${NC}"
    echo -e "Please source the setup script first:"
    echo -e "  ${YELLOW}source /path/to/riscv-toolchain/setup.sh${NC}"
    exit 1
fi

# Create work directory
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

# Copy C file and entry files
echo -e "${YELLOW}[1/6] Setting up build directory...${NC}"
cp "$C_FILE_ABS" "$WORK_DIR/test.c"

# Copy or create entry.S and link.ld
if [ -f "/mnt/d/Tomato_Fish/assassyn/benchmarks/multiply/entry.o" ]; then
    cp /mnt/d/Tomato_Fish/assassyn/benchmarks/multiply/entry.o "$WORK_DIR/"
else
    echo -e "${RED}Error: entry.o not found!${NC}"
    exit 1
fi

if [ -f "/mnt/d/Tomato_Fish/assassyn/benchmarks/add_while/link.ld" ]; then
    cp /mnt/d/Tomato_Fish/assassyn/benchmarks/add_while/link.ld "$WORK_DIR/"
else
    echo -e "${RED}Error: link.ld not found!${NC}"
    exit 1
fi

# Create make_hex.py if not exists
if [ ! -f "make_hex.py" ]; then
    cat > make_hex.py << 'EOF'
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
EOF
fi

# Compile C program
echo -e "${YELLOW}[2/6] Compiling C program...${NC}"
riscv64-unknown-elf-gcc \
    -march=rv32i \
    -mabi=ilp32 \
    -O0 \
    -g \
    -mno-relax \
    -I. \
    -c test.c -o test.o

if [ $? -ne 0 ]; then
    echo -e "${RED}Compilation failed!${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Compilation successful${NC}"

# Link
echo -e "${YELLOW}[3/6] Linking...${NC}"
riscv64-unknown-elf-gcc \
    -march=rv32i \
    -mabi=ilp32 \
    -O0 \
    -g \
    -mno-relax \
    -I. \
    -nostdlib \
    -nostartfiles \
    -T link.ld \
    -o test.elf entry.o test.o \
    -lgcc

if [ $? -ne 0 ]; then
    echo -e "${RED}Linking failed!${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Linking successful${NC}"

# Generate binary and dump
echo -e "${YELLOW}[4/6] Generating binary files...${NC}"
riscv64-unknown-elf-objcopy -O binary test.elf test.bin
riscv64-unknown-elf-objdump -d test.elf > test.dump
echo -e "${GREEN}✓ Binary files generated${NC}"

# Generate hex file
echo -e "${YELLOW}[5/6] Generating hex file...${NC}"
python3 make_hex.py test.bin > test.hex
INSTRUCTION_COUNT=$(wc -l < test.hex)
echo -e "${GREEN}✓ Generated $INSTRUCTION_COUNT instructions${NC}"

# Copy to root directory
echo -e "${YELLOW}[6/6] Copying files to CPU directory...${NC}"
PROJECT_ROOT="/mnt/d/Tomato_Fish/assassyn"
cp test.hex "$PROJECT_ROOT/test_program.txt"
cat test.hex | sed 's/0x//g' > "$PROJECT_ROOT/data.hex"
echo -e "${GREEN}✓ Files copied to $PROJECT_ROOT${NC}"

# Show summary
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Build Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "${YELLOW}Instructions:${NC} $INSTRUCTION_COUNT"
echo -e "${YELLOW}Output files:${NC}"
echo -e "  - $PROJECT_ROOT/test_program.txt"
echo -e "  - $PROJECT_ROOT/data.hex"
echo -e "  - $WORK_DIR/test.dump (for debugging)"
echo ""

# Run simulation if requested
if [ "$RUN_SIM" = "yes" ]; then
    echo -e "${YELLOW}Running CPU simulation (compiling if needed)...${NC}"
    echo -e "${GREEN}----------------------------------------${NC}"

    cd "$PROJECT_ROOT"

    # Output file for CPU log() output (current directory)
    RESULT_OUT="./result.out"
    SIMULATOR_BIN="workspace/rv32i_cpu/simulator/target/release/rv32i_cpu_simulator"

    # Build simulator (always rebuild to get latest changes)
    echo -e "${YELLOW}Building simulator...${NC}"
    rm -rf workspace/rv32i_cpu
    apptainer exec assassyn.sif python src/rv32i_cpu.py 2>&1 | tee /tmp/build.log
    if [ ! -f "$SIMULATOR_BIN" ]; then
        echo -e "${RED}Error: Failed to build simulator${NC}"
        echo -e "${RED}Build log saved to: /tmp/build.log${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ Simulator ready${NC}"

    # Run simulator
    echo -e "${YELLOW}Running simulation...${NC}"
    apptainer exec assassyn.sif "$SIMULATOR_BIN" > "$RESULT_OUT" 2>&1
    EXIT_CODE=$?

    # Show the log() output in terminal
    if [ -s "$RESULT_OUT" ]; then
        cat "$RESULT_OUT"
    fi

    echo ""
    echo -e "${YELLOW}Extracting result...${NC}"

    # Check if simulation completed successfully
    if grep -q "Finish Execution" "$RESULT_OUT"; then
        # Extract result value
        RESULT=$(grep "Finish Execution" "$RESULT_OUT" | tail -1)
        RESULT_VALUE=$(echo "$RESULT" | grep -oP "result is \K[0-9]+")
        echo -e "${GREEN}$RESULT${NC}"
        echo ""
        echo -e "${GREEN}========================================${NC}"
        echo -e "${GREEN}Simulation Result: ${YELLOW}$RESULT_VALUE${NC}"
        echo -e "${GREEN}========================================${NC}"
        echo ""
        echo -e "${YELLOW}CPU log saved to:${NC} $RESULT_OUT"
    else
        echo -e "${RED}Error: Simulation failed with exit code $EXIT_CODE${NC}"
        echo -e "${YELLOW}Log saved to:${NC} $RESULT_OUT"
        echo ""
        echo "Last 30 lines of log:"
        tail -30 "$RESULT_OUT"
        exit 1
    fi
else
    echo -e "${YELLOW}Skipping simulation (run with 'yes' to simulate)${NC}"
    echo ""
    echo "To run manually:"
    echo "  cd $PROJECT_ROOT"
    echo "  rm -rf workspace/rv32i_cpu"
    echo "  apptainer exec assassyn.sif python src/rv32i_cpu.py"
fi

echo ""
echo -e "${GREEN}Done!${NC}"
