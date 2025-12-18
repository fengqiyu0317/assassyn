#!/usr/bin/env python3
"""
测试语法速查表中的示例代码
Test examples from the quick reference guide
"""

from assassyn.frontend import *
from assassyn.backend import elaborate
from assassyn import utils


def test_example_1_simple_counter():
    """测试示例 1: 简单计数器"""
    print("=" * 50)
    print("测试示例 1: 简单计数器")
    print("=" * 50)
    
    class SimpleCounter(Module):
        def __init__(self):
            super().__init__(ports={})
        
        @module.combinational
        def build(self):
            # 定义计数器
            cnt = RegArray(UInt(32), 1)
            
            # 计算新值
            new_cnt = cnt[0] + UInt(32)(1)
            
            # 更新计数器
            (cnt & self)[0] <= new_cnt
            
            # 打印当前值
            log("计数器: {}", cnt[0])

    sys = SysBuilder('counter')
    with sys:
        counter = SimpleCounter()
        counter.build()
    
    simulator_path, _ = elaborate(sys, verilog=False)
    raw = utils.run_simulator(simulator_path)
    print(raw)
    print("✅ 示例 1 测试通过\n")


def test_example_2_conditional_counter():
    """测试示例 2: 带条件的计数器"""
    print("=" * 50)
    print("测试示例 2: 带条件的计数器")
    print("=" * 50)
    
    class ConditionalCounter(Module):
        def __init__(self):
            super().__init__(ports={})
        
        @module.combinational
        def build(self):
            # 定义计数器和标志
            cnt = RegArray(UInt(32), 1)
            done = RegArray(Bits(1), 1)
            
            # 只在未完成时计数
            with Condition(done[0] == Bits(1)(0)):
                new_cnt = cnt[0] + UInt(32)(1)
                (cnt & self)[0] <= new_cnt
                
                # 达到100时设置完成标志
                with Condition(new_cnt >= UInt(32)(100)):
                    (done & self)[0] <= Bits(1)(1)
                    log("计数完成！")
                
                log("计数中: {}", cnt[0])

    sys = SysBuilder('conditional')
    with sys:
        counter = ConditionalCounter()
        counter.build()
    
    simulator_path, _ = elaborate(sys, verilog=False)
    raw = utils.run_simulator(simulator_path)
    print(raw)
    print("✅ 示例 2 测试通过\n")


def test_example_3_communication():
    """测试示例 3: 模块间通信"""
    print("=" * 50)
    print("测试示例 3: 模块间通信")
    print("=" * 50)
    
    class DataProcessor(Module):
        """数据处理模块"""
        def __init__(self):
            super().__init__(ports={
                'data': Port(UInt(32))
            })
        
        @module.combinational
        def build(self):
            data = self.pop_all_ports(True)
            
            # 数据翻倍
            result = data * UInt(32)(2)
            log("处理数据: {} -> {}", data, result)

    class Driver(Module):
        """驱动模块"""
        def __init__(self):
            super().__init__(ports={})
        
        @module.combinational
        def build(self, processor: DataProcessor):
            # 定义计数器
            cnt = RegArray(UInt(32), 1)
            (cnt & self)[0] <= cnt[0] + UInt(32)(1)
            
            # 每个周期发送数据给处理器
            processor.async_called(data=cnt[0])
            log("发送数据: {}", cnt[0])

    sys = SysBuilder('communication')
    with sys:
        processor = DataProcessor()
        driver = Driver()
        
        processor.build()
        driver.build(processor)
    
    simulator_path, _ = elaborate(sys, verilog=False)
    raw = utils.run_simulator(simulator_path)
    print(raw)
    print("✅ 示例 3 测试通过\n")


def test_example_4_sram():
    """测试示例 4: 使用 SRAM"""
    print("=" * 50)
    print("测试示例 4: 使用 SRAM")
    print("=" * 50)
    
    class SRAMReader(Module):
        """SRAM 读取模块"""
        def __init__(self):
            super().__init__(ports={
                'rdata': Port(Bits(32))
            })
        
        @module.combinational
        def build(self):
            rdata = self.pop_all_ports(False)
            log("读取数据: {}", rdata)

    class SRAMDriver(Module):
        """SRAM 驱动模块"""
        def __init__(self):
            super().__init__(ports={})
        
        @module.combinational
        def build(self, sram, reader: SRAMReader):
            cnt = RegArray(UInt(32), 1)
            (cnt & self)[0] <= cnt[0] + UInt(32)(1)
            
            # 地址
            addr = (cnt[0] & UInt(32)(7)).bitcast(Int(9))
            
            # 前8个周期写入，后面读取
            we = (cnt[0] < UInt(32)(8)).bitcast(Bits(1))
            re = (cnt[0] >= UInt(32)(8)).bitcast(Bits(1))
            
            # 写入数据
            wdata = (cnt[0] * UInt(32)(10)).bitcast(Bits(32))
            
            # 调用 SRAM
            sram.build(we=we, re=re, addr=addr, wdata=wdata, user=reader)
            
            log("SRAM 操作: addr={}, we={}, re={}", addr, we, re)

    sys = SysBuilder('sram_test')
    with sys:
        sram = SRAM(width=32, depth=16, init_file=None)
        reader = SRAMReader()
        driver = SRAMDriver()
        
        reader.build()
        driver.build(sram, reader)
        
        sys.expose_on_top(sram.dout)
    
    simulator_path, _ = elaborate(sys, verilog=False)
    raw = utils.run_simulator(simulator_path)
    print(raw)
    print("✅ 示例 4 测试通过\n")


def main():
    """运行所有测试"""
    print("\n" + "=" * 50)
    print("开始测试语法速查表中的所有示例")
    print("=" * 50 + "\n")
    
    try:
        test_example_1_simple_counter()
        test_example_2_conditional_counter()
        test_example_3_communication()
        test_example_4_sram()
        
        print("=" * 50)
        print("✅ 所有测试通过！")
        print("=" * 50)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
