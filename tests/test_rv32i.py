#!/usr/bin/env python3
"""
RV32I CPU测试程序
包含简单的测试程序，验证CPU功能
"""

from assassyn.frontend import *
from assassyn.backend import elaborate
from assassyn import utils
from rv32i_cpu import Driver

# 测试程序：计算斐波那契数列
# 使用RISC-V指令序列
TEST_PROGRAM = [
    0x00000193,  # addi x1, x0, 3    # x1 = 3
    0x00000113,  # addi x2, x0, 4    # x2 = 4
    0x00000193,  # addi x3, x0, 3    # x3 = 3
    0x00000193,  # addi x4, x0, 3    # x4 = 3
    0x00000193,  # addi x5, x0, 3    # x5 = 3
    0x00000193,  # addi x6, x0, 3    # x6 = 3
    0x00000193,  # addi x7, x0, 3    # x7 = 3
    0x00000193,  # addi x8, x0, 3    # x8 = 3
    0x00000193,  # addi x9, x0, 3    # x9 = 3
    0x00000193,  # addi x10, x0, 3   # x10 = 3
    
    # 斐波那契计算循环
    0x000081b3,  # add x11, x1, x2   # x11 = x1 + x2
    0x00008233,  # add x12, x10, x3  # x12 = x10 + x3
    0x000083b3,  # add x13, x11, x12 # x13 = x11 + x12
    0x004083b3,  # sw x13, 0(x0), 0   # store x13 to memory[0]
    0x00008233,  # add x14, x10, x3  # x14 = x10 + x3
    0x004084b3,  # sw x14, 0(x0), 4   # store x14 to memory[4]
    0x000083b3,  # add x15, x11, x13 # x15 = x11 + x13
    0x004085b3,  # sw x15, 0(x0), 8   # store x15 to memory[8]
    0x000084b3,  # add x16, x14, x15 # x16 = x14 + x15
    0x004086b3,  # sw x16, 0(x0), 12  # store x16 to memory[12]
    0x000085b3,  # add x17, x15, x16 # x17 = x15 + x16
    0x004087b3,  # sw x17, 0(x0), 16  # store x17 to memory[16]
    0x000086b3,  # add x18, x16, x17 # x18 = x16 + x17
    0x004088b3,  # sw x18, 0(x0), 20  # store x18 to memory[20]
    0x000087b3,  # add x19, x17, x18 # x19 = x17 + x18
    0x004089b3,  # sw x19, 0(x0), 24  # store x19 to memory[24]
    0x000088b3,  # add x20, x18, x19 # x20 = x18 + x19
    0x00408ab3,  # sw x20, 0(x0), 28  # store x20 to memory[28]
    
    # 循环控制
    0x004084b3,  # add x21, x10, x14  # x21 = x10 + x14
    0x004085b3,  # add x22, x11, x21  # x22 = x11 + x21
    0xfe514ce3,  # beq x22, x23, loop_end  # if x22 == x23, jump to loop_end
    0x000086b3,  # addi x23, x0, -1  # x23 = -1 (loop counter)
    0xfe514ce3,  # beq x23, x0, loop_start # if x23 == 0, jump to loop_start
    0xff5ff06f,  # jal x0, loop_end      # jump and link to loop_end (exit)
]

class TestMemory(Module):
    """测试用的指令内存"""
    def __init__(self, program):
        super().__init__(ports={
            'addr': Port(UInt(32)),
            'data_out': Port(UInt(32))
        })
        
        # 将测试程序加载到内存
        self.memory = RegArray(UInt(32), len(program))
        for i, instr in enumerate(program):
            (self.memory & self)[i] <= UInt(32)(instr)
    
    @module.combinational
    def build(self):
        addr = self.addr.pop()
        word_addr = addr >> UInt(32)(2)
        instruction = self.memory[word_addr]
        self.data_out.push(instruction)
        
        log("IMEM: Addr={:08x}, Instruction={:08x}", addr, instruction)

