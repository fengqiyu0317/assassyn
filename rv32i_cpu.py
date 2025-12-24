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
CONTROL_LEN = 42 # 控制信号长度

# ==================== IF阶段：指令获取 ===================
class FetchStage(Module):
    """指令获取阶段(IF)"""
    def __init__(self):
        super().__init__(ports={
        })
    
    @module.combinational
    def build(self, pc, stall, if_id_pc, if_id_instruction, if_id_valid, instruction_memory, decode_stage):
        current_pc = pc[0]
        word_addr = current_pc >> UInt(XLEN)(2)
        instruction = UInt(XLEN)(0)

        log("IF_ID_VALID={}", if_id_valid[0])

        instruction = instruction_memory[word_addr]
        with Condition(if_id_valid[0]):
            if_id_pc[0] = stall[0].select(UInt(XLEN)(0), current_pc)
            # if_id_instruction[0] = stall[0].select(UInt(XLEN)(0), instruction)
            if_id_valid[0] = stall[0].select(UInt(1)(0), UInt(1)(1))
            log("IF: PC={:08x}, Instruction={:08x}", current_pc, instruction)

        decode_stage.async_called()

        fetch_signals = if_id_valid[0].select(stall[0].select(UInt(XLEN)(0), instruction), if_id_instruction[0]).bitcast(Bits(XLEN))
        return fetch_signals

