#!/usr/bin/env python3
\"\"\"
Run the add_while benchmark on the RV32I CPU
\"\"\"

from assassyn.backend import elaborate
from assassyn import utils
from assassyn.frontend import SysBuilder
from rv32i_cpu import Driver

class AddWhileDriver(Driver):
    def init_memory(self, program_file=None):
        # Override to load our specific file
        print("Loading add_while benchmark...")
        super().init_memory("benchmarks/add_while/program.txt")

def run():
    sys = SysBuilder('rv32i_add_while')
    with sys:
        cpu_top = AddWhileDriver()
        cpu_top.build()
    
    # Generate and run simulator
    simulator_path, _ = elaborate(sys, verilog=False)
    print(f"Simulator generated at: {simulator_path}")
    raw = utils.run_simulator(simulator_path)
    print(raw)

if __name__ == "__main__":
    run()