class TestRV32ICPU(Module):
    """带测试内存的RV32I CPU"""
    def __init__(self):
        super().__init__(ports={})
        
        # 创建CPU核心
        self.cpu = RV32ICPU()
        
        # 替换为测试内存
        self.test_imem = TestMemory(TEST_PROGRAM)
        
        # 暴露寄存器文件用于验证
        sys.expose_on_top(self.cpu.reg_file.regs, kind='Output')
    
    @module.combinational
    def build(self):
        # 替换指令内存访问
        # 这里需要修改CPU的IF阶段以使用测试内存
        # 简化处理，直接调用测试内存
        current_pc = self.cpu.pc[0]
        self.test_imem.async_called(addr=current_pc)
        instruction = self.test_imem.data_out.peek()
        
        # 手动更新流水线寄存器（IF/ID）
        (self.cpu.pipeline_regs.if_id_pc & self)[0] <= current_pc
        (self.cpu.pipeline_regs.if_id_instruction & self)[0] <= instruction
        (self.cpu.pipeline_regs.if_id_valid & self)[0] <= UInt(1)(1)
        
        # 继续正常的ID阶段处理
        self.cpu.decode.async_called(
            instruction_in=instruction,
            valid_in=UInt(1)(1)
        )
        
        # 手动更新流水线寄存器（ID/EX）
        (self.cpu.pipeline_regs.id_ex_pc & self)[0] <= current_pc
        (self.cpu.pipeline_regs.id_ex_instruction & self)[0] <= instruction
        (self.cpu.pipeline_regs.id_ex_valid & self)[0] <= UInt(1)(1)
        (self.cpu.pipeline_regs.id_ex_rs1_data & self)[0] <= self.cpu.reg_file.regs[instruction[19:15]]
        (self.cpu.pipeline_regs.id_ex_rs2_data & self)[0] <= self.cpu.reg_file.regs[instruction[24:20]]
        (self.cpu.pipeline_regs.id_ex_immediate & self)[0] <= self.cpu.decode.immediate.peek()
        # 以下信号已经包含在control_in中，无需单独传递
        # (self.cpu.pipeline_regs.id_ex_rd_addr & self)[0] <= self.cpu.decode.rd_addr.peek()    # control_in[28:24]
        
        # 继续正常的EX阶段处理
        self.cpu.execute.async_called(
            pc_in=current_pc,
            rs1_data_in=self.cpu.pipeline_regs.id_ex_rs1_data[0],
            rs2_data_in=self.cpu.pipeline_regs.id_ex_rs2_data[0],
            immediate_in=self.cpu.pipeline_regs.id_ex_immediate[0],
            control_in=self.cpu.decode.control_out.peek(),
            valid_in=UInt(1)(1)
        )
        
        # 手动更新流水线寄存器（EX/MEM）
        (self.cpu.pipeline_regs.ex_mem_pc & self)[0] <= current_pc
        (self.cpu.pipeline_regs.ex_mem_instruction & self)[0] <= instruction
        (self.cpu.pipeline_regs.ex_mem_valid & self)[0] <= UInt(1)(1)
        (self.cpu.pipeline_regs.ex_mem_result & self)[0] <= self.cpu.execute.result_out.peek()
        (self.cpu.pipeline_regs.ex_mem_addr & self)[0] <= self.cpu.execute.addr_out.peek()
        (self.cpu.pipeline_regs.ex_mem_data & self)[0] <= self.cpu.execute.data_out.peek()
        # 以下信号已经包含在control_in中，无需单独传递
        # (self.cpu.pipeline_regs.ex_mem_rd_addr & self)[0] <= self.cpu.decode.rd_addr.peek()       # control_in[28:24]
        # (self.cpu.pipeline_regs.ex_mem_we & self)[0] <= self.cpu.decode.control_out.peek()[6]     # control_in[6]
        # (self.cpu.pipeline_regs.ex_mem_mem_op & self)[0] <= self.cpu.decode.control_out.peek()[5] | self.cpu.decode.control_out.peek()[6]  # control_in[5] | control_in[6]
        
        # 继续正常的MEM阶段处理
        self.cpu.memory.async_called(
            pc_in=current_pc,
            addr_in=self.cpu.pipeline_regs.ex_mem_addr[0],
            data_in=self.cpu.pipeline_regs.ex_mem_data[0],
            control_in=instruction,  # 使用指令作为控制信号
            valid_in=UInt(1)(1)
        )
        
        # 手动更新流水线寄存器（MEM/WB）
        (self.cpu.pipeline_regs.mem_wb_pc & self)[0] <= current_pc
        (self.cpu.pipeline_regs.mem_wb_instruction & self)[0] <= instruction
        (self.cpu.pipeline_regs.mem_wb_valid & self)[0] <= UInt(1)(1)
        (self.cpu.pipeline_regs.mem_wb_result & self)[0] <= self.cpu.memory.data_out.peek()
        # 以下信号已经包含在control_in中，无需单独传递
        # (self.cpu.pipeline_regs.mem_wb_rd_addr & self)[0] <= self.cpu.decode.control_out.peek()[28:24]  # control_in[28:24]
        # (self.cpu.pipeline_regs.mem_wb_we & self)[0] <= self.cpu.decode.control_out.peek()[6]           # control_in[7]
        
        # 继续正常的WB阶段处理
        self.cpu.writeback.async_called(
            pc_in=current_pc,
            mem_data_in=self.cpu.pipeline_regs.mem_wb_result[0],
            ex_result_in=self.cpu.pipeline_regs.ex_mem_result[0],
            control_in=instruction,
            valid_in=UInt(1)(1)
        )
        
        # 写回寄存器文件
        self.cpu.reg_file.async_called(
            rs1_addr=UInt(5)(0),
            rs2_addr=UInt(5)(0),
            rd_addr=self.cpu.writeback.wb_rd_out.peek(),
            rd_data=self.cpu.writeback.wb_data_out.peek(),
            we=self.cpu.writeback.wb_we_out.peek()
        )
        
        # 更新PC（简化处理）
        # 分支成功时使用分支目标
        with Condition(self.cpu.execute.branch_taken_out.peek()):
            next_pc = self.cpu.execute.branch_target_out.peek()
        else:
            # 默认PC+4
            next_pc = current_pc + UInt(32)(4)
        
        (self.cpu.pc & self)[0] <= next_pc

def test_rv32i_cpu():
    """测试RV32I CPU"""
    sys = SysBuilder('test_rv32i_cpu')
    with sys:
        cpu_top = TestRV32ICPU()
        cpu_top.build()
    
    # 生成模拟器
    simulator_path, _ = elaborate(sys, verilog=False)
    raw = utils.run_simulator(simulator_path)
    print(raw)

if __name__ == "__main__":
    test_rv32i_cpu()