# ==================== ID阶段：指令解码 ===================
class DecodeStage(Module):
    """指令解码阶段(ID)"""
    def __init__(self):
        super().__init__(ports={})
    
    @module.combinational
    def build(self, if_id_valid, if_id_pc, if_id_instruction, id_ex_pc, id_ex_control, id_ex_valid, id_ex_rs1_idx, id_ex_rs2_idx, id_ex_immediate, id_ex_need_rs1, id_ex_need_rs2, reg_file, execute_stage):
        if_id_pc_in = if_id_pc[0]
        instruction = if_id_instruction[0]

        log("Instruction={:08x}", instruction)
        
        # 如果指令无效，直接返回，不更新ID/EX寄存器
        opcode = instruction[0:6]          # bits 6:0
        rd = instruction[7:11]             # bits 11:7
        func3 = instruction[12:14]          # bits 14:12
        rs1 = instruction[15:19]           # bits 19:15
        rs2 = instruction[20:24]           # bits 24:20
        funct7 = instruction[25:31]         # bits 31:25

        # 提取立即数 - 使用手动符号扩展
        # I型立即数 (12位有符号数)
        imm_i_bits = instruction[20:31]
        sign_bit_i = imm_i_bits[11:11]  # 获取符号位
        # 手动扩展符号位：如果符号位为1，则高位全为1；否则为0
        immediate_i = (sign_bit_i == UInt(1)(1)).select(
            concat(Bits(20)(0xFFFFF), imm_i_bits).bitcast(UInt(32)),  # 负数扩展
            concat(Bits(20)(0x00000), imm_i_bits).bitcast(UInt(32))   # 正数扩展
        )
        
        # S型立即数 (12位有符号数)
        imm_s_bits = concat(instruction[25:31], instruction[7:11])
        sign_bit_s = imm_s_bits[11:11]  # 获取符号位
        immediate_s = (sign_bit_s == UInt(1)(1)).select(
            concat(Bits(20)(0xFFFFF), imm_s_bits).bitcast(UInt(32)),  # 负数扩展
            concat(Bits(20)(0x00000), imm_s_bits).bitcast(UInt(32))   # 正数扩展
        )
        
        # B型立即数 (13位有符号数，左移1位)
        imm_b_bits = concat(instruction[31:31], instruction[7:7], instruction[25:30], instruction[8:11], UInt(1)(0))
        sign_bit_b = imm_b_bits[12:12]  # 获取符号位
        immediate_b = (sign_bit_b == UInt(1)(1)).select(
            concat(Bits(19)(0x7FFFF), imm_b_bits).bitcast(UInt(32)),  # 负数扩展
            concat(Bits(19)(0x00000), imm_b_bits).bitcast(UInt(32))   # 正数扩展
        )
        
        # U型立即数 (20位无符号数，左移12位)
        immediate_u = (instruction[12:31] << UInt(XLEN)(12)).bitcast(UInt(32))
        
        # J型立即数 (21位有符号数，左移1位)
        imm_j_bits = concat(instruction[31:31], instruction[12:19], instruction[20:20], instruction[21:30], UInt(1)(0))
        sign_bit_j = imm_j_bits[20:20]  # 获取符号位
        immediate_j = (sign_bit_j == UInt(1)(1)).select(
            concat(Bits(11)(0x7FF), imm_j_bits).bitcast(UInt(32)),  # 负数扩展
            concat(Bits(11)(0x000), imm_j_bits).bitcast(UInt(32))   # 正数扩展
        )
        
        # 控制信号解码
        alu_op = UInt(5)(0)
        mem_read = UInt(1)(0)
        mem_write = UInt(1)(0)
        reg_write = UInt(1)(0)
        mem_to_reg = UInt(1)(0)
        alu_src = UInt(2)(0)  # 00:寄存器, 01:立即数, 10:PC
        branch_op = UInt(3)(0)
        jump_op = UInt(1)(0)  # 跳转指令标志
        jumpr_op = UInt(1)(0)  # 寄存器跳转指令标志
        immediate = UInt(XLEN)(0)  # 初始化立即数
        
        is_r_type = (opcode == UInt(7)(0b0110011))
        is_i_type = (opcode == UInt(7)(0b0010011))
        is_l_type = (opcode == UInt(7)(0b0000011))
        is_s_type = (opcode == UInt(7)(0b0100011))
        is_b_type = (opcode == UInt(7)(0b1100011))
        is_j_type = (opcode == UInt(7)(0b1101111))
        is_jr_type = (opcode == UInt(7)(0b1100111))
        is_lui_type = (opcode == UInt(7)(0b0110111))
        is_auipc_type = (opcode == UInt(7)(0b0010111))
        alu_op_tmp = UInt(5)(0)
        alu_op_tmp = ((is_r_type & funct7[5:5] == UInt(1)(1)) & (func3 == UInt(3)(0b000))).select(UInt(5)(0b00001), alu_op_tmp)  # SUB
        alu_op_tmp = ((funct7[5:5] == UInt(1)(1)) & (func3 == UInt(3)(0b101))).select(UInt(5)(0b00110), alu_op_tmp)  # SRA
        alu_op_tmp = (~(is_r_type & funct7[5:5] == UInt(1)(1)) & (func3 == UInt(3)(0b000))).select(UInt(5)(0b00000), alu_op_tmp)  # ADD
        alu_op_tmp = (func3 == UInt(3)(0b111)).select(UInt(5)(0b01001), alu_op_tmp)  # AND
        alu_op_tmp = (func3 == UInt(3)(0b110)).select(UInt(5)(0b01000), alu_op_tmp)  # OR
        alu_op_tmp = (func3 == UInt(3)(0b100)).select(UInt(5)(0b00100), alu_op_tmp)  # XOR
        alu_op_tmp = (func3 == UInt(3)(0b010)).select(UInt(5)(0b00011), alu_op_tmp)  # SLT
        alu_op_tmp = (func3 == UInt(3)(0b011)).select(UInt(5)(0b00111), alu_op_tmp)  # SLTU
        alu_op_tmp = (func3 == UInt(3)(0b001)).select(UInt(5)(0b00010), alu_op_tmp)  # SLL
        alu_op_tmp = ((funct7[5:5] == UInt(1)(0)) & (func3 == UInt(3)(0b101))).select(UInt(5)(0b00101), alu_op_tmp)  # SRL
        alu_op = (is_r_type | is_i_type).select(alu_op_tmp, alu_op)
        reg_write = (is_r_type | is_i_type).select(UInt(1)(1), reg_write)
        alu_src = is_r_type.select(UInt(2)(0), alu_src)
        alu_src = is_i_type.select(UInt(2)(1), alu_src)
        immediate = is_i_type.select(immediate_i, immediate)
        
        mem_read = is_l_type.select(UInt(1)(1), mem_read)  # LW (Load Word)
        reg_write = is_l_type.select(UInt(1)(1), reg_write)  # x0寄存器不会写入
        mem_to_reg = is_l_type.select(UInt(1)(1), mem_to_reg)  # LW (Load Word)
        alu_src = is_l_type.select(UInt(2)(1), alu_src)
        immediate = is_l_type.select(immediate_i, immediate)
            
        store_type_bits = UInt(2)(0)
        mem_write = is_s_type.select(UInt(1)(1), mem_write)  # SW (Store Word)
        alu_src = is_s_type.select(UInt(2)(1), alu_src)
        immediate = is_s_type.select(immediate_s, immediate)
        store_type_bits = (is_s_type & (func3 == UInt(3)(0b010))).select(UInt(2)(0b10), store_type_bits)  # SW (Store Word)
        store_type_bits = (is_s_type & (func3 == UInt(3)(0b000))).select(UInt(2)(0b00), store_type_bits)  # SB (Store Byte)
        store_type_bits = (is_s_type & (func3 == UInt(3)(0b001))).select(UInt(2)(0b01), store_type_bits)  # SH (Store Halfword)

        branch_op_tmp = UInt(3)(0)
        branch_op_tmp = (func3 == UInt(3)(0b000)).select(UInt(3)(0b001), branch_op_tmp)  # BEQ
        branch_op_tmp = (func3 == UInt(3)(0b001)).select(UInt(3)(0b010), branch_op_tmp)  # BNE
        branch_op_tmp = (func3 == UInt(3)(0b100)).select(UInt(3)(0b011), branch_op_tmp)  # BLT
        branch_op_tmp = (func3 == UInt(3)(0b101)).select(UInt(3)(0b100), branch_op_tmp)  # BGE
        branch_op_tmp = (func3 == UInt(3)(0b110)).select(UInt(3)(0b101), branch_op_tmp)  # BLTU
        branch_op_tmp = (func3 == UInt(3)(0b111)).select(UInt(3)(0b110), branch_op_tmp)  # BGEU
        immediate = is_b_type.select(immediate_b, immediate)
        branch_op = is_b_type.select(branch_op_tmp, branch_op)
            
        reg_write = (is_lui_type | is_auipc_type).select(UInt(1)(1), reg_write)
        alu_src = is_lui_type.select(UInt(2)(1), alu_src)
        immediate = (is_lui_type | is_auipc_type).select(immediate_u, immediate)
        alu_src = is_auipc_type.select(UInt(2)(2), alu_src)
        
        reg_write = is_j_type.select(UInt(1)(1), reg_write)
        alu_src = is_j_type.select(UInt(2)(1), alu_src)
        immediate = is_j_type.select(immediate_j, immediate)
        jump_op = is_j_type.select(UInt(1)(1), jump_op)

        reg_write = is_jr_type.select(UInt(1)(1), reg_write)
        alu_src = is_jr_type.select(UInt(2)(1), alu_src)
        immediate = is_jr_type.select(immediate_i, immediate)
        jumpr_op = is_jr_type.select(UInt(1)(1), jumpr_op)

        reg_write = (rd == UInt(5)(0)).select(UInt(1)(0), reg_write)  # rd为x0时不写入
        
        control_signals = concat(
            immediate[0:11],   # [41:30] 立即数低12位
            rd,               # [29:25] rd地址
            UInt(1)(0),       # [24]    保留位
            store_type_bits,  # [23:22] 存储类型: 00=SB, 01=SH, 10=SW
            jumpr_op,       # [21]    保留位
            jump_op,          # [20]    跳转指令标志
            branch_op,        # [19:17] 分支操作类型
            UInt(6)(0),       # [16:11] 保留位
            alu_src,          # [10:9]  ALU输入选择
            mem_to_reg,       # [8]     内存到寄存器
            reg_write,        # [7]     寄存器写
            mem_write,        # [6]     内存写
            mem_read,         # [5]     内存读
            alu_op,           # [4:0]   ALU操作码
        )

        need_rs1 = (is_i_type | is_r_type | is_s_type | is_b_type | is_l_type | is_jr_type)
        need_rs2 = (is_r_type | is_s_type | is_b_type)
        
        
        with Condition(id_ex_valid[0]):
            id_ex_pc[0] = if_id_valid[0].select(if_id_pc_in, UInt(XLEN)(0))
            id_ex_need_rs1[0] = if_id_valid[0].select(need_rs1, Bits(1)(0))
            id_ex_need_rs2[0] = if_id_valid[0].select(need_rs2, Bits(1)(0))
            
            # id_ex_control[0] = control_signals
            # id_ex_valid[0] = UInt(1)(1)
            # id_ex_rs1_idx[0] = rs1
            # id_ex_rs2_idx[0] = rs2
            # id_ex_immediate[0] = immediate
            
            log("ID: PC={}, Opcode={:07b}, RD={}, RS1={}, RS2={}, Immediate={}, Alu_op={}, Branch_op={}, Jump_op={}, Alu_src={}, Mem_read={}, Mem_write={}, Reg_write={}, Mem_to_reg={}, Control={:042b}",
                if_id_pc_in, opcode, rd, rs1, rs2, immediate, alu_op, branch_op, jump_op, alu_src, mem_read, mem_write, reg_write, mem_to_reg, control_signals)
        
        # rs1 = (~if_id_valid[0]).select(Bits(5)(0), rs1)
        # rs2 = (~if_id_valid[0]).select(Bits(5)(0), rs2)
        # immediate = (~if_id_valid[0]).select(UInt(XLEN)(0), immediate)
        # control_signals = (~if_id_valid[0]).select(Bits(CONTROL_LEN)(0), control_signals)

        execute_stage.async_called()

        decode_signals = concat(
            id_ex_valid[0].select(if_id_valid[0].select(need_rs2.bitcast(UInt(1)), UInt(1)(0)), id_ex_need_rs2[0]), 
            id_ex_valid[0].select(if_id_valid[0].select(need_rs1.bitcast(UInt(1)), UInt(1)(0)), id_ex_need_rs1[0]),
            id_ex_valid[0].select(if_id_valid[0].select(immediate, UInt(XLEN)(0)), id_ex_immediate[0]),
            id_ex_valid[0].select(if_id_valid[0].select(rs2.bitcast(UInt(5)), UInt(5)(0)), id_ex_rs2_idx[0]),
            id_ex_valid[0].select(if_id_valid[0].select(rs1.bitcast(UInt(5)), UInt(5)(0)), id_ex_rs1_idx[0]),
            id_ex_valid[0].select(if_id_valid[0].select(control_signals, Bits(CONTROL_LEN)(0)).bitcast(UInt(CONTROL_LEN)), id_ex_control[0]),
        )
        return decode_signals

