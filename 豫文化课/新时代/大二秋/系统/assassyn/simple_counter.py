#!/usr/bin/env python3
"""
最简单的Assassyn程序 - 基本计数器
每周期递增并打印当前值
"""

from assassyn.frontend import *
from assassyn.backend import elaborate
from assassyn import utils

class SimpleCounter(Module):
    """一个简单的计数器模块，每周期递增"""
    
    def __init__(self):
        super().__init__(ports={})  # 无端口
        
    @module.combinational
    def build(self):
        # 定义一个32位计数器寄存器
        cnt = RegArray(UInt(32), 1)
        
        # 读取当前值
        current = cnt[0]
        
        # 计算新值
        new_value = current + UInt(32)(1)
        
        # 打印当前值
        log("计数器值: {}", current)
        
        # 更新计数器（下一周期生效）
        (cnt & self)[0] <= new_value

def test_simple_counter():
    """测试简单计数器系统"""
    print("=" * 40)
    print("测试简单计数器")
    print("=" * 40)
    
    # 构建系统
    sys = SysBuilder('simple_counter')
    with sys:
        counter = SimpleCounter()
        counter.build()
    
    # 生成仿真器并运行
    simulator_path, _ = elaborate(sys, verilog=False)
    raw = utils.run_simulator(simulator_path)
    print(raw)

if __name__ == "__main__":
    test_simple_counter()