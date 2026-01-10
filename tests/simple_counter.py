#!/usr/bin/env python3
"""
Simple Counter Demo
A minimal Assassyn program that increments a counter each cycle.
"""

from assassyn.frontend import *
from assassyn.backend import elaborate
from assassyn import utils

class SimpleCounter(Module):
    def __init__(self):
        super().__init__(ports={})
    
    @module.combinational
    def build(self):
        # 8-bit counter register
        cnt = RegArray(UInt(8), 1)
        current = cnt[0]
        new_value = current + UInt(8)(1)
        log('Counter = {}', current)
        # Schedule update for next cycle
        (cnt & self)[0] <= new_value

def main():
    print("=== Simple Counter Simulation ===")
    sys = SysBuilder('simple_counter')
    with sys:
        counter = SimpleCounter()
        counter.build()
    
    # Generate simulator (no Verilog)
    simulator_path, _ = elaborate(sys, verilog=False)
    raw = utils.run_simulator(simulator_path)
    print(raw)

if __name__ == '__main__':
    main()