# ==================== EX阶段：执行 ===================
class ExecuteStage(Module):
    """执行阶段(EX)"""
    def __init__(self):
        super().__init__(ports={})
    
    def alu_unit(self, op: Value, a: Value, b: Value):
        
        # 默认结果
        result = UInt(XLEN)(0)
        zero = UInt(1)(0)
        a_signed = a.bitcast(Int(XLEN))
        b_signed = b.bitcast(Int(XLEN))
        
        # 根据操作码执行不同操作
        result = (op == UInt(5)(0b00000)).select(a + b, result)  # ADD
        result = (op == UInt(5)(0b00001)).select(a - b, result)  # SUB
        result = (op == UInt(5)(0b00010)).select((a << (b & UInt(XLEN)(0x1F))).bitcast(UInt(XLEN)), result)  # SLL
        result = (op == UInt(5)(0b00011)).select((a_signed < b_signed).select(UInt(XLEN)(1), UInt(XLEN)(0)), result)  # SLT
        result = (op == UInt(5)(0b00100)).select((a ^ b).bitcast(UInt(XLEN)), result)  # XOR
        result = (op == UInt(5)(0b00101)).select((a >> (b & UInt(XLEN)(0x1F))).bitcast(UInt(XLEN)), result)  # SRL
        result = (op == UInt(5)(0b00110)).select((a_signed >> (b & UInt(XLEN)(0x1F))).bitcast(UInt(XLEN)), result)  # SRA
        result = (op == UInt(5)(0b00111)).select((a < b).select(UInt(XLEN)(1), UInt(XLEN)(0)), result)  # SLTU
        result = (op == UInt(5)(0b01000)).select((a | b).bitcast(UInt(XLEN)), result)  # OR
        result = (op == UInt(5)(0b01001)).select((a & b).bitcast(UInt(XLEN)), result)  # AND
        
        log("ALU: OP={:05b}, A={:08x}, B={:08x}, Result={:08x}",
            op, a, b, result)
        
        return result

    def branch_unit(self, op: Value, a: Value, b: Value):
        
        taken = UInt(1)(0)
        a_signed = a.bitcast(Int(XLEN))
        b_signed = b.bitcast(Int(XLEN))
        taken = (op == UInt(3)(0b001)).select((a == b).select(UInt(1)(1), UInt(1)(0)), taken)  # BEQ
        taken = (op == UInt(3)(0b010)).select((a != b).select(UInt(1)(1), UInt(1)(0)), taken)  # BNE
        taken = (op == UInt(3)(0b011)).select((a_signed < b_signed).select(UInt(1)(1), UInt(1)(0)), taken)  # BLT
        taken = (op == UInt(3)(0b100)).select((a_signed >= b_signed).select(UInt(1)(1), UInt(1)(0)), taken)  # BGE
        taken = (op == UInt(3)(0b101)).select((a < b).select(UInt(1)(1), UInt(1)(0)), taken)  # BLTU
        taken = (op == UInt(3)(0b110)).select((a >= b).select(UInt(1)(1), UInt(1)(0)), taken)  # BGEU
        
        log("BRANCH: OP={:03b}, A={:08x}, B={:08x}, Taken={}",
            op, a, b, taken)
        
        return taken

    @module.combinational
    def build(self, id_ex_valid, id_ex_pc, id_ex_rs1_idx, id_ex_rs2_idx, id_ex_immediate, id_ex_control, ex_mem_pc, ex_mem_control, ex_mem_valid, ex_mem_result, ex_mem_data, reg_file, memory_stage):
        pc_in = id_ex_pc[0]
        rs1_idx = id_ex_rs1_idx[0]
        rs2_idx = id_ex_rs2_idx[0]
        immediate_in = id_ex_immediate[0]
        control_in = id_ex_control[0]

        # 直接从寄存器文件读取rs1和rs2的值
        rs1_data = reg_file[rs1_idx]
        rs2_data = reg_file[rs2_idx]
        
        # 初始化PC变化控制信号
        pc_change = UInt(1)(0)
        target_pc = pc_in + UInt(XLEN)(4)  # 默认目标PC是PC+4

        # 解析控制信号
        alu_op = control_in[0:4]
        mem_read = control_in[5:5]
        mem_write = control_in[6:6]
        reg_write = control_in[7:7]
        mem_to_reg = control_in[8:8]
        alu_src = control_in[9:10]
        branch_op = control_in[17:19]  # 修正：branch_op在[19:17]位
        jump_op = control_in[20:20]  # 跳转指令标志
        jumpr_op = control_in[21:21]  # 寄存器跳转指令标志
        rd_addr = control_in[25:29]  # rd地址
        immediate = control_in[22:31]  # 立即数
        
        # ALU输入B选择
        alu_b = immediate_in
        alu_b = (alu_src == UInt(2)(0)).select(rs2_data, alu_b)
        
        # 根据指令类型决定执行ALU操作还是分支操作
        alu_result = UInt(XLEN)(0)
        
        # 判断是否为分支指令 (branch_op != 0)
        is_branch = (branch_op != UInt(3)(0b000))
        is_jump = (jump_op == UInt(1)(1))
        is_jumpr = (jumpr_op == UInt(1)(1))
        
        # 对于AUIPC指令，ALU输入A应该是PC而不是rs1_data
        alu_a = rs1_data
        alu_a = (alu_src == UInt(2)(2)).select(pc_in, alu_a)

        branch_result = is_branch.select(self.branch_unit(branch_op, rs1_data, rs2_data), UInt(1)(0))
        alu_result = is_branch.select(UInt(XLEN)(0), (is_jump | is_jumpr).select(pc_in + UInt(XLEN)(4), self.alu_unit(alu_op, alu_a, alu_b)))
        target_pc = (is_branch | is_jump).select(pc_in + immediate_in, target_pc)
        new_pc_temp = rs1_data + immediate_in
        new_pc = (new_pc_temp ^ (new_pc_temp & UInt(XLEN)(1)))
        target_pc = is_jumpr.select(new_pc.bitcast(UInt(32)), target_pc)
        pc_change = (branch_result.bitcast(Bits(1)) | is_jump | is_jumpr).select(UInt(1)(1), pc_change)

        with Condition(is_jump & (immediate_in == UInt(XLEN)(0))):
            log("Finish Execution.")
            finish()
        

        with Condition(ex_mem_valid[0]):
            ex_mem_pc[0] = id_ex_valid[0].select(pc_in, UInt(XLEN)(0))
            ex_mem_control[0] = id_ex_valid[0].select(control_in, UInt(CONTROL_LEN)(0))
            # ex_mem_valid[0] = UInt(1)(1)
            ex_mem_result[0] = id_ex_valid[0].select(alu_result, UInt(XLEN)(0))
            ex_mem_data[0] = id_ex_valid[0].select(rs2_data, UInt(XLEN)(0))
            
            log("EX: PC={}, ALU_OP={:05b}, ALU_A={}, ALU_B={}, Result={:08x}, PC_Change={}, Target_PC={:08x}, Immediate={:08x}, ALU_SRC={}",
                pc_in, alu_op, alu_a, alu_b, alu_result, pc_change, target_pc, immediate_in, alu_src)
        
        memory_stage.async_called()

        execute_signals = concat(
            id_ex_valid[0].select(control_in.bitcast(Bits(CONTROL_LEN)), Bits(CONTROL_LEN)(0)),
            id_ex_valid[0].select(target_pc, UInt(XLEN)(0)),       # [31:1]  目标PC
            id_ex_valid[0].select(pc_change, UInt(1)(0)),      # [0]     PC变化标志
        )

        return execute_signals

