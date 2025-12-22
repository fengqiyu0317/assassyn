#!/usr/bin/env python3
"""
五级流水线RV32I CPU实现
使用Assassyn语言实现完整的RISC-V 32位基础指令集处理器
"""

from assassyn.frontend import *
from assassyn.backend import elaborate
from assassyn import utils
from assassyn.ir.memory.sram import SRAM
from assassyn.ir.module import downstream, Downstream

# ==================== 常量定义 ===================
XLEN = 32  # RISC-V XLEN
REG_COUNT = 32  # 通用寄存器数量


FETCH_SIGNALS = Record(
    instruction=UInt(XLEN),
    zero=UInt(1)
)

DECODE_SIGNALS = Record(
    control=UInt(32),
    rs1=UInt(XLEN),
    rs2=UInt(XLEN),
    immediate=UInt(XLEN)
)

EXECUTE_SIGNALS = Record(
    pc_change=UInt(1),
    target_pc=UInt(XLEN)
)

PIPELINE_REGS = Record(
    # IF/ID阶段寄存器
    if_id_pc=UInt(XLEN),
    if_id_instruction=UInt(XLEN),
    if_id_valid=UInt(1),
    
    # ID/EX阶段寄存器
    id_ex_pc=UInt(XLEN),
    id_ex_control=UInt(32),       # 控制信号
    id_ex_valid=UInt(1),
    id_ex_rs1_idx=UInt(5),        # rs1寄存器索引
    id_ex_rs2_idx=UInt(5),        # rs2寄存器索引
    id_ex_immediate=UInt(XLEN),
    
    # EX/MEM阶段寄存器
    ex_mem_pc=UInt(XLEN),
    ex_mem_control=UInt(32),        # 控制信号
    ex_mem_valid=UInt(1),
    ex_mem_result=UInt(XLEN),
    ex_mem_data=UInt(XLEN),
    
    # MEM/WB阶段寄存器
    mem_wb_control=UInt(32),        # 控制信号
    mem_wb_valid=UInt(1),
    mem_wb_mem_data=UInt(XLEN),     # 内存读取的数据
    mem_wb_ex_result=UInt(XLEN)     # EX阶段的结果
)

# ==================== 寄存器文件 ===================
# 32个通用寄存器，x0硬线为0
# 使用RegArray定义寄存器数组，而不是模块
    

# ==================== IF阶段：指令获取 ===================
class FetchStage(Module):
    """指令获取阶段(IF)"""
    def __init__(self):
        super().__init__(ports={
        })
    
    @module.combinational
    def build(self, pc, stall, pipeline_regs, instruction_memory, decode_stage):
        instruction = UInt(XLEN)(0)
        with Condition(~stall[0]):
            current_pc = pc[0]
            word_addr = current_pc >> UInt(XLEN)(2)
            instruction = instruction_memory[word_addr]
            
            pipeline_regs[0].if_id_pc = current_pc
            
            log("IF: PC={:08x}, Instruction={:08x}", current_pc, instruction)
        
        decode_stage.async_called(
            instruction_in=pipeline_regs[0].if_id_instruction,
            if_id_pc_in=pipeline_regs[0].if_id_pc
        )

        fetch_signals = FETCH_SIGNALS.bundle(
            instruction=instruction,
            zero=UInt(1)(0)
        )
        return fetch_signals

