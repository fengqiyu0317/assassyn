# RV32I CPU Automation - Quick Start

## 🚀 One-Command Testing

Now you can test your RV32I CPU with any C program using a single command:

```bash
./run_cpu_test.sh <your_c_file.c>
```

**Supports:**
- ✅ Relative paths (files in current directory)
- ✅ Relative paths (files in subdirectories)
- ✅ Absolute paths (files anywhere on system)

## ✨ What You Get

✅ Automatic compilation
✅ Automatic file generation
✅ Automatic simulation
✅ Result displayed in green

## 📝 Example Usage

```bash
# Test a file in current directory
./run_cpu_test.sh test_sum.c

# Test a file in subdirectory
./run_cpu_test.sh test_sum/test.c

# Test with absolute path
./run_cpu_test.sh /full/path/to/program.c

# Output:
# ========================================
# RV32I CPU Test Automation Script
# ========================================
#
# [1/6] Setting up build directory...
# [2/6] Compiling C program...
# ✓ Compilation successful
# ...
# ========================================
# Simulation Result: 5050
# ========================================
```

## 📦 Files Created

For each test, a directory is created with the test name:
- `test_sum/` - Contains all build artifacts
- `test_sum/test.dump` - Disassembly for debugging
- `test_sum/test.elf` - ELF executable

## 🎯 What This Script Does

1. **Compiles** your C code to RISC-V instructions
2. **Links** with entry point and startup code
3. **Generates** hex files (test_program.txt, data.hex)
4. **Copies** files to CPU directory
5. **Runs** simulation
6. **Extracts** and displays the result

## 📖 Full Documentation

See `CPU_TEST_GUIDE.md` for:
- Example C programs
- Debugging tips
- Advanced usage
- Troubleshooting

## 🎉 Test Examples Included

- `test_sum.c` - Sum from 0 to 100 (Result: 5050)
- `example_test.c` - Factorial of 5 (Result: 120)

## ⚙️ How It Works

```
Your C Program
     ↓
riscv64-unknown-elf-gcc (compile + link)
     ↓
test.hex (instructions)
     ↓
test_program.txt + data.hex
     ↓
RV32I CPU Simulation
     ↓
Result displayed!
```

## 🔧 Requirements

- RISC-V toolchain installed
- apptainer/singularity
- This script in your assassyn root directory

## 💡 Tips

- Use full paths if C file is in another directory
- Check `test.dump` for debugging
- Script automatically cleans and rebuilds

---

**Happy Testing! 🚀**
