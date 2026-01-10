# RV32I CPU Test Automation Guide

## Quick Start

The `run_cpu_test.sh` script automates the entire process of compiling C programs and running them on your RV32I CPU simulator.

### Usage

```bash
./run_cpu_test.sh <c_file> [run_simulation]
```

**Parameters:**
- `<c_file>`: Path to C source file (supports both relative and absolute paths)
- `[run_simulation]`: Optional - "yes" (default) to run simulation, "no" to compile only

**Examples:**

```bash
# Using relative path (file in current directory)
./run_cpu_test.sh example_test.c

# Using relative path (file in subdirectory)
./run_cpu_test.sh test_sum/test.c

# Using absolute path
./run_cpu_test.sh /full/path/to/my_program.c

# Compile and run (explicit)
./run_cpu_test.sh example_test.c yes

# Compile only (don't run simulation)
./run_cpu_test.sh my_test.c no
```

### What It Does

The script automatically:

1. ✅ **Validates** your C file and toolchain
2. ✅ **Sets up** build directory with all necessary files
3. ✅ **Compiles** C program to RISC-V instructions
4. ✅ **Links** with entry point and startup code
5. ✅ **Generates** hex files (test_program.txt and data.hex)
6. ✅ **Copies** files to the correct CPU directory
7. ✅ **Runs** simulation and extracts the result
8. ✅ **Displays** the final result in a clean format

## Example Test Programs

### Example 1: Summation (Already Tested)

```c
// test_sum.c
int main() {
    int sum = 0, i = 0;
    while(i <= 100) {
        sum += i;
        i++;
    }
    return sum;  // Expected: 5050
}
```

Run: `./run_cpu_test.sh test_sum.c`

### Example 2: Factorial

```c
// test_factorial.c
int main() {
    int result = 1;
    int n = 5;

    while (n > 0) {
        result = result * n;
        n = n - 1;
    }

    return result;  // Expected: 120 (5! = 120)
}
```

Run: `./run_cpu_test.sh test_factorial.c`

### Example 3: Fibonacci

```c
// test_fibonacci.c
int main() {
    int a = 0, b = 1, c;
    int n = 10;  // Calculate 10th Fibonacci number

    while (n > 1) {
        c = a + b;
        a = b;
        b = c;
        n = n - 1;
    }

    return b;  // Expected: 55 (10th Fibonacci number)
}
```

Run: `./run_cpu_test.sh test_fibonacci.c`

### Example 4: Simple Arithmetic

```c
// test_arithmetic.c
int main() {
    int x = 10;
    int y = 20;
    int z = x + y;

    // Simple calculation: (x + y) * 2
    z = z * 2;

    return z;  // Expected: 60 ( (10 + 20) * 2 )
}
```

Run: `./run_cpu_test.sh test_arithmetic.c`

### Example 5: Multiplication Test (RV32M)

```c
// test_mul.c
int main() {
    int a = 15;
    int b = 17;

    // This will use the MUL instruction (RV32M extension)
    int result = a * b;

    return result;  // Expected: 255 (15 * 17)
}
```

Run: `./run_cpu_test.sh test_mul.c`

## Understanding the Output

When you run the script, you'll see colored output:

```
========================================
RV32I CPU Test Automation Script
========================================

Input file: example_test.c
Work directory: /path/to/example_test

[1/6] Setting up build directory...
✓ Build directory ready
[2/6] Compiling C program...
✓ Compilation successful
[3/6] Linking...
✓ Linking successful
[4/6] Generating binary files...
✓ Binary files generated
[5/6] Generating hex file...
✓ Generated 25 instructions
[6/6] Copying files to CPU directory...
✓ Files copied to /path/to/assassyn

Running CPU simulation...
----------------------------------------
@line:2419  Cycle @1442.00: [ExecuteStageInstance]	Finish Execution. The result is 120

========================================
Simulation Result: 120
========================================

Done!
```

## How It Works

### Compilation Flow

```
C File (test.c)
    ↓
riscv64-unknown-elf-gcc (compile)
    ↓
test.o (object file)
    ↓
riscv64-unknown-elf-gcc (link with entry.o)
    ↓
test.elf (ELF executable)
    ↓
riscv64-unknown-elf-objcopy
    ↓
test.bin (binary)
    ↓
make_hex.py
    ↓
test.hex (hex instructions)
    ↓
test_program.txt & data.hex
    ↓
RV32I CPU Simulation
    ↓
Result
```