# ==================== ID阶段：指令解码 ===================
class DecodeStage(Module):
    """指令解码阶段(ID)"""
    def __init__(self):
        super().__init__(ports={
            'instruction_in': Port(UInt(XLEN)),  # 输入指令
            'if_id_pc_in': Port(UInt(XLEN)),  # IF/ID PC输入
        })
    
    @module.combinational
    def build(self, pipeline_regs, reg_file, execute_stage):
        instruction, if_id_pc_in = self.pop_all_ports(True)

        control_signals = UInt(32)(0)
        rs1 = UInt(XLEN)(0)
        rs2 = UInt(XLEN)(0)
        immediate = UInt(XLEN)(0)
        
        # 如果指令无效，直接返回，不更新ID/EX寄存器
        with Condition(pipeline_regs[0].if_id_valid):
            # 解析指令字段
            opcode = instruction[6:0]          # bits 6:0
            rd = instruction[11:7]             # bits 11:7
            func3 = instruction[14:12]          # bits 14:12
            rs1 = instruction[19:15]           # bits 19:15
            rs2 = instruction[24:20]           # bits 24:20
            funct7 = instruction[31:25]         # bits 31:25

            # 提取立即数
            immediate_i = instruction[31:20].sext(Int(32))     # I型立即数
            immediate_s = concat(instruction[31:25], instruction[11:7]).sext(Int(32))  # S型立即数
            immediate_b = concat(instruction[31:31], instruction[7:7], instruction[30:25], instruction[11:8], UInt(1)(0)).sext(Int(32))  # B型立即数
            immediate_u = (instruction[31:12] << UInt(XLEN)(12)).sext(Int(32))  # U型立即数
            immediate_j = concat(instruction[31:31], instruction[19:12], instruction[20:20], instruction[30:21], UInt(1)(0)).sext(Int(32))  # J型立即数
            
            # 控制信号解码
            alu_op = UInt(5)(0)
            mem_read = UInt(1)(0)
            mem_write = UInt(1)(0)
            reg_write = UInt(1)(0)
            mem_to_reg = UInt(1)(0)
            alu_src = UInt(2)(0)  # 00:寄存器, 01:立即数, 10:PC
            branch_op = UInt(3)(0)
            jump_op = UInt(1)(0)  # 跳转指令标志
            immediate = UInt(XLEN)(0)  # 初始化立即数
            
            # 根据opcode设置控制信号
            with Condition(opcode == UInt(7)(0b0110011)):  # R型指令
                with Condition(funct7[5:5] == UInt(1)(1)):  # SUB or SRA
                    with Condition(func3 == UInt(3)(0b000)):  # SUB
                        alu_op = UInt(5)(0b00001)
                    with Condition(func3 == UInt(3)(0b101)):  # SRA
                        alu_op = UInt(5)(0b00110)
                # ADD, AND, OR, XOR, SLT, SLTU, SLL, SRL
                with Condition(funct7[5:5] == UInt(1)(0)):  # funct7[5] == 0
                    with Condition(func3 == UInt(3)(0b000)):  # ADD
                        alu_op = UInt(5)(0b00000)
                    with Condition(func3 == UInt(3)(0b111)):  # AND
                        alu_op = UInt(5)(0b01001)
                    with Condition(func3 == UInt(3)(0b110)):  # OR
                        alu_op = UInt(5)(0b01000)
                    with Condition(func3 == UInt(3)(0b100)):  # XOR
                        alu_op = UInt(5)(0b00100)
                    with Condition(func3 == UInt(3)(0b010)):  # SLT
                        alu_op = UInt(5)(0b00011)
                    with Condition(func3 == UInt(3)(0b011)):  # SLTU
                        alu_op = UInt(5)(0b00111)
                    with Condition(func3 == UInt(3)(0b001)):  # SLL
                        alu_op = UInt(5)(0b00010)
                    with Condition(func3 == UInt(3)(0b101)):  # SRL
                        alu_op = UInt(5)(0b00101)
                # 其他操作...
                reg_write = UInt(1)(1) & (rd != UInt(5)(0))  # x0寄存器不会写入
                alu_src = UInt(2)(0)
                
            with Condition(opcode == UInt(7)(0b0010011)):  # I型指令
                with Condition(func3 == UInt(3)(0b000)):  # ADDI
                    alu_op = UInt(5)(0b00000)
                with Condition(func3 == UInt(3)(0b111)):  # ANDI
                    alu_op = UInt(5)(0b01001)
                with Condition(func3 == UInt(3)(0b110)):  # ORI
                    alu_op = UInt(5)(0b01000)
                with Condition(func3 == UInt(3)(0b100)):  # XORI
                    alu_op = UInt(5)(0b00100)
                with Condition(func3 == UInt(3)(0b010)):  # SLTI
                    alu_op = UInt(5)(0b00011)
                with Condition(func3 == UInt(3)(0b011)):  # SLTIU
                    alu_op = UInt(5)(0b00111)
                with Condition(func3 == UInt(3)(0b001)):  # SLLI
                    alu_op = UInt(5)(0b00010)
                with Condition(func3 == UInt(3)(0b101)):  # SRLI or SRAI
                    with Condition(funct7[5:5] == UInt(1)(1)):  # SRAI
                        alu_op = UInt(5)(0b00110)
                    with Condition(funct7[5:5] == UInt(1)(0)):  # SRLI
                        alu_op = UInt(5)(0b00101)
                # 其他操作...
                reg_write = UInt(1)(1) & (rd != UInt(5)(0))  # x0寄存器不会写入
                alu_src = UInt(2)(1)
                immediate = immediate_i
                
            with Condition(opcode == UInt(7)(0b0000011)):
                # LW加载指令
                alu_op = UInt(5)(0b00000)  # ADD用于地址计算
                mem_read = UInt(1)(1)
                reg_write = UInt(1)(1) & (rd != UInt(5)(0))  # x0寄存器不会写入
                mem_to_reg = UInt(1)(1)
                alu_src = UInt(2)(1)
                immediate = immediate_i
                
            store_type_bits = UInt(2)(0)
            with Condition(opcode == UInt(7)(0b0100011)):  # 存储指令
                with Condition(func3 == UInt(3)(0b010)):  # SW (Store Word)
                    alu_op = UInt(5)(0b00000)  # ADD用于地址计算
                    mem_write = UInt(1)(1)     # 存储使能
                    alu_src = UInt(2)(1)
                    immediate = immediate_s
                    store_type_bits = UInt(2)(0b10)
                with Condition(func3 == UInt(3)(0b000)):  # SB (Store Byte)
                    alu_op = UInt(5)(0b00000)
                    mem_write = UInt(1)(1)     # 存储使能
                    alu_src = UInt(2)(1)
                    immediate = immediate_s
                    store_type_bits = UInt(2)(0b00)
                with Condition(func3 == UInt(3)(0b001)):  # SH (Store Halfword)
                    alu_op = UInt(5)(0b00000)
                    mem_write = UInt(1)(1)     # 存储使能
                    alu_src = UInt(2)(1)
                    immediate = immediate_s
                    store_type_bits = UInt(2)(0b01)

            with Condition(opcode == UInt(7)(0b1100011)):  # 分支指令
                immediate = immediate_b
                with Condition(func3 == UInt(3)(0b000)):  # BEQ
                    branch_op = UInt(3)(0b001)  # 修改为非0值，确保被识别为分支指令
                with Condition(func3 == UInt(3)(0b001)):  # BNE
                    branch_op = UInt(3)(0b010)
                with Condition(func3 == UInt(3)(0b100)):  # BLT
                    branch_op = UInt(3)(0b011)
                with Condition(func3 == UInt(3)(0b101)):  # BGE
                    branch_op = UInt(3)(0b100)
                with Condition(func3 == UInt(3)(0b110)):  # BLTU
                    branch_op = UInt(3)(0b101)
                with Condition(func3 == UInt(3)(0b111)):  # BGEU
                    branch_op = UInt(3)(0b110)
                
            
            with Condition(opcode == UInt(7)(0b0110111)):  # LUI
                reg_write = UInt(1)(1) & (rd != UInt(5)(0))  # x0寄存器不会写入
                alu_src = UInt(2)(1)
                immediate = immediate_u
            
            with Condition(opcode == UInt(7)(0b0010111)):  # AUIPC
                reg_write = UInt(1)(1) & (rd != UInt(5)(0))  # x0寄存器不会写入
                alu_src = UInt(2)(2)
                immediate = immediate_u
            
            with Condition(opcode == UInt(7)(0b1101111)):  # JAL
                reg_write = UInt(1)(1) & (rd != UInt(5)(0))  # x0寄存器不会写入
                alu_src = UInt(2)(1)  # 使用立即数作为ALU输入
                immediate = immediate_j
                jump_op = UInt(1)(1)  # 设置跳转指令标志
                # JAL指令需要特殊处理，在EX阶段会计算返回地址(PC+4)
            
            control_signals = concat(
                alu_op,           # [4:0]   ALU操作码
                mem_read,         # [5]     内存读
                mem_write,        # [6]     内存写
                reg_write,        # [7]     寄存器写
                mem_to_reg,       # [8]     内存到寄存器
                UInt(1)(0),       # [9]     保留位
                alu_src,          # [10:9]  ALU输入选择
                UInt(6)(0),       # [16:11] 保留位
                branch_op,        # [19:17] 分支操作类型
                jump_op,          # [20]    跳转指令标志
                store_type_bits,  # [23:22] 存储类型: 00=SB, 01=SH, 10=SW
                UInt(1)(0),       # [21]    保留位
                rd,               # [29:25] rd地址
                immediate[11:0]   # [31:30] 立即数低12位
            )
            
            pipeline_regs[0].id_ex_pc = if_id_pc_in
            
            log("ID: PC={}, Opcode={:07x}, RD={}, RS1={}, RS2={}",
                if_id_pc_in, opcode, rd, rs1, rs2)

        execute_stage.async_called(
            pc_in=pipeline_regs[0].id_ex_pc,
            rs1_idx_in=pipeline_regs[0].id_ex_rs1_idx,
            rs2_idx_in=pipeline_regs[0].id_ex_rs2_idx,
            immediate_in=pipeline_regs[0].id_ex_immediate,
            control_in=pipeline_regs[0].id_ex_control,    # 控制信号
        )

        decode_signals = DECODE_SIGNALS.bundle(
            control=control_signals,
            rs1=rs1,
            rs2=rs2,
            immediate=immediate
        )
        return decode_signals

