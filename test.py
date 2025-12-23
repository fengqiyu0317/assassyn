#!/usr/bin/env python3
"""
Simple Assassyn Program
A minimal example that demonstrates basic functionality.
"""

from assassyn.frontend import *
from assassyn.backend import elaborate
from assassyn import utils

class Driver(Module):
    def __init__(self):
        super().__init__(ports={})
    
    @module.combinational
    def build(self):
        # Create a simple counter
        counter = RegArray(Record(value=UInt(8)), 1)
        counter[0].value = counter[0].value + UInt(8)(1)
        
        # Log the current value
        log('Current value: {}', counter[0].value)

def main():
    print("=== Simple Assassyn Program ===")
    
    # Create system builder
    sys = SysBuilder('simple_program')
    with sys:
        module = Driver()
        module.build()
    
    # Generate and run simulator
    simulator_path, _ = elaborate(sys, verilog=False)
    raw = utils.run_simulator(simulator_path)
    print(raw)

if __name__ == '__main__':
    main()