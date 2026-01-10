#!/usr/bin/env python3
"""
将test.c的逻辑转换为RISC-V指令并在RV32I CPU中测试
"""

from assassyn.frontend import *
from assassyn.backend import elaborate
from assassyn import utils

# 导入现有的CPU实现
from rv32i_cpu import *

# ==================== 测试适配器 ===================
class TestAdapter(Module):
    """test.c程序的RISC-V适配器"""
    def __init__(self):
        super().__init__(ports={})
        
        # 创建CPU核心
        self.cpu = RV32ICPU()
        
        # 初始化内存
        self.init_test_program()
    
    def init_test_program(self):
        """初始化内存内容 - 将test.c的逻辑转换为RISC-V指令加载到指令寄存器"""
        # 获取指令内存寄存器数组
        imem = self.cpu.instruction_memory
        
        # 将test.c的逻辑转换为RISC-V指令：
        # int main() {
        #     int sum = 0, i = 0;
        #     while(i <= 100) {
        #         sum += i;
        #         i++;
        #     }
        #     return 0;
        # }
        
        test_program = [
            # 初始化：sum = 0, i = 0
            0x00000193,  # ADDI x3, x0, 0    # x3 = sum = 0
            0x00000213,  # ADDI x4, x0, 0    # x4 = i = 0
            
            # 循环开始标签：loop_start
            # 检查 i <= 100
            0x06400293,  # ADDI x5, x0, 100  # x5 = 100
            0x0042a2b3,  # SLT  x5, x4, x5   # x5 = (x4 < x5) ? 1 : 0
            
            # 如果 i > 100，跳转到循环结束
            0x00028463,  # BEQ  x5, x0, end  # if (x5 == 0) goto end
            
            # 循环体：
            # sum += i
            0x004182b3,  # ADD  x5, x3, x4   # x5 = sum + i
            0x00518193,  # ADDI x3, x5, 0    # sum = x5
            
            # i++
            0x00120213,  # ADDI x4, x4, 1    # i = i + 1
            
            # 跳回循环开始
            0xff9ff06f,  # J    loop_start   # goto loop_start
            
            # 循环结束标签：end
            # 返回0
            0x00000513,  # ADDI x10, x0, 0   # x10 = 0 (返回值)
            0x00100073   # EBREAK            # 停止执行
        ]
        
        # 修正跳转地址
        # 计算跳转偏移量
        loop_start_offset = -6  # 从当前指令(地址0x10)跳到地址0x8，偏移为-6条指令
        end_offset = 4          # 从当前指令(地址0xc)跳到地址0x1c，偏移为4条指令
        
        test_program[4] = 0x00428463 | ((end_offset & 0xFFF) << 20)  # BEQ x5, x0, end
        test_program[9] = 0x0000006f | ((loop_start_offset & 0xFFFFF) << 12)  # J loop_start
        
        # 直接加载测试程序到寄存器数组
        for i, instruction in enumerate(test_program):
            (imem[i] & self.cpu) <= UInt(32)(instruction)
        
        print(f"Loaded test program with {len(test_program)} RISC-V instructions into instruction memory registers")
        
        # 打印指令列表
        print("\nRISC-V指令列表:")
        for i, instruction in enumerate(test_program):
            print(f"0x{i:04x}: 0x{instruction:08x}")
    
    @module.combinational
    def build(self):
        # 构建CPU
        self.cpu.build()

def test_rv32i_with_test_c():
    """测试RV32I CPU运行test.c的逻辑"""
    sys = SysBuilder('rv32i_test_c')
    with sys:
        cpu_top = TestAdapter()
        cpu_top.build()
    
    # 生成模拟器
    simulator_path, _ = elaborate(sys, verilog=False)
    raw = utils.run_simulator(simulator_path)
    print(raw)
    
    # 分析结果
    print("\n=== 测试结果分析 ===")
    print("程序执行完成，应该计算了从0到100的整数和")
    print("预期结果: sum = 5050 (0x13BA)")
    print("请检查CPU日志中的寄存器状态")

if __name__ == "__main__":
    test_rv32i_with_test_c()