# ==================== EX阶段：执行 ===================
class ExecuteStage(Module):
    """执行阶段(EX)"""
    def __init__(self):
        super().__init__(ports={
            'pc_in': Port(UInt(XLEN)),          # 输入PC
            'rs1_idx_in': Port(UInt(5)),       # 输入rs1索引
            'rs2_idx_in': Port(UInt(5)),       # 输入rs2索引
            'immediate_in': Port(UInt(XLEN)),   # 输入立即数
            'control_in': Port(UInt(32)),     # 输入控制信号
        })
    
    def alu_unit(self, op: Value, a: Value, b: Value):
        
        # 默认结果
        result = UInt(XLEN)(0)
        zero = UInt(1)(0)
        
        # 根据操作码执行不同操作
        with Condition(op == UInt(5)(0b00000)):  # ADD
            result = a + b
        
        with Condition(op == UInt(5)(0b00001)):  # SUB
            result = a - b
        
        with Condition(op == UInt(5)(0b00010)):  # SLL
            result = a << (b & UInt(XLEN)(0x1F))
        
        with Condition(op == UInt(5)(0b00011)):  # SLT
            # 有符号比较：如果a < b（有符号），则结果为1
            a_signed = a.bitcast(Int(XLEN))
            b_signed = b.bitcast(Int(XLEN))
            result = UInt(XLEN)(0)
            with Condition(a_signed < b_signed):
                result = UInt(XLEN)(1)
        
        with Condition(op == UInt(5)(0b00100)):  # XOR
            result = a ^ b
        
        with Condition(op == UInt(5)(0b00101)):  # SRL
            # 逻辑右移：高位补0
            shift_amount = b & UInt(XLEN)(0x1F)
            result = a >> shift_amount
        
        with Condition(op == UInt(5)(0b00110)):  # SRA
            # 算术右移：保持符号位
            shift_amount = b & UInt(XLEN)(0x1F)
            a_signed = a.bitcast(Int(XLEN))
            result = (a_signed >> shift_amount).bitcast(UInt(XLEN))
        
        with Condition(op == UInt(5)(0b00111)):  # SLTU
            # 无符号比较：如果a < b（无符号），则结果为1
            result = UInt(XLEN)(0)
            with Condition(a < b):
                result = UInt(XLEN)(1)
        
        with Condition(op == UInt(5)(0b01000)):  # OR
            result = a | b
        
        with Condition(op == UInt(5)(0b01001)):  # AND
            result = a & b
        
        log("ALU: OP={:05b}, A={:08x}, B={:08x}, Result={:08x}",
            op, a, b, result)
        
        return result

    def branch_unit(self, op: Value, a: Value, b: Value):
        
        taken = UInt(1)(0)
        
        # 执行分支比较
        with Condition(op == UInt(3)(0b001)):  # BEQ (修改后的值)
            with Condition(a == b):
                taken = UInt(1)(1)
        
        with Condition(op == UInt(3)(0b010)):  # BNE (修改后的值)
            with Condition(a != b):
                taken = UInt(1)(1)
        
        with Condition(op == UInt(3)(0b011)):  # BLT (修改后的值)
            # 有符号比较：如果a < b（有符号），则分支成功
            a_signed = a.bitcast(Int(XLEN))
            b_signed = b.bitcast(Int(XLEN))
            with Condition(a_signed < b_signed):
                taken = UInt(1)(1)
        
        with Condition(op == UInt(3)(0b100)):  # BGE (修改后的值)
            # 有符号比较：如果a >= b（有符号），则分支成功
            a_signed = a.bitcast(Int(XLEN))
            b_signed = b.bitcast(Int(XLEN))
            with Condition(a_signed >= b_signed):
                taken = UInt(1)(1)
        
        with Condition(op == UInt(3)(0b101)):  # BLTU (修改后的值)
            # 无符号比较：如果a < b（无符号），则分支成功
            with Condition(a < b):
                taken = UInt(1)(1)
        
        with Condition(op == UInt(3)(0b110)):  # BGEU (修改后的值)
            # 无符号比较：如果a >= b（无符号），则分支成功
            with Condition(a >= b):
                taken = UInt(1)(1)
        
        log("BRANCH: OP={:03b}, A={:08x}, B={:08x}, Taken={}",
            op, a, b, taken)
        
        return taken

    @module.combinational
    def build(self, pipeline_regs, reg_file, memory_stage):
        pc_in, rs1_idx, rs2_idx, immediate_in, control_in = self.pop_all_ports(True)
        
        # 直接从寄存器文件读取rs1和rs2的值
        rs1_data = reg_file[rs1_idx]
        rs2_data = reg_file[rs2_idx]
        
        # 初始化PC变化控制信号
        pc_change = UInt(1)(0)
        target_pc = pc_in + UInt(XLEN)(4)  # 默认目标PC是PC+4

        with Condition(pipeline_regs[0].id_ex_valid):
            # 解析控制信号
            alu_op = control_in[4:0]
            mem_read = control_in[5:5]
            mem_write = control_in[6:6]
            reg_write = control_in[7:7]
            mem_to_reg = control_in[8:8]
            alu_src = control_in[10:9]
            branch_op = control_in[19:17]  # 修正：branch_op在[19:17]位
            jump_op = control_in[20:20]  # 跳转指令标志
            rd_addr = control_in[29:25]  # rd地址
            immediate = control_in[31:22]  # 立即数
            
            # ALU输入B选择
            alu_b = immediate_in
            with Condition(alu_src == UInt(2)(0)):  # 寄存器
                alu_b = rs2_data
            
            # 根据指令类型决定执行ALU操作还是分支操作
            alu_result = UInt(XLEN)(0)
            
            # 判断是否为分支指令 (branch_op != 0)
            is_branch = (branch_op != UInt(3)(0b000))
            
            # 对于AUIPC指令，ALU输入A应该是PC而不是rs1_data
            alu_a = rs1_data
            with Condition(alu_src == UInt(2)(2)):  # AUIPC指令
                alu_a = pc_in
            
            
            with Condition(is_branch | jump_op):
                with Condition(is_branch):
                    # 分支指令：执行分支比较
                    branch_result = self.branch_unit(branch_op, rs1_data, rs2_data)
                    # 如果分支成功，计算目标地址
                    with Condition(branch_result):
                        target_pc = pc_in + immediate_in
                        pc_change = UInt(1)(1)  # 分支成功，PC需要改变
                    alu_result = pc_in  # 使用pc_in作为默认值，不会被实际使用
                    
                with Condition(jump_op):
                    # JAL指令：计算返回地址(PC+4)和跳转目标
                    alu_result = pc_in + UInt(XLEN)(4)  # 返回地址是PC+4
                    target_pc = pc_in + immediate_in  # 跳转目标是PC+立即数
                    pc_change = UInt(1)(1)  # 跳转指令总是成功，PC需要改变
            
            with Condition(~is_branch & ~jump_op):
                # 普通指令：执行ALU操作
                # 对于需要rs2的ALU操作，使用rs2_data
                alu_b_final = alu_b
                with Condition(alu_src == UInt(2)(0)):  # 寄存器操作
                    alu_b_final = rs2_data
                with Condition(alu_src == UInt(2)(1)):  # 立即数操作
                    alu_b_final = alu_b
                with Condition(alu_src == UInt(2)(2)):  # PC操作 (AUIPC)
                    alu_b_final = alu_b
                alu_result = self.alu_unit(alu_op, alu_a, alu_b_final)
            
            pipeline_regs[0].ex_mem_pc = pc_in
            pipeline_regs[0].ex_mem_control = control_in          # 传递控制信号
            pipeline_regs[0].ex_mem_result = alu_result
            pipeline_regs[0].ex_mem_data = rs2_data
            
            log("EX: PC={}, ALU_OP={:05b}, Result={:08x}, PC_Change={}, Target_PC={:08x}",
                pc_in, alu_op, alu_result, pc_change, target_pc)
        
        memory_stage.async_called(
            pc_in=pipeline_regs[0].ex_mem_pc,
            addr_in=pipeline_regs[0].ex_mem_result,  # 直接使用ex_mem_result作为内存地址
            data_in=pipeline_regs[0].ex_mem_data,
            control_in=pipeline_regs[0].ex_mem_control,    # 控制信号
        )

        execute_signals = EXECUTE_SIGNALS.bundle(
            pc_change=pc_change,
            target_pc=target_pc
        )

        return execute_signals

