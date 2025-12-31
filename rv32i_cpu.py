#!/usr/bin/env python3
"""
五级流水线RV32IM CPU实现
使用Assassyn语言实现完整的RISC-V 32位基础指令集处理器
支持BTB + 2-bit饱和计数器动态分支预测
支持RV32IM乘法扩展 (mul, mulh, mulhsu, mulhu)
使用Wallace Tree 3周期乘法器
"""

from assassyn.frontend import *
from assassyn.backend import elaborate
from assassyn import utils
from assassyn.ir.memory.sram import SRAM
from assassyn.ir.module import downstream, Downstream

# ==================== 常量定义 ===================
XLEN = 32  # RISC-V XLEN
REG_COUNT = 32  # 通用寄存器数量
CONTROL_LEN = 45 # 控制信号长度 (42 + 3位mul_op)
BTB_SIZE = 64  # BTB表大小
BTB_INDEX_BITS = 6  # BTB索引位数 (log2(64)=6)
PREDICTION_INFO_LEN = 34  # 预测信息长度: [0]: btb_hit, [1]: predict_taken, [2:33]: predicted_pc
PREDICTION_RESULT_LEN = 68  # 预测结果长度

# ==================== M扩展乘法操作码 ===================
# mul_op 编码 (3位):
# 000 - 非乘法指令
# 001 - MUL    (signed × signed, low 32 bits)
# 010 - MULH   (signed × signed, high 32 bits)
# 011 - MULHSU (signed × unsigned, high 32 bits)
# 100 - MULHU  (unsigned × unsigned, high 32 bits)
MUL_OP_NONE   = 0b000
MUL_OP_MUL    = 0b001
MUL_OP_MULH   = 0b010
MUL_OP_MULHSU = 0b011
MUL_OP_MULHU  = 0b100

