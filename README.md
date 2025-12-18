# Assassyn - Python-based Hardware Description Language

Assassyn is a Python-based framework for modeling hardware that allows you to write RTL-like code using Python syntax. It bridges the gap between software programming and hardware design.

## Files Overview

- [`assassyn基本语法速查.md`](assassyn基本语法速查.md): **⭐ Quick Reference** - Chinese quick syntax guide with examples (新手推荐！)
- [`assassyn入门教程.md`](assassyn入门教程.md): Comprehensive Chinese tutorial for getting started with Assassyn
- [`assassyn_documentation.md`](assassyn_documentation.md): Detailed English documentation explaining Assassyn concepts and API
- [`assassyn_example.py`](assassyn_example.py): Comprehensive example program demonstrating various Assassyn concepts
- [`README.md`](README.md): This file with usage instructions

## Quick Start (快速开始)

**新用户推荐学习路径 / Recommended Learning Path for New Users:**

1. 🚀 **快速入门**: 阅读 [`assassyn基本语法速查.md`](assassyn基本语法速查.md) - 5分钟快速了解基本语法
2. 📖 **深入学习**: 阅读 [`assassyn入门教程.md`](assassyn入门教程.md) - 全面理解核心概念
3. 💻 **实践练习**: 运行 [`assassyn_example.py`](assassyn_example.py) - 查看实际应用
4. 📚 **API参考**: 查阅 [`assassyn_documentation.md`](assassyn_documentation.md) - 详细API文档

**For English Speakers:**
- Start with [`assassyn_documentation.md`](assassyn_documentation.md) for comprehensive documentation
- Run [`assassyn_example.py`](assassyn_example.py) to see examples in action

## Prerequisites

- Python 3.7 or higher
- Assassyn framework installed
- Optional: Verilator for Verilog generation and simulation

## Installation

### Installing Assassyn

Assassyn is not available through standard pip. You need to install it from the official repository:

```bash
# Clone the Assassyn repository
git clone https://github.com/assassyn/assassyn.git
cd assassyn

# Install the framework
pip install -e .
```

### Optional: Installing Verilator

For Verilog generation and simulation:

```bash
# Ubuntu/Debian
sudo apt-get install verilator

# macOS
brew install verilator

# For other systems, visit: https://www.veripool.org/verilator/
```

## Running the Examples

### Basic Usage

Run the example program to see various Assassyn concepts in action:

```bash
python assassyn_example.py
```

This will execute four different example systems:
1. Counter System - Simple counter module
2. Processor System - Counter with data processing
3. FIFO System - First-in-first-out queue implementation
4. SRAM System - Memory access patterns

### Expected Output

When you run the example, you'll see output similar to this:

```
==================================================
Testing Counter System
==================================================
[INFO] Counter value: 0
[INFO] Counter value: 1
[INFO] Counter value: 2
...

==================================================
Testing Processor System
==================================================
[INFO] Counter value: 0
[INFO] Driver cycle: 0, test_data: 0, enable: 1
[INFO] Processing: 0 -> 0
[INFO] Processed data available: 0
...

==================================================
Testing FIFO System
==================================================
[INFO] FIFO Status: Count=0, Empty=True, Full=False
[INFO] FIFO: Writing 0 to address 0
[INFO] FIFO Status: Count=1, Empty=False, Full=False
...

==================================================
Testing SRAM System
==================================================
[INFO] SRAM operation: addr=0, we=1, re=0, wdata=0
[INFO] SRAM operation: addr=1, we=1, re=0, wdata=7
[INFO] SRAM read data: 0
...

All examples completed!
```

## Understanding the Examples

### 1. Counter System

Demonstrates the most basic Assassyn concepts:
- Register definition with `RegArray`
- Register updates with `(reg & self)[index] <= value`
- Combinational logic with `@module.combinational`
- Logging with `log()`

### 2. Processor System

Shows module interaction:
- Multiple modules working together
- Asynchronous module calls with `async_called()`
- Port communication between modules
- Conditional execution with `with Condition()`

### 3. FIFO System

Implements a common hardware component:
- Complex state management with multiple registers
- Pointer arithmetic for queue management
- Full/empty condition checking
- Read/write operations with proper control

### 4. SRAM System

Demonstrates memory usage:
- SRAM instantiation and configuration
- Memory read/write operations
- Address calculation
- Data flow between modules

## Key Concepts Demonstrated

### Register vs Variable Behavior

```python
# Python variable (immediate)
counter = 0
counter = counter + 1  # Immediately 1

# Assassyn register (next cycle)
cnt = RegArray(UInt(32), 1)
new_value = cnt[0] + UInt(32)(1)
(cnt & self)[0] <= new_value  # Updates next cycle
```

### Module Communication

```python
# Caller
processor.async_called(data=value, enable=enable)

# Receiver
data, enable = self.pop_all_ports(True)
```