# ==================== MEM阶段：内存访问 ===================
class MemoryStage(Module):
    """内存访问阶段(MEM)"""
    def __init__(self):
        super().__init__(ports={
            'pc_in': Port(UInt(XLEN)),          # 输入PC
            'addr_in': Port(UInt(XLEN)),        # 输入地址
            'data_in': Port(UInt(XLEN)),        # 输入数据
            'control_in': Port(UInt(32)),     # 输入控制信号
        })
    
    @module.combinational
    def build(self, pipeline_regs, ex_mem_result, writeback_stage):
        pc_in, addr_in, data_in, control_in = self.pop_all_ports(True)
        
        # 如果指令无效，直接返回，不更新MEM/WB寄存器
        with Condition(pipeline_regs[0].ex_mem_valid):
            # 解析控制信号
            mem_read = control_in[5:5]
            mem_write = control_in[6:6]
            store_type = control_in[23:22]  # 存储类型: 00=SB, 01=SH, 10=SW
            
            # 默认输出
            mem_data = UInt(XLEN)(0)
            
            # 执行内存访问
            with Condition(mem_read | mem_write):
                # SRAM接口：we（写使能）, re（读使能）, addr（地址）, wdata（写数据）
                # 字对齐地址 - 右移2位（除以4）得到字地址
                word_addr = addr_in >> UInt(XLEN)(2)
                
                # 根据存储类型处理数据
                write_data = data_in
                with Condition(mem_write):
                    with Condition(store_type == UInt(2)(0b00)):  # SB (Store Byte)
                        # 只保留低8位，其他位清零
                        write_data = data_in & UInt(XLEN)(0xFF)
                    with Condition(store_type == UInt(2)(0b01)):  # SH (Store Halfword)
                        # 只保留低16位，其他位清零
                        write_data = data_in & UInt(XLEN)(0xFFFF)
                    with Condition(store_type == UInt(2)(0b10)):  # SW (Store Word)
                        # 保留所有32位
                        write_data = data_in
                
                # 调用SRAM的build方法
                data_sram = SRAM(width=XLEN, depth=1024, init_file=None)
                data_sram.build(we=mem_write, re=mem_read, addr=word_addr, wdata=write_data)
                
                # 读取数据从SRAM的dout寄存器
                mem_data = data_sram.dout[0]

            pipeline_regs[0].mem_wb_control = control_in          # 传递控制信号
            pipeline_regs[0].mem_wb_mem_data = mem_data          # 内存读取的数据
            pipeline_regs[0].mem_wb_ex_result = ex_mem_result     # EX/MEM阶段的结果
            
            log("MEM: PC={}, Addr={:08x}, Read={}, Write={}",
                pc_in, addr_in, mem_read, mem_write)

        writeback_stage.async_called(
            mem_data_in=pipeline_regs[0].mem_wb_mem_data,  # 内存读取的数据
            ex_result_in=pipeline_regs[0].mem_wb_ex_result, # EX阶段的结果
            control_in=pipeline_regs[0].mem_wb_control,    # 控制信号
        )