# ==================== MEM阶段：内存访问 ===================
class MemoryStage(Module):
    """内存访问阶段(MEM)"""
    def __init__(self):
        super().__init__(ports={})
    
    @module.combinational
    def build(self, ex_mem_valid, ex_mem_result, ex_mem_pc, ex_mem_data, ex_mem_control, mem_wb_control, mem_wb_valid, mem_wb_mem_data, mem_wb_ex_result, writeback_stage, data_sram):
        pc_in = ex_mem_pc[0]
        addr_in = ex_mem_result[0]
        data_in = ex_mem_data[0]
        control_in = ex_mem_control[0]
        
        # 如果指令无效，直接返回，不更新MEM/WB寄存器
        # 解析控制信号
        mem_read = control_in[5:5]
        mem_write = control_in[6:6]
        store_type = control_in[22:23]  # 存储类型: 00=SB, 01=SH, 10=SW
        
        # 默认输出
        mem_data = UInt(XLEN)(0)
        
        word_addr = addr_in >> UInt(XLEN)(2)
        write_data = data_in

        with Condition(mem_wb_valid[0]):
            with Condition(mem_read | mem_write):
                with Condition(ex_mem_valid[0]):
                    data_sram.build(we=mem_write, re=mem_read, addr=word_addr, wdata=write_data)
                    mem_wb_mem_data[0] = data_sram.dout[0]          # 内存读取的数据
                with Condition(~ex_mem_valid[0]):
                    mem_wb_mem_data[0] = UInt(XLEN)(0)
            mem_wb_control[0] = ex_mem_valid[0].select(control_in, UInt(CONTROL_LEN)(0))
            # mem_wb_valid[0] = ex_mem_valid[0].select(UInt(1)(1), UInt(1)(0))
            mem_wb_ex_result[0] = ex_mem_valid[0].select(ex_mem_result[0], UInt(XLEN)(0))
            
            log("MEM: PC={}, Addr={:08x}, Read={}, Write={}, data_in={}, data_out={}",
                pc_in, addr_in, mem_read, mem_write, data_in, data_sram.dout[0])


        writeback_stage.async_called()

        memory_signals = control_in.bitcast(Bits(CONTROL_LEN))
        return memory_signals