# ==================== Wallace Tree 乘法器说明 ====================
# Wallace Tree 乘法器集成在 ExecuteStage 中实现
# 
# 架构设计:
# - 输入: 32位 × 32位
# - 输出: 64位 (根据指令选择高32位或低32位)
# - 延迟: 3周期
#
# 支持的指令:
# - MUL:    signed × signed, 返回低32位
# - MULH:   signed × signed, 返回高32位  
# - MULHSU: signed × unsigned, 返回高32位
# - MULHU:  unsigned × unsigned, 返回高32位
#
# Wallace Tree压缩使用 Carry-Save Adder (CSA):
# - 3个操作数 → 2个操作数 (sum + carry)
# - sum = a ^ b ^ c
# - carry = ((a & b) | (b & c) | (a & c)) << 1
# - 只有最终阶段使用普通加法器
#
# 3周期流水线:
# - Cycle 1: 符号扩展 + 部分积生成 + CSA压缩 (32→22→15→10)
# - Cycle 2: 继续CSA压缩 (10→7→5→4→3→2)  
# - Cycle 3: 最终加法 + 结果选择

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

        # IF/ID 寄存器更新:
        # - 暂停时(stall=1): 保持不变
        # - 正常时: 更新为当前取的指令
        with Condition(if_id_valid[0]):
            if_id_pc[0] = stall[0].select(if_id_pc[0], current_pc)
            # if_id_valid 应该在正常情况下保持为1，只有 need_flush 时才清0（由 HazardUnit 处理）
            if_id_prediction_info[0] = stall[0].select(if_id_prediction_info[0], prediction_info)

        decode_stage.async_called()

        # fetch_signals 逻辑:
        # - 正常情况(stall=0, if_id_valid=1): 输出当前取的指令
        # - 暂停情况(stall=1): 输出 if_id_instruction[0] (保持当前指令)
        # - 刷新情况(if_id_valid=0): 输出 if_id_instruction[0] (使用存储的指令)
        fetch_signals = stall[0].select(if_id_instruction[0], if_id_valid[0].select(instruction, if_id_instruction[0])).bitcast(Bits(XLEN))
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
        
        # M扩展指令检测: opcode=0110011, funct7=0000001
        is_m_ext = (is_r_type & (funct7 == UInt(7)(0b0000001)))
        
        # M扩展乘法指令解码 (func3决定具体操作)
        # func3: 000=MUL, 001=MULH, 010=MULHSU, 011=MULHU
        mul_op = UInt(3)(MUL_OP_NONE)
        mul_op = (is_m_ext & (func3 == UInt(3)(0b000))).select(UInt(3)(MUL_OP_MUL), mul_op)     # MUL
        mul_op = (is_m_ext & (func3 == UInt(3)(0b001))).select(UInt(3)(MUL_OP_MULH), mul_op)    # MULH
        mul_op = (is_m_ext & (func3 == UInt(3)(0b010))).select(UInt(3)(MUL_OP_MULHSU), mul_op)  # MULHSU
        mul_op = (is_m_ext & (func3 == UInt(3)(0b011))).select(UInt(3)(MUL_OP_MULHU), mul_op)   # MULHU
        
        # 是否为乘法指令
        is_mul_inst = (mul_op != UInt(3)(MUL_OP_NONE))
        # log("ID DECODE: opcode={:07b}, funct7={:07b}, func3={:03b}, is_r_type={}, is_m_ext={}, mul_op={}, is_mul_inst={}", 
            # opcode, funct7, func3, is_r_type, is_m_ext, mul_op, is_mul_inst)
        
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
        
        # M扩展乘法指令设置
        reg_write = is_mul_inst.select(UInt(1)(1), reg_write)  # 乘法指令写回寄存器
        alu_src = is_mul_inst.select(UInt(2)(0), alu_src)  # 乘法使用寄存器操作数

        reg_write = (rd == UInt(5)(0)).select(UInt(1)(0), reg_write)  # rd为x0时不写入
        
        # 新控制信号格式 (45位):
        # [44:42] - mul_op (3位乘法操作码)
        # [41:30] - 立即数低12位
        # [29:25] - rd地址
        # [24]    - 保留位
        # [23:22] - 存储类型: 00=SB, 01=SH, 10=SW
        # [21]    - jumpr_op
        # [20]    - jump_op
        # [19:17] - branch_op
        # [16:11] - 保留位
        # [10:9]  - alu_src
        # [8]     - mem_to_reg
        # [7]     - reg_write
        # [6]     - mem_write
        # [5]     - mem_read
        # [4:0]   - alu_op
        control_signals = concat(
            mul_op,           # [44:42] 乘法操作码
            immediate[0:11],   # [41:30] 立即数低12位
            rd,               # [29:25] rd地址
            UInt(1)(0),       # [24]    保留位
            store_type_bits,  # [23:22] 存储类型: 00=SB, 01=SH, 10=SW
            jumpr_op,       # [21]    jumpr_op
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

        # 乘法指令也需要rs1和rs2
        need_rs1 = (is_i_type | is_r_type | is_s_type | is_b_type | is_l_type | is_jr_type | is_mul_inst)
        need_rs2 = (is_r_type | is_s_type | is_b_type | is_mul_inst)
        
        
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

        # decode_signals 的生成逻辑:
        # - need_flush=1 (id_ex_valid=0): 输出 0（清空EX阶段）
        # - data_hazard=1 (if_id_valid=0, id_ex_valid=1): 输出旧值（保持EX阶段指令）
        # - 正常情况 (if_id_valid=1, id_ex_valid=1): 输出新值
        # 
        # 逻辑: id_ex_valid.select(if_id_valid.select(new_value, old_value), zero)
        out_control = id_ex_valid[0].select(if_id_valid[0].select(control_signals.bitcast(UInt(CONTROL_LEN)), id_ex_control[0]), UInt(CONTROL_LEN)(0))
        out_mul_op = out_control[42:44]
        # log("DECODE OUT: if_id_valid={}, id_ex_valid={}, control_mul_op={}, id_ex_mul_op={}, out_mul_op={}",
        #     if_id_valid[0], id_ex_valid[0], mul_op, id_ex_control[0][42:44], out_mul_op)
        
        decode_signals = concat(
            id_ex_valid[0].select(if_id_valid[0].select(prediction_info_in, id_ex_prediction_info[0]), UInt(PREDICTION_INFO_LEN)(0)),  # 预测信息 (34位)
            id_ex_valid[0].select(if_id_valid[0].select(need_rs2.bitcast(UInt(1)), id_ex_need_rs2[0].bitcast(UInt(1))), UInt(1)(0)), 
            id_ex_valid[0].select(if_id_valid[0].select(need_rs1.bitcast(UInt(1)), id_ex_need_rs1[0].bitcast(UInt(1))), UInt(1)(0)),
            id_ex_valid[0].select(if_id_valid[0].select(immediate, id_ex_immediate[0]), UInt(XLEN)(0)),
            id_ex_valid[0].select(if_id_valid[0].select(rs2.bitcast(UInt(5)), id_ex_rs2_idx[0]), UInt(5)(0)),
            id_ex_valid[0].select(if_id_valid[0].select(rs1.bitcast(UInt(5)), id_ex_rs1_idx[0]), UInt(5)(0)),
            out_control,
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
    def build(self, id_ex_valid, id_ex_pc, id_ex_rs1_idx, id_ex_rs2_idx, id_ex_immediate, id_ex_control, id_ex_prediction_info, ex_mem_pc, ex_mem_control, ex_mem_valid, ex_mem_result, ex_mem_data, reg_file, memory_stage, mem_wb_control, mem_wb_valid, mem_wb_mem_data, mem_wb_ex_result, data_sram, mul_a, mul_b, mul_op_reg, mul_start, mul_cycle_counter, mul_stage1_sum, mul_stage1_carry, mul_stage2_sum, mul_stage2_carry, mul_valid, mul_result_reg, mul_in_progress, mul_rd_reg, mul_control_reg, mul_pc_reg):
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

        # 解析控制信号 (新格式45位)
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
        mul_op = control_in[42:44]  # 乘法操作码 [44:42]
        
        # 判断是否为乘法指令
        is_mul_inst = (mul_op != UInt(3)(MUL_OP_NONE))
        
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
        
        # ==================== 乘法器逻辑 ====================
        # 乘法器状态检查
        mul_cycle = mul_cycle_counter[0]
        mul_busy = (mul_cycle != UInt(2)(0)).select(UInt(1)(1), UInt(1)(0))
        mul_done = (mul_cycle == UInt(2)(3)).select(UInt(1)(1), UInt(1)(0))
        
        # 当前是否需要启动新的乘法
        # 只有当乘法器空闲且当前指令是乘法指令时才启动
        start_new_mul = (is_mul_inst & id_ex_valid[0] & ~mul_busy).select(UInt(1)(1), UInt(1)(0))
        # log("MUL CHECK: is_mul_inst={}, id_ex_valid={}, mul_busy={}, mul_op={}, start_new_mul={}", 
        #     is_mul_inst, id_ex_valid[0], mul_busy, mul_op, start_new_mul)
        
        # 保存乘法操作数和控制信息
        with Condition(start_new_mul):
            mul_a[0] = rs1_data
            mul_b[0] = rs2_data
            mul_op_reg[0] = mul_op
            mul_rd_reg[0] = rd_addr
            mul_control_reg[0] = control_in
            mul_pc_reg[0] = pc_in
            mul_in_progress[0] = UInt(1)(1)
            mul_cycle_counter[0] = UInt(2)(1)  # 开始第1周期
            # log("MUL START: a={}, b={}, mul_op={}", rs1_data, rs2_data, mul_op)
        
        # ==================== Wallace Tree 乘法器计算 ====================
        # Cycle 1: 生成部分积并进行第一级CSA压缩
        with Condition(mul_cycle == UInt(2)(1)):
            a = mul_a[0]
            b = mul_b[0]
            saved_op = mul_op_reg[0]
            # log("MUL CYCLE 1 READ: a={}, b={}, mul_a[0]={}", a, b, mul_a[0])
            
            # 确定操作数符号属性
            a_signed = ((saved_op == UInt(3)(MUL_OP_MUL)) | (saved_op == UInt(3)(MUL_OP_MULH)) | (saved_op == UInt(3)(MUL_OP_MULHSU))).select(UInt(1)(1), UInt(1)(0))
            b_signed = ((saved_op == UInt(3)(MUL_OP_MUL)) | (saved_op == UInt(3)(MUL_OP_MULH))).select(UInt(1)(1), UInt(1)(0))
            
            # 符号扩展到64位
            a_sign = a[31:31]
            b_sign = b[31:31]
            a_high = (a_signed & a_sign).select(UInt(32)(0xFFFFFFFF), UInt(32)(0))
            b_high = (b_signed & b_sign).select(UInt(32)(0xFFFFFFFF), UInt(32)(0))
            
            # 直接将32位数转为64位进行计算，不使用concat
            a_64 = a.bitcast(UInt(64))
            b_64 = b.bitcast(UInt(64))
            # log("MUL DEBUG3: a={}, a_64={}, b={}, b_64={}", a, a_64, b, b_64)
            
            # 生成32个部分积 (移位后需要bitcast回UInt(64))
            # 使用显式比较确保条件正确
            pp0 = (b[0:0] == UInt(1)(1)).select(a_64, UInt(64)(0))
            pp1 = (b[1:1] == UInt(1)(1)).select((a_64 << UInt(64)(1)).bitcast(UInt(64)), UInt(64)(0))
            pp2 = (b[2:2] == UInt(1)(1)).select((a_64 << UInt(64)(2)).bitcast(UInt(64)), UInt(64)(0))
            pp3 = (b[3:3] == UInt(1)(1)).select((a_64 << UInt(64)(3)).bitcast(UInt(64)), UInt(64)(0))
            pp4 = (b[4:4] == UInt(1)(1)).select((a_64 << UInt(64)(4)).bitcast(UInt(64)), UInt(64)(0))
            pp5 = (b[5:5] == UInt(1)(1)).select((a_64 << UInt(64)(5)).bitcast(UInt(64)), UInt(64)(0))
            pp6 = (b[6:6] == UInt(1)(1)).select((a_64 << UInt(64)(6)).bitcast(UInt(64)), UInt(64)(0))
            pp7 = (b[7:7] == UInt(1)(1)).select((a_64 << UInt(64)(7)).bitcast(UInt(64)), UInt(64)(0))
            pp8 = (b[8:8] == UInt(1)(1)).select((a_64 << UInt(64)(8)).bitcast(UInt(64)), UInt(64)(0))
            pp9 = (b[9:9] == UInt(1)(1)).select((a_64 << UInt(64)(9)).bitcast(UInt(64)), UInt(64)(0))
            pp10 = (b[10:10] == UInt(1)(1)).select((a_64 << UInt(64)(10)).bitcast(UInt(64)), UInt(64)(0))
            pp11 = (b[11:11] == UInt(1)(1)).select((a_64 << UInt(64)(11)).bitcast(UInt(64)), UInt(64)(0))
            pp12 = (b[12:12] == UInt(1)(1)).select((a_64 << UInt(64)(12)).bitcast(UInt(64)), UInt(64)(0))
            pp13 = (b[13:13] == UInt(1)(1)).select((a_64 << UInt(64)(13)).bitcast(UInt(64)), UInt(64)(0))
            pp14 = (b[14:14] == UInt(1)(1)).select((a_64 << UInt(64)(14)).bitcast(UInt(64)), UInt(64)(0))
            pp15 = (b[15:15] == UInt(1)(1)).select((a_64 << UInt(64)(15)).bitcast(UInt(64)), UInt(64)(0))
            pp16 = (b[16:16] == UInt(1)(1)).select((a_64 << UInt(64)(16)).bitcast(UInt(64)), UInt(64)(0))
            pp17 = (b[17:17] == UInt(1)(1)).select((a_64 << UInt(64)(17)).bitcast(UInt(64)), UInt(64)(0))
            pp18 = (b[18:18] == UInt(1)(1)).select((a_64 << UInt(64)(18)).bitcast(UInt(64)), UInt(64)(0))
            pp19 = (b[19:19] == UInt(1)(1)).select((a_64 << UInt(64)(19)).bitcast(UInt(64)), UInt(64)(0))
            pp20 = (b[20:20] == UInt(1)(1)).select((a_64 << UInt(64)(20)).bitcast(UInt(64)), UInt(64)(0))
            pp21 = (b[21:21] == UInt(1)(1)).select((a_64 << UInt(64)(21)).bitcast(UInt(64)), UInt(64)(0))
            pp22 = (b[22:22] == UInt(1)(1)).select((a_64 << UInt(64)(22)).bitcast(UInt(64)), UInt(64)(0))
            pp23 = (b[23:23] == UInt(1)(1)).select((a_64 << UInt(64)(23)).bitcast(UInt(64)), UInt(64)(0))
            pp24 = (b[24:24] == UInt(1)(1)).select((a_64 << UInt(64)(24)).bitcast(UInt(64)), UInt(64)(0))
            pp25 = (b[25:25] == UInt(1)(1)).select((a_64 << UInt(64)(25)).bitcast(UInt(64)), UInt(64)(0))
            pp26 = (b[26:26] == UInt(1)(1)).select((a_64 << UInt(64)(26)).bitcast(UInt(64)), UInt(64)(0))
            pp27 = (b[27:27] == UInt(1)(1)).select((a_64 << UInt(64)(27)).bitcast(UInt(64)), UInt(64)(0))
            pp28 = (b[28:28] == UInt(1)(1)).select((a_64 << UInt(64)(28)).bitcast(UInt(64)), UInt(64)(0))
            pp29 = (b[29:29] == UInt(1)(1)).select((a_64 << UInt(64)(29)).bitcast(UInt(64)), UInt(64)(0))
            pp30 = (b[30:30] == UInt(1)(1)).select((a_64 << UInt(64)(30)).bitcast(UInt(64)), UInt(64)(0))
            pp31 = (b[31:31] == UInt(1)(1)).select((a_64 << UInt(64)(31)).bitcast(UInt(64)), UInt(64)(0))
            
            # CSA函数: sum = a ^ b ^ c, carry = ((a&b)|(b&c)|(a&c)) << 1
            def csa(x, y, z):
                s = (x ^ y ^ z).bitcast(UInt(64))
                c = (((x & y) | (y & z) | (x & z)) << UInt(64)(1)).bitcast(UInt(64))
                return s, c
            
            # 第一级CSA: 32->22 (10组CSA压缩)
            s0, c0 = csa(pp0, pp1, pp2)
            s1, c1 = csa(pp3, pp4, pp5)
            s2, c2 = csa(pp6, pp7, pp8)
            s3, c3 = csa(pp9, pp10, pp11)
            s4, c4 = csa(pp12, pp13, pp14)
            s5, c5 = csa(pp15, pp16, pp17)
            s6, c6 = csa(pp18, pp19, pp20)
            s7, c7 = csa(pp21, pp22, pp23)
            s8, c8 = csa(pp24, pp25, pp26)
            s9, c9 = csa(pp27, pp28, pp29)
            # pp30, pp31 保留
            
            # 第二级CSA: 22->15
            t0, u0 = csa(s0, c0, s1)
            t1, u1 = csa(c1, s2, c2)
            t2, u2 = csa(s3, c3, s4)
            t3, u3 = csa(c4, s5, c5)
            t4, u4 = csa(s6, c6, s7)
            t5, u5 = csa(c7, s8, c8)
            t6, u6 = csa(s9, c9, pp30)
            # pp31 保留
            
            # 第三级CSA: 15->10
            v0, w0 = csa(t0, u0, t1)
            v1, w1 = csa(u1, t2, u2)
            v2, w2 = csa(t3, u3, t4)
            v3, w3 = csa(u4, t5, u5)
            v4, w4 = csa(t6, u6, pp31)
            
            # 第四级CSA: 10->7
            # 输入: v0, w0, v1, w1, v2, w2, v3, w3, v4, w4
            x0, y0 = csa(v0, w0, v1)
            x1, y1 = csa(w1, v2, w2)
            x2, y2 = csa(v3, w3, v4)
            # 保留: w4
            # 输出: x0, y0, x1, y1, x2, y2, w4 (7个)
            
            # 第五级CSA: 7->5
            z0, z1 = csa(x0, y0, x1)
            z2, z3 = csa(y1, x2, y2)
            # 保留: w4
            # 输出: z0, z1, z2, z3, w4 (5个)
            
            # 第六级CSA: 5->4
            q0, q1 = csa(z0, z1, z2)
            # 保留: z3, w4
            # 输出: q0, q1, z3, w4 (4个)
            
            # log("MUL CYCLE 1: a_64={}, b_64={}, pp0={}, pp1={}, pp2={}", a_64, b_64, pp0, pp1, pp2)
            # log("MUL CYCLE 1 END: q0={}, q1={}, z3={}, w4={}", q0, q1, z3, w4)
            
            # 保存4个完整的64位中间值
            mul_stage1_sum[0] = q0
            mul_stage1_carry[0] = q1
            mul_stage2_sum[0] = z3
            mul_stage2_carry[0] = w4
            
            mul_cycle_counter[0] = UInt(2)(2)
        
        # Cycle 2: 继续CSA压缩 (4->3->2)
        with Condition(mul_cycle == UInt(2)(2)):
            # 从寄存器恢复4个64位中间值
            q0_r = mul_stage1_sum[0]
            q1_r = mul_stage1_carry[0]
            z3_r = mul_stage2_sum[0]
            w4_r = mul_stage2_carry[0]
            
            def csa2(x, y, z):
                s = (x ^ y ^ z).bitcast(UInt(64))
                c = (((x & y) | (y & z) | (x & z)) << UInt(64)(1)).bitcast(UInt(64))
                return s, c
            
            # 第七级CSA: 4->3
            r0, r1 = csa2(q0_r, q1_r, z3_r)
            # 保留: w4_r
            # 输出: r0, r1, w4_r (3个)
            
            # 第八级CSA: 3->2
            final_sum, final_carry = csa2(r0, r1, w4_r)
            # 输出: final_sum, final_carry (2个)
            
            # 保存最终的sum和carry
            mul_stage1_sum[0] = final_sum
            mul_stage1_carry[0] = final_carry
            mul_cycle_counter[0] = UInt(2)(3)
        
        # Cycle 3: 最终加法并选择结果
        with Condition(mul_cycle == UInt(2)(3)):
            final_result = mul_stage1_sum[0] + mul_stage1_carry[0]
            saved_op = mul_op_reg[0]
            
            # 根据mul_op选择高32位或低32位
            result_low = final_result[0:31].bitcast(UInt(32))
            result_high = final_result[32:63].bitcast(UInt(32))
            
            # MUL: 低32位; MULH/MULHSU/MULHU: 高32位
            mul_result_val = (saved_op == UInt(3)(MUL_OP_MUL)).select(result_low, result_high)
            # log("MUL CYCLE 3: sum={}, carry={}, final_result={}, result_low={}, saved_op={}", 
                # mul_stage1_sum[0], mul_stage1_carry[0], final_result, result_low, saved_op)
            mul_result_reg[0] = mul_result_val
            mul_valid[0] = UInt(1)(1)
            mul_cycle_counter[0] = UInt(2)(0)
            mul_in_progress[0] = UInt(1)(0)
        
        # 在外部也计算当前周期的乘法结果（供 mul_done 时使用）
        # 这个计算在每个周期都会执行，但只有在 mul_cycle == 3 时结果才有意义
        current_final_result = mul_stage1_sum[0] + mul_stage1_carry[0]
        current_result_low = current_final_result[0:31].bitcast(UInt(32))
        current_result_high = current_final_result[32:63].bitcast(UInt(32))
        current_saved_op = mul_op_reg[0]
        current_mul_result = (current_saved_op == UInt(3)(MUL_OP_MUL)).select(current_result_low, current_result_high)
        
        # 非乘法周期重置valid
        with Condition(mul_cycle == UInt(2)(0)):
            mul_valid[0] = UInt(1)(0)
        
        # ==================== ALU结果选择 ====================
        # 普通ALU结果
        normal_alu_result = is_branch.select(UInt(XLEN)(0), (is_jump | is_jumpr).select(pc_in + UInt(XLEN)(4), self.alu_unit(alu_op, alu_a, alu_b)))
        
        # 乘法完成时使用当前周期计算的乘法结果
        alu_result = mul_done.select(current_mul_result, normal_alu_result)
        # log("EX RESULT: mul_done={}, current_mul_result={}, normal_alu_result={}, alu_result={}", 
            # mul_done, current_mul_result, normal_alu_result, alu_result)
        
        target_pc = (is_branch | is_jump).select(actual_target_pc, target_pc)
        target_pc = is_jumpr.select(new_pc.bitcast(UInt(32)), target_pc)
        
        # 需要刷新的情况: 预测错误、JAL、JALR
        need_flush = (mispredict | is_jump | is_jumpr).select(UInt(1)(1), UInt(1)(0))
        pc_change = need_flush

        # DEBUG: 检查跳转指令
        # with Condition(is_jumpr):
        #     log("EX JALR: PC={:08x}, rs1_data={:08x}, imm={:08x}, target={:08x}, rs1_idx={}", 
        #         pc_in, rs1_data, immediate_in, new_pc, rs1_idx)
        # with Condition(is_jump):
        #     log("EX JAL: PC={:08x}, imm={:08x}, target={:08x}, rd={}", 
        #         pc_in, immediate_in, actual_target_pc, rd_addr)
        # with Condition(is_branch):
        #     log("EX BRANCH: PC={:08x}, taken={}, target={:08x}, rs1={:08x}, rs2={:08x}", 
        #         pc_in, actual_taken, actual_target_pc, rs1_data, rs2_data)
        
        with Condition(is_jump & (immediate_in == UInt(XLEN)(0))):
            log("Finish Execution. The result is {}", reg_file[10])
            finish()
        
        # 乘法指令需要等待乘法完成才能传递到MEM阶段
        # 当乘法器正在执行(cycle 1或2)时，向MEM阶段传递NOP
        # 当乘法完成(cycle 3, mul_done=1)时，传递乘法结果
        mul_in_ex_stage = is_mul_inst & id_ex_valid[0]
        mul_wait = mul_in_ex_stage & ~mul_done  # 乘法未完成，需要等待
        
        # 当乘法完成时，使用保存的控制信息而不是当前的 control_in（因为当前可能是 NOP）
        mul_control = mul_control_reg[0]
        mul_pc = mul_pc_reg[0]
        
        with Condition(ex_mem_valid[0]):
            # 如果是乘法指令且乘法未完成，传递NOP；否则正常传递
            # 乘法完成时 (mul_done=1)，使用保存的控制信息
            should_pass = id_ex_valid[0] & ~mul_wait
            pass_or_mul_done = should_pass | mul_done  # 要么正常传递，要么乘法完成
            
            # PC: 乘法完成时用保存的 PC，否则用当前 PC
            final_pc = mul_done.select(mul_pc, pc_in)
            # 控制信号: 乘法完成时用保存的控制信号，否则用当前控制信号
            final_control = mul_done.select(mul_control, control_in)
            
            ex_mem_pc[0] = pass_or_mul_done.select(final_pc, UInt(XLEN)(0))
            ex_mem_control[0] = pass_or_mul_done.select(final_control, UInt(CONTROL_LEN)(0))
            ex_mem_result[0] = pass_or_mul_done.select(alu_result, UInt(XLEN)(0))
            ex_mem_data[0] = pass_or_mul_done.select(rs2_data, UInt(XLEN)(0))
            
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
        
        # 乘法器信号
        # mul_busy: 乘法器正在执行中 (cycle 1, 2)
        # mul_done: 乘法器完成 (cycle 3)
        # mul_stall: 当前有乘法指令但乘法器正在执行中，需要暂停
        mul_executing = ((mul_cycle == UInt(2)(1)) | (mul_cycle == UInt(2)(2))).select(UInt(1)(1), UInt(1)(0))
        mul_stall_needed = (is_mul_inst & id_ex_valid[0] & mul_executing).select(UInt(1)(1), UInt(1)(0))

        execute_signals = concat(
            mul_stall_needed.bitcast(Bits(1)),   # [180] 乘法暂停信号
            mul_done.bitcast(Bits(1)),           # [179] 乘法完成
            mul_busy.bitcast(Bits(1)),           # [178] 乘法忙
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
        
        # log("WB STAGE: ex_result_in={}, mem_to_reg={}, wb_data={}, wb_rd={}, reg_write={}", 
            # ex_result_in, mem_to_reg, wb_data, wb_rd, reg_write)
            
        # 如果指令无效，直接返回
        with Condition(mem_wb_valid[0]):
            with Condition(reg_write):
                reg_file[wb_rd] = wb_data
                # log("WB WRITE: reg[{}] = {}", wb_rd, wb_data)
            # log("WB: Write_Data={}, RD={}, WE={}",
            #     wb_data, wb_rd, reg_write)
            # success = (wb_data == UInt(XLEN)(5050))
            # with Condition(success):
            #     log("SUCCESSFUL!")

        writeback_signals = control_in.bitcast(Bits(CONTROL_LEN))
        return writeback_signals

class HazardUnit(Downstream):
    """冒险检测单元 - 包含分支预测器更新逻辑"""
    def __init__(self):
        super().__init__()

    @downstream.combinational
    def build(self, pc, stall, if_id_valid, if_id_instruction, if_id_prediction_info, id_ex_control, id_ex_valid, id_ex_rs1_idx, id_ex_rs2_idx, id_ex_immediate, id_ex_prediction_info, ex_mem_valid, mem_wb_valid, btb, bht, btb_valid, fetch_signals, decode_signals, execute_signals, memory_signals, writeback_signals, mul_in_progress, mul_cycle_counter):

        # 计算新的信号长度 (增加3位乘法信号: mul_busy, mul_done, mul_stall_needed)
        EXECUTE_SIGNALS_LEN = XLEN + 1 + CONTROL_LEN + 103 + 3  # pc_change(1) + target_pc(32) + control(45) + prediction_result(103) + mul_signals(3)
        DECODE_SIGNALS_LEN = 2 + CONTROL_LEN + 5 + 5 + XLEN + PREDICTION_INFO_LEN  # need_rs1(1) + need_rs2(1) + control(45) + rs1(5) + rs2(5) + immediate(32) + prediction_info(34)

        execute_signals = execute_signals.optional(Bits(EXECUTE_SIGNALS_LEN)(0))
        decode_signals = decode_signals.optional(Bits(DECODE_SIGNALS_LEN)(0))
        fetch_signals = fetch_signals.optional(Bits(XLEN)(0))
        memory_signals = memory_signals.optional(Bits(CONTROL_LEN)(0))
        writeback_signals = writeback_signals.optional(Bits(CONTROL_LEN)(0))

        # 解析execute_signals
        pc_change = execute_signals[0:0].bitcast(UInt(1))
        target_pc = execute_signals[1:XLEN].bitcast(UInt(XLEN))
        
        # 解析预测结果 (从execute_signals中提取)
        # execute_signals布局: [0]: pc_change, [1:32]: target_pc, [33:77]: control(45), [78:180]: prediction_result(103), [181:183]: mul_signals(3)
        pred_result_start = XLEN + 1 + CONTROL_LEN
        prediction_result = execute_signals[pred_result_start:pred_result_start + 102].bitcast(UInt(103))
        
        # 解析乘法器信号
        mul_signals_start = pred_result_start + 103
        mul_busy_sig = execute_signals[mul_signals_start:mul_signals_start].bitcast(UInt(1))
        mul_done_sig = execute_signals[mul_signals_start + 1:mul_signals_start + 1].bitcast(UInt(1))
        mul_stall_sig = execute_signals[mul_signals_start + 2:mul_signals_start + 2].bitcast(UInt(1))
        
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
        
        # ==================== 乘法冒险检测 ====================
        # 检测EX阶段是否有乘法指令
        ex_control = id_ex_control[0]
        ex_rd = ex_control[25:29]
        ex_mul_op = ex_control[42:44]
        is_ex_mul = (ex_mul_op != UInt(3)(MUL_OP_NONE))
        
        # 乘法暂停条件：
        # 乘法器正在执行中(cycle 1, 2, 或 3)，需要暂停IF/ID阶段
        # cycle 3 (mul_done) 时也需要暂停，因为结果还在 MEM/WB 阶段传递
        mul_cycle = mul_cycle_counter[0]
        # 包含 cycle 1, 2, 3 - 只有 cycle 0 时才不暂停
        mul_executing = (mul_cycle != UInt(2)(0)).select(UInt(1)(1), UInt(1)(0))
        
        # 检测乘法结果冒险：ID阶段的指令依赖于正在执行的乘法结果
        # 使用 is_ex_mul 直接检测 EX 阶段是否有 MUL 指令，而不是依赖 mul_in_progress
        # 因为 mul_in_progress 需要一个周期才能更新，导致在 MUL 开始的同一周期检测失败
        # 条件：EX阶段有MUL指令 且 rd != 0 且 ID阶段指令依赖于rd
        mul_result_hazard = (is_ex_mul & (ex_rd != UInt(5)(0)) &
                            ((needs_rs1 & (rs1 == ex_rd)) | (needs_rs2 & (rs2 == ex_rd))))
        
        # 需要刷新的情况: mispredict || is_jump || is_jumpr
        need_flush = (mispredict | is_jump_ex | is_jumpr_ex).select(UInt(1)(1), UInt(1)(0))
        
        # 综合暂停逻辑：
        # 1. Load-Use 冒险
        # 2. 乘法器执行中（cycle 1或2，需要等待乘法完成）
        # 3. 乘法结果冒险（下一条指令依赖乘法结果）
        data_hazard = ((load_use_hazard_mem | mul_executing | mul_result_hazard) & ~need_flush)
        # log("HAZARD2: data_hazard={}, need_flush={}, mul_executing={}, mul_result_hazard={}", 
        #     data_hazard, need_flush, mul_executing, mul_result_hazard)
        
        # id_ex_valid 的含义：EX阶段是否有有效指令需要执行
        # - need_flush时，EX阶段指令作废，设为0
        # - data_hazard时，EX阶段指令仍然有效（只是IF/ID暂停），保持为1
        # 但是！如果是因为mul_executing导致的data_hazard，说明乘法正在执行，
        # 此时我们不应该再次启动乘法，所以对于新指令的启动检查应该用额外的信号
        id_ex_valid[0] = (~need_flush)
        # if_id_valid控制是否接受新指令到ID阶段
        if_id_valid[0] = (~data_hazard & ~need_flush)
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
        # JAL时使用actual_target_pc (pc + immediate)
        # 分支误预测时使用correct_pc
        flush_pc = is_jumpr_ex.select(target_pc, is_jump_ex.select(actual_target_pc, correct_pc))
        
        # 关键修复：当上一个周期是 flush 时 (if_id_valid[0]=0)，
        # 当前周期 IF 阶段正在取新指令，不应该更新 PC
        # 只有当 if_id_valid[0]=1 时才正常更新 PC
        if_id_valid_current = if_id_valid[0]  # 上一个周期的 if_id_valid 值
        
        # DEBUG: 检查 flush_pc 和 target_pc
        # log("HAZARD PC: is_jumpr_ex={}, target_pc={}, correct_pc={}, flush_pc={}, need_flush={}, if_id_valid_current={}",
        #     is_jumpr_ex, target_pc, correct_pc, flush_pc, need_flush, if_id_valid_current)
        
        # PC 更新逻辑：
        # - need_flush=1: 跳转到 flush_pc
        # - need_flush=0 且 if_id_valid_current=0: 保持 PC 不变（上一周期刚 flush，正在取指令）
        # - need_flush=0 且 if_id_valid_current=1 且 data_hazard=1: 保持 PC 不变（暂停）
        # - need_flush=0 且 if_id_valid_current=1 且 data_hazard=0: PC = normal_next_pc
        pc_hold_after_flush = (~if_id_valid_current & ~need_flush).select(pc[0], normal_next_pc)
        pc_with_hazard = data_hazard.select(pc[0], pc_hold_after_flush)
        pc[0] = need_flush.select(flush_pc, pc_with_hazard)
        # log("HAZARD PC RESULT: pc[0]={}", pc[0])
        
        # 流水线刷新 (根据branch_prediction_rules.md)
        # IF/ID阶段刷新: if_id_valid[0] = 0, if_id_pc[0] = 0, if_id_instruction[0] = NOP
        # ID/EX阶段刷新: 清空所有寄存器
        
        # IF/ID 寄存器更新逻辑:
        # - need_flush=1: 写入NOP
        # - data_hazard=1: 保持当前指令（暂停，等待冒险解决）
        # - 正常情况: 写入新指令
        with Condition(~data_hazard):
            # 只有在不暂停时才更新 IF/ID 指令寄存器
            if_id_instruction[0] = need_flush.select(UInt(XLEN)(0x00000013), instruction)  # NOP指令
            if_id_prediction_info[0] = need_flush.select(UInt(PREDICTION_INFO_LEN)(0), prediction_info_id)
        
        # ID/EX 寄存器更新逻辑:
        # - need_flush=1: 清空（写入NOP）
        # - data_hazard=1: 插入气泡（NOP），ID阶段指令等待冒险解决
        # - 正常情况: 更新为新指令
        with Condition(id_ex_valid[0]):
            # 当刷新或暂停时清空，否则更新为新指令
            should_insert_nop = (need_flush | data_hazard).select(UInt(1)(1), UInt(1)(0))
            id_ex_control[0] = should_insert_nop.select(nop_control, control_in)
            id_ex_immediate[0] = should_insert_nop.select(UInt(XLEN)(0), immediate)
            id_ex_rs1_idx[0] = should_insert_nop.select(UInt(5)(0), rs1)
            id_ex_rs2_idx[0] = should_insert_nop.select(UInt(5)(0), rs2)
            id_ex_prediction_info[0] = should_insert_nop.select(UInt(PREDICTION_INFO_LEN)(0), prediction_info_id)

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
        id_ex_control = RegArray(UInt(CONTROL_LEN), 1, initializer=[0])  # 控制信号 (45位)
        id_ex_valid = RegArray(UInt(1), 1, initializer=[1])            # 有效标志 (1位)
        id_ex_rs1_idx = RegArray(UInt(5), 1, initializer=[0])         # rs1索引 (5位)
        id_ex_rs2_idx = RegArray(UInt(5), 1, initializer=[0])         # rs2索引 (5位)
        id_ex_immediate = RegArray(UInt(XLEN), 1, initializer=[0])    # 立即数 (32位)
        id_ex_need_rs1 = RegArray(UInt(1), 1, initializer=[0])        # 是否需要rs1 (1位)
        id_ex_need_rs2 = RegArray(UInt(1), 1, initializer=[0])        # 是否需要rs2 (1位)
        id_ex_prediction_info = RegArray(UInt(PREDICTION_INFO_LEN), 1, initializer=[0])  # 预测信息 (34位)

        # EX/MEM阶段寄存器
        ex_mem_pc = RegArray(UInt(XLEN), 1, initializer=[0])           # PC (32位)
        ex_mem_control = RegArray(UInt(CONTROL_LEN), 1, initializer=[0])  # 控制信号 (45位)
        ex_mem_valid = RegArray(UInt(1), 1, initializer=[1])            # 有效标志 (1位)
        ex_mem_result = RegArray(UInt(XLEN), 1, initializer=[0])       # ALU结果 (32位)
        ex_mem_data = RegArray(UInt(XLEN), 1, initializer=[0])          # 数据 (32位)

        # MEM/WB阶段寄存器
        mem_wb_control = RegArray(UInt(CONTROL_LEN), 1, initializer=[0])  # 控制信号 (45位)
        mem_wb_valid = RegArray(UInt(1), 1, initializer=[1])            # 有效标志 (1位)
        mem_wb_mem_data = RegArray(UInt(XLEN), 1, initializer=[0])     # 内存数据 (32位)
        mem_wb_ex_result = RegArray(UInt(XLEN), 1, initializer=[0])     # EX阶段结果 (32位)

        # ==================== 乘法器寄存器 ====================
        # Wallace Tree 乘法器流水线寄存器
        mul_a = RegArray(UInt(32), 1, initializer=[0])                # 乘法操作数A
        mul_b = RegArray(UInt(32), 1, initializer=[0])                # 乘法操作数B
        mul_op_reg = RegArray(UInt(3), 1, initializer=[0])            # 乘法操作码
        mul_start = RegArray(UInt(1), 1, initializer=[0])             # 乘法开始信号
        mul_cycle_counter = RegArray(UInt(2), 1, initializer=[0])     # 乘法周期计数器 (0=空闲, 1/2/3=执行中)
        mul_stage1_sum = RegArray(UInt(64), 1, initializer=[0])       # 第一级CSA压缩结果-sum
        mul_stage1_carry = RegArray(UInt(64), 1, initializer=[0])     # 第一级CSA压缩结果-carry
        mul_stage2_sum = RegArray(UInt(64), 1, initializer=[0])       # 第二级CSA压缩结果-sum
        mul_stage2_carry = RegArray(UInt(64), 1, initializer=[0])     # 第二级CSA压缩结果-carry
        mul_valid = RegArray(UInt(1), 1, initializer=[0])             # 乘法结果有效
        mul_result_reg = RegArray(UInt(32), 1, initializer=[0])       # 乘法结果
        mul_in_progress = RegArray(UInt(1), 1, initializer=[0])       # 乘法执行中标志
        mul_rd_reg = RegArray(UInt(5), 1, initializer=[0])            # 乘法目标寄存器
        mul_control_reg = RegArray(UInt(CONTROL_LEN), 1, initializer=[0])  # 乘法控制信号
        mul_pc_reg = RegArray(UInt(XLEN), 1, initializer=[0])         # 乘法指令PC

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
        execute_signals = execute_stage.build(id_ex_valid, id_ex_pc, id_ex_rs1_idx, id_ex_rs2_idx, id_ex_immediate, id_ex_control, id_ex_prediction_info, ex_mem_pc, ex_mem_control, ex_mem_valid, ex_mem_result, ex_mem_data, reg_file, memory_stage, mem_wb_control, mem_wb_valid, mem_wb_mem_data, mem_wb_ex_result, data_sram, mul_a, mul_b, mul_op_reg, mul_start, mul_cycle_counter, mul_stage1_sum, mul_stage1_carry, mul_stage2_sum, mul_stage2_carry, mul_valid, mul_result_reg, mul_in_progress, mul_rd_reg, mul_control_reg, mul_pc_reg)
        decode_signals = decode_stage.build(if_id_valid, if_id_pc, if_id_instruction, if_id_prediction_info, id_ex_pc, id_ex_control, id_ex_valid, id_ex_rs1_idx, id_ex_rs2_idx, id_ex_immediate, id_ex_need_rs1, id_ex_need_rs2, id_ex_prediction_info, reg_file, execute_stage)
        fetch_signals = fetch_stage.build(pc, stall, if_id_pc, if_id_instruction, if_id_valid, if_id_prediction_info, instruction_memory, btb, bht, btb_valid, decode_stage)
        hazard_unit.build(pc, stall, if_id_valid, if_id_instruction, if_id_prediction_info, id_ex_control, id_ex_valid, id_ex_rs1_idx, id_ex_rs2_idx, id_ex_immediate, id_ex_prediction_info, ex_mem_valid, mem_wb_valid, btb, bht, btb_valid, fetch_signals, decode_signals, execute_signals, memory_signals, writeback_signals, mul_in_progress, mul_cycle_counter)
        
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
