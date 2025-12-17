#!/usr/bin/env python3
"""
Assassyn Example Program
This example demonstrates the basic usage of Assassyn for hardware modeling.
It includes a counter module, a data processing module, and a driver module.
"""

from assassyn.frontend import *
from assassyn.backend import elaborate
from assassyn import utils


class Counter(Module):
    """A simple counter module that increments every cycle."""
    
    def __init__(self):
        super().__init__(ports={})
        
    @module.combinational
    def build(self):
        # Define a 32-bit counter register
        cnt = RegArray(UInt(32), 1)
        
        # Read current value
        current = cnt[0]
        
        # Calculate new value
        new_value = current + UInt(32)(1)
        
        # Log the current value
        log("Counter value: {}", current)
        
        # Update counter for next cycle
        (cnt & self)[0] <= new_value


class DataProcessor(Module):
    """A module that processes data based on counter value."""
    
    def __init__(self):
        super().__init__(ports={
            'data_in': Port(UInt(32)),
            'enable': Port(Bits(1))
        })
        
    @module.combinational
    def build(self):
        # Get input data and enable signal
        data_in, enable = self.pop_all_ports(True)
        
        # Define a register to store processed data
        processed_data = RegArray(UInt(32), 1)
        
        # Process data only when enabled
        with Condition(enable == Bits(1)(1)):
            # Double the input data
            result = data_in * UInt(32)(2)
            
            # Store the result
            (processed_data & self)[0] <= result
            
            # Log the processing
            log("Processing: {} -> {}", data_in, result)
        
        # Always output the current processed data
        log("Processed data available: {}", processed_data[0])


class Driver(Module):
    """Driver module that coordinates the system."""
    
    def __init__(self):
        super().__init__(ports={})
        
    @module.combinational
    def build(self, counter: Counter, processor: DataProcessor):
        # Define a cycle counter
        cycle_cnt = RegArray(UInt(32), 1)
        (cycle_cnt & self)[0] <= cycle_cnt[0] + UInt(32)(1)
        
        # Define test data
        test_data = RegArray(UInt(32), 1)
        
        # Generate test data based on cycle
        new_test_data = cycle_cnt[0] * UInt(32)(3)
        (test_data & self)[0] <= new_test_data
        
        # Enable processing every other cycle
        enable_signal = (cycle_cnt[0] & UInt(32)(1)) == UInt(32)(0)
        
        # Call the data processor with test data
        processor.async_called(
            data_in=test_data[0],
            enable=enable_signal.bitcast(Bits(1))
        )
        
        # Log driver activity
        log("Driver cycle: {}, test_data: {}, enable: {}", 
            cycle_cnt[0], test_data[0], enable_signal)


class FIFO(Module):
    """A simple FIFO implementation."""
    
    def __init__(self, width=32, depth=16):
        super().__init__(ports={
            'data_in': Port(Bits(width)),
            'write_en': Port(Bits(1)),
            'read_en': Port(Bits(1))
        })
        
        # FIFO state
        self.buffer = RegArray(Bits(width), depth)
        self.read_ptr = RegArray(UInt(log2(depth)), 1)
        self.write_ptr = RegArray(UInt(log2(depth)), 1)
        self.count = RegArray(UInt(log2(depth) + 1), 1)
        
    @module.combinational
    def build(self):
        data_in, write_en, read_en = self.pop_all_ports(True)
        
        # Write logic
        with Condition(write_en & ~self.is_full()):
            self.buffer[self.write_ptr[0]] <= data_in
            self.write_ptr[0] <= self.write_ptr[0] + UInt(log2(16))(1)
            self.count[0] <= self.count[0] + UInt(log2(16) + 1)(1)
            log("FIFO: Writing {} to address {}", data_in, self.write_ptr[0])
        
        # Read logic
        with Condition(read_en & ~self.is_empty()):
            output_data = self.buffer[self.read_ptr[0]]
            self.read_ptr[0] <= self.read_ptr[0] + UInt(log2(16))(1)
            self.count[0] <= self.count[0] - UInt(log2(16) + 1)(1)
            log("FIFO: Reading {} from address {}", output_data, self.read_ptr[0])
        
        # Status indicators
        log("FIFO Status: Count={}, Empty={}, Full={}", 
            self.count[0], self.is_empty(), self.is_full())
    
    def is_full(self):
        return self.count[0] == UInt(log2(16) + 1)(16)
    
    def is_empty(self):
        return self.count[0] == UInt(log2(16) + 1)(0)