# ==================== WB阶段：写回 ===================
class WriteBackStage(Module):
    """写回阶段(WB)"""
    def __init__(self):
        super().__init__(ports={})
    
    @module.combinational
    def build(self, mem_wb_valid, mem_wb_mem_data, mem_wb_ex_result, mem_wb_control, reg_file, data_sram):
        mem_data_in = data_sram.dout[0]
        ex_result_in = mem_wb_ex_result[0]
        control_in = mem_wb_control[0]
        
            # 解析控制信号
        reg_write = control_in[7:7]
        mem_to_reg = control_in[8:8]
        wb_rd = control_in[25:29]
            
        # 选择写回数据
        wb_data = mem_to_reg.select(mem_data_in, ex_result_in)
            
        # 如果指令无效，直接返回
        with Condition(mem_wb_valid[0]):
            with Condition(reg_write):
                reg_file[wb_rd] = wb_data
            log("WB: Write_Data={}, RD={}, WE={}",
                wb_data, wb_rd, reg_write)

        writeback_signals = control_in.bitcast(Bits(CONTROL_LEN))
        return writeback_signals

class HazardUnit(Downstream):
    def __init__(self):
        super().__init__()

    @downstream.combinational
    def build(self, pc, stall, if_id_valid, if_id_instruction, id_ex_control, id_ex_valid, id_ex_rs1_idx, id_ex_rs2_idx, id_ex_immediate, ex_mem_valid, mem_wb_valid, fetch_signals, decode_signals, execute_signals, memory_signals, writeback_signals):

        execute_signals = execute_signals.optional(Bits(XLEN + 1 + CONTROL_LEN)(0))
        decode_signals = decode_signals.optional(Bits(2 + CONTROL_LEN + 5 + 5 + XLEN)(0))
        fetch_signals = fetch_signals.optional(Bits(XLEN)(0))
        memory_signals = memory_signals.optional(Bits(CONTROL_LEN)(0))
        writeback_signals = writeback_signals.optional(Bits(CONTROL_LEN)(0))

        pc_change = execute_signals[0:0].bitcast(UInt(1))
        target_pc = execute_signals[1:XLEN].bitcast(UInt(XLEN))
        instruction = fetch_signals.bitcast(UInt(XLEN))
        immediate = decode_signals[CONTROL_LEN + 5 + 5:CONTROL_LEN + 5 + 5 + XLEN - 1].bitcast(UInt(XLEN))
        rs1 = decode_signals[CONTROL_LEN:CONTROL_LEN + 5 - 1].bitcast(UInt(5))
        rs2 = decode_signals[CONTROL_LEN + 5:CONTROL_LEN + 5 + 5 - 1].bitcast(UInt(5))
        control_in = decode_signals[0:CONTROL_LEN - 1].bitcast(UInt(CONTROL_LEN))

        memory_control = execute_signals[XLEN + 1:XLEN + 1 + CONTROL_LEN - 1].bitcast(UInt(CONTROL_LEN))
        memory_control = id_ex_valid[0].select(memory_control, UInt(CONTROL_LEN)(0))
        rd_mem = memory_control[25:29]
        reg_write_mem = memory_control[7:7]
        
        wb_control = memory_signals.bitcast(UInt(CONTROL_LEN))
        wb_control = ex_mem_valid[0].select(wb_control, UInt(CONTROL_LEN)(0))
        rd_wb = wb_control[25:29]
        reg_write_wb = wb_control[7:7]
        
        # 初始化数据冒险信号
        data_hazard_ex = UInt(1)(0)  # 与EX阶段指令的数据冒险
        data_hazard_wb = UInt(1)(0)   # 与WB阶段指令的数据冒险
        
        needs_rs1 = decode_signals[CONTROL_LEN + 5 + 5 + XLEN:CONTROL_LEN + 5 + 5 + XLEN].bitcast(UInt(1))
        needs_rs2 = decode_signals[CONTROL_LEN + 5 + 5 + XLEN + 1:CONTROL_LEN + 5 + 5 + XLEN + 1].bitcast(UInt(1))
        
        data_hazard_ex = (reg_write_mem & ((needs_rs1 & (rs1 == rd_mem)) | (needs_rs2 & (rs2 == rd_mem)))).select(UInt(1)(1), data_hazard_ex)

        data_hazard_wb = (reg_write_wb & ((needs_rs1 & (rs1 == rd_wb)) | (needs_rs2 & (rs2 == rd_wb)))).select(UInt(1)(1), data_hazard_wb)
        
        # 综合数据冒险信号
        data_hazard = ((data_hazard_ex | data_hazard_wb) & ~pc_change)
        id_ex_valid[0] = (~data_hazard)
        if_id_valid[0] = (~data_hazard)
        ex_mem_valid[0] = UInt(1)(1)  # ID/EX和EX/MEM阶段始终有效
        mem_wb_valid[0] = UInt(1)(1)  # EX/MEM和MEM/WB阶段始终有效
        stall[0] = data_hazard
        nop_control = UInt(CONTROL_LEN)(0) # NOP控制信号，全0表示无操作

        # 更新PC和IF/ID寄存器        
        pc[0] = pc_change.select(target_pc, data_hazard.select(pc[0], pc[0] + UInt(XLEN)(4)))
        with Condition(if_id_valid[0]):
            if_id_instruction[0] = pc_change.select(UInt(XLEN)(0x00000013), instruction)  # NOP指令
        with Condition(id_ex_valid[0]):
            id_ex_control[0] = pc_change.select(nop_control, control_in)
            id_ex_immediate[0] = pc_change.select(UInt(XLEN)(0), immediate)
            id_ex_rs1_idx[0] = pc_change.select(UInt(5)(0), rs1)
            id_ex_rs2_idx[0] = pc_change.select(UInt(5)(0), rs2)

        log("RD_MEM={}, REG_WRITE_MEM={}, RD_WB={}, REG_WRITE_WB={}",
            rd_mem, reg_write_mem, rd_wb, reg_write_wb)
        log("Hazard Unit: Data_Hazard={}, PC_Change={}, Target_PC={:08x}, IF_ID_VALID={}, ID_EX_VALID={}, Immediate={:08x}, RS1={}, RS2={}, Control={:042b}",
            data_hazard, pc_change, target_pc, if_id_valid[0], id_ex_valid[0], immediate, rs1, rs2, control_in)

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
        # 创建单独的流水线寄存器，每个寄存器使用适合的宽度
        
        # IF/ID阶段寄存器
        if_id_pc = RegArray(UInt(XLEN), 1, initializer=[0])           # PC (32位)
        if_id_instruction = RegArray(UInt(XLEN), 1, initializer=[0])  # 指令 (32位)
        if_id_valid = RegArray(UInt(1), 1, initializer=[1])            # 有效标志 (1位)

        # ID/EX阶段寄存器
        id_ex_pc = RegArray(UInt(XLEN), 1, initializer=[0])           # PC (32位)
        id_ex_control = RegArray(UInt(CONTROL_LEN), 1, initializer=[0])  # 控制信号 (42位)
        id_ex_valid = RegArray(UInt(1), 1, initializer=[1])            # 有效标志 (1位)
        id_ex_rs1_idx = RegArray(UInt(5), 1, initializer=[0])         # rs1索引 (5位)
        id_ex_rs2_idx = RegArray(UInt(5), 1, initializer=[0])         # rs2索引 (5位)
        id_ex_immediate = RegArray(UInt(XLEN), 1, initializer=[0])    # 立即数 (32位)
        id_ex_need_rs1 = RegArray(UInt(1), 1, initializer=[0])        # 是否需要rs1 (1位)
        id_ex_need_rs2 = RegArray(UInt(1), 1, initializer=[0])        # 是否需要rs2 (1位)

        # EX/MEM阶段寄存器
        ex_mem_pc = RegArray(UInt(XLEN), 1, initializer=[0])           # PC (32位)
        ex_mem_control = RegArray(UInt(CONTROL_LEN), 1, initializer=[0])  # 控制信号 (42位)
        ex_mem_valid = RegArray(UInt(1), 1, initializer=[1])            # 有效标志 (1位)
        ex_mem_result = RegArray(UInt(XLEN), 1, initializer=[0])       # ALU结果 (32位)
        ex_mem_data = RegArray(UInt(XLEN), 1, initializer=[0])          # 数据 (32位)

        # MEM/WB阶段寄存器
        mem_wb_control = RegArray(UInt(CONTROL_LEN), 1, initializer=[0])  # 控制信号 (42位)
        mem_wb_valid = RegArray(UInt(1), 1, initializer=[1])            # 有效标志 (1位)
        mem_wb_mem_data = RegArray(UInt(XLEN), 1, initializer=[0])     # 内存数据 (32位)
        mem_wb_ex_result = RegArray(UInt(XLEN), 1, initializer=[0])     # EX阶段结果 (32位)

        # 创建指令内存
        test_program = init_memory(program_file)
        instruction_memory = RegArray(UInt(XLEN), 1024, initializer=test_program + [0]*(1024 - len(test_program)))
        
        # 创建寄存器文件
        reg_file = RegArray(UInt(XLEN), REG_COUNT, initializer=[0]*REG_COUNT)

        pc = RegArray(UInt(XLEN), 1, initializer=[0])
        stall = RegArray(UInt(1), 1, initializer=[0])
        
        data_sram = SRAM(width=XLEN, depth=65536, init_file=None)
        hazard_unit = HazardUnit()
        fetch_stage = FetchStage()
        decode_stage = DecodeStage()
        execute_stage = ExecuteStage()
        memory_stage = MemoryStage()
        writeback_stage = WriteBackStage()
        driver = Driver()

        # 按照流水线顺序构建模块
        writeback_signals = writeback_stage.build(mem_wb_valid, mem_wb_mem_data, mem_wb_ex_result, mem_wb_control, reg_file, data_sram)
        memory_signals = memory_stage.build(ex_mem_valid, ex_mem_result, ex_mem_pc, ex_mem_data, ex_mem_control, mem_wb_control, mem_wb_valid, mem_wb_mem_data, mem_wb_ex_result, writeback_stage, data_sram)
        execute_signals = execute_stage.build(id_ex_valid, id_ex_pc, id_ex_rs1_idx, id_ex_rs2_idx, id_ex_immediate, id_ex_control, ex_mem_pc, ex_mem_control, ex_mem_valid, ex_mem_result, ex_mem_data, reg_file, memory_stage)
        decode_signals = decode_stage.build(if_id_valid, if_id_pc, if_id_instruction, id_ex_pc, id_ex_control, id_ex_valid, id_ex_rs1_idx, id_ex_rs2_idx, id_ex_immediate, id_ex_need_rs1, id_ex_need_rs2, reg_file, execute_stage)
        fetch_signals = fetch_stage.build(pc, stall, if_id_pc, if_id_instruction, if_id_valid, instruction_memory, decode_stage)
        hazard_unit.build(pc, stall, if_id_valid, if_id_instruction, id_ex_control, id_ex_valid, id_ex_rs1_idx, id_ex_rs2_idx, id_ex_immediate, ex_mem_valid, mem_wb_valid, fetch_signals, decode_signals, execute_signals, memory_signals, writeback_signals)
        
        # 构建Driver模块，处理PC更新
        driver.build(fetch_stage)
    
    return sys

def test_rv32i_cpu(program_file="test_program.txt"):
    """测试RV32I CPU"""
    sys = build_cpu(program_file)
    
    # 生成模拟器
    simulator_path, _ = elaborate(sys, verilog=False, sim_threshold=2500)
    raw = utils.run_simulator(simulator_path)
    with open("result.out", 'w', encoding='utf-8') as f:
        print(raw, file=f)

if __name__ == "__main__":
    test_rv32i_cpu(program_file="test_program.txt")
