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

# ==================== OoO 相关常量 ===================
ROB_SIZE = 16       # ROB 大小
ROB_ID_BITS = 4     # ROB ID 位宽 (log2(16) = 4)

# Phase 3: RS 相关常量
RS_SIZE = 8         # RS 条目数量
RS_ID_BITS = 3      # RS ID 位宽 (log2(8) = 3)

# 功能单元类型编码
FU_ALU    = 0b000   # ALU 运算
FU_BRANCH = 0b001   # 分支计算
FU_LOAD   = 0b010   # Load
FU_STORE  = 0b011   # Store
FU_MUL    = 0b100   # 乘法
FU_DIV    = 0b101   # 除法

# Phase 4: 多周期 FU 延迟
MUL_LATENCY = 3     # 乘法 3 周期
DIV_LATENCY = 10    # 除法 10 周期

# Phase 5: LSQ 相关常量
LSQ_SIZE = 8        # LSQ 大小
LSQ_ID_BITS = 3     # LSQ ID 位宽 (log2(8) = 3)

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
    def build(self, if_id_valid, if_id_pc, if_id_instruction, id_ex_pc, id_ex_control, id_ex_valid, id_ex_rs1_idx, id_ex_rs2_idx, id_ex_immediate, id_ex_need_rs1, id_ex_need_rs2, 
              rat_valid, rat_tag, rob_head, rob_tail, rob_valid, rob_ready, rob_value, rob_dest, rob_pc,
              rob_old_tag_valid, rob_old_tag,
              rs_busy, rs_op, rs_vj, rs_vk, rs_qj, rs_qk, rs_qj_valid, rs_qk_valid, rs_dest_arr, rs_imm, rs_func, rs_control, rs_lsq_id, rs_pc,
              lsq_valid, lsq_is_store, lsq_addr_ready, lsq_data_ready, lsq_addr, lsq_data, lsq_rob_id, lsq_done, lsq_head, lsq_tail,
              rob_is_store, rob_lsq_id,
              issue_ex_valid, issue_ex_op, issue_ex_vj, issue_ex_vk, issue_ex_dest, issue_ex_imm, issue_ex_control, issue_ex_func, issue_ex_lsq_id,
              md_busy,
              # 多 FU 并行: 各 FU 独立寄存器
              alu_fu_valid, alu_fu_op, alu_fu_vj, alu_fu_vk, alu_fu_dest, alu_fu_imm, alu_fu_control,
              branch_fu_valid, branch_fu_vj, branch_fu_vk, branch_fu_dest, branch_fu_imm, branch_fu_control, branch_fu_pc,
              lsq_fu_valid, lsq_fu_lsq_id, lsq_fu_vj, lsq_fu_vk, lsq_fu_imm, lsq_fu_dest, lsq_fu_is_store, lsq_fu_control,
              reg_file, dispatch_issue_stage, execute_stage):
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
        
        # ==================== RAT 查询逻辑 ====================
        # rs1 操作数查询
        rs1_rat_valid = rat_valid[rs1]  # 是否有未提交指令写 rs1
        rs1_rat_tag = rat_tag[rs1]      # 对应的 ROB ID
        
        rs1_from_rf = ~rs1_rat_valid                           # 从RF取值
        rs1_from_rob = rs1_rat_valid & rob_ready[rs1_rat_tag]  # 从ROB取值
        rs1_need_tag = rs1_rat_valid & ~rob_ready[rs1_rat_tag] # 需要等待
        
        rs1_value = rs1_from_rf.select(
            reg_file[rs1],
            rs1_from_rob.select(rob_value[rs1_rat_tag], UInt(XLEN)(0))
        )
        rs1_tag_out = rs1_need_tag.select(rs1_rat_tag, UInt(ROB_ID_BITS)(0))
        rs1_ready = (rs1_from_rf | rs1_from_rob).bitcast(UInt(1))
        
        # rs2 操作数查询
        rs2_rat_valid = rat_valid[rs2]
        rs2_rat_tag = rat_tag[rs2]
        
        rs2_from_rf = ~rs2_rat_valid
        rs2_from_rob = rs2_rat_valid & rob_ready[rs2_rat_tag]
        rs2_need_tag = rs2_rat_valid & ~rob_ready[rs2_rat_tag]
        
        rs2_value = rs2_from_rf.select(
            reg_file[rs2],
            rs2_from_rob.select(rob_value[rs2_rat_tag], UInt(XLEN)(0))
        )
        rs2_tag_out = rs2_need_tag.select(rs2_rat_tag, UInt(ROB_ID_BITS)(0))
        rs2_ready = (rs2_from_rf | rs2_from_rob).bitcast(UInt(1))
        
        # 分配 ROB ID (用于目标寄存器)
        allocated_rob_id = rob_tail[0]
        
        # ==================== ROB 满检测 ====================
        # 计算下一个 tail 位置
        next_rob_tail = (rob_tail[0] + UInt(ROB_ID_BITS)(1)) & UInt(ROB_ID_BITS)(ROB_SIZE - 1)
        # ROB 满的条件：下一个 tail 位置等于 head
        rob_full = (next_rob_tail == rob_head[0])
        
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
        
        # ==================== RAT 更新逻辑 ====================
        # 当有写寄存器操作且目标不是x0且ROB未满时，更新RAT
        with Condition(if_id_valid[0] & reg_write & (rd != UInt(5)(0)) & ~rob_full):
            # 保存旧的 RAT 映射到 ROB（用于 Walk-back 恢复）
            rob_old_tag_valid[allocated_rob_id] = rat_valid[rd]
            rob_old_tag[allocated_rob_id] = rat_tag[rd]
            
            # 更新 RAT
            rat_valid[rd] = UInt(1)(1)
            rat_tag[rd] = allocated_rob_id
            
            # 同时在ROB中分配条目
            rob_valid[allocated_rob_id] = UInt(1)(1)
            rob_ready[allocated_rob_id] = UInt(1)(0)  # 结果未就绪
            rob_dest[allocated_rob_id] = rd.bitcast(UInt(5))
            rob_pc[allocated_rob_id] = if_id_pc_in
            # 递增 rob_tail (环形队列)
            rob_tail[0] = next_rob_tail
            log("RAT Update: rd={}, rob_id={}, old_valid={}, old_tag={}", rd, allocated_rob_id, rat_valid[rd], rat_tag[rd])
        
        # rs1 = (~if_id_valid[0]).select(Bits(5)(0), rs1)
        # rs2 = (~if_id_valid[0]).select(Bits(5)(0), rs2)
        # immediate = (~if_id_valid[0]).select(UInt(XLEN)(0), immediate)
        # control_signals = (~if_id_valid[0]).select(Bits(CONTROL_LEN)(0), control_signals)

        # Phase 3: 调用 Dispatch 阶段将指令放入 RS
        dispatch_valid = if_id_valid[0] & id_ex_valid[0] & ~rob_full
        rs_full, issue_valid = dispatch_issue_stage.build(
            dispatch_valid, control_signals.bitcast(UInt(CONTROL_LEN)), immediate, allocated_rob_id, if_id_pc_in,
            rs1_value, rs1_tag_out, rs1_ready,
            rs2_value, rs2_tag_out, rs2_ready,
            rs_busy, rs_op, rs_vj, rs_vk, rs_qj, rs_qk, rs_qj_valid, rs_qk_valid,
            rs_dest_arr, rs_imm, rs_func, rs_control, rs_lsq_id, rs_pc,
            lsq_valid, lsq_is_store, lsq_addr_ready, lsq_data_ready,
            lsq_addr, lsq_data, lsq_rob_id, lsq_done,
            lsq_head, lsq_tail,
            rob_is_store, rob_lsq_id,
            issue_ex_valid, issue_ex_op, issue_ex_vj, issue_ex_vk, issue_ex_dest, issue_ex_imm, issue_ex_control, issue_ex_func,
            issue_ex_lsq_id,
            md_busy,
            # 多 FU 并行: 各 FU 独立寄存器
            alu_fu_valid, alu_fu_op, alu_fu_vj, alu_fu_vk, alu_fu_dest, alu_fu_imm, alu_fu_control,
            branch_fu_valid, branch_fu_vj, branch_fu_vk, branch_fu_dest, branch_fu_imm, branch_fu_control, branch_fu_pc,
            lsq_fu_valid, lsq_fu_lsq_id, lsq_fu_vj, lsq_fu_vk, lsq_fu_imm, lsq_fu_dest, lsq_fu_is_store, lsq_fu_control,
            execute_stage)
        
        execute_stage.async_called()

        decode_signals = concat(
            # rs_full 信号
            id_ex_valid[0].select(if_id_valid[0].select(rs_full, UInt(1)(0)), UInt(1)(0)),  # RS满标志
            # OoO 相关信号
            id_ex_valid[0].select(if_id_valid[0].select(rob_full, UInt(1)(0)), UInt(1)(0)),  # ROB满标志 (新增)
            id_ex_valid[0].select(if_id_valid[0].select(allocated_rob_id, UInt(ROB_ID_BITS)(0)), UInt(ROB_ID_BITS)(0)),  # 分配的ROB ID
            id_ex_valid[0].select(if_id_valid[0].select(rs2_value, UInt(XLEN)(0)), UInt(XLEN)(0)),      # rs2值
            id_ex_valid[0].select(if_id_valid[0].select(rs2_tag_out, UInt(ROB_ID_BITS)(0)), UInt(ROB_ID_BITS)(0)),  # rs2 tag
            id_ex_valid[0].select(if_id_valid[0].select(rs2_ready, UInt(1)(0)), UInt(1)(0)),            # rs2就绪
            id_ex_valid[0].select(if_id_valid[0].select(rs1_value, UInt(XLEN)(0)), UInt(XLEN)(0)),      # rs1值
            id_ex_valid[0].select(if_id_valid[0].select(rs1_tag_out, UInt(ROB_ID_BITS)(0)), UInt(ROB_ID_BITS)(0)),  # rs1 tag
            id_ex_valid[0].select(if_id_valid[0].select(rs1_ready, UInt(1)(0)), UInt(1)(0)),            # rs1就绪
            # 原有信号
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
    
    # Phase 4: MulDiv 单元 (组合逻辑部分，用于计算结果)
    def muldiv_unit(self, op: Value, a: Value, b: Value):
        """乘除计算单元 - 仅计算结果，多周期由状态机控制"""
        result = UInt(XLEN)(0)
        a_signed = a.bitcast(Int(XLEN))
        b_signed = b.bitcast(Int(XLEN))
        
        # MUL: result = (a * b)[31:0]
        mul_result = (a * b).bitcast(UInt(XLEN))
        # MULH: result = (signed(a) * signed(b))[63:32]
        mulh_result = ((a_signed * b_signed) >> Int(32)(32)).bitcast(UInt(XLEN))
        # DIV: result = signed(a) / signed(b)
        div_result = (b != UInt(XLEN)(0)).select(
            (a_signed / b_signed).bitcast(UInt(XLEN)), 
            UInt(XLEN)(0xFFFFFFFF)  # 除以 0 返回 -1
        )
        # REM: result = signed(a) % signed(b)
        rem_result = (b != UInt(XLEN)(0)).select(
            (a_signed % b_signed).bitcast(UInt(XLEN)),
            a  # 除以 0 返回被除数
        )
        
        # 根据 op 选择结果 (使用 alu_op 的低 3 位区分 M 扩展指令)
        result = (op[0:2] == UInt(3)(0b000)).select(mul_result, result)   # MUL
        result = (op[0:2] == UInt(3)(0b001)).select(mulh_result, result)  # MULH
        result = (op[0:2] == UInt(3)(0b100)).select(div_result, result)   # DIV
        result = (op[0:2] == UInt(3)(0b110)).select(rem_result, result)   # REM
        
        log("MULDIV: OP={:05b}, A={:08x}, B={:08x}, Result={:08x}", op, a, b, result)
        
        return result

    @module.combinational
    def build(self, id_ex_valid, id_ex_pc, id_ex_rs1_idx, id_ex_rs2_idx, id_ex_immediate, id_ex_control,
              id_ex_rob_id,  # Phase 2: ROB ID from Decode
              ex_mem_pc, ex_mem_control, ex_mem_valid, ex_mem_result, ex_mem_data, ex_mem_target_pc, ex_mem_pc_change,
              ex_mem_rob_id,  # Phase 2: ROB ID to Memory
              ex_mem_lsq_id,  # Phase 5: LSQ ID to Memory
              # Phase 4: MulDiv 状态寄存器
              md_busy, md_cnt, md_op, md_vj, md_vk, md_dest,
              md_pending, md_pending_value, md_pending_dest,
              # Phase 5: LSQ 相关
              issue_ex_lsq_id, lsq_addr, lsq_addr_ready, lsq_data, lsq_data_ready,
              # 多 FU 并行: 各 FU 输入寄存器
              alu_fu_valid, alu_fu_op, alu_fu_vj, alu_fu_vk, alu_fu_dest, alu_fu_imm, alu_fu_control,
              branch_fu_valid, branch_fu_vj, branch_fu_vk, branch_fu_dest, branch_fu_imm, branch_fu_control, branch_fu_pc,
              lsq_fu_valid, lsq_fu_lsq_id, lsq_fu_vj, lsq_fu_vk, lsq_fu_imm, lsq_fu_dest, lsq_fu_is_store, lsq_fu_control,
              # 多 FU 并行: 4条独立CDB
              cdb_alu_valid, cdb_alu_tag, cdb_alu_value,
              cdb_branch_valid, cdb_branch_tag, cdb_branch_value,
              cdb_md_valid, cdb_md_tag, cdb_md_value,
              cdb_lsq_valid, cdb_lsq_tag, cdb_lsq_value,
              reg_file, memory_stage):
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
        
        # ========== Phase 4: MulDiv FU 多周期状态机 ==========
        # 检测是否为 MulDiv 指令 (使用 alu_op 的高位判断 M 扩展)
        is_muldiv_op = (alu_op[3:4] == UInt(2)(0b01))  # M 扩展指令 alu_op = 0b01xxx
        is_mul = is_muldiv_op & (alu_op[2:2] == UInt(1)(0))  # MUL/MULH
        is_div = is_muldiv_op & (alu_op[2:2] == UInt(1)(1))  # DIV/REM
        
        # 启动新的 MulDiv 运算
        with Condition(id_ex_valid[0] & is_muldiv_op & ~md_busy[0]):
            md_busy[0] = UInt(1)(1)
            md_op[0] = alu_op
            md_vj[0] = rs1_data
            md_vk[0] = alu_b
            md_dest[0] = id_ex_rob_id[0]
            # 设置延迟周期数
            md_cnt[0] = is_mul.select(UInt(4)(MUL_LATENCY), UInt(4)(DIV_LATENCY))
            log("MulDiv Start: op={:05b}, vj={:08x}, vk={:08x}, dest=ROB[{}], latency={}",
                alu_op, rs1_data, alu_b, id_ex_rob_id[0], md_cnt[0])
        
        # 递减计数器
        with Condition(md_busy[0] & (md_cnt[0] > UInt(4)(1))):
            md_cnt[0] = md_cnt[0] - UInt(4)(1)
        
        # MulDiv 完成检测
        md_done = md_busy[0] & (md_cnt[0] == UInt(4)(1))
        md_result = self.muldiv_unit(md_op[0], md_vj[0], md_vk[0])
        
        with Condition(md_done):
            md_busy[0] = UInt(1)(0)
            log("MulDiv Done: dest=ROB[{}], result={:08x}", md_dest[0], md_result)
        
        # 处理 pending 的 MulDiv 结果 (上周期被抢占的)
        with Condition(md_pending[0]):
            md_pending[0] = UInt(1)(0)
            log("MulDiv Pending Cleared: dest=ROB[{}], value={:08x}", md_pending_dest[0], md_pending_value[0])
        
        # 如果当前有 Branch 且 MulDiv 同时完成，MulDiv 进入 pending
        with Condition(md_done & is_branch & branch_result.bitcast(UInt(1))):
            md_pending[0] = UInt(1)(1)
            md_pending_value[0] = md_result
            md_pending_dest[0] = md_dest[0]
        
        # MulDiv 指令不写 ex_mem 流水线（结果直接通过 CDB 广播）
        # 修正 alu_result：MulDiv 指令结果不经过普通 ALU 路径
        alu_result = is_muldiv_op.select(UInt(XLEN)(0), alu_result)

        with Condition(is_jump & (immediate_in == UInt(XLEN)(0))):
            log("Finish Execution. The result is {}", reg_file[10])
            finish()
        
        # Phase 5: LSQ 地址/数据回填
        lsq_id = issue_ex_lsq_id[0]
        is_load = mem_read
        is_store = mem_write
        
        with Condition(id_ex_valid[0] & (is_load | is_store)):
            # 地址 = alu_result (rs1 + imm)
            lsq_addr[lsq_id] = alu_result
            lsq_addr_ready[lsq_id] = UInt(1)(1)
            log("EX: LSQ[{}] addr={:08x} ready", lsq_id, alu_result)
        
        with Condition(id_ex_valid[0] & is_store):
            # Store 数据 = rs2
            lsq_data[lsq_id] = rs2_data
            lsq_data_ready[lsq_id] = UInt(1)(1)
            log("EX: LSQ[{}] store_data={:08x} ready", lsq_id, rs2_data)

        with Condition(ex_mem_valid[0]):
            ex_mem_pc[0] = id_ex_valid[0].select(pc_in, UInt(XLEN)(0))
            ex_mem_control[0] = id_ex_valid[0].select(control_in, UInt(CONTROL_LEN)(0))
            # ex_mem_valid[0] = UInt(1)(1)
            ex_mem_result[0] = id_ex_valid[0].select(alu_result, UInt(XLEN)(0))
            ex_mem_data[0] = id_ex_valid[0].select(rs2_data, UInt(XLEN)(0))
            ex_mem_rob_id[0] = id_ex_valid[0].select(id_ex_rob_id[0], UInt(ROB_ID_BITS)(0))
            ex_mem_lsq_id[0] = id_ex_valid[0].select(issue_ex_lsq_id[0], UInt(LSQ_ID_BITS)(0))  # Phase 5
            
            log("EX: PC={}, ALU_OP={:05b}, ALU_A={}, ALU_B={}, Result={:08x}, PC_Change={}, Target_PC={:08x}, Immediate={:08x}, ALU_SRC={}",
                pc_in, alu_op, alu_a, alu_b, alu_result, pc_change, target_pc, immediate_in, alu_src)
        
        # ========== 多 FU 并行执行 + CDB 广播 ==========
        # ALU FU: 单周期执行，立即广播到 CDB_ALU
        with Condition(alu_fu_valid[0]):
            alu_fu_result = self.alu_unit(alu_fu_op[0], alu_fu_vj[0], alu_fu_vk[0])
            cdb_alu_valid[0] = UInt(1)(1)
            cdb_alu_tag[0] = alu_fu_dest[0]
            cdb_alu_value[0] = alu_fu_result
            alu_fu_valid[0] = UInt(1)(0)  # 清除 FU 占用
            log("CDB_ALU: tag=ROB[{}], value={:08x}", alu_fu_dest[0], alu_fu_result)
        with Condition(~alu_fu_valid[0]):
            cdb_alu_valid[0] = UInt(1)(0)
        
        # Branch FU: 单周期执行，广播分支结果到 CDB_Branch
        # 注意: 分支结果也需要标记 ROB ready (即使 rd=x0)
        with Condition(branch_fu_valid[0]):
            branch_fu_control_in = branch_fu_control[0]
            branch_fu_branch_op = branch_fu_control_in[17:19]
            branch_taken = self.branch_unit(branch_fu_branch_op, branch_fu_vj[0], branch_fu_vk[0])
            # 分支指令返回的"值"用于指示跳转目标 (仅供 ROB 记录)
            branch_fu_target = branch_fu_pc[0] + branch_fu_imm[0]
            branch_fu_value = branch_taken.select(branch_fu_target, branch_fu_pc[0] + UInt(XLEN)(4))
            cdb_branch_valid[0] = UInt(1)(1)
            cdb_branch_tag[0] = branch_fu_dest[0]
            cdb_branch_value[0] = branch_fu_value
            branch_fu_valid[0] = UInt(1)(0)  # 清除 FU 占用
            log("CDB_Branch: tag=ROB[{}], taken={}, target={:08x}", branch_fu_dest[0], branch_taken, branch_fu_target)
        with Condition(~branch_fu_valid[0]):
            cdb_branch_valid[0] = UInt(1)(0)
        
        # MulDiv FU: 多周期执行，完成时广播到 CDB_MD
        with Condition(md_done):
            cdb_md_valid[0] = UInt(1)(1)
            cdb_md_tag[0] = md_dest[0]
            cdb_md_value[0] = md_result
            log("CDB_MD: tag=ROB[{}], value={:08x}", md_dest[0], md_result)
        with Condition(~md_done):
            cdb_md_valid[0] = UInt(1)(0)
        
        # LSQ FU: 执行地址计算并更新 LSQ
        with Condition(lsq_fu_valid[0]):
            lsq_fu_addr = lsq_fu_vj[0] + lsq_fu_imm[0]  # 地址 = base + offset
            lsq_fu_id = lsq_fu_lsq_id[0]
            lsq_addr[lsq_fu_id] = lsq_fu_addr
            lsq_addr_ready[lsq_fu_id] = UInt(1)(1)
            log("LSQ_FU: LSQ[{}] addr={:08x} computed", lsq_fu_id, lsq_fu_addr)
            
            with Condition(lsq_fu_is_store[0]):
                # Store: 写入 data
                lsq_data[lsq_fu_id] = lsq_fu_vk[0]
                lsq_data_ready[lsq_fu_id] = UInt(1)(1)
                log("LSQ_FU: Store LSQ[{}] data={:08x} ready", lsq_fu_id, lsq_fu_vk[0])
            
            # LSQ 结果通过 CDB_LSQ 广播 (仅 Load 需要，Store 由 Commit 处理)
            # 注意: Load 结果需要等待内存返回，这里先清除 FU 有效位
            lsq_fu_valid[0] = UInt(1)(0)
        
        # CDB_LSQ: Load 结果广播 (由 MemoryStage 或 LSQ 前递设置)
        # 这里暂时保持空，Load 结果在 MemoryStage 完成后通过其他路径广播
        # TODO: 完整实现需要 Load 完成后的 CDB 广播逻辑

        memory_stage.async_called()

        execute_signals = concat(
            ex_mem_valid[0].select(id_ex_valid[0].select(control_in.bitcast(Bits(CONTROL_LEN)), Bits(CONTROL_LEN)(0)), ex_mem_control[0].bitcast(Bits(CONTROL_LEN))),  # 控制信号
            ex_mem_valid[0].select(id_ex_valid[0].select(target_pc, UInt(XLEN)(0)), ex_mem_target_pc[0]),       # 目标PC
            ex_mem_valid[0].select(id_ex_valid[0].select(pc_change, UInt(1)(0)), ex_mem_pc_change[0]),          # PC变化标志
        )

        return execute_signals

# ==================== MEM阶段：内存访问 ===================
class MemoryStage(Module):
    """内存访问阶段(MEM)"""
    def __init__(self):
        super().__init__(ports={})
    
    @module.combinational
    def build(self, ex_mem_valid, ex_mem_result, ex_mem_pc, ex_mem_data, ex_mem_control,
              ex_mem_rob_id,  # Phase 2: ROB ID from Execute
              ex_mem_lsq_id,  # Phase 5: LSQ ID
              mem_wb_control, mem_wb_valid, mem_wb_mem_data, mem_wb_ex_result,
              mem_wb_rob_id,  # Phase 2: ROB ID to Writeback
              mem_wb_lsq_id,  # Phase 5: LSQ ID to Writeback
              # Phase 5: LSQ 前递结果
              forward_hit, forward_data, load_blocked,
              lsq_done,  # Phase 5: LSQ done 标记
              writeback_stage, data_sram):
        pc_in = ex_mem_pc[0]
        addr_in = ex_mem_result[0]
        data_in = ex_mem_data[0]
        control_in = ex_mem_control[0]
        lsq_id = ex_mem_lsq_id[0]
        
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
                    # Phase 5: Load 前递检查
                    with Condition(mem_read & forward_hit):
                        # 前递命中，使用前递数据
                        mem_wb_mem_data[0] = forward_data
                        lsq_done[lsq_id] = UInt(1)(1)
                        log("MEM: Load LSQ[{}] forwarded data={:08x}", lsq_id, forward_data)
                    with Condition(mem_read & ~forward_hit & ~load_blocked):
                        # 无前递，从内存读取
                        data_sram.build(we=UInt(1)(0), re=UInt(1)(1), addr=word_addr, wdata=UInt(XLEN)(0))
                        mem_wb_mem_data[0] = data_sram.dout[0]
                        lsq_done[lsq_id] = UInt(1)(1)
                        log("MEM: Load LSQ[{}] from memory, data={:08x}", lsq_id, data_sram.dout[0])
                    with Condition(mem_write):
                        # Phase 5 完整版: Store 不在 MEM 阶段写内存，只标记 done
                        # Store 将在 Commit 阶段由 WriteBackStage 写入内存
                        lsq_done[lsq_id] = UInt(1)(1)
                        log("MEM: Store LSQ[{}] ready for commit, addr={:08x} data={:08x}", lsq_id, addr_in, write_data)
                with Condition(~ex_mem_valid[0]):
                    mem_wb_mem_data[0] = UInt(XLEN)(0)
            mem_wb_control[0] = ex_mem_valid[0].select(control_in, UInt(CONTROL_LEN)(0))
            mem_wb_ex_result[0] = ex_mem_valid[0].select(ex_mem_result[0], UInt(XLEN)(0))
            # Phase 2: 传递 ROB ID
            mem_wb_rob_id[0] = ex_mem_valid[0].select(ex_mem_rob_id[0], UInt(ROB_ID_BITS)(0))
            # Phase 5: 传递 LSQ ID
            mem_wb_lsq_id[0] = ex_mem_valid[0].select(lsq_id, UInt(LSQ_ID_BITS)(0))
            
            log("MEM: PC={}, Addr={:08x}, Read={}, Write={}, data_in={}, ROB_ID={}, LSQ_ID={}",
                pc_in, addr_in, mem_read, mem_write, data_in, ex_mem_rob_id[0], lsq_id)

        writeback_stage.async_called()

        memory_signals = mem_wb_valid[0].select(ex_mem_valid[0].select(control_in.bitcast(Bits(CONTROL_LEN)), Bits(CONTROL_LEN)(0)), mem_wb_control[0].bitcast(Bits(CONTROL_LEN)))
        return memory_signals

# ==================== Phase 3: 分派阶段 ===================
# ==================== Phase 3: 分派发射阶段 (合并) ===================
class DispatchIssueStage(Module):
    """指令分派与发射阶段 - 将解码后的指令放入 RS，并选择就绪指令发射"""
    def __init__(self):
        super().__init__(ports={})
    
    @module.combinational
    def build(self, dispatch_valid, dispatch_control, dispatch_immediate, dispatch_rob_id, dispatch_pc,
              rs1_value, rs1_tag, rs1_ready,
              rs2_value, rs2_tag, rs2_ready,
              rs_busy, rs_op, rs_vj, rs_vk, rs_qj, rs_qk, rs_qj_valid, rs_qk_valid, 
              rs_dest, rs_imm, rs_func, rs_control, rs_lsq_id, rs_pc,  # Phase 5: rs_lsq_id, 多FU: rs_pc
              # Phase 5: LSQ 相关参数
              lsq_valid, lsq_is_store, lsq_addr_ready, lsq_data_ready,
              lsq_addr, lsq_data, lsq_rob_id, lsq_done,
              lsq_head, lsq_tail,
              # Phase 5: ROB Store 信息
              rob_is_store, rob_lsq_id,
              # Issue 阶段输出寄存器 (MulDiv 兼容)
              issue_ex_valid, issue_ex_op, issue_ex_vj, issue_ex_vk, issue_ex_dest, issue_ex_imm, issue_ex_control, issue_ex_func,
              issue_ex_lsq_id,  # Phase 5: issue_ex_lsq_id
              md_busy,  # Phase 4: MulDiv 忙状态
              # 多 FU 并行: 各 FU 独立寄存器
              alu_fu_valid, alu_fu_op, alu_fu_vj, alu_fu_vk, alu_fu_dest, alu_fu_imm, alu_fu_control,
              branch_fu_valid, branch_fu_vj, branch_fu_vk, branch_fu_dest, branch_fu_imm, branch_fu_control, branch_fu_pc,
              lsq_fu_valid, lsq_fu_lsq_id, lsq_fu_vj, lsq_fu_vk, lsq_fu_imm, lsq_fu_dest, lsq_fu_is_store, lsq_fu_control,
              execute_stage):
        
        # ==================== Part 1: Dispatch 逻辑 ====================
        # 解析控制信号
        alu_op = dispatch_control[0:4]
        mem_read = dispatch_control[5:5]
        mem_write = dispatch_control[6:6]
        reg_write = dispatch_control[7:7]
        branch_op = dispatch_control[17:19]
        
        # 确定功能单元类型
        fu_type = UInt(3)(FU_ALU)  # 默认为 ALU
        fu_type = (branch_op != UInt(3)(0)).select(UInt(3)(FU_BRANCH), fu_type)
        fu_type = mem_read.select(UInt(3)(FU_LOAD), fu_type)
        fu_type = mem_write.select(UInt(3)(FU_STORE), fu_type)
        
        # Phase 5: 判断是否为访存指令
        is_load = mem_read
        is_store = mem_write
        is_mem_op = is_load | is_store
        
        # Phase 5: 计算 LSQ 满
        lsq_next_tail = (lsq_tail[0] + UInt(LSQ_ID_BITS)(1)) & UInt(LSQ_ID_BITS)(LSQ_SIZE - 1)
        lsq_full = (lsq_next_tail == lsq_head[0]) & is_mem_op
        
        # 找空闲 RS (简单优先级编码)
        rs_free = UInt(RS_ID_BITS)(0)
        rs_found = UInt(1)(0)

        for i in range(RS_SIZE):
            rs_free = (~rs_busy[i] & ~rs_found).select(UInt(RS_ID_BITS)(i), rs_free)
            rs_found = (~rs_busy[i] & ~rs_found).select(UInt(1)(1), rs_found)
        
        # RS 满检测
        rs_full = ~rs_found
        
        # Phase 5: 综合 Stall 条件
        stall_condition = rs_full | lsq_full
        
        # 分配 RS（仅当有有效指令且 RS 未满且 LSQ 未满）
        with Condition(dispatch_valid & ~stall_condition):
            rs_busy[rs_free] = UInt(1)(1)
            rs_op[rs_free] = alu_op
            rs_dest[rs_free] = dispatch_rob_id
            rs_imm[rs_free] = dispatch_immediate
            rs_func[rs_free] = fu_type
            rs_control[rs_free] = dispatch_control
            rs_pc[rs_free] = dispatch_pc  # 多FU并行: 保存PC供Branch使用
            
            # 源操作数1
            rs_vj[rs_free] = rs1_ready.select(rs1_value, UInt(XLEN)(0))
            rs_qj[rs_free] = rs1_tag
            rs_qj_valid[rs_free] = ~rs1_ready  # 需要等待
            
            # 源操作数2
            rs_vk[rs_free] = rs2_ready.select(rs2_value, UInt(XLEN)(0))
            rs_qk[rs_free] = rs2_tag
            rs_qk_valid[rs_free] = ~rs2_ready  # 需要等待
            
            # Phase 5: 为访存指令分配 LSQ
            rs_lsq_id[rs_free] = lsq_tail[0]  # 记录 LSQ ID
            
            log("Dispatch: RS[{}] <- ROB[{}], op={:05b}, Vj={:08x}, Qj={}, Qj_valid={}, Vk={:08x}, Qk={}, Qk_valid={}",
                rs_free, dispatch_rob_id, alu_op, rs_vj[rs_free], rs_qj[rs_free], rs_qj_valid[rs_free],
                rs_vk[rs_free], rs_qk[rs_free], rs_qk_valid[rs_free])
        
        # Phase 5: 分配 LSQ entry (仅访存指令)
        with Condition(dispatch_valid & ~stall_condition & is_mem_op):
            lsq_id = lsq_tail[0]
            lsq_valid[lsq_id] = UInt(1)(1)
            lsq_is_store[lsq_id] = is_store
            lsq_addr_ready[lsq_id] = UInt(1)(0)
            lsq_data_ready[lsq_id] = UInt(1)(0)
            lsq_rob_id[lsq_id] = dispatch_rob_id
            lsq_done[lsq_id] = UInt(1)(0)
            lsq_tail[0] = lsq_next_tail
            # Phase 5: 在 ROB 中记录 Store 信息（用于 Commit 阶段写内存）
            rob_is_store[dispatch_rob_id] = is_store
            rob_lsq_id[dispatch_rob_id] = lsq_id
            log("Dispatch: LSQ[{}] allocated, is_store={}, ROB[{}]", lsq_id, is_store, dispatch_rob_id)
        
        # ==================== Part 2: Multi-FU Issue 逻辑 ====================
        # 为每种 FU 类型独立选择一条就绪指令
        
        # --- ALU FU Issue ---
        alu_issue_idx = UInt(RS_ID_BITS)(0)
        alu_issue_found = UInt(1)(0)
        for i in range(RS_SIZE):
            is_alu = (rs_func[i] == UInt(3)(FU_ALU))
            ready_alu = rs_busy[i] & ~rs_qj_valid[i] & ~rs_qk_valid[i] & is_alu
            alu_issue_idx = (ready_alu & ~alu_issue_found).select(UInt(RS_ID_BITS)(i), alu_issue_idx)
            alu_issue_found = (ready_alu & ~alu_issue_found).select(UInt(1)(1), alu_issue_found)
        
        with Condition(alu_issue_found):
            alu_fu_valid[0] = UInt(1)(1)
            alu_fu_op[0] = rs_op[alu_issue_idx]
            alu_fu_vj[0] = rs_vj[alu_issue_idx]
            alu_fu_vk[0] = rs_vk[alu_issue_idx]
            alu_fu_dest[0] = rs_dest[alu_issue_idx]
            alu_fu_imm[0] = rs_imm[alu_issue_idx]
            alu_fu_control[0] = rs_control[alu_issue_idx]
            rs_busy[alu_issue_idx] = UInt(1)(0)
            log("Issue ALU: RS[{}] -> ALU_FU, ROB[{}], op={:05b}", alu_issue_idx, rs_dest[alu_issue_idx], rs_op[alu_issue_idx])
        
        with Condition(~alu_issue_found):
            alu_fu_valid[0] = UInt(1)(0)
        
        # --- Branch FU Issue ---
        branch_issue_idx = UInt(RS_ID_BITS)(0)
        branch_issue_found = UInt(1)(0)
        for i in range(RS_SIZE):
            is_branch = (rs_func[i] == UInt(3)(FU_BRANCH))
            ready_branch = rs_busy[i] & ~rs_qj_valid[i] & ~rs_qk_valid[i] & is_branch
            branch_issue_idx = (ready_branch & ~branch_issue_found).select(UInt(RS_ID_BITS)(i), branch_issue_idx)
            branch_issue_found = (ready_branch & ~branch_issue_found).select(UInt(1)(1), branch_issue_found)
        
        with Condition(branch_issue_found):
            branch_fu_valid[0] = UInt(1)(1)
            branch_fu_vj[0] = rs_vj[branch_issue_idx]
            branch_fu_vk[0] = rs_vk[branch_issue_idx]
            branch_fu_dest[0] = rs_dest[branch_issue_idx]
            branch_fu_imm[0] = rs_imm[branch_issue_idx]
            branch_fu_control[0] = rs_control[branch_issue_idx]
            branch_fu_pc[0] = rs_pc[branch_issue_idx]  # 多FU并行: 传递PC
            rs_busy[branch_issue_idx] = UInt(1)(0)
            log("Issue Branch: RS[{}] -> Branch_FU, ROB[{}], PC={:08x}", branch_issue_idx, rs_dest[branch_issue_idx], rs_pc[branch_issue_idx])
        
        with Condition(~branch_issue_found):
            branch_fu_valid[0] = UInt(1)(0)
        
        # --- MulDiv FU Issue (仅当 md_busy=0) ---
        muldiv_issue_idx = UInt(RS_ID_BITS)(0)
        muldiv_issue_found = UInt(1)(0)
        for i in range(RS_SIZE):
            is_muldiv = (rs_func[i] == UInt(3)(FU_MUL)) | (rs_func[i] == UInt(3)(FU_DIV))
            ready_muldiv = rs_busy[i] & ~rs_qj_valid[i] & ~rs_qk_valid[i] & is_muldiv & ~md_busy[0]
            muldiv_issue_idx = (ready_muldiv & ~muldiv_issue_found).select(UInt(RS_ID_BITS)(i), muldiv_issue_idx)
            muldiv_issue_found = (ready_muldiv & ~muldiv_issue_found).select(UInt(1)(1), muldiv_issue_found)
        
        # MulDiv 发射直接启动多周期执行 (md_* 寄存器在 ExecuteStage 处理)
        
        # --- LSQ FU Issue (Load/Store) ---
        lsq_issue_idx = UInt(RS_ID_BITS)(0)
        lsq_issue_found = UInt(1)(0)
        for i in range(RS_SIZE):
            is_lsq = (rs_func[i] == UInt(3)(FU_LOAD)) | (rs_func[i] == UInt(3)(FU_STORE))
            ready_lsq = rs_busy[i] & ~rs_qj_valid[i] & ~rs_qk_valid[i] & is_lsq
            lsq_issue_idx = (ready_lsq & ~lsq_issue_found).select(UInt(RS_ID_BITS)(i), lsq_issue_idx)
            lsq_issue_found = (ready_lsq & ~lsq_issue_found).select(UInt(1)(1), lsq_issue_found)
        
        with Condition(lsq_issue_found):
            lsq_fu_valid[0] = UInt(1)(1)
            lsq_fu_lsq_id[0] = rs_lsq_id[lsq_issue_idx]
            lsq_fu_vj[0] = rs_vj[lsq_issue_idx]
            lsq_fu_vk[0] = rs_vk[lsq_issue_idx]
            lsq_fu_imm[0] = rs_imm[lsq_issue_idx]
            lsq_fu_dest[0] = rs_dest[lsq_issue_idx]
            lsq_fu_is_store[0] = (rs_func[lsq_issue_idx] == UInt(3)(FU_STORE))
            lsq_fu_control[0] = rs_control[lsq_issue_idx]
            rs_busy[lsq_issue_idx] = UInt(1)(0)
            log("Issue LSQ: RS[{}] -> LSQ_FU, ROB[{}], LSQ[{}], is_store={}", 
                lsq_issue_idx, rs_dest[lsq_issue_idx], rs_lsq_id[lsq_issue_idx], (rs_func[lsq_issue_idx] == UInt(3)(FU_STORE)))
        
        with Condition(~lsq_issue_found):
            lsq_fu_valid[0] = UInt(1)(0)
        
        # 保持原有 issue_ex 兼容性 (用于 ExecuteStage)
        issue_valid = alu_issue_found | branch_issue_found | muldiv_issue_found | lsq_issue_found
        
        # 将 MulDiv 发射信息写入 issue_ex (MulDiv 走原有 ExecuteStage 路径)
        with Condition(muldiv_issue_found):
            issue_ex_valid[0] = UInt(1)(1)
            issue_ex_op[0] = rs_op[muldiv_issue_idx]
            issue_ex_vj[0] = rs_vj[muldiv_issue_idx]
            issue_ex_vk[0] = rs_vk[muldiv_issue_idx]
            issue_ex_dest[0] = rs_dest[muldiv_issue_idx]
            issue_ex_imm[0] = rs_imm[muldiv_issue_idx]
            issue_ex_control[0] = rs_control[muldiv_issue_idx]
            issue_ex_func[0] = rs_func[muldiv_issue_idx]
            issue_ex_lsq_id[0] = rs_lsq_id[muldiv_issue_idx]
            rs_busy[muldiv_issue_idx] = UInt(1)(0)
            log("Issue MulDiv: RS[{}] -> MulDiv_FU, ROB[{}], op={:05b}", muldiv_issue_idx, rs_dest[muldiv_issue_idx], rs_op[muldiv_issue_idx])
        
        with Condition(~muldiv_issue_found):
            issue_ex_valid[0] = UInt(1)(0)
            issue_ex_op[0] = UInt(5)(0)
            issue_ex_vj[0] = UInt(XLEN)(0)
            issue_ex_vk[0] = UInt(XLEN)(0)
            issue_ex_dest[0] = UInt(ROB_ID_BITS)(0)
            issue_ex_imm[0] = UInt(XLEN)(0)
            issue_ex_control[0] = UInt(CONTROL_LEN)(0)
            issue_ex_func[0] = UInt(3)(0)
            issue_ex_lsq_id[0] = UInt(LSQ_ID_BITS)(0)
        
        execute_stage.async_called()
        
        # 返回 stall 信号给 HazardUnit 用于 Stall
        return stall_condition, issue_valid


# ==================== Phase 5: LSQ 前递单元 ===================
class LSQUnit(Module):
    """LSQ 前递与依赖检查单元"""
    def __init__(self):
        super().__init__(ports={})
    
    @module.combinational
    def build(self,
              lsq_valid, lsq_is_store, lsq_addr_ready, lsq_data_ready,
              lsq_addr, lsq_data, lsq_rob_id,
              # 当前 Load 信息
              load_lsq_id, load_addr, load_valid):
        """
        检查 Load 是否可以执行：
        1. 检查所有更早的 Store
        2. 若存在未知地址的 Store，Load 阻塞
        3. 若地址匹配且数据就绪，前递数据
        """
        
        # 初始化
        has_unknown_addr = UInt(1)(0)
        forward_match = UInt(1)(0)
        fwd_data = UInt(XLEN)(0)
        load_rob = lsq_rob_id[load_lsq_id]
        
        # 遍历检查前序 Store
        for i in range(LSQ_SIZE):
            # 判断：这是一个比当前 Load 更早的有效 Store 吗？
            # 使用 ROB ID 比较（更小的 ROB ID = 程序顺序更早）
            is_earlier_store = lsq_valid[i] & lsq_is_store[i] & (lsq_rob_id[i] < load_rob)
            
            # 检查地址是否未知
            addr_unknown = is_earlier_store & ~lsq_addr_ready[i]
            has_unknown_addr = has_unknown_addr | addr_unknown
            
            # 检查地址匹配（仅当地址已知时）
            addr_match = is_earlier_store & lsq_addr_ready[i] & (lsq_addr[i] == load_addr)
            # 若匹配且数据就绪，记录前递
            fwd_hit = addr_match & lsq_data_ready[i]
            forward_match = fwd_hit.select(UInt(1)(1), forward_match)
            fwd_data = fwd_hit.select(lsq_data[i], fwd_data)
        
        # 输出信号
        # forward_hit: 可以前递且无未知地址阻塞
        forward_hit = forward_match & ~has_unknown_addr & load_valid
        # forward_data: 前递的数据
        forward_data = fwd_data
        # load_blocked: 有未知地址的前序 Store，必须等待
        load_blocked = has_unknown_addr & load_valid
        
        log("LSQUnit: load_lsq={}, load_addr={:08x}, fwd_hit={}, fwd_data={:08x}, blocked={}",
            load_lsq_id, load_addr, forward_hit, forward_data, load_blocked)
        
        return forward_hit, forward_data, load_blocked


# ==================== Phase 3: 唤醒单元 (多CDB版本) ===================
class WakeupUnit(Module):
    """唤醒单元 - 监听所有4条CDB，更新等待中的 RS"""
    def __init__(self):
        super().__init__(ports={})
    
    @module.combinational
    def build(self, 
              cdb_alu_valid, cdb_alu_tag, cdb_alu_value,
              cdb_branch_valid, cdb_branch_tag, cdb_branch_value,
              cdb_md_valid, cdb_md_tag, cdb_md_value,
              cdb_lsq_valid, cdb_lsq_tag, cdb_lsq_value,
              rs_busy, rs_vj, rs_vk, rs_qj, rs_qk, rs_qj_valid, rs_qk_valid):
        
        # 监听 ALU CDB
        with Condition(cdb_alu_valid[0]):
            for i in range(RS_SIZE):
                with Condition(rs_busy[i] & rs_qj_valid[i] & (rs_qj[i] == cdb_alu_tag[0])):
                    rs_vj[i] = cdb_alu_value[0]
                    rs_qj_valid[i] = UInt(1)(0)
                    log("Wakeup ALU: RS[{}].Vj <- tag={}", UInt(RS_ID_BITS)(i), cdb_alu_tag[0])
                with Condition(rs_busy[i] & rs_qk_valid[i] & (rs_qk[i] == cdb_alu_tag[0])):
                    rs_vk[i] = cdb_alu_value[0]
                    rs_qk_valid[i] = UInt(1)(0)
                    log("Wakeup ALU: RS[{}].Vk <- tag={}", UInt(RS_ID_BITS)(i), cdb_alu_tag[0])
        
        # 监听 Branch CDB
        with Condition(cdb_branch_valid[0]):
            for i in range(RS_SIZE):
                with Condition(rs_busy[i] & rs_qj_valid[i] & (rs_qj[i] == cdb_branch_tag[0])):
                    rs_vj[i] = cdb_branch_value[0]
                    rs_qj_valid[i] = UInt(1)(0)
                    log("Wakeup Branch: RS[{}].Vj <- tag={}", UInt(RS_ID_BITS)(i), cdb_branch_tag[0])
                with Condition(rs_busy[i] & rs_qk_valid[i] & (rs_qk[i] == cdb_branch_tag[0])):
                    rs_vk[i] = cdb_branch_value[0]
                    rs_qk_valid[i] = UInt(1)(0)
                    log("Wakeup Branch: RS[{}].Vk <- tag={}", UInt(RS_ID_BITS)(i), cdb_branch_tag[0])
        
        # 监听 MulDiv CDB
        with Condition(cdb_md_valid[0]):
            for i in range(RS_SIZE):
                with Condition(rs_busy[i] & rs_qj_valid[i] & (rs_qj[i] == cdb_md_tag[0])):
                    rs_vj[i] = cdb_md_value[0]
                    rs_qj_valid[i] = UInt(1)(0)
                    log("Wakeup MulDiv: RS[{}].Vj <- tag={}", UInt(RS_ID_BITS)(i), cdb_md_tag[0])
                with Condition(rs_busy[i] & rs_qk_valid[i] & (rs_qk[i] == cdb_md_tag[0])):
                    rs_vk[i] = cdb_md_value[0]
                    rs_qk_valid[i] = UInt(1)(0)
                    log("Wakeup MulDiv: RS[{}].Vk <- tag={}", UInt(RS_ID_BITS)(i), cdb_md_tag[0])
        
        # 监听 LSQ CDB (Load 结果)
        with Condition(cdb_lsq_valid[0]):
            for i in range(RS_SIZE):
                with Condition(rs_busy[i] & rs_qj_valid[i] & (rs_qj[i] == cdb_lsq_tag[0])):
                    rs_vj[i] = cdb_lsq_value[0]
                    rs_qj_valid[i] = UInt(1)(0)
                    log("Wakeup LSQ: RS[{}].Vj <- tag={}", UInt(RS_ID_BITS)(i), cdb_lsq_tag[0])
                with Condition(rs_busy[i] & rs_qk_valid[i] & (rs_qk[i] == cdb_lsq_tag[0])):
                    rs_vk[i] = cdb_lsq_value[0]
                    rs_qk_valid[i] = UInt(1)(0)
                    log("Wakeup LSQ: RS[{}].Vk <- tag={}", UInt(RS_ID_BITS)(i), cdb_lsq_tag[0])


# ==================== WB阶段：写回 (多CDB版本) ===================
class WriteBackStage(Module):
    """写回阶段(WB) - 接收多条CDB并更新ROB"""
    def __init__(self):
        super().__init__(ports={})
    
    @module.combinational
    def build(self, mem_wb_valid, mem_wb_mem_data, mem_wb_ex_result, mem_wb_control,
              mem_wb_rob_id,  # Phase 2: ROB ID
              rob_head, rob_valid, rob_ready, rob_value, rob_dest,  # Phase 2: ROB arrays
              rob_is_store, rob_lsq_id,  # Phase 5: Store info in ROB
              rat_valid, rat_tag,  # Phase 2: RAT for clearing on commit
              # 多 FU 并行: 4条独立CDB
              cdb_alu_valid, cdb_alu_tag, cdb_alu_value,
              cdb_branch_valid, cdb_branch_tag, cdb_branch_value,
              cdb_md_valid, cdb_md_tag, cdb_md_value,
              cdb_lsq_valid, cdb_lsq_tag, cdb_lsq_value,
              # Phase 5: LSQ for Store commit
              lsq_valid, lsq_addr, lsq_data, lsq_head,
              reg_file, data_sram):
        mem_data_in = data_sram.dout[0]
        ex_result_in = mem_wb_ex_result[0]
        control_in = mem_wb_control[0]
        
        # 解析控制信号
        reg_write = control_in[7:7]
        mem_to_reg = control_in[8:8]
        wb_rd = control_in[25:29]
            
        # 选择写回数据
        wb_data = mem_to_reg.select(mem_data_in, ex_result_in)
            
        # ========== 多 CDB ROB Writeback ==========
        # ALU CDB -> ROB
        with Condition(cdb_alu_valid[0]):
            rob_ready[cdb_alu_tag[0]] = UInt(1)(1)
            rob_value[cdb_alu_tag[0]] = cdb_alu_value[0]
            log("ROB WB ALU: ID={}, Value={:08x}", cdb_alu_tag[0], cdb_alu_value[0])
        
        # Branch CDB -> ROB
        with Condition(cdb_branch_valid[0]):
            rob_ready[cdb_branch_tag[0]] = UInt(1)(1)
            rob_value[cdb_branch_tag[0]] = cdb_branch_value[0]
            log("ROB WB Branch: ID={}, Value={:08x}", cdb_branch_tag[0], cdb_branch_value[0])
        
        # MulDiv CDB -> ROB
        with Condition(cdb_md_valid[0]):
            rob_ready[cdb_md_tag[0]] = UInt(1)(1)
            rob_value[cdb_md_tag[0]] = cdb_md_value[0]
            log("ROB WB MulDiv: ID={}, Value={:08x}", cdb_md_tag[0], cdb_md_value[0])
        
        # LSQ CDB -> ROB (Load 结果)
        with Condition(cdb_lsq_valid[0]):
            rob_ready[cdb_lsq_tag[0]] = UInt(1)(1)
            rob_value[cdb_lsq_tag[0]] = cdb_lsq_value[0]
            log("ROB WB LSQ: ID={}, Value={:08x}", cdb_lsq_tag[0], cdb_lsq_value[0])
        
        # ========== Phase 2: ROB Commit（顺序提交）==========
        head_id = rob_head[0]
        head_valid = rob_valid[head_id]
        head_ready = rob_ready[head_id]
        head_dest = rob_dest[head_id]
        head_value = rob_value[head_id]
        
        with Condition(head_valid & head_ready):
            # 写入 reg_file（x0 不写）
            with Condition(head_dest != UInt(5)(0)):
                reg_file[head_dest] = head_value
            
            # 清除 RAT 映射（仅当 RAT 仍指向此 ROB ID）
            with Condition(rat_valid[head_dest] & (rat_tag[head_dest] == head_id)):
                rat_valid[head_dest] = UInt(1)(0)
            
            # 释放 ROB 条目
            rob_valid[head_id] = UInt(1)(0)
            rob_ready[head_id] = UInt(1)(0)
            
            # Phase 5: Store Commit - 写入内存
            with Condition(rob_is_store[head_id]):
                store_lsq_id = rob_lsq_id[head_id]
                store_addr = lsq_addr[store_lsq_id]
                store_data = lsq_data[store_lsq_id]
                word_addr = store_addr >> UInt(XLEN)(2)
                data_sram.build(we=UInt(1)(1), re=UInt(1)(0), addr=word_addr, wdata=store_data)
                # 释放 LSQ 条目
                lsq_valid[store_lsq_id] = UInt(1)(0)
                # 前移 LSQ head
                lsq_head[0] = (store_lsq_id + UInt(LSQ_ID_BITS)(1)) & UInt(LSQ_ID_BITS)(LSQ_SIZE - 1)
                log("Store Commit: ROB[{}] LSQ[{}] addr={:08x} data={:08x}", head_id, store_lsq_id, store_addr, store_data)
            
            # 前移 head
            rob_head[0] = (head_id + UInt(ROB_ID_BITS)(1)) & UInt(ROB_ID_BITS)(ROB_SIZE - 1)
            
            log("ROB Commit: ID={}, Dest=x{}, Value={:08x}", head_id, head_dest, head_value)

        writeback_signals = control_in.bitcast(Bits(CONTROL_LEN))
        return writeback_signals

class HazardUnit(Downstream):
    def __init__(self):
        super().__init__()

    @downstream.combinational
    def build(self, pc, stall, if_id_valid, if_id_instruction, id_ex_control, id_ex_valid, id_ex_rs1_idx, id_ex_rs2_idx, id_ex_immediate, ex_mem_valid, mem_wb_valid, 
              rob_valid, rob_ready, rob_tail, rob_dest, rob_old_tag_valid, rob_old_tag, rat_valid, rat_tag,
              rs_busy, rs_dest,  # Phase 3: RS for Walk-back
              lsq_valid, lsq_rob_id, lsq_head, lsq_tail,  # Phase 5: LSQ for Walk-back
              md_busy, md_dest,  # Phase 4: MulDiv for Walk-back
              fetch_signals, decode_signals, execute_signals, memory_signals, writeback_signals):

        execute_signals = execute_signals.optional(Bits(XLEN + 1 + CONTROL_LEN)(0))
        decode_signals = decode_signals.optional(Bits(2 + CONTROL_LEN + 5 + 5 + XLEN + 3*ROB_ID_BITS + 2*XLEN + 2 + 1)(0))  # +1 for rob_full
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
        
        # 提取 rob_full 信号 (在 decode_signals 的最高位)
        # decode_signals 结构: [control(42), rs1(5), rs2(5), imm(32), need_rs1(1), need_rs2(1), 
        #                       rs1_ready(1), rs1_tag(4), rs1_value(32), rs2_ready(1), rs2_tag(4), rs2_value(32), rob_id(4), rob_full(1)]
        rob_full_offset = 2 + CONTROL_LEN + 5 + 5 + XLEN + 3*ROB_ID_BITS + 2*XLEN + 2
        rob_full = decode_signals[rob_full_offset:rob_full_offset].bitcast(UInt(1))
        
        # 提取被 flush 指令分配的 ROB ID (用于 Walk-back)
        flush_rob_id_offset = 2 + CONTROL_LEN + 5 + 5 + XLEN + 3*ROB_ID_BITS + 2*XLEN + 2 - ROB_ID_BITS
        flush_rob_id = decode_signals[flush_rob_id_offset:flush_rob_id_offset + ROB_ID_BITS - 1].bitcast(UInt(ROB_ID_BITS))
        
        # 当 ROB 满且当前指令需要写寄存器时，产生 Stall
        reg_write_decode = control_in[7:7]
        rob_stall = rob_full & reg_write_decode
        
        # Phase 3: RS 满 Stall
        rs_stall = rs_full & if_id_valid[0]
        
        data_hazard_ex = (reg_write_mem & ((needs_rs1 & (rs1 == rd_mem)) | (needs_rs2 & (rs2 == rd_mem)))).select(UInt(1)(1), data_hazard_ex)

        data_hazard_wb = (reg_write_wb & ((needs_rs1 & (rs1 == rd_wb)) | (needs_rs2 & (rs2 == rd_wb)))).select(UInt(1)(1), data_hazard_wb)
        
        # 综合数据冒险信号 (加入 rob_stall)
        data_hazard = ((data_hazard_ex | data_hazard_wb) & ~pc_change)
        id_ex_valid[0] = (~data_hazard)
        if_id_valid[0] = (~data_hazard)
        ex_mem_valid[0] = UInt(1)(1)  # ID/EX和EX/MEM阶段始终有效
        mem_wb_valid[0] = UInt(1)(1)  # EX/MEM和MEM/WB阶段始终有效
        stall[0] = data_hazard
        nop_control = UInt(CONTROL_LEN)(0) # NOP控制信号，全0表示无操作

        # 更新PC和IF/ID寄存器        
        pc[0] = pc_change.select(target_pc, (data_hazard | rob_stall | rs_stall).select(pc[0], pc[0] + UInt(XLEN)(4)))

        if_id_instruction[0] = pc_change.select(UInt(XLEN)(0x00000013), (if_id_valid[0] & ~rob_stall & ~rs_stall).select(stall[0].select(UInt(XLEN)(0x00000013), instruction), if_id_instruction[0]))  # NOP指令
        
        # 提取 allocated_rob_id（在 decode_signals 中 rob_full 之前 ROB_ID_BITS 位）
        allocated_rob_id_offset = 2 + CONTROL_LEN + 5 + 5 + XLEN + 3*ROB_ID_BITS + 2*XLEN + 2 - ROB_ID_BITS
        allocated_rob_id = decode_signals[allocated_rob_id_offset:allocated_rob_id_offset + ROB_ID_BITS - 1].bitcast(UInt(ROB_ID_BITS))
        
        with Condition(id_ex_valid[0]):
            id_ex_control[0] = (pc_change | rob_stall | rs_stall).select(nop_control, control_in)
            id_ex_immediate[0] = (pc_change | rob_stall | rs_stall).select(UInt(XLEN)(0), immediate)
            id_ex_rs1_idx[0] = (pc_change | rob_stall | rs_stall).select(UInt(5)(0), rs1)
            id_ex_rs2_idx[0] = (pc_change | rob_stall | rs_stall).select(UInt(5)(0), rs2)
            # Phase 2: 写入 ROB ID
            id_ex_rob_id[0] = (pc_change | rob_stall | rs_stall).select(UInt(ROB_ID_BITS)(0), allocated_rob_id)

        # ==================== Walk-back 恢复逻辑 ====================
        # 当 pc_change=1 且 ID 阶段有有效指令且该指令有写寄存器操作时
        # 需要撤销 DecodeStage 已执行的 ROB/RAT 分配
        flush_dest = rob_dest[flush_rob_id]
        with Condition(pc_change & reg_write_decode):
            # 1. 恢复 RAT（仅当 RAT 仍指向被 flush 的 ROB）
            with Condition(rat_valid[flush_dest] & (rat_tag[flush_dest] == flush_rob_id)):
                # 恢复到旧映射
                rat_valid[flush_dest] = rob_old_tag_valid[flush_rob_id]
                rat_tag[flush_dest] = rob_old_tag[flush_rob_id]
            
            # 2. 清除 ROB 条目
            rob_valid[flush_rob_id] = UInt(1)(0)
            rob_ready[flush_rob_id] = UInt(1)(0)
            
            # 3. 回滚 rob_tail（撤销分配）
            rob_tail[0] = flush_rob_id  # tail 回退到 flush 点
            
            log("Walk-back: flush ROB[{}], dest=x{}", flush_rob_id, flush_dest)
        
        # Phase 3: Walk-back 时选择性清空 RS
        # 只清空那些指向已被清除 ROB 的条目
        with Condition(pc_change):
            for i in range(RS_SIZE):
                with Condition(rs_busy[i] & ~rob_valid[rs_dest[i]]):
                    rs_busy[i] = UInt(1)(0)
                    log("Walk-back: RS[{}] cleared (ROB[{}] invalid)", UInt(RS_ID_BITS)(i), rs_dest[i])
            
            # Phase 4: Walk-back 时清理 MulDiv FU
            # 如果 MulDiv 正在执行的指令对应的 ROB 被清除，则清理 MulDiv
            with Condition(md_busy[0] & ~rob_valid[md_dest[0]]):
                md_busy[0] = UInt(1)(0)
                log("Walk-back: MulDiv cleared (ROB[{}] invalid)", md_dest[0])
            
            # Phase 5: Walk-back 时清理 LSQ 并精细回退 tail
            # 策略：从 tail-1 向 head 方向扫描，找到第一个有效且 ROB 有效的条目
            # 新 tail = 该条目 + 1；如果全部无效，则 tail = head
            
            # 计算新 tail：遍历找最后一个有效条目
            new_lsq_tail = lsq_head[0]  # 默认回退到 head（全空）
            found_valid = UInt(1)(0)
            
            for i in range(LSQ_SIZE):
                idx = new_lsq_tail
                # 条目有效且其 ROB 仍有效
                entry_valid = lsq_valid[idx] & rob_valid[lsq_rob_id[idx]]
                with Condition(entry_valid):
                    # 更新 new_tail 为该条目的下一个位置
                    next_pos = (idx + UInt(LSQ_ID_BITS)(1)) & UInt(LSQ_ID_BITS)(LSQ_SIZE - 1)
                    new_lsq_tail = next_pos
                    found_valid = UInt(1)(1)
            
            # 清除所有对应 ROB 被清除的 LSQ 条目
            for i in range(LSQ_SIZE):
                with Condition(lsq_valid[i] & ~rob_valid[lsq_rob_id[i]]):
                    lsq_valid[i] = UInt(1)(0)
                    log("Walk-back: LSQ[{}] cleared (ROB[{}] invalid)", UInt(LSQ_ID_BITS)(i), lsq_rob_id[i])
            
            # 精细回退 tail
            lsq_tail[0] = new_lsq_tail
            log("Walk-back: LSQ tail reset to {}, found_valid={}", new_lsq_tail, found_valid)

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
        id_ex_rob_id = RegArray(UInt(ROB_ID_BITS), 1, initializer=[0])  # 分配的 ROB ID (Phase 2)

        # ==================== OoO 相关寄存器 ====================
        # RAT (Register Alias Table) - 32项
        rat_valid = RegArray(UInt(1), REG_COUNT, initializer=[0]*REG_COUNT)
        rat_tag = RegArray(UInt(ROB_ID_BITS), REG_COUNT, initializer=[0]*REG_COUNT)
        
        # ROB 指针
        rob_head = RegArray(UInt(ROB_ID_BITS), 1, initializer=[0])  # 队头(Commit点)
        rob_tail = RegArray(UInt(ROB_ID_BITS), 1, initializer=[0])  # 队尾(分配点)
        
        # ROB 数据数组 (每个ROB条目的字段)
        rob_valid = RegArray(UInt(1), ROB_SIZE, initializer=[0]*ROB_SIZE)      # 条目是否有效
        rob_ready = RegArray(UInt(1), ROB_SIZE, initializer=[0]*ROB_SIZE)      # 结果是否就绪
        rob_value = RegArray(UInt(XLEN), ROB_SIZE, initializer=[0]*ROB_SIZE)   # 执行结果
        rob_dest = RegArray(UInt(5), ROB_SIZE, initializer=[0]*ROB_SIZE)       # 目标寄存器号
        rob_pc = RegArray(UInt(XLEN), ROB_SIZE, initializer=[0]*ROB_SIZE)      # 指令PC
        rob_is_store = RegArray(UInt(1), ROB_SIZE, initializer=[0]*ROB_SIZE)   # Phase 5: 是否为Store
        rob_lsq_id = RegArray(UInt(LSQ_ID_BITS), ROB_SIZE, initializer=[0]*ROB_SIZE)  # Phase 5: LSQ ID
        # Walk-back 恢复所需字段
        rob_old_tag_valid = RegArray(UInt(1), ROB_SIZE, initializer=[0]*ROB_SIZE)  # 旧 RAT valid
        rob_old_tag = RegArray(UInt(ROB_ID_BITS), ROB_SIZE, initializer=[0]*ROB_SIZE)  # 旧 RAT tag

        # ==================== Phase 3: RS 数据结构 ====================
        rs_busy = RegArray(UInt(1), RS_SIZE, initializer=[0]*RS_SIZE)          # 是否被占用
        rs_op = RegArray(UInt(5), RS_SIZE, initializer=[0]*RS_SIZE)            # ALU 操作码
        rs_vj = RegArray(UInt(XLEN), RS_SIZE, initializer=[0]*RS_SIZE)         # 源操作数1的值
        rs_vk = RegArray(UInt(XLEN), RS_SIZE, initializer=[0]*RS_SIZE)         # 源操作数2的值
        rs_qj = RegArray(UInt(ROB_ID_BITS), RS_SIZE, initializer=[0]*RS_SIZE)  # 源操作数1的 ROB tag
        rs_qk = RegArray(UInt(ROB_ID_BITS), RS_SIZE, initializer=[0]*RS_SIZE)  # 源操作数2的 ROB tag
        rs_qj_valid = RegArray(UInt(1), RS_SIZE, initializer=[0]*RS_SIZE)      # Qj 是否有效 (需要等待)
        rs_qk_valid = RegArray(UInt(1), RS_SIZE, initializer=[0]*RS_SIZE)      # Qk 是否有效 (需要等待)
        rs_dest = RegArray(UInt(ROB_ID_BITS), RS_SIZE, initializer=[0]*RS_SIZE)# 目标 ROB ID
        rs_imm = RegArray(UInt(XLEN), RS_SIZE, initializer=[0]*RS_SIZE)        # 立即数
        rs_func = RegArray(UInt(3), RS_SIZE, initializer=[0]*RS_SIZE)          # 功能单元类型
        rs_control = RegArray(UInt(CONTROL_LEN), RS_SIZE, initializer=[0]*RS_SIZE)  # 控制信号
        rs_lsq_id = RegArray(UInt(LSQ_ID_BITS), RS_SIZE, initializer=[0]*RS_SIZE)  # Phase 5: 对应 LSQ ID
        rs_pc = RegArray(UInt(XLEN), RS_SIZE, initializer=[0]*RS_SIZE)         # 指令 PC (用于分支目标计算)
        
        # ==================== Phase 5: LSQ 数据结构 ====================
        lsq_valid = RegArray(UInt(1), LSQ_SIZE, initializer=[0]*LSQ_SIZE)       # 是否有效
        lsq_is_store = RegArray(UInt(1), LSQ_SIZE, initializer=[0]*LSQ_SIZE)    # 1=Store, 0=Load
        lsq_addr_ready = RegArray(UInt(1), LSQ_SIZE, initializer=[0]*LSQ_SIZE)  # 地址是否就绪
        lsq_data_ready = RegArray(UInt(1), LSQ_SIZE, initializer=[0]*LSQ_SIZE)  # 数据是否就绪(Store用)
        lsq_addr = RegArray(UInt(XLEN), LSQ_SIZE, initializer=[0]*LSQ_SIZE)     # 访存地址
        lsq_data = RegArray(UInt(XLEN), LSQ_SIZE, initializer=[0]*LSQ_SIZE)     # Store 数据
        lsq_rob_id = RegArray(UInt(ROB_ID_BITS), LSQ_SIZE, initializer=[0]*LSQ_SIZE)  # 对应 ROB ID
        lsq_done = RegArray(UInt(1), LSQ_SIZE, initializer=[0]*LSQ_SIZE)        # 是否完成
        # LSQ 指针
        lsq_head = RegArray(UInt(LSQ_ID_BITS), 1, initializer=[0])  # 最旧条目
        lsq_tail = RegArray(UInt(LSQ_ID_BITS), 1, initializer=[0])  # 下一个分配位置
        
        # ==================== 多FU并行: 4条独立CDB ====================
        # ALU CDB
        cdb_alu_valid = RegArray(UInt(1), 1, initializer=[0])
        cdb_alu_tag = RegArray(UInt(ROB_ID_BITS), 1, initializer=[0])
        cdb_alu_value = RegArray(UInt(XLEN), 1, initializer=[0])
        # Branch CDB
        cdb_branch_valid = RegArray(UInt(1), 1, initializer=[0])
        cdb_branch_tag = RegArray(UInt(ROB_ID_BITS), 1, initializer=[0])
        cdb_branch_value = RegArray(UInt(XLEN), 1, initializer=[0])
        # MulDiv CDB
        cdb_md_valid = RegArray(UInt(1), 1, initializer=[0])
        cdb_md_tag = RegArray(UInt(ROB_ID_BITS), 1, initializer=[0])
        cdb_md_value = RegArray(UInt(XLEN), 1, initializer=[0])
        # LSQ CDB (Load结果)
        cdb_lsq_valid = RegArray(UInt(1), 1, initializer=[0])
        cdb_lsq_tag = RegArray(UInt(ROB_ID_BITS), 1, initializer=[0])
        cdb_lsq_value = RegArray(UInt(XLEN), 1, initializer=[0])
        
        # ==================== 多FU并行: 各FU独立发射寄存器 ====================
        # ALU FU 寄存器 (单周期)
        alu_fu_valid = RegArray(UInt(1), 1, initializer=[0])
        alu_fu_op = RegArray(UInt(5), 1, initializer=[0])
        alu_fu_vj = RegArray(UInt(XLEN), 1, initializer=[0])
        alu_fu_vk = RegArray(UInt(XLEN), 1, initializer=[0])
        alu_fu_dest = RegArray(UInt(ROB_ID_BITS), 1, initializer=[0])
        alu_fu_imm = RegArray(UInt(XLEN), 1, initializer=[0])
        alu_fu_control = RegArray(UInt(CONTROL_LEN), 1, initializer=[0])
        alu_fu_pc = RegArray(UInt(XLEN), 1, initializer=[0])
        
        # Branch FU 寄存器 (单周期)
        branch_fu_valid = RegArray(UInt(1), 1, initializer=[0])
        branch_fu_vj = RegArray(UInt(XLEN), 1, initializer=[0])
        branch_fu_vk = RegArray(UInt(XLEN), 1, initializer=[0])
        branch_fu_dest = RegArray(UInt(ROB_ID_BITS), 1, initializer=[0])
        branch_fu_imm = RegArray(UInt(XLEN), 1, initializer=[0])
        branch_fu_control = RegArray(UInt(CONTROL_LEN), 1, initializer=[0])
        branch_fu_pc = RegArray(UInt(XLEN), 1, initializer=[0])
        
        # LSQ FU 寄存器 (Load/Store)
        lsq_fu_valid = RegArray(UInt(1), 1, initializer=[0])
        lsq_fu_lsq_id = RegArray(UInt(LSQ_ID_BITS), 1, initializer=[0])
        lsq_fu_vj = RegArray(UInt(XLEN), 1, initializer=[0])
        lsq_fu_vk = RegArray(UInt(XLEN), 1, initializer=[0])
        lsq_fu_imm = RegArray(UInt(XLEN), 1, initializer=[0])
        lsq_fu_dest = RegArray(UInt(ROB_ID_BITS), 1, initializer=[0])
        lsq_fu_is_store = RegArray(UInt(1), 1, initializer=[0])
        lsq_fu_control = RegArray(UInt(CONTROL_LEN), 1, initializer=[0])
        
        # 保留原有的 issue_ex 寄存器用于兼容 (后续逐步移除)
        issue_ex_valid = RegArray(UInt(1), 1, initializer=[0])
        issue_ex_op = RegArray(UInt(5), 1, initializer=[0])
        issue_ex_vj = RegArray(UInt(XLEN), 1, initializer=[0])
        issue_ex_vk = RegArray(UInt(XLEN), 1, initializer=[0])
        issue_ex_dest = RegArray(UInt(ROB_ID_BITS), 1, initializer=[0])
        issue_ex_imm = RegArray(UInt(XLEN), 1, initializer=[0])
        issue_ex_control = RegArray(UInt(CONTROL_LEN), 1, initializer=[0])
        issue_ex_func = RegArray(UInt(3), 1, initializer=[0])  # Phase 4: FU 类型
        issue_ex_lsq_id = RegArray(UInt(LSQ_ID_BITS), 1, initializer=[0])  # Phase 5: LSQ ID

        # ==================== Phase 4: MulDiv 状态寄存器 ====================
        md_busy = RegArray(UInt(1), 1, initializer=[0])        # 是否忙
        md_cnt = RegArray(UInt(4), 1, initializer=[0])         # 剩余周期计数
        md_op = RegArray(UInt(5), 1, initializer=[0])          # 操作类型
        md_vj = RegArray(UInt(XLEN), 1, initializer=[0])       # 源操作数1
        md_vk = RegArray(UInt(XLEN), 1, initializer=[0])       # 源操作数2
        md_dest = RegArray(UInt(ROB_ID_BITS), 1, initializer=[0])  # 目标 ROB ID
        # MulDiv pending (CDB 冲突时使用)
        md_pending = RegArray(UInt(1), 1, initializer=[0])
        md_pending_value = RegArray(UInt(XLEN), 1, initializer=[0])
        md_pending_dest = RegArray(UInt(ROB_ID_BITS), 1, initializer=[0])

        # EX/MEM阶段寄存器
        ex_mem_pc = RegArray(UInt(XLEN), 1, initializer=[0])           # PC (32位)
        ex_mem_control = RegArray(UInt(CONTROL_LEN), 1, initializer=[0])  # 控制信号 (42位)
        ex_mem_valid = RegArray(UInt(1), 1, initializer=[1])            # 有效标志 (1位)
        ex_mem_target_pc = RegArray(UInt(XLEN), 1, initializer=[0])    # 目标PC (32位)
        ex_mem_pc_change = RegArray(UInt(1), 1, initializer=[0])       # PC变化标志 (1位)
        ex_mem_result = RegArray(UInt(XLEN), 1, initializer=[0])       # ALU结果 (32位)
        ex_mem_data = RegArray(UInt(XLEN), 1, initializer=[0])          # 数据 (32位)
        ex_mem_rob_id = RegArray(UInt(ROB_ID_BITS), 1, initializer=[0])  # ROB ID (Phase 2)

        # MEM/WB阶段寄存器
        mem_wb_control = RegArray(UInt(CONTROL_LEN), 1, initializer=[0])  # 控制信号 (42位)
        mem_wb_valid = RegArray(UInt(1), 1, initializer=[1])            # 有效标志 (1位)
        mem_wb_mem_data = RegArray(UInt(XLEN), 1, initializer=[0])     # 内存数据 (32位)
        mem_wb_ex_result = RegArray(UInt(XLEN), 1, initializer=[0])     # EX阶段结果 (32位)
        mem_wb_rob_id = RegArray(UInt(ROB_ID_BITS), 1, initializer=[0])  # ROB ID (Phase 2)
        mem_wb_lsq_id = RegArray(UInt(LSQ_ID_BITS), 1, initializer=[0])  # Phase 5: LSQ ID

        # 创建指令内存
        test_program = init_memory(program_file)
        instruction_memory = RegArray(UInt(XLEN), 2048, initializer=test_program + [0]*(2048 - len(test_program)))
        
        # 创建寄存器文件
        reg_file = RegArray(UInt(XLEN), REG_COUNT, initializer=[0]*REG_COUNT)

        pc = RegArray(UInt(XLEN), 1, initializer=[0])
        stall = RegArray(UInt(1), 1, initializer=[0])
        
        data_sram = SRAM(width=XLEN, depth=65536, init_file="data.hex")
        hazard_unit = HazardUnit()
        wakeup_unit = WakeupUnit()  # Phase 3
        dispatch_issue_stage = DispatchIssueStage()  # Phase 3: 合并的分派发射阶段
        lsq_unit = LSQUnit()  # Phase 5: LSQ forwarding unit
        fetch_stage = FetchStage()
        decode_stage = DecodeStage()
        execute_stage = ExecuteStage()
        memory_stage = MemoryStage()
        writeback_stage = WriteBackStage()
        driver = Driver()

        # 按照流水线顺序构建模块
        writeback_signals = writeback_stage.build(mem_wb_valid, mem_wb_mem_data, mem_wb_ex_result, mem_wb_control,
                                                   mem_wb_rob_id,  # Phase 2
                                                   rob_head, rob_valid, rob_ready, rob_value, rob_dest,  # Phase 2
                                                   rob_is_store, rob_lsq_id,  # Phase 5: Store info in ROB
                                                   rat_valid, rat_tag,  # Phase 2
                                                   # 多 FU 并行: 4条独立CDB
                                                   cdb_alu_valid, cdb_alu_tag, cdb_alu_value,
                                                   cdb_branch_valid, cdb_branch_tag, cdb_branch_value,
                                                   cdb_md_valid, cdb_md_tag, cdb_md_value,
                                                   cdb_lsq_valid, cdb_lsq_tag, cdb_lsq_value,
                                                   # Phase 5: LSQ for Store commit
                                                   lsq_valid, lsq_addr, lsq_data, lsq_head,
                                                   reg_file, data_sram)
        # Phase 5: LSQ Store-to-Load 前递
        forward_hit, forward_data, load_blocked = lsq_unit.build(
            lsq_valid, lsq_is_store, lsq_addr_ready, lsq_data_ready,
            lsq_addr, lsq_data, lsq_rob_id, lsq_head,
            ex_mem_lsq_id, ex_mem_result, ex_mem_control)
        
        memory_signals = memory_stage.build(ex_mem_valid, ex_mem_result, ex_mem_pc, ex_mem_data, ex_mem_control,
                                                 ex_mem_rob_id,  # Phase 2
                                                 ex_mem_lsq_id,  # Phase 5: LSQ ID
                                                 mem_wb_control, mem_wb_valid, mem_wb_mem_data, mem_wb_ex_result,
                                                 mem_wb_rob_id,  # Phase 2
                                                 mem_wb_lsq_id,  # Phase 5: LSQ ID to Writeback
                                                 forward_hit, forward_data, load_blocked,  # Phase 5: LSQ forwarding
                                                 lsq_done,  # Phase 5: LSQ done flag
                                                 writeback_stage, data_sram)
        execute_signals = execute_stage.build(id_ex_valid, id_ex_pc, id_ex_rs1_idx, id_ex_rs2_idx, id_ex_immediate, id_ex_control,
                                                   id_ex_rob_id,  # Phase 2
                                                   ex_mem_pc, ex_mem_control, ex_mem_valid, ex_mem_result, ex_mem_data, ex_mem_target_pc, ex_mem_pc_change,
                                                   ex_mem_rob_id,  # Phase 2
                                                   ex_mem_lsq_id,  # Phase 5: LSQ ID to Memory
                                                   # Phase 4: MulDiv 状态寄存器
                                                   md_busy, md_cnt, md_op, md_vj, md_vk, md_dest,
                                                   md_pending, md_pending_value, md_pending_dest,
                                                   # Phase 5: LSQ 相关
                                                   issue_ex_lsq_id, lsq_addr, lsq_addr_ready, lsq_data, lsq_data_ready,
                                                   # 多 FU 并行: 各 FU 输入和 CDB 输出
                                                   alu_fu_valid, alu_fu_op, alu_fu_vj, alu_fu_vk, alu_fu_dest, alu_fu_imm, alu_fu_control,
                                                   branch_fu_valid, branch_fu_vj, branch_fu_vk, branch_fu_dest, branch_fu_imm, branch_fu_control, branch_fu_pc,
                                                   lsq_fu_valid, lsq_fu_lsq_id, lsq_fu_vj, lsq_fu_vk, lsq_fu_imm, lsq_fu_dest, lsq_fu_is_store, lsq_fu_control,
                                                   cdb_alu_valid, cdb_alu_tag, cdb_alu_value,
                                                   cdb_branch_valid, cdb_branch_tag, cdb_branch_value,
                                                   cdb_md_valid, cdb_md_tag, cdb_md_value,
                                                   cdb_lsq_valid, cdb_lsq_tag, cdb_lsq_value,
                                                   reg_file, memory_stage)
        decode_signals = decode_stage.build(if_id_valid, if_id_pc, if_id_instruction, id_ex_pc, id_ex_control, id_ex_valid, id_ex_rs1_idx, id_ex_rs2_idx, id_ex_immediate, id_ex_need_rs1, id_ex_need_rs2,
                                          rat_valid, rat_tag, rob_head, rob_tail, rob_valid, rob_ready, rob_value, rob_dest, rob_pc,
                                          rob_old_tag_valid, rob_old_tag,
                                          rs_busy, rs_op, rs_vj, rs_vk, rs_qj, rs_qk, rs_qj_valid, rs_qk_valid, rs_dest, rs_imm, rs_func, rs_control, rs_lsq_id, rs_pc,
                                          lsq_valid, lsq_is_store, lsq_addr_ready, lsq_data_ready, lsq_addr, lsq_data, lsq_rob_id, lsq_done, lsq_head, lsq_tail,
                                          rob_is_store, rob_lsq_id,
                                          issue_ex_valid, issue_ex_op, issue_ex_vj, issue_ex_vk, issue_ex_dest, issue_ex_imm, issue_ex_control, issue_ex_func, issue_ex_lsq_id,
                                          md_busy,
                                          # 多 FU 并行: 各 FU 寄存器
                                          alu_fu_valid, alu_fu_op, alu_fu_vj, alu_fu_vk, alu_fu_dest, alu_fu_imm, alu_fu_control,
                                          branch_fu_valid, branch_fu_vj, branch_fu_vk, branch_fu_dest, branch_fu_imm, branch_fu_control, branch_fu_pc,
                                          lsq_fu_valid, lsq_fu_lsq_id, lsq_fu_vj, lsq_fu_vk, lsq_fu_imm, lsq_fu_dest, lsq_fu_is_store, lsq_fu_control,
                                          reg_file, dispatch_issue_stage, execute_stage)
        fetch_signals = fetch_stage.build(pc, stall, if_id_pc, if_id_instruction, if_id_valid, instruction_memory, decode_stage)
        # Phase 3: 分派发射阶段 - 已合并到 DecodeStage 内部调用
        
        # Phase 3: 唤醒单元 (多CDB版本)
        wakeup_unit.build(cdb_alu_valid, cdb_alu_tag, cdb_alu_value,
                          cdb_branch_valid, cdb_branch_tag, cdb_branch_value,
                          cdb_md_valid, cdb_md_tag, cdb_md_value,
                          cdb_lsq_valid, cdb_lsq_tag, cdb_lsq_value,
                          rs_busy, rs_vj, rs_vk, rs_qj, rs_qk, rs_qj_valid, rs_qk_valid)
        
        hazard_unit.build(pc, stall, if_id_valid, if_id_instruction, id_ex_control, id_ex_valid, id_ex_rs1_idx, id_ex_rs2_idx, id_ex_immediate,
                          id_ex_rob_id,  # Phase 2
                          ex_mem_valid, mem_wb_valid,
                          rob_valid, rob_ready, rob_tail, rob_dest, rob_old_tag_valid, rob_old_tag, rat_valid, rat_tag,
                          rs_busy, rs_dest,  # Phase 3
                          lsq_valid, lsq_rob_id, lsq_head, lsq_tail,  # Phase 5: LSQ for Walk-back
                          md_busy, md_dest,  # Phase 4
                          fetch_signals, decode_signals, execute_signals, memory_signals, writeback_signals)
        
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