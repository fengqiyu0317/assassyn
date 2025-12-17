# Assasyn - Asynchronous Circuit Simulator Documentation

## Table of Contents
1. [Introduction](#introduction)
2. [Key Concepts](#key-concepts)
3. [Architecture](#architecture)
4. [Module Types](#module-types)
5. [Signal System](#signal-system)
6. [Simulation Process](#simulation-process)
7. [API Reference](#api-reference)
8. [Examples](#examples)
9. [Best Practices](#best-practices)

## Introduction

Assasyn is an asynchronous circuit simulator designed to model and simulate the behavior of asynchronous digital circuits. Unlike synchronous circuits that use a global clock, asynchronous circuits use handshaking protocols and local timing to coordinate operations.

### What are Asynchronous Circuits?

Asynchronous circuits are digital circuits that do not rely on a global clock signal. Instead, they use:
- Handshaking protocols for communication between components
- Local timing and delay elements
- Event-driven operation
- Request/Acknowledge signals

### Advantages of Asynchronous Circuits

- **Lower Power Consumption**: No clock distribution network
- **Better Modularity**: Components can be designed independently
- **No Clock Skew Issues**: No global clock to synchronize
- **Adaptive Performance**: Components operate at their own pace

## Key Concepts

### Signals

Signals in asynchronous circuits can have multiple states:
- **ZERO**: Logical 0
- **ONE**: Logical 1
- **UNKNOWN**: Uninitialized or indeterminate state
- **RISING**: Transition from 0 to 1
- **FALLING**: Transition from 1 to 0

### Modules

Modules are the basic building blocks of asynchronous circuits. They:
- Process input signals
- Produce output signals after specified delays
- Maintain internal state if necessary
- Communicate through signals

### Events

Events represent changes in the circuit:
- Signal value changes
- Module evaluations
- Delay completions

### Event-Driven Simulation

The simulator operates on an event-driven basis:
1. Input changes trigger events
2. Events are scheduled based on module delays
3. Modules evaluate when their scheduled time arrives
4. Output changes generate new events

## Architecture

### Core Components

1. **Signal Class**: Represents wires and connections in the circuit
2. **Module Class**: Base class for all circuit components
3. **AssasynSimulator Class**: Main simulation engine
4. **Event Queue**: Manages time-ordered events

### Simulation Flow

```
Input Change → Event Scheduling → Module Evaluation → Output Change → New Events
```

## Module Types

### Basic Logic Gates

#### AND Gate
- Inputs: 2 or more signals
- Output: Logical AND of inputs
- Delay: Configurable propagation delay

#### OR Gate
- Inputs: 2 or more signals
- Output: Logical OR of inputs
- Delay: Configurable propagation delay

#### NOT Gate
- Input: 1 signal
- Output: Logical NOT of input
- Delay: Configurable propagation delay

### Asynchronous-Specific Components

#### C-Element (Mutual Exclusion Element)
The C-element is fundamental to asynchronous circuits:
- Inputs: 2 or more signals
- Output: Changes only when all inputs agree
- Memory: Maintains previous output when inputs disagree
- Use: Synchronization and arbitration

Truth Table:
```
A B | Output
0 0 |   0
0 1 |  Previous
1 0 |  Previous
1 1 |   1
```

## Signal System

### Signal Properties

Each signal has:
- **Name**: Unique identifier
- **Value**: Current signal state
- **Last Change Time**: Timestamp of last modification
- **Drivers**: Set of modules that drive this signal

### Signal Transitions

Signals can transition between states:
- UNKNOWN → ZERO/ONE: Initialization
- ZERO ↔ ONE: Normal operation
- ZERO/ONE → RISING/FALLING: Transition states
- RISING/FALLING → ONE/ZERO: Transition completion

### Driver Management

- Each signal tracks which modules drive it
- Prevents multiple drivers from conflicting
- Enables proper event propagation

## Simulation Process

### Initialization

1. Create circuit components (modules and signals)
2. Connect signals to modules
3. Set initial input values
4. Initialize event queue

### Execution Loop

1. Process events in chronological order
2. Evaluate affected modules
3. Update output signals
4. Schedule new events based on delays
5. Check for convergence/stability

### Convergence Detection

The simulator considers the circuit stable when:
- No signal changes occur within a threshold time
- All pending events have been processed
- All modules have evaluated their current inputs

## API Reference

### Signal Class

```python
class Signal:
    def __init__(self, name: str, value: SignalValue = SignalValue.UNKNOWN)
```

**Properties:**
- `name`: Signal identifier
- `value`: Current signal value
- `last_change_time`: Timestamp of last change
- `drivers`: Set of module names that drive this signal

### Module Class

```python
class Module:
    def __init__(self, name: str)
    def add_input(self, signal_name: str, signal: Signal)
    def add_output(self, signal_name: str, signal: Signal)
    def add_internal_signal(self, signal_name: str, signal: Signal)
    def evaluate(self, current_time: float) -> bool
```

**Methods:**
- `add_input()`: Connect an input signal
- `add_output()`: Connect an output signal
- `add_internal_signal()`: Add an internal signal
- `evaluate()`: Evaluate module behavior (must be implemented by subclasses)

### AssasynSimulator Class

```python
class AssasynSimulator:
    def __init__(self)
    def add_module(self, module: Module)
    def add_signal(self, signal: Signal)
    def set_input_signal(self, signal_name: str, value: SignalValue)
    def step(self, time_step: float = 0.1)
    def run_until_stable(self, max_time: float = 100.0, time_step: float = 0.1)
    def print_circuit_state(self)
```

**Methods:**
- `add_module()`: Add a module to the circuit
- `add_signal()`: Add a signal to the circuit
- `set_input_signal()`: Change an input signal value
- `step()`: Advance simulation by one time step
- `run_until_stable()`: Run until circuit stabilizes
- `print_circuit_state()`: Display current signal values

## Examples

### Basic AND Gate Example

```python
# Create simulator
simulator = AssasynSimulator()

# Create signals
a = Signal("a")
b = Signal("b")
out = Signal("out")

# Create AND gate
and_gate = AndGate("and_gate", delay=1.0)
and_gate.add_input("a", a)
and_gate.add_input("b", b)
and_gate.add_output("out", out)

# Add to simulator
simulator.add_signal(a)
simulator.add_signal(b)
simulator.add_signal(out)
simulator.add_module(and_gate)

# Set inputs and run
simulator.set_input_signal("a", SignalValue.ONE)
simulator.set_input_signal("b", SignalValue.ONE)
simulator.run_until_stable()
simulator.print_circuit_state()
```

### C-Element Synchronization Example

```python
# Create C-element for synchronization
c_element = CElement("sync_element", delay=1.2)
req1 = Signal("req1")
req2 = Signal("req2")
ack = Signal("ack")

c_element.add_input("req1", req1)
c_element.add_input("req2", req2)
c_element.add_output("ack", ack)

# Add to simulator and test
simulator.add_signal(req1)
simulator.add_signal(req2)
simulator.add_signal(ack)
simulator.add_module(c_element)

# Test synchronization
simulator.set_input_signal("req1", SignalValue.ONE)
simulator.set_input_signal("req2", SignalValue.ZERO)
simulator.run_until_stable()  # Output should remain unchanged

simulator.set_input_signal("req2", SignalValue.ONE)
simulator.run_until_stable()  # Output should change to 1
```

## Best Practices

### Circuit Design

1. **Minimize Combinational Loops**: Avoid feedback without delay elements
2. **Use Appropriate Delays**: Model realistic propagation delays
3. **Initialize Signals**: Start with known states
4. **Design for Testability**: Include observation points

### Simulation

1. **Use Reasonable Time Steps**: Balance accuracy and performance
2. **Monitor Convergence**: Ensure circuits reach stable states
3. **Check for Hazards**: Look for unintended signal transitions
4. **Verify Timing**: Ensure delays meet design requirements

### Performance Optimization

1. **Limit Simulation Time**: Set appropriate maximum times
2. **Optimize Event Processing**: Minimize unnecessary evaluations
3. **Use Efficient Data Structures**: Choose appropriate containers
4. **Profile Complex Circuits**: Identify bottlenecks

## Advanced Topics

### Handshaking Protocols

Asynchronous circuits often use handshaking:
- **Request/Acknowledge**: Basic two-phase protocol
- **Four-Phase Protocol**: More robust communication
- **Bundled Data**: Data with request/acknowledge signals

### Arbitration

When multiple components request shared resources:
- **Mutual Exclusion**: Ensure exclusive access
- **Priority Arbitration**: Prefer certain requests
- **Fair Arbitration**: Round-robin or similar

### Metastability

Handling indeterminate states:
- **Synchronizers**: Reduce metastability risk
- **Timeouts**: Detect and resolve hangs
- **Error Detection**: Identify metastable conditions

## Troubleshooting

### Common Issues

1. **Circuit Not Stabilizing**
   - Check for combinational loops
   - Verify delay values
   - Ensure proper initialization

2. **Unexpected Signal Values**
   - Verify signal connections
   - Check for multiple drivers
   - Review module logic

3. **Performance Issues**
   - Reduce time step size
   - Optimize module evaluation
   - Limit simulation scope

### Debugging Techniques

1. **Signal Tracing**: Monitor signal changes over time
2. **Event Logging**: Track event processing
3. **State Inspection**: Examine module internal states
4. **Waveform Analysis**: Visualize signal behavior

## Conclusion

Assasyn provides a flexible framework for simulating asynchronous circuits. By understanding the key concepts and using the API effectively, you can model complex asynchronous systems and verify their behavior before implementation.

For more examples and advanced usage, refer to the example programs and test cases included with the simulator.