# ==================== WB阶段：写回 ===================
class WriteBackStage(Module):
    """写回阶段(WB)"""
    def __init__(self):
        super().__init__(ports={
            'mem_data_in': Port(UInt(XLEN)),    # 输入内存数据
            'ex_result_in': Port(UInt(XLEN)),   # 输入EX阶段结果
            'control_in': Port(UInt(32)),     # 输入控制信号
        })
    
    @module.combinational
    def build(self, pipeline_regs, reg_file):
        mem_data_in, ex_result_in, control_in = self.pop_all_ports(True)
        
        # 如果指令无效，直接返回
        with Condition(pipeline_regs[0].mem_wb_valid):
            # 解析控制信号
            reg_write = control_in[7:7]
            mem_to_reg = control_in[8:8]
            wb_rd = control_in[29:25]
            
            # 选择写回数据
            wb_data = UInt(XLEN)(0)
            
            with Condition(reg_write):
                wb_data = ex_result_in  # 默认从EX阶段的结果
                with Condition(mem_to_reg):
                    wb_data = mem_data_in  # 从内存读取的数据
                # x0寄存器不会写入（已经在reg_write中处理）
                reg_file[wb_rd] <= wb_data
            
            log("WB: Write_Data={:08x}, RD={}, WE={}",
                wb_data, control_in[29:25], reg_write)

