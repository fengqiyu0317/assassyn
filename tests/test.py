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
        cnt = RegArray(UInt(8), 2, initializer=[0, 0])
        cnt[0] = Int(2)(-1).sext(Int(8)).bitcast(UInt(8))
        # cnt = RegArray(UInt(8), 2, initializer=[cnt[0] + UInt(8)(1), cnt[1]])
        log('Current value: {}', cnt[0])
        return cnt[0]

class DownstreamModule(Downstream):
    def __init__(self):
        super().__init__()

    @downstream.combinational
    def build(self, input_signal, temp):
        temp[0] = input_signal
        log('Received value in DownstreamModule: {}', input_signal)
        return None

def main():
    print("=== Simple Assassyn Program ===")
    
    # Create system builder
    sys = SysBuilder('simple_program')
    with sys:
        module = Driver()
        cnt = module.build()
        temp = RegArray(UInt(8), 1)
        another = DownstreamModule()
        another.build(cnt, temp)
    
    # Generate and run simulator
    simulator_path, _ = elaborate(sys, verilog=False)
    raw = utils.run_simulator(simulator_path)
    print(raw)

if __name__ == '__main__':
    main()