def test_counter_system():
    """Test a simple counter system."""
    print("=" * 50)
    print("Testing Counter System")
    print("=" * 50)
    
    sys = SysBuilder('counter_system')
    with sys:
        counter = Counter()
        counter.build()
    
    simulator_path, _ = elaborate(sys, verilog=False)
    raw = utils.run_simulator(simulator_path)
    print(raw)


def test_processor_system():
    """Test a system with counter and data processor."""
    print("=" * 50)
    print("Testing Processor System")
    print("=" * 50)
    
    sys = SysBuilder('processor_system')
    with sys:
        counter = Counter()
        processor = DataProcessor()
        driver = Driver()
        
        counter.build()
        processor.build()
        driver.build(counter, processor)
    
    simulator_path, _ = elaborate(sys, verilog=False)
    raw = utils.run_simulator(simulator_path)
    print(raw)


def test_fifo_system():
    """Test a FIFO system."""
    print("=" * 50)
    print("Testing FIFO System")
    print("=" * 50)
    
    class FIFODriver(Module):
        def __init__(self):
            super().__init__(ports={})
            
        @module.combinational
        def build(self, fifo: FIFO):
            cnt = RegArray(UInt(32), 1)
            (cnt & self)[0] <= cnt[0] + UInt(32)(1)
            
            # Generate test data
            test_data = cnt[0].bitcast(Bits(32))
            
            # Write for first 10 cycles
            write_en = (cnt[0] < UInt(32)(10)).bitcast(Bits(1))
            
            # Read after 5 cycles
            read_en = (cnt[0] >= UInt(32)(5)).bitcast(Bits(1))
            
            # Call FIFO
            fifo.async_called(
                data_in=test_data,
                write_en=write_en,
                read_en=read_en
            )
    
    sys = SysBuilder('fifo_system')
    with sys:
        fifo = FIFO()
        driver = FIFODriver()
        
        fifo.build()
        driver.build(fifo)
    
    simulator_path, _ = elaborate(sys, verilog=False)
    raw = utils.run_simulator(simulator_path)
    print(raw)


def test_sram_system():
    """Test a system with SRAM."""
    print("=" * 50)
    print("Testing SRAM System")
    print("=" * 50)
    
    class SRAMUser(Module):
        def __init__(self):
            super().__init__(ports={'rdata': Port(Bits(32))})
            
        @module.combinational
        def build(self):
            rdata = self.pop_all_ports(False)
            log("SRAM read data: {}", rdata)
    
    class SRAMDriver(Module):
        def __init__(self):
            super().__init__(ports={})
            
        @module.combinational
        def build(self, sram, user: SRAMUser):
            cnt = RegArray(UInt(32), 1)
            (cnt & self)[0] <= cnt[0] + UInt(32)(1)
            
            # Use low bits as address
            addr = (cnt[0] & UInt(32)(15)).bitcast(Int(9))
            
            # Write for first 8 cycles
            we = (cnt[0] < UInt(32)(8)).bitcast(Bits(1))
            re = (cnt[0] >= UInt(32)(8)).bitcast(Bits(1))
            
            # Data to write
            wdata = (cnt[0] * UInt(32)(7)).bitcast(Bits(32))
            
            # Call SRAM
            sram.build(
                we=we,
                re=re,
                addr=addr,
                wdata=wdata,
                user=user
            )
            
            log("SRAM operation: addr={}, we={}, re={}, wdata={}", 
                addr, we, re, wdata)
    
    sys = SysBuilder('sram_system')
    with sys:
        sram = SRAM(width=32, depth=512, init_file=None)
        user = SRAMUser()
        driver = SRAMDriver()
        
        user.build()
        driver.build(sram, user)
        
        # Expose SRAM output
        sys.expose_on_top(sram.dout)
    
    simulator_path, _ = elaborate(sys, verilog=False)
    raw = utils.run_simulator(simulator_path)
    print(raw)


def main():
    """Run all example systems."""
    print("Assassyn Example Program")
    print("This program demonstrates various Assassyn concepts and modules.")
    print()
    
    # Test different systems
    test_counter_system()
    print()
    
    test_processor_system()
    print()
    
    test_fifo_system()
    print()
    
    test_sram_system()
    
    print("\nAll examples completed!")


if __name__ == "__main__":
    main()