class HazardUnit(Downstream):
    def __init__(self):
        super().__init__()

    @downstream.combinational
    def build(self, pc, stall, pipeline_regs, fetch_signals, decode_signals, execute_signals):
        # 解析各阶段指令的目标寄存器(rd)和写使能
        control = pipeline_regs[0].id_ex_control

        rd_mem = pipeline_regs[0].id_ex_control[29:25]
        reg_write_mem = pipeline_regs[0].id_ex_control[7:7]
        
        rd_wb = pipeline_regs[0].ex_mem_control[29:25]
        reg_write_wb = pipeline_regs[0].ex_mem_control[7:7]
        
        # 初始化数据冒险信号
        data_hazard_ex = UInt(1)(0)  # 与EX阶段指令的数据冒险
        data_hazard_wb = UInt(1)(0)   # 与WB阶段指令的数据冒险
        
        needs_rs1 = (control[4:0] != UInt(5)(0)) | (control[19:17] != UInt(3)(0)) | (control[20:20] == UInt(1)(1))  # ALU操作、分支操作或跳转操作需要rs1
        needs_rs2 = (control[10:9] == UInt(2)(0)) & ((control[4:0] != UInt(5)(0)) | (control[19:17] != UInt(3)(0)))  # 只有当ALU源是寄存器且是ALU或分支操作时才需要rs2
        
        with Condition(reg_write_mem):
            with Condition((needs_rs1 & (pipeline_regs[0].id_ex_rs1_idx == rd_mem)) | (needs_rs2 & (pipeline_regs[0].id_ex_rs2_idx == rd_mem))):
                data_hazard_ex = UInt(1)(1)
        
        # 检查与WB阶段的冲突
        with Condition(reg_write_wb):
            with Condition((needs_rs1 & (pipeline_regs[0].id_ex_rs1_idx == rd_wb)) | (needs_rs2 & (pipeline_regs[0].id_ex_rs2_idx == rd_wb))):
                data_hazard_wb = UInt(1)(1)
        
        # 综合数据冒险信号
        data_hazard = data_hazard_ex | data_hazard_wb
        pipeline_regs[0].id_ex_valid = pipeline_regs[0].if_id_valid = ~data_hazard 
        pipeline_regs[0].ex_mem_valid = pipeline_regs[0].mem_wb_valid = UInt(1)(1)  # EX/MEM和MEM/WB阶段始终有效
        stall[0] = data_hazard

        with Condition(execute_signals.pc_change):
            pc[0] = execute_signals.target_pc
            # PC改变时需要将后续指令替换为NOP
            # IF/ID寄存器：替换为NOP指令
            pipeline_regs[0].if_id_instruction = UInt(XLEN)(0x00000013)  # NOP指令
            # ID/EX寄存器：替换为NOP指令的控制信号
            # NOP指令的控制信号：ADDI x0, x0, 0
            nop_control = concat(
                UInt(5)(0b00000),    # [4:0]   ALU操作码: ADD
                UInt(1)(0),          # [5]     内存读
                UInt(1)(0),          # [6]     内存写
                UInt(1)(0),          # [7]     寄存器写 (x0不需要写)
                UInt(1)(0),          # [8]     内存到寄存器
                UInt(1)(0),          # [9]     保留位
                UInt(2)(1),          # [10:9]  ALU输入选择: 立即数
                UInt(6)(0),          # [16:11] 保留位
                UInt(3)(0),          # [19:17] 分支操作类型
                UInt(1)(0),          # [20]    跳转指令标志
                UInt(2)(0),          # [23:22] 存储类型
                UInt(1)(0),          # [21]    保留位
                UInt(5)(0),          # [29:25] rd地址: x0
                UInt(12)(0)          # [31:20] 立即数低12位
            )
            pipeline_regs[0].id_ex_control = nop_control
            pipeline_regs[0].id_ex_immediate = UInt(XLEN)(0)  # 立即数为0
            pipeline_regs[0].id_ex_rs1_idx = UInt(5)(0)  # rs1为x0
            pipeline_regs[0].id_ex_rs2_idx = UInt(5)(0)  # rs2为x0
        with Condition(~execute_signals.pc_change):
            pc[0] = pc[0] + UInt(XLEN)(4)
            pipeline_regs[0].if_id_instruction = fetch_signals.instruction
            pipeline_regs[0].id_ex_control = decode_signals.control
            pipeline_regs[0].id_ex_immediate = decode_signals.immediate
            pipeline_regs[0].id_ex_rs1_idx = decode_signals.rs1
            pipeline_regs[0].id_ex_rs2_idx = decode_signals.rs2