### Conditional Logic

```python
# Hardware-friendly conditionals
with Condition(enable):
    # Execute when enable is true
    do_something()
```

## Creating Your Own Assassyn Models

### Basic Structure

```python
from assassyn.frontend import *
from assassyn.backend import elaborate
from assassyn import utils

class MyModule(Module):
    def __init__(self):
        super().__init__(ports={
            'input': Port(UInt(32)),
            'output': Port(UInt(32))
        })
    
    @module.combinational
    def build(self):
        input_val = self.pop_all_ports(True)
        
        # Define state
        counter = RegArray(UInt(32), 1)
        
        # Process input
        result = input_val + counter[0]
        
        # Update state
        (counter & self)[0] <= counter[0] + UInt(32)(1)
        
        # Log
        log("Processed: {} + {} = {}", input_val, counter[0], result)

def test_my_module():
    sys = SysBuilder('my_system')
    with sys:
        module = MyModule()
        module.build()
    
    simulator_path, _ = elaborate(sys, verilog=False)
    raw = utils.run_simulator(simulator_path)
    print(raw)

if __name__ == "__main__":
    test_my_module()
```

### Common Patterns

1. **State Definition**: Use `RegArray` for all state
2. **Port Access**: Always use `pop_all_ports()`
3. **Conditionals**: Use `with Condition()` not Python `if`
4. **Updates**: Schedule all updates together
5. **Logging**: Use `log()` for debugging

## Learning Resources

### Documentation

**For Chinese Readers (中文资源):**
- [`assassyn基本语法速查.md`](assassyn基本语法速查.md): ⭐ Quick syntax reference with runnable examples (推荐新手从这里开始)
- [`assassyn入门教程.md`](assassyn入门教程.md): Comprehensive Chinese tutorial with detailed explanations

**For English Readers:**
- [`assassyn_documentation.md`](assassyn_documentation.md): Comprehensive English documentation

### Key Concepts to Master

1. **Register Timing**: Understanding that updates happen next cycle
2. **Combinational Logic**: Pure computation without state
3. **Module Communication**: How modules interact
4. **System Building**: Organizing modules into systems
5. **Simulation**: Running and debugging models

### Common Pitfalls

1. **Reading after writing**: Don't read a register immediately after updating it
2. **Python conditionals**: Use `with Condition()` not `if`
3. **Port access**: Use `pop_all_ports()` not direct access
4. **Type conversions**: Properly convert between types

## Advanced Features

### Verilog Generation

Generate Verilog for synthesis:

```python
# Enable Verilog generation
simulator_path, verilator_path = elaborate(sys, verilog=True)

# The generated Verilog will be available at verilator_path
```

### Parameterized Modules

Create reusable modules with parameters:

```python
class ParameterizedModule(Module):
    def __init__(self, width=32, depth=16):
        super().__init__(ports={
            'data': Port(UInt(width))
        })
        self.width = width
        self.depth = depth
```

### State Machines

Implement finite state machines:

```python
class FSM(Module):
    @module.combinational
    def build(self):
        state = RegArray(Bits(2), 1)
        
        # State definitions
        IDLE = Bits(2)(0)
        WORKING = Bits(2)(1)
        DONE = Bits(2)(2)
        
        # State transitions
        with Condition(state[0] == IDLE):
            # Transition logic
            pass
```

## Troubleshooting

### Common Issues

1. **Import Errors**: Ensure Assassyn is properly installed
2. **Type Errors**: Check that port types match expected values
3. **Simulation Hangs**: Verify there are no infinite loops
4. **Unexpected Values**: Check register update timing

### Debugging Tips

1. **Use Logging**: Add `log()` statements to trace execution
2. **Check Types**: Verify all type conversions are correct
3. **Simplify**: Start with simple modules and build up complexity
4. **Review Timing**: Ensure register updates follow proper timing

### Getting Help

- Check the official Assassyn repository
- Review the tutorial files
- Examine the example code
- Start with minimal examples and build up

## Performance Considerations

### Optimization Tips

1. **Minimize Registers**: Only store necessary state
2. **Optimize Logic**: Simplify combinational expressions
3. **Use Appropriate Widths**: Choose minimal bit widths
4. **Pipeline Operations**: Break complex operations into stages

### Simulation Performance

- Use `verilog=False` for faster simulation when Verilog isn't needed
- Limit simulation time for complex systems
- Use logging judiciously to avoid slowdown

## Conclusion

Assassyn provides a powerful way to model hardware using Python while maintaining proper hardware semantics. By understanding the key concepts and following the patterns demonstrated in the examples, you can create complex hardware systems that are both correct and efficient.

Start with the simple examples, gradually add complexity, and don't hesitate to refer to the documentation and tutorial files when you need clarification on specific concepts.

Happy hardware modeling with Assassyn!