### Important Files

- **test.c**: Your C source code
- **entry.o**: Startup code (sets up stack, calls main)
- **link.ld**: Linker script (memory layout)
- **test.elf**: ELF executable (for debugging)
- **test.dump**: Disassembly (for debugging)
- **test.hex**: Hex instructions
- **test_program.txt**: Instructions with "0x" prefix (for CPU)
- **data.hex**: Instructions without "0x" prefix (for data memory)

## Debugging Tips

### If Compilation Fails

1. Check that RISC-V toolchain is installed:
   ```bash
   which riscv64-unknown-elf-gcc
   ```

2. Verify C syntax is correct

3. Check the error message in the output

### If Simulation Fails

1. Check the disassembly:
   ```bash
   cat <work_dir>/test.dump
   ```

2. Verify instruction count matches expectations

3. Check if the program has an infinite loop

### To Debug Without Running Full Simulation

```bash
# Compile only
./run_cpu_test.sh my_test.c no

# Check the generated files
cat test_program.txt
cat test.dump
```

## Advanced Usage

### Manual Compilation

If you want more control, you can compile manually:

```bash
# Create work directory
mkdir my_test && cd my_test

# Copy necessary files
cp /path/to/assassyn/benchmarks/multiply/entry.o .
cp /path/to/assassyn/benchmarks/add_while/link.ld .
cp /path/to/assassyn/benchmarks/add_while/make_hex.py .

# Compile
riscv64-unknown-elf-gcc -march=rv32i -mabi=ilp32 -O0 -g -mno-relax -I. -c test.c -o test.o

# Link
riscv64-unknown-elf-gcc -march=rv32i -mabi=ilp32 -O0 -g -mno-relax -I. -nostdlib -nostartfiles -T link.ld -o test.elf entry.o test.o -lgcc

# Generate binary
riscv64-unknown-elf-objcopy -O binary test.elf test.bin
riscv64-unknown-elf-objdump -d test.elf > test.dump

# Generate hex
python3 make_hex.py test.bin > test.hex

# Copy to CPU directory
cp test.hex /path/to/assassyn/test_program.txt
cat test.hex | sed 's/0x//g' > /path/to/assassyn/data.hex

# Run simulation
cd /path/to/assassyn
rm -rf workspace/rv32i_cpu
apptainer exec assassyn.sif python src/rv32i_cpu.py
```

## Supported C Features

Your RV32I CPU supports:
- ✅ Integer arithmetic (add, sub, mul, div, rem)
- ✅ Logical operations (and, or, xor, shifts)
- ✅ Comparison operations (==, !=, <, >, <=, >=)
- ✅ Control flow (if, while, for)
- ✅ Functions (simple calls)
- ✅ Local variables (stack-based)

Limitations:
- ❌ No standard library (printf, scanf, etc.)
- ❌ No floating point
- ❌ No arrays (unless using pointers carefully)
- ❌ No recursion (might cause stack overflow)

## Test Your Knowledge

Try writing a C program that:
1. Calculates the sum of squares from 1 to 10
2. Finds the greatest common divisor (GCD) of two numbers
3. Implements a simple counter that increments 100 times
4. Tests multiplication with large numbers
5. Uses nested loops

## Troubleshooting

### "entry.o not found"
```bash
# Ensure the file exists
ls -la /mnt/d/Tomato_Fish/assassyn/benchmarks/multiply/entry.o
```

### "link.ld not found"
```bash
# Ensure the linker script exists
ls -la /mnt/d/Tomato_Fish/assassyn/benchmarks/add_while/link.ld
```

### "Timeout during simulation"
- Your program might have an infinite loop
- Check your loop conditions carefully

### Wrong result
- Check the disassembly: `cat <work_dir>/test.dump`
- Verify your logic is correct
- Make sure you're returning the right value

## Summary

The `run_cpu_test.sh` script makes it **easy** to test your RV32I CPU with C programs:

1. Write C code
2. Run the script
3. Get the result

**No manual compilation, no file copying, no complex commands!**

🚀 Happy testing!