# ==================== 顶层CPU模块 ===================
class Driver(Module):
    """五级流水线RV32I CPU"""
    def __init__(self, program_file="test_program.txt"):
        super().__init__(ports={})
    
    @module.combinational
    def build(self, fetch_stage):
        fetch_stage.async_called()
        
def init_memory(self, program_file="test_program.txt"):
    """初始化内存内容 - 从指定文件加载程序到指令寄存器"""
    test_program = []
    
    try:
        # 尝试从文件读取指令
        with open(program_file, 'r') as f:
            for line in f:
                line = line.strip()
                # 跳过空行和注释行
                if not line or line.startswith('#'):
                    continue
                # 支持十六进制格式（带或不带0x前缀）
                if line.startswith('0x') or line.startswith('0X'):
                    instruction = int(line, 16)
                else:
                    instruction = int(line, 0)  # 自动检测进制
                test_program.append(instruction)
        
        print(f"Loaded {len(test_program)} instructions from {program_file}")
    
    except FileNotFoundError:
        print(f"Warning: Program file {program_file} not found. Using empty program.")
    except Exception as e:
        print(f"Error loading program from {program_file}: {e}")
    
    return test_program     

def build_cpu(program_file="test_program.txt"):
    """构建RV32I CPU系统"""
    sys = SysBuilder('rv32i_cpu')
    with sys:

        pipeline_regs = RegArray(PIPELINE_REGS, 1, initializer=[PIPELINE_REGS.bundle(
            if_id_pc=UInt(XLEN)(0),
            if_id_instruction=UInt(XLEN)(0),
            if_id_valid=UInt(1)(0),
            id_ex_pc=UInt(XLEN)(0),
            id_ex_control=UInt(32)(0),
            id_ex_valid=UInt(1)(0),
            id_ex_rs1_idx=UInt(5)(0),
            id_ex_rs2_idx=UInt(5)(0),
            id_ex_immediate=UInt(XLEN)(0),
            ex_mem_pc=UInt(XLEN)(0),
            ex_mem_control=UInt(32)(0),
            ex_mem_valid=UInt(1)(0),
            ex_mem_result=UInt(XLEN)(0),
            ex_mem_data=UInt(XLEN)(0),
            mem_wb_control=UInt(32)(0),
            mem_wb_valid=UInt(1)(0),
            mem_wb_mem_data=UInt(XLEN)(0),
            mem_wb_ex_result=UInt(XLEN)(0)
        )])

        # 创建指令内存
        test_program = init_memory(program_file)
        instruction_memory = RegArray(UInt(XLEN), 1024, initializer=test_program + [0]*(1024 - len(test_program)))
        
        # 创建寄存器文件
        reg_file = RegArray(UInt(XLEN), REG_COUNT, initializer=[0]*REG_COUNT)

        pc = RegArray(UInt(XLEN), 1, initializer=[0])
        stall = RegArray(UInt(1), 1, initializer=[0])
        
        hazard_unit = HazardUnit()
        fetch_stage = FetchStage()
        decode_stage = DecodeStage()
        execute_stage = ExecuteStage()
        memory_stage = MemoryStage()
        writeback_stage = WriteBackStage()
        driver = Driver()

        # 按照流水线顺序构建模块
        writeback_stage.build(pipeline_regs, reg_file)
        memory_stage.build(pipeline_regs, execute_stage, writeback_stage)
        execute_signals = execute_stage.build(pipeline_regs, reg_file, memory_stage)
        decode_signals = decode_stage.build(pipeline_regs, reg_file, execute_stage)
        fetch_signals = fetch_stage.build(pc, stall, pipeline_regs, instruction_memory, decode_stage)
        hazard_unit.build(pc, stall, pipeline_regs, fetch_signals, decode_signals, execute_signals)
        
        # 构建Driver模块，处理PC更新
        driver.build(fetch_stage)
    
    return sys

def test_rv32i_cpu(program_file="test_program.txt"):
    """测试RV32I CPU"""
    sys = build_cpu(program_file)
    
    # 生成模拟器
    simulator_path, _ = elaborate(sys, verilog=False)
    raw = utils.run_simulator(simulator_path)
    print(raw)

if __name__ == "__main__":
    test_rv32i_cpu(program_file="test_program.txt")
