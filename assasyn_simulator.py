#!/usr/bin/env python3
"""
Asynchronous Circuit Simulator (Assasyn)
This simulator demonstrates asynchronous circuit behavior with module drivers.
It implements basic asynchronous circuit components and simulation logic.
"""

import time
from enum import Enum
from typing import Dict, List, Set, Tuple, Optional, Callable
from dataclasses import dataclass
import random


class SignalValue(Enum):
    """Represents possible signal values in asynchronous circuits."""
    ZERO = 0
    ONE = 1
    UNKNOWN = 2
    RISING = 3  # Transition from 0 to 1
    FALLING = 4  # Transition from 1 to 0


@dataclass
class Signal:
    """Represents a signal in the asynchronous circuit."""
    name: str
    value: SignalValue = SignalValue.UNKNOWN
    last_change_time: float = 0.0
    drivers: Set[str] = None
    
    def __post_init__(self):
        if self.drivers is None:
            self.drivers = set()


class Module:
    """Base class for asynchronous circuit modules."""
    
    def __init__(self, name: str):
        self.name = name
        self.inputs: Dict[str, Signal] = {}
        self.outputs: Dict[str, Signal] = {}
        self.internal_signals: Dict[str, Signal] = {}
        self.last_evaluation_time = 0.0
        
    def add_input(self, signal_name: str, signal: Signal):
        """Add an input signal to the module."""
        self.inputs[signal_name] = signal
        signal.drivers.add(self.name)
    
    def add_output(self, signal_name: str, signal: Signal):
        """Add an output signal to the module."""
        self.outputs[signal_name] = signal
        signal.drivers.add(self.name)
    
    def add_internal_signal(self, signal_name: str, signal: Signal):
        """Add an internal signal to the module."""
        self.internal_signals[signal_name] = signal
    
    def evaluate(self, current_time: float) -> bool:
        """
        Evaluate the module's behavior.
        Returns True if any output changed, False otherwise.
        Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement evaluate method")
    
    def get_all_signals(self) -> Dict[str, Signal]:
        """Get all signals associated with this module."""
        all_signals = {}
        all_signals.update(self.inputs)
        all_signals.update(self.outputs)
        all_signals.update(self.internal_signals)
        return all_signals


class AndGate(Module):
    """Asynchronous AND gate module."""
    
    def __init__(self, name: str, delay: float = 1.0):
        super().__init__(name)
        self.delay = delay
    
    def evaluate(self, current_time: float) -> bool:
        """Evaluate AND gate logic."""
        if len(self.inputs) < 2:
            return False
        
        # Get input values
        input_values = list(self.inputs.values())
        a_val = input_values[0].value
        b_val = input_values[1].value
        
        # Determine output based on inputs
        new_output_value = SignalValue.UNKNOWN
        
        if a_val == SignalValue.ZERO or b_val == SignalValue.ZERO:
            new_output_value = SignalValue.ZERO
        elif a_val == SignalValue.ONE and b_val == SignalValue.ONE:
            new_output_value = SignalValue.ONE
        elif a_val == SignalValue.RISING and b_val == SignalValue.ONE:
            new_output_value = SignalValue.RISING
        elif a_val == SignalValue.ONE and b_val == SignalValue.RISING:
            new_output_value = SignalValue.RISING
        elif a_val == SignalValue.FALLING and b_val == SignalValue.ONE:
            new_output_value = SignalValue.FALLING
        elif a_val == SignalValue.ONE and b_val == SignalValue.FALLING:
            new_output_value = SignalValue.FALLING
        
        # Get output signal
        output_signal = list(self.outputs.values())[0]
        
        # Check if output needs to change
        if output_signal.value != new_output_value:
            # Apply delay
            if current_time - self.last_evaluation_time >= self.delay:
                output_signal.value = new_output_value
                output_signal.last_change_time = current_time
                self.last_evaluation_time = current_time
                return True
        
        return False


class OrGate(Module):
    """Asynchronous OR gate module."""
    
    def __init__(self, name: str, delay: float = 1.0):
        super().__init__(name)
        self.delay = delay
    
    def evaluate(self, current_time: float) -> bool:
        """Evaluate OR gate logic."""
        if len(self.inputs) < 2:
            return False
        
        # Get input values
        input_values = list(self.inputs.values())
        a_val = input_values[0].value
        b_val = input_values[1].value
        
        # Determine output based on inputs
        new_output_value = SignalValue.UNKNOWN
        
        if a_val == SignalValue.ONE or b_val == SignalValue.ONE:
            new_output_value = SignalValue.ONE
        elif a_val == SignalValue.ZERO and b_val == SignalValue.ZERO:
            new_output_value = SignalValue.ZERO
        elif a_val == SignalValue.RISING and b_val == SignalValue.ZERO:
            new_output_value = SignalValue.RISING
        elif a_val == SignalValue.ZERO and b_val == SignalValue.RISING:
            new_output_value = SignalValue.RISING
        elif a_val == SignalValue.FALLING and b_val == SignalValue.ZERO:
            new_output_value = SignalValue.FALLING
        elif a_val == SignalValue.ZERO and b_val == SignalValue.FALLING:
            new_output_value = SignalValue.FALLING
        
        # Get output signal
        output_signal = list(self.outputs.values())[0]
        
        # Check if output needs to change
        if output_signal.value != new_output_value:
            # Apply delay
            if current_time - self.last_evaluation_time >= self.delay:
                output_signal.value = new_output_value
                output_signal.last_change_time = current_time
                self.last_evaluation_time = current_time
                return True
        
        return False


class NotGate(Module):
    """Asynchronous NOT gate module."""
    
    def __init__(self, name: str, delay: float = 1.0):
        super().__init__(name)
        self.delay = delay
    
    def evaluate(self, current_time: float) -> bool:
        """Evaluate NOT gate logic."""
        if len(self.inputs) < 1:
            return False
        
        # Get input value
        input_val = list(self.inputs.values())[0].value
        
        # Determine output based on input
        new_output_value = SignalValue.UNKNOWN
        
        if input_val == SignalValue.ZERO:
            new_output_value = SignalValue.ONE
        elif input_val == SignalValue.ONE:
            new_output_value = SignalValue.ZERO
        elif input_val == SignalValue.RISING:
            new_output_value = SignalValue.FALLING
        elif input_val == SignalValue.FALLING:
            new_output_value = SignalValue.RISING
        
        # Get output signal
        output_signal = list(self.outputs.values())[0]
        
        # Check if output needs to change
        if output_signal.value != new_output_value:
            # Apply delay
            if current_time - self.last_evaluation_time >= self.delay:
                output_signal.value = new_output_value
                output_signal.last_change_time = current_time
                self.last_evaluation_time = current_time
                return True
        
        return False


class CElement(Module):
    """C-element (mutual exclusion element) for asynchronous circuits."""
    
    def __init__(self, name: str, delay: float = 1.0):
        super().__init__(name)
        self.delay = delay
        self.memory = SignalValue.UNKNOWN  # C-element has memory
    
    def evaluate(self, current_time: float) -> bool:
        """Evaluate C-element logic."""
        if len(self.inputs) < 2:
            return False
        
        # Get input values
        input_values = list(self.inputs.values())
        a_val = input_values[0].value
        b_val = input_values[1].value
        
        # C-element logic
        new_output_value = self.memory
        
        if a_val == SignalValue.ZERO and b_val == SignalValue.ZERO:
            new_output_value = SignalValue.ZERO
        elif a_val == SignalValue.ONE and b_val == SignalValue.ONE:
            new_output_value = SignalValue.ONE
        # If inputs differ, maintain previous state (memory)
        
        # Get output signal
        output_signal = list(self.outputs.values())[0]
        
        # Check if output needs to change
        if output_signal.value != new_output_value:
            # Apply delay
            if current_time - self.last_evaluation_time >= self.delay:
                output_signal.value = new_output_value
                output_signal.last_change_time = current_time
                self.memory = new_output_value
                self.last_evaluation_time = current_time
                return True
        
        return False


class AssasynSimulator:
    """Main asynchronous circuit simulator."""
    
    def __init__(self):
        self.modules: Dict[str, Module] = {}
        self.signals: Dict[str, Signal] = {}
        self.current_time = 0.0
        self.event_queue: List[Tuple[float, Module]] = []
        self.max_iterations = 1000
        self.convergence_threshold = 0.01  # Time threshold for convergence
    
    def add_module(self, module: Module):
        """Add a module to the simulator."""
        self.modules[module.name] = module
    
    def add_signal(self, signal: Signal):
        """Add a signal to the simulator."""
        self.signals[signal.name] = signal
    
    def set_input_signal(self, signal_name: str, value: SignalValue):
        """Set the value of an input signal."""
        if signal_name in self.signals:
            self.signals[signal_name].value = value
            self.signals[signal_name].last_change_time = self.current_time
            # Schedule all modules that use this signal
            for module_name in self.signals[signal_name].drivers:
                if module_name in self.modules:
                    self.event_queue.append((self.current_time, self.modules[module_name]))
    
    def step(self, time_step: float = 0.1):
        """Advance simulation by one time step."""
        self.current_time += time_step
        
        # Process events in order
        self.event_queue.sort(key=lambda x: x[0])
        
        changed_modules = set()
        
        # Process all events up to current time
        while self.event_queue and self.event_queue[0][0] <= self.current_time:
            event_time, module = self.event_queue.pop(0)
            
            # Skip if we've already processed this module recently
            if module.name in changed_modules:
                continue
                
            # Evaluate module
            if module.evaluate(self.current_time):
                changed_modules.add(module.name)
                
                # Schedule connected modules
                for output_signal in module.outputs.values():
                    for driver_name in output_signal.drivers:
                        if driver_name in self.modules and driver_name != module.name:
                            self.event_queue.append((self.current_time, self.modules[driver_name]))
    
    def run_until_stable(self, max_time: float = 100.0, time_step: float = 0.1):
        """Run simulation until circuit stabilizes or max_time is reached."""
        stable_time = 0.0
        last_signal_values = {}
        
        # Record initial signal values
        for signal_name, signal in self.signals.items():
            last_signal_values[signal_name] = signal.value
        
        iteration = 0
        while self.current_time < max_time and iteration < self.max_iterations:
            self.step(time_step)
            iteration += 1
            
            # Check if signals have changed
            signals_changed = False
            for signal_name, signal in self.signals.items():
                if signal_name in last_signal_values and last_signal_values[signal_name] != signal.value:
                    signals_changed = True
                    break
            
            if signals_changed:
                stable_time = 0.0
                # Update last signal values
                for signal_name, signal in self.signals.items():
                    last_signal_values[signal_name] = signal.value
            else:
                stable_time += time_step
                if stable_time >= self.convergence_threshold:
                    print(f"Circuit stabilized at time {self.current_time:.2f}")
                    return True
        
        print(f"Simulation ended at time {self.current_time:.2f} (max time reached or max iterations)")
        return False
    
    def print_circuit_state(self):
        """Print the current state of all signals."""
        print(f"\nCircuit State at time {self.current_time:.2f}:")
        print("-" * 40)
        for signal_name, signal in self.signals.items():
            value_str = {
                SignalValue.ZERO: "0",
                SignalValue.ONE: "1",
                SignalValue.UNKNOWN: "?",
                SignalValue.RISING: "↑",
                SignalValue.FALLING: "↓"
            }.get(signal.value, "?")
            print(f"{signal_name}: {value_str}")
        print("-" * 40)


def create_example_circuit():
    """Create an example asynchronous circuit for demonstration."""
    simulator = AssasynSimulator()
    
    # Create signals
    a = Signal("a")
    b = Signal("b")
    c = Signal("c")
    d = Signal("d")
    and_out = Signal("and_out")
    or_out = Signal("or_out")
    not_out = Signal("not_out")
    c_out = Signal("c_out")
    
    # Add signals to simulator
    for signal in [a, b, c, d, and_out, or_out, not_out, c_out]:
        simulator.add_signal(signal)
    
    # Create modules
    and_gate = AndGate("and_gate", delay=1.0)
    or_gate = OrGate("or_gate", delay=1.5)
    not_gate = NotGate("not_gate", delay=0.8)
    c_element = CElement("c_element", delay=1.2)
    
    # Connect signals to modules
    # AND gate: a, b -> and_out
    and_gate.add_input("a", a)
    and_gate.add_input("b", b)
    and_gate.add_output("out", and_out)
    
    # OR gate: c, d -> or_out
    or_gate.add_input("c", c)
    or_gate.add_input("d", d)
    or_gate.add_output("out", or_out)
    
    # NOT gate: and_out -> not_out
    not_gate.add_input("in", and_out)
    not_gate.add_output("out", not_out)
    
    # C-element: not_out, or_out -> c_out
    c_element.add_input("a", not_out)
    c_element.add_input("b", or_out)
    c_element.add_output("out", c_out)
    
    # Add modules to simulator
    for module in [and_gate, or_gate, not_gate, c_element]:
        simulator.add_module(module)
    
    return simulator


def main():
    """Main function to demonstrate the asynchronous circuit simulator."""
    print("=" * 50)
    print("Asynchronous Circuit Simulator (Assasyn)")
    print("=" * 50)
    
    # Create example circuit
    simulator = create_example_circuit()
    
    print("\nInitial circuit state:")
    simulator.print_circuit_state()
    
    # Test case 1: Set inputs and run simulation
    print("\nTest Case 1: Setting a=1, b=1, c=0, d=0")
    simulator.set_input_signal("a", SignalValue.ONE)
    simulator.set_input_signal("b", SignalValue.ONE)
    simulator.set_input_signal("c", SignalValue.ZERO)
    simulator.set_input_signal("d", SignalValue.ZERO)
    
    simulator.run_until_stable(max_time=20.0)
    simulator.print_circuit_state()
    
    # Test case 2: Change inputs
    print("\nTest Case 2: Changing a=0, b=1, c=1, d=0")
    simulator.set_input_signal("a", SignalValue.ZERO)
    simulator.set_input_signal("b", SignalValue.ONE)
    simulator.set_input_signal("c", SignalValue.ONE)
    simulator.set_input_signal("d", SignalValue.ZERO)
    
    simulator.run_until_stable(max_time=20.0)
    simulator.print_circuit_state()
    
    # Test case 3: More complex changes
    print("\nTest Case 3: Changing all inputs to 1")
    simulator.set_input_signal("a", SignalValue.ONE)
    simulator.set_input_signal("b", SignalValue.ONE)
    simulator.set_input_signal("c", SignalValue.ONE)
    simulator.set_input_signal("d", SignalValue.ONE)
    
    simulator.run_until_stable(max_time=20.0)
    simulator.print_circuit_state()
    
    print("\nSimulation completed!")


if __name__ == "__main__":
    main()