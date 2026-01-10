#!/usr/bin/env python3
"""
五级流水线RV32I CPU实现
使用Assassyn语言实现完整的RISC-V 32位基础指令集处理器
支持BTB + 2-bit饱和计数器动态分支预测
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
BTB_SIZE = 64  # BTB表大小
BTB_INDEX_BITS = 6  # BTB索引位数 (log2(64)=6)
PREDICTION_INFO_LEN = 34  # 预测信息长度: [0]: btb_hit, [1]: predict_taken, [2:33]: predicted_pc
PREDICTION_RESULT_LEN = 68  # 预测结果长度

# ==================== IF阶段：指令获取 ===================
class FetchStage(Module):
    """指令获取阶段(IF) - 包含BTB预测逻辑"""
    def __init__(self):
        super().__init__(ports={
        })
    
    @module.combinational
    def build(self, pc, stall, if_id_pc, if_id_instruction, if_id_valid, if_id_prediction_info, instruction_memory, btb, bht, btb_valid, decode_stage):
        current_pc = pc[0]
        word_addr = current_pc >> UInt(XLEN)(2)
        instruction = UInt(XLEN)(0)

        instruction = instruction_memory[word_addr]
        
        # BTB查询逻辑 - 使用PC[2:7]作为索引(6位)
        btb_index = current_pc[2:7].bitcast(UInt(BTB_INDEX_BITS))
        
        # 读取BTB、BHT和有效位
        btb_entry = btb[btb_index]  # 预测目标地址
        bht_entry = bht[btb_index]  # 2-bit饱和计数器
        btb_valid_bit = btb_valid[btb_index]  # 有效位
        
        # BTB命中判断
        btb_hit = btb_valid_bit
        
        # 根据BHT值判断预测方向: bht >= 2 预测跳转
        predict_taken = (bht_entry >= UInt(2)(2)).select(UInt(1)(1), UInt(1)(0))
        
        # 如果BTB命中且预测跳转,使用BTB中的目标地址
        predicted_pc = (btb_hit & predict_taken).select(btb_entry, current_pc + UInt(XLEN)(4))
        
        # 构建预测信息: [0]: btb_hit, [1]: predict_taken, [2:33]: predicted_pc
        prediction_info = concat(
            predicted_pc,           # [33:2] 预测的PC (32位)
            predict_taken,          # [1]    预测是否跳转
            btb_hit                 # [0]    BTB是否命中
        ).bitcast(UInt(PREDICTION_INFO_LEN))

        with Condition(if_id_valid[0]):
            if_id_pc[0] = stall[0].select(UInt(XLEN)(0), current_pc)
            if_id_valid[0] = stall[0].select(UInt(1)(0), UInt(1)(1))
            if_id_prediction_info[0] = stall[0].select(UInt(PREDICTION_INFO_LEN)(0), prediction_info)

        decode_stage.async_called()

        fetch_signals = if_id_valid[0].select(stall[0].select(UInt(XLEN)(0), instruction), if_id_instruction[0]).bitcast(Bits(XLEN))
        return fetch_signals

# ==================== ID阶段：指令解码 ===================
class DecodeStage(Module):
    """指令解码阶段(ID) - 传递预测信息"""
    def __init__(self):
        super().__init__(ports={})
    
    @module.combinational
    def build(self, if_id_valid, if_id_pc, if_id_instruction, if_id_prediction_info, id_ex_pc, id_ex_control, id_ex_valid, id_ex_rs1_idx, id_ex_rs2_idx, id_ex_immediate, id_ex_need_rs1, id_ex_need_rs2, id_ex_prediction_info, reg_file, execute_stage):
        if_id_pc_in = if_id_pc[0]
        instruction = if_id_instruction[0]
        prediction_info_in = if_id_prediction_info[0]

        # log("Instruction={:08x}", instruction)
        
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
            # 传递预测信息到EX阶段
            id_ex_prediction_info[0] = if_id_valid[0].select(prediction_info_in, UInt(PREDICTION_INFO_LEN)(0))
            
            # id_ex_control[0] = control_signals
            # id_ex_valid[0] = UInt(1)(1)
            # id_ex_rs1_idx[0] = rs1
            # id_ex_rs2_idx[0] = rs2
            # id_ex_immediate[0] = immediate
            
            # log("ID: PC={}, Opcode={:07b}, RD={}, RS1={}, RS2={}, Immediate={}, Alu_op={}, Branch_op={}, Jump_op={}, Alu_src={}, Mem_read={}, Mem_write={}, Reg_write={}, Mem_to_reg={}, Control={:042b}",
                # if_id_pc_in, opcode, rd, rs1, rs2, immediate, alu_op, branch_op, jump_op, alu_src, mem_read, mem_write, reg_write, mem_to_reg, control_signals)
        
        # rs1 = (~if_id_valid[0]).select(Bits(5)(0), rs1)
        # rs2 = (~if_id_valid[0]).select(Bits(5)(0), rs2)
        # immediate = (~if_id_valid[0]).select(UInt(XLEN)(0), immediate)
        # control_signals = (~if_id_valid[0]).select(Bits(CONTROL_LEN)(0), control_signals)

        execute_stage.async_called()

        decode_signals = concat(
            id_ex_valid[0].select(if_id_valid[0].select(prediction_info_in, UInt(PREDICTION_INFO_LEN)(0)), id_ex_prediction_info[0]),  # 预测信息 (34位)
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
    """执行阶段(EX) - 包含预测验证逻辑"""
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
        
        # log("ALU: OP={:05b}, A={:08x}, B={:08x}, Result={:08x}",
            # op, a, b, result)
        
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
        
        # log("BRANCH: OP={:03b}, A={:08x}, B={:08x}, Taken={}",
        #     op, a, b, taken)
        
        return taken

    @module.combinational
    def build(self, id_ex_valid, id_ex_pc, id_ex_rs1_idx, id_ex_rs2_idx, id_ex_immediate, id_ex_control, id_ex_prediction_info, ex_mem_pc, ex_mem_control, ex_mem_valid, ex_mem_result, ex_mem_data, reg_file, memory_stage, mem_wb_control, mem_wb_valid, mem_wb_mem_data, mem_wb_ex_result, data_sram):
        pc_in = id_ex_pc[0]
        rs1_idx = id_ex_rs1_idx[0]
        rs2_idx = id_ex_rs2_idx[0]
        immediate_in = id_ex_immediate[0]
        control_in = id_ex_control[0]
        prediction_info_in = id_ex_prediction_info[0]

        # ==================== Bypass/Forwarding 逻辑 ====================
        # 从寄存器文件读取基础值
        rs1_reg = reg_file[rs1_idx]
        rs2_reg = reg_file[rs2_idx]
        
        # 解析 MEM 阶段控制信号（来自 EX/MEM 寄存器）用于前递
        mem_control = ex_mem_control[0]
        mem_reg_write = mem_control[7:7]  # reg_write 在第7位
        mem_rd = mem_control[25:29]       # rd 在第25-29位
        mem_result = ex_mem_result[0]     # MEM 阶段的 ALU 结果
        
        # 解析 WB 阶段控制信号用于前递
        wb_control = mem_wb_control[0]
        wb_reg_write = wb_control[7:7]    # reg_write 在第7位
        wb_mem_to_reg = wb_control[8:8]   # mem_to_reg 在第8位
        wb_rd = wb_control[25:29]         # rd 在第25-29位
        wb_ex_result = mem_wb_ex_result[0]
        wb_mem_data = data_sram.dout[0]   # 从 SRAM 读取的数据
        
        # WB 阶段数据选择：若 mem_to_reg=1 使用内存数据，否则使用 ALU 结果
        wb_data = wb_mem_to_reg.select(wb_mem_data, wb_ex_result)
        
        # rs1 前递逻辑：优先级 MEM > WB > reg_file
        # 条件：reg_write=1 且 rs1_idx=rd 且 rd!=0（x0不能前递）
        rs1_forward_mem = (ex_mem_valid[0] & mem_reg_write & (rs1_idx == mem_rd) & (mem_rd != UInt(5)(0)))
        rs1_forward_wb = (mem_wb_valid[0] & wb_reg_write & (rs1_idx == wb_rd) & (wb_rd != UInt(5)(0)))
        
        rs1_data = rs1_reg
        rs1_data = rs1_forward_wb.select(wb_data, rs1_data)
        rs1_data = rs1_forward_mem.select(mem_result, rs1_data)
        
        # rs2 前递逻辑：优先级 MEM > WB > reg_file
        rs2_forward_mem = (ex_mem_valid[0] & mem_reg_write & (rs2_idx == mem_rd) & (mem_rd != UInt(5)(0)))
        rs2_forward_wb = (mem_wb_valid[0] & wb_reg_write & (rs2_idx == wb_rd) & (wb_rd != UInt(5)(0)))
        
        rs2_data = rs2_reg
        rs2_data = rs2_forward_wb.select(wb_data, rs2_data)
        rs2_data = rs2_forward_mem.select(mem_result, rs2_data)
        
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
        
        # 解析预测信息: [0]: btb_hit, [1]: predict_taken, [2:33]: predicted_pc
        btb_hit = prediction_info_in[0:0]
        predict_taken = prediction_info_in[1:1]
        predicted_pc = prediction_info_in[2:33].bitcast(UInt(XLEN))
        
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

        # 计算实际分支结果
        actual_taken = is_branch.select(self.branch_unit(branch_op, rs1_data, rs2_data), UInt(1)(0))
        
        # 计算实际目标地址
        actual_target_pc = pc_in + immediate_in
        new_pc_temp = rs1_data + immediate_in
        new_pc = (new_pc_temp ^ (new_pc_temp & UInt(XLEN)(1)))
        
        # 分支正确的下一个PC (taken则跳转到目标，否则PC+4)
        correct_pc = actual_taken.select(actual_target_pc, pc_in + UInt(XLEN)(4))
        
        # 预测验证逻辑 (根据branch_prediction_rules.md)
        # BTB命中时: prediction_correct = (predict_taken == actual_taken) && (predicted_pc == correct_pc)
        # BTB未命中时: prediction_correct = !actual_taken
        prediction_correct_hit = ((predict_taken == actual_taken) & (predicted_pc == correct_pc)).select(UInt(1)(1), UInt(1)(0))
        prediction_correct_miss = (~actual_taken).select(UInt(1)(1), UInt(1)(0))
        prediction_correct = btb_hit.select(prediction_correct_hit, prediction_correct_miss)
        
        # 仅对分支指令生成mispredict信号
        mispredict = (is_branch & ~prediction_correct).select(UInt(1)(1), UInt(1)(0))
        
        alu_result = is_branch.select(UInt(XLEN)(0), (is_jump | is_jumpr).select(pc_in + UInt(XLEN)(4), self.alu_unit(alu_op, alu_a, alu_b)))
        target_pc = (is_branch | is_jump).select(actual_target_pc, target_pc)
        target_pc = is_jumpr.select(new_pc.bitcast(UInt(32)), target_pc)
        
        # 需要刷新的情况: 预测错误、JAL、JALR
        need_flush = (mispredict | is_jump | is_jumpr).select(UInt(1)(1), UInt(1)(0))
        pc_change = need_flush

        with Condition(is_jump & (immediate_in == UInt(XLEN)(0))):
            log("Finish Execution. The result is {}", reg_file[10])
            finish()
        

        with Condition(ex_mem_valid[0]):
            ex_mem_pc[0] = id_ex_valid[0].select(pc_in, UInt(XLEN)(0))
            ex_mem_control[0] = id_ex_valid[0].select(control_in, UInt(CONTROL_LEN)(0))
            # ex_mem_valid[0] = UInt(1)(1)
            ex_mem_result[0] = id_ex_valid[0].select(alu_result, UInt(XLEN)(0))
            ex_mem_data[0] = id_ex_valid[0].select(rs2_data, UInt(XLEN)(0))
            
            # log("EX: PC={}, ALU_OP={:05b}, ALU_A={}, ALU_B={}, Result={:08x}, PC_Change={}, Target_PC={:08x}, Immediate={:08x}, ALU_SRC={}",
            #     pc_in, alu_op, alu_a, alu_b, alu_result, pc_change, target_pc, immediate_in, alu_src)
        
        memory_stage.async_called()

        # 构建预测结果:
        # [0]: mispredict (预测错误标志)
        # [1:32]: correct_pc (正确的PC)
        # [33]: actual_taken (实际跳转标志)
        # [34:65]: actual_target_pc (实际目标地址)
        # [66]: btb_hit
        # [67]: predict_taken
        # [68:99]: pc_in (分支指令PC，用于计算BTB索引)
        # [100]: is_branch
        # [101]: is_jump
        # [102]: is_jumpr
        prediction_result = concat(
            is_jumpr.bitcast(Bits(1)),           # [102] is_jumpr
            is_jump.bitcast(Bits(1)),            # [101] is_jump
            is_branch.bitcast(Bits(1)),          # [100] is_branch
            pc_in.bitcast(Bits(XLEN)),           # [99:68] 分支指令的PC
            predict_taken.bitcast(Bits(1)),      # [67] 预测是否跳转
            btb_hit.bitcast(Bits(1)),            # [66] BTB是否命中
            actual_target_pc.bitcast(Bits(XLEN)), # [65:34] 实际目标地址
            actual_taken.bitcast(Bits(1)),       # [33] 实际跳转标志
            correct_pc.bitcast(Bits(XLEN)),      # [32:1] 正确的PC
            mispredict.bitcast(Bits(1))          # [0] 预测错误标志
        )

        execute_signals = concat(
            id_ex_valid[0].select(prediction_result, Bits(103)(0)),  # 预测结果
            id_ex_valid[0].select(control_in.bitcast(Bits(CONTROL_LEN)), Bits(CONTROL_LEN)(0)),
            id_ex_valid[0].select(target_pc.bitcast(Bits(XLEN)), Bits(XLEN)(0)),       # [31:1]  目标PC
            id_ex_valid[0].select(pc_change.bitcast(Bits(1)), Bits(1)(0)),      # [0]     PC变化标志
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
            
            # log("MEM: PC={}, Addr={:08x}, Read={}, Write={}, data_in={}, data_out={}",
            #     pc_in, addr_in, mem_read, mem_write, data_in, data_sram.dout[0])


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
            # log("WB: Write_Data={}, RD={}, WE={}",
            #     wb_data, wb_rd, reg_write)
            success = (wb_data == UInt(XLEN)(5050))
            with Condition(success):
                log("SUCCESSFUL!")

        writeback_signals = control_in.bitcast(Bits(CONTROL_LEN))
        return writeback_signals

class HazardUnit(Downstream):
    """冒险检测单元 - 包含分支预测器更新逻辑"""
    def __init__(self):
        super().__init__()

    @downstream.combinational
    def build(self, pc, stall, if_id_valid, if_id_instruction, if_id_prediction_info, id_ex_control, id_ex_valid, id_ex_rs1_idx, id_ex_rs2_idx, id_ex_immediate, id_ex_prediction_info, ex_mem_valid, mem_wb_valid, btb, bht, btb_valid, fetch_signals, decode_signals, execute_signals, memory_signals, writeback_signals):

        # 计算新的信号长度
        EXECUTE_SIGNALS_LEN = XLEN + 1 + CONTROL_LEN + 103  # pc_change(1) + target_pc(32) + control(42) + prediction_result(103)
        DECODE_SIGNALS_LEN = 2 + CONTROL_LEN + 5 + 5 + XLEN + PREDICTION_INFO_LEN  # need_rs1(1) + need_rs2(1) + control(42) + rs1(5) + rs2(5) + immediate(32) + prediction_info(34)

        execute_signals = execute_signals.optional(Bits(EXECUTE_SIGNALS_LEN)(0))
        decode_signals = decode_signals.optional(Bits(DECODE_SIGNALS_LEN)(0))
        fetch_signals = fetch_signals.optional(Bits(XLEN)(0))
        memory_signals = memory_signals.optional(Bits(CONTROL_LEN)(0))
        writeback_signals = writeback_signals.optional(Bits(CONTROL_LEN)(0))

        # 解析execute_signals
        pc_change = execute_signals[0:0].bitcast(UInt(1))
        target_pc = execute_signals[1:XLEN].bitcast(UInt(XLEN))
        
        # 解析预测结果 (从execute_signals中提取)
        # execute_signals布局: [0]: pc_change, [1:32]: target_pc, [33:74]: control, [75:177]: prediction_result
        pred_result_start = XLEN + 1 + CONTROL_LEN
        prediction_result = execute_signals[pred_result_start:pred_result_start + 102].bitcast(UInt(103))
        
        # 解析prediction_result:
        # [0]: mispredict, [1:32]: correct_pc, [33]: actual_taken, [34:65]: actual_target_pc
        # [66]: btb_hit, [67]: predict_taken, [68:99]: pc_in, [100]: is_branch, [101]: is_jump, [102]: is_jumpr
        mispredict = prediction_result[0:0].bitcast(UInt(1))
        correct_pc = prediction_result[1:32].bitcast(UInt(XLEN))
        actual_taken = prediction_result[33:33].bitcast(UInt(1))
        actual_target_pc = prediction_result[34:65].bitcast(UInt(XLEN))
        pred_btb_hit = prediction_result[66:66].bitcast(UInt(1))
        pred_predict_taken = prediction_result[67:67].bitcast(UInt(1))
        branch_pc = prediction_result[68:99].bitcast(UInt(XLEN))
        is_branch_ex = prediction_result[100:100].bitcast(UInt(1))
        is_jump_ex = prediction_result[101:101].bitcast(UInt(1))
        is_jumpr_ex = prediction_result[102:102].bitcast(UInt(1))
        
        instruction = fetch_signals.bitcast(UInt(XLEN))
        
        # 解析decode_signals (新布局)
        control_in = decode_signals[0:CONTROL_LEN - 1].bitcast(UInt(CONTROL_LEN))
        rs1 = decode_signals[CONTROL_LEN:CONTROL_LEN + 4].bitcast(UInt(5))
        rs2 = decode_signals[CONTROL_LEN + 5:CONTROL_LEN + 9].bitcast(UInt(5))
        immediate = decode_signals[CONTROL_LEN + 10:CONTROL_LEN + 10 + XLEN - 1].bitcast(UInt(XLEN))
        needs_rs1 = decode_signals[CONTROL_LEN + 10 + XLEN:CONTROL_LEN + 10 + XLEN].bitcast(UInt(1))
        needs_rs2 = decode_signals[CONTROL_LEN + 10 + XLEN + 1:CONTROL_LEN + 10 + XLEN + 1].bitcast(UInt(1))
        prediction_info_id = decode_signals[CONTROL_LEN + 10 + XLEN + 2:CONTROL_LEN + 10 + XLEN + 2 + PREDICTION_INFO_LEN - 1].bitcast(UInt(PREDICTION_INFO_LEN))

        memory_control = execute_signals[XLEN + 1:XLEN + CONTROL_LEN].bitcast(UInt(CONTROL_LEN))
        memory_control = id_ex_valid[0].select(memory_control, UInt(CONTROL_LEN)(0))
        rd_mem = memory_control[25:29]
        reg_write_mem = memory_control[7:7]
        mem_read_mem = memory_control[5:5]  # 解析 mem_read 信号用于检测 Load-Use 冒险
        
        wb_control = memory_signals.bitcast(UInt(CONTROL_LEN))
        wb_control = ex_mem_valid[0].select(wb_control, UInt(CONTROL_LEN)(0))
        rd_wb = wb_control[25:29]
        reg_write_wb = wb_control[7:7]
        mem_read_wb = wb_control[5:5]  # WB 阶段的 mem_read 信号
        
        # ==================== Load-Use 冒险检测 ====================
        # 只有 Load-Use 冒险需要暂停，其他数据冒险通过 bypass/forwarding 解决
        # Load-Use 冒险：MEM 阶段为 Load 指令（mem_read=1）且目标寄存器与 ID 阶段源寄存器相同
        load_use_hazard_mem = (mem_read_mem & reg_write_mem & (rd_mem != UInt(5)(0)) & 
                               ((needs_rs1 & (rs1 == rd_mem)) | (needs_rs2 & (rs2 == rd_mem))))
        
        # WB 阶段 Load-Use 冒险（理论上通过前递可以解决，但作为安全检测保留）
        load_use_hazard_wb = (mem_read_wb & reg_write_wb & (rd_wb != UInt(5)(0)) & 
                              ((needs_rs1 & (rs1 == rd_wb)) | (needs_rs2 & (rs2 == rd_wb))))
        
        # 需要刷新的情况: mispredict || is_jump || is_jumpr
        need_flush = (mispredict | is_jump_ex | is_jumpr_ex).select(UInt(1)(1), UInt(1)(0))
        
        # 仅在 Load-Use 冒险且无控制冒险时暂停流水线
        # 注意：WB 阶段的 Load 数据已经可用，可以通过前递获取，因此只检测 MEM 阶段
        data_hazard = (load_use_hazard_mem & ~need_flush)
        
        id_ex_valid[0] = (~data_hazard)
        if_id_valid[0] = (~data_hazard)
        ex_mem_valid[0] = UInt(1)(1)
        mem_wb_valid[0] = UInt(1)(1)
        stall[0] = data_hazard
        nop_control = UInt(CONTROL_LEN)(0)

        # BTB索引计算
        btb_update_index = branch_pc[2:7].bitcast(UInt(BTB_INDEX_BITS))
        
        # 分支预测器更新逻辑 (仅在is_branch == 1时更新)
        # 根据branch_prediction_rules.md:
        # - 更新BTB: btb[index] = actual_target_pc, btb_valid[index] = 1
        # - 更新BHT (2-bit饱和计数器):
        #   - actual_taken == 1: bht[index] = (bht[index] == 3) ? 3 : bht[index] + 1
        #   - actual_taken == 0: bht[index] = (bht[index] == 0) ? 0 : bht[index] - 1
        current_bht = bht[btb_update_index]
        new_bht_taken = (current_bht == UInt(2)(3)).select(UInt(2)(3), current_bht + UInt(2)(1))
        new_bht_not_taken = (current_bht == UInt(2)(0)).select(UInt(2)(0), current_bht - UInt(2)(1))
        new_bht = actual_taken.select(new_bht_taken, new_bht_not_taken)
        
        with Condition(is_branch_ex):
            btb[btb_update_index] = actual_target_pc
            btb_valid[btb_update_index] = UInt(1)(1)
            bht[btb_update_index] = new_bht

        # PC更新逻辑 (根据branch_prediction_rules.md)
        # need_flush == 1:
        #   - JALR指令: pc[0] = (rs1_data + immediate_in) & ~1 (已在target_pc中计算)
        #   - 其他情况: pc[0] = correct_pc
        # need_flush == 0:
        #   - 数据冒险: pc[0] = pc[0] (保持不变)
        #   - 无数据冒险: 
        #     - 如果有预测且预测跳转，使用预测的PC
        #     - 否则 pc[0] = pc[0] + 4
        
        # 从IF阶段获取当前指令的预测信息
        current_btb_hit = if_id_prediction_info[0][0:0].bitcast(UInt(1))
        current_predict_taken = if_id_prediction_info[0][1:1].bitcast(UInt(1))
        current_predicted_pc = if_id_prediction_info[0][2:33].bitcast(UInt(XLEN))
        
        # 正常情况下的下一个PC
        # 如果BTB命中且预测跳转，使用预测的目标PC
        normal_next_pc = (current_btb_hit & current_predict_taken).select(current_predicted_pc, pc[0] + UInt(XLEN)(4))
        
        # PC更新
        # JALR时使用target_pc (因为在EX阶段已经计算为 (rs1 + imm) & ~1)
        flush_pc = is_jumpr_ex.select(target_pc, is_jump_ex.select(actual_target_pc, correct_pc))
        pc[0] = need_flush.select(flush_pc, data_hazard.select(pc[0], normal_next_pc))
        
        # 流水线刷新 (根据branch_prediction_rules.md)
        # IF/ID阶段刷新: if_id_valid[0] = 0, if_id_pc[0] = 0, if_id_instruction[0] = NOP
        # ID/EX阶段刷新: 清空所有寄存器
        with Condition(if_id_valid[0]):
            if_id_instruction[0] = need_flush.select(UInt(XLEN)(0x00000013), instruction)  # NOP指令
            if_id_prediction_info[0] = need_flush.select(UInt(PREDICTION_INFO_LEN)(0), prediction_info_id)
        with Condition(id_ex_valid[0]):
            id_ex_control[0] = need_flush.select(nop_control, control_in)
            id_ex_immediate[0] = need_flush.select(UInt(XLEN)(0), immediate)
            id_ex_rs1_idx[0] = need_flush.select(UInt(5)(0), rs1)
            id_ex_rs2_idx[0] = need_flush.select(UInt(5)(0), rs2)
            id_ex_prediction_info[0] = need_flush.select(UInt(PREDICTION_INFO_LEN)(0), prediction_info_id)

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
    """构建RV32I CPU系统 - 包含BTB分支预测器"""
    sys = SysBuilder('rv32i_cpu')
    with sys:
        # 创建单独的流水线寄存器，每个寄存器使用适合的宽度
        
        # IF/ID阶段寄存器
        if_id_pc = RegArray(UInt(XLEN), 1, initializer=[0])           # PC (32位)
        if_id_instruction = RegArray(UInt(XLEN), 1, initializer=[0])  # 指令 (32位)
        if_id_valid = RegArray(UInt(1), 1, initializer=[1])            # 有效标志 (1位)
        if_id_prediction_info = RegArray(UInt(PREDICTION_INFO_LEN), 1, initializer=[0])  # 预测信息 (34位)

        # ID/EX阶段寄存器
        id_ex_pc = RegArray(UInt(XLEN), 1, initializer=[0])           # PC (32位)
        id_ex_control = RegArray(UInt(CONTROL_LEN), 1, initializer=[0])  # 控制信号 (42位)
        id_ex_valid = RegArray(UInt(1), 1, initializer=[1])            # 有效标志 (1位)
        id_ex_rs1_idx = RegArray(UInt(5), 1, initializer=[0])         # rs1索引 (5位)
        id_ex_rs2_idx = RegArray(UInt(5), 1, initializer=[0])         # rs2索引 (5位)
        id_ex_immediate = RegArray(UInt(XLEN), 1, initializer=[0])    # 立即数 (32位)
        id_ex_need_rs1 = RegArray(UInt(1), 1, initializer=[0])        # 是否需要rs1 (1位)
        id_ex_need_rs2 = RegArray(UInt(1), 1, initializer=[0])        # 是否需要rs2 (1位)
        id_ex_prediction_info = RegArray(UInt(PREDICTION_INFO_LEN), 1, initializer=[0])  # 预测信息 (34位)

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

        # 分支预测器 - BTB + BHT + 有效位
        btb = RegArray(UInt(XLEN), BTB_SIZE, initializer=[0]*BTB_SIZE)        # Branch Target Buffer (32位 x 64)
        bht = RegArray(UInt(2), BTB_SIZE, initializer=[1]*BTB_SIZE)           # 2-bit饱和计数器 (初始化为01=Weakly Not Taken)
        btb_valid = RegArray(UInt(1), BTB_SIZE, initializer=[0]*BTB_SIZE)     # BTB有效位

        # 创建指令内存
        test_program = init_memory(program_file)
        instruction_memory = RegArray(UInt(XLEN), 2048, initializer=test_program + [0]*(2048 - len(test_program)))
        
        # 创建寄存器文件
        reg_file = RegArray(UInt(XLEN), REG_COUNT, initializer=[0]*REG_COUNT)

        pc = RegArray(UInt(XLEN), 1, initializer=[0])
        stall = RegArray(UInt(1), 1, initializer=[0])
        
        data_sram = SRAM(width=XLEN, depth=65536, init_file="data.hex")
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
        execute_signals = execute_stage.build(id_ex_valid, id_ex_pc, id_ex_rs1_idx, id_ex_rs2_idx, id_ex_immediate, id_ex_control, id_ex_prediction_info, ex_mem_pc, ex_mem_control, ex_mem_valid, ex_mem_result, ex_mem_data, reg_file, memory_stage, mem_wb_control, mem_wb_valid, mem_wb_mem_data, mem_wb_ex_result, data_sram)
        decode_signals = decode_stage.build(if_id_valid, if_id_pc, if_id_instruction, if_id_prediction_info, id_ex_pc, id_ex_control, id_ex_valid, id_ex_rs1_idx, id_ex_rs2_idx, id_ex_immediate, id_ex_need_rs1, id_ex_need_rs2, id_ex_prediction_info, reg_file, execute_stage)
        fetch_signals = fetch_stage.build(pc, stall, if_id_pc, if_id_instruction, if_id_valid, if_id_prediction_info, instruction_memory, btb, bht, btb_valid, decode_stage)
        hazard_unit.build(pc, stall, if_id_valid, if_id_instruction, if_id_prediction_info, id_ex_control, id_ex_valid, id_ex_rs1_idx, id_ex_rs2_idx, id_ex_immediate, id_ex_prediction_info, ex_mem_valid, mem_wb_valid, btb, bht, btb_valid, fetch_signals, decode_signals, execute_signals, memory_signals, writeback_signals)
        
        # 构建Driver模块，处理PC更新
        driver.build(fetch_stage)
    
    return sys

def test_rv32i_cpu(program_file="test_program.txt"):
    """测试RV32I CPU"""
    sys = build_cpu(program_file)
    
    # 生成模拟器
    simulator_path, _ = elaborate(sys, verilog=False, sim_threshold=2500, resource_base='.')
    raw = utils.run_simulator(simulator_path)
    with open("result.out", 'w', encoding='utf-8') as f:
        print(raw, file=f)

if __name__ == "__main__":
    test_rv32i_cpu(program_file="test_program.txt")