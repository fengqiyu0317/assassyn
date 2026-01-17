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
ROB_SLOT_BITS = 4   # ROB 槽位索引位宽 (log2(16) = 4)
ROB_ID_BITS = 16    # ROB ID 位宽 (全局唯一递增 ID)

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
    def build(self, pc, if_id_pc, if_id_instruction, instruction_memory, decode_stage):
        current_pc = pc[0]
        word_addr = current_pc >> UInt(XLEN)(2)
        instruction = UInt(XLEN)(0)

        instruction = instruction_memory[word_addr]
        if_id_pc[0] = current_pc
        log("IF: PC={:08x}, Instruction={:08x}", current_pc, instruction)

        decode_stage.async_called()

        fetch_signals = instruction.bitcast(Bits(XLEN))
        return fetch_signals

# ==================== ID阶段：指令解码 ===================
class DecodeStage(Module):
    """指令解码阶段(ID) - OoO 架构：解码、ROB 分配、RAT 查询"""
    def __init__(self):
        super().__init__(ports={})
    
    @module.combinational
    def build(self, if_id_pc, if_id_instruction,
              # RAT 和 ROB
              rat_valid, rat_tag, rob_head, rob_tail, rob_valid, rob_ready, rob_value, rob_dest, rob_pc,
              rob_old_tag_valid, rob_old_tag, rob_id, rob_id_counter,
              # Dispatch 中间寄存器 (写入供 DispatchIssueStage 读取)
              dispatch_valid_reg, dispatch_rob_id_reg, dispatch_pc_reg,
              dispatch_rs1_value, dispatch_rs1_tag, dispatch_rs1_ready,
              dispatch_rs2_value, dispatch_rs2_tag, dispatch_rs2_ready,
              # 控制和立即数寄存器 (供 DispatchIssueStage 使用)
              decode_control, decode_immediate,
              reg_file):
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
        
        # M 扩展指令检测：opcode=0b0110011 (R型) 且 funct7=0b0000001
        is_m_type = is_r_type & (funct7 == UInt(7)(0b0000001))
        
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
        
        # M 扩展指令的 alu_op：使用 0b10xxx 编码
        # MUL=0b10000, MULH=0b10001, MULHSU=0b10010, MULHU=0b10011
        # DIV=0b10100, DIVU=0b10101, REM=0b10110, REMU=0b10111
        m_alu_op = concat(UInt(2)(0b10), func3).bitcast(UInt(5))  # 0b10 + func3[2:0]
        alu_op_tmp = is_m_type.select(m_alu_op, alu_op_tmp)
        
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
        
        # ==================== 指令类型决定操作数需求 ====================
        # 不同指令类型对 rs1/rs2 的需求:
        # - R-type (ADD, SUB, etc.): 需要 rs1, rs2
        # - I-type (ADDI, etc.): 需要 rs1，不需要 rs2
        # - L-type (LW, etc.): 需要 rs1 (基址)，不需要 rs2
        # - S-type (SW, etc.): 需要 rs1 (基址), rs2 (数据)
        # - B-type (BEQ, etc.): 需要 rs1, rs2 (比较)
        # - U-type (LUI, AUIPC): 不需要 rs1, rs2
        # - J-type (JAL): 不需要 rs1, rs2
        # - JR-type (JALR): 需要 rs1，不需要 rs2
        need_rs1 = (is_i_type | is_r_type | is_s_type | is_b_type | is_l_type | is_jr_type)
        need_rs2 = (is_r_type | is_s_type | is_b_type)
        
        # ==================== RAT 查询逻辑 ====================
        # rs1 操作数查询
        rs1_rat_valid = rat_valid[rs1]  # 是否有未提交指令写 rs1
        rs1_rat_tag = rat_tag[rs1]      # 对应的 ROB ID (16位全局唯一)
        rs1_rat_slot = rs1_rat_tag[0:ROB_SLOT_BITS - 1].bitcast(UInt(ROB_SLOT_BITS))  # 转换为槽位索引
        
        rs1_from_rf = ~rs1_rat_valid                            # 从RF取值
        rs1_from_rob = rs1_rat_valid & rob_ready[rs1_rat_slot]  # 从ROB取值
        rs1_need_tag = rs1_rat_valid & ~rob_ready[rs1_rat_slot] # 需要等待
        
        rs1_value_raw = rs1_from_rf.select(
            reg_file[rs1],
            rs1_from_rob.select(rob_value[rs1_rat_slot], UInt(XLEN)(0))
        )
        rs1_tag_raw = rs1_need_tag.select(rs1_rat_tag, UInt(ROB_ID_BITS)(0))  # 仍然传递全局 ROB ID
        rs1_ready_raw = (rs1_from_rf | rs1_from_rob).bitcast(UInt(1))
        
        # 根据指令类型决定 rs1 的最终值
        # 如果不需要 rs1，则 ready=1, value=0, tag=0
        rs1_value = need_rs1.select(rs1_value_raw, UInt(XLEN)(0))
        rs1_tag_out = need_rs1.select(rs1_tag_raw, UInt(ROB_ID_BITS)(0))
        rs1_ready = need_rs1.select(rs1_ready_raw, UInt(1)(1))  # 不需要时直接 ready
        
        # rs2 操作数查询
        rs2_rat_valid = rat_valid[rs2]
        rs2_rat_tag = rat_tag[rs2]
        rs2_rat_slot = rs2_rat_tag[0:ROB_SLOT_BITS - 1].bitcast(UInt(ROB_SLOT_BITS))  # 转换为槽位索引
        
        rs2_from_rf = ~rs2_rat_valid
        rs2_from_rob = rs2_rat_valid & rob_ready[rs2_rat_slot]
        rs2_need_tag = rs2_rat_valid & ~rob_ready[rs2_rat_slot]
        
        rs2_value_raw = rs2_from_rf.select(
            reg_file[rs2],
            rs2_from_rob.select(rob_value[rs2_rat_slot], UInt(XLEN)(0))
        )
        rs2_tag_raw = rs2_need_tag.select(rs2_rat_tag, UInt(ROB_ID_BITS)(0))  # 仍然传递全局 ROB ID
        rs2_ready_raw = (rs2_from_rf | rs2_from_rob).bitcast(UInt(1))
        
        # 根据指令类型决定 rs2 的最终值
        # 如果不需要 rs2，则 ready=1, value=0, tag=0
        rs2_value = need_rs2.select(rs2_value_raw, UInt(XLEN)(0))
        rs2_tag_out = need_rs2.select(rs2_tag_raw, UInt(ROB_ID_BITS)(0))
        rs2_ready = need_rs2.select(rs2_ready_raw, UInt(1)(1))  # 不需要时直接 ready
        
        # 分配 ROB ID (用于目标寄存器) - 使用全局唯一递增 ID
        allocated_rob_id = rob_id_counter[0]
        # ROB 槽位索引 (循环队列)
        rob_slot = rob_tail[0]
        
        # ==================== ROB 满检测 ====================
        # 计算下一个 tail 位置
        next_rob_tail = (rob_tail[0] + UInt(ROB_SLOT_BITS)(1)) & UInt(ROB_SLOT_BITS)(ROB_SIZE - 1)
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
        
        log("ID: PC={}, Opcode={:07b}, RD={}, RS1={}, RS2={}, Immediate={}, Alu_op={}, Branch_op={}, Jump_op={}, Alu_src={}, Mem_read={}, Mem_write={}, Reg_write={}, Mem_to_reg={}, need_rs1={}, need_rs2={}, Control={:042b}",
            if_id_pc_in, opcode, rd, rs1, rs2, immediate, alu_op, branch_op, jump_op, alu_src, mem_read, mem_write, reg_write, mem_to_reg, need_rs1, need_rs2, control_signals)
        
        # ==================== RAT 更新逻辑 ====================
        # 当有写寄存器操作且目标不是x0且ROB未满时，更新RAT
        with Condition(reg_write & (rd != UInt(5)(0)) & ~rob_full):
            # 保存旧的 RAT 映射到 ROB（用于 Walk-back 恢复）
            rob_old_tag_valid[rob_slot] = rat_valid[rd]
            rob_old_tag[rob_slot] = rat_tag[rd]
            
            # 更新 RAT (使用全局唯一 ROB ID)
            rat_valid[rd] = UInt(1)(1)
            rat_tag[rd] = allocated_rob_id
            
            # 同时在ROB中分配条目 (使用槽位索引)
            rob_valid[rob_slot] = UInt(1)(1)
            rob_ready[rob_slot] = UInt(1)(0)  # 结果未就绪
            rob_dest[rob_slot] = rd.bitcast(UInt(5))
            rob_pc[rob_slot] = if_id_pc_in
            rob_id[rob_slot] = allocated_rob_id  # 存储全局唯一 ROB ID
            # 递增 rob_tail (环形队列) 和 rob_id_counter (全局唯一)
            rob_tail[0] = next_rob_tail
            rob_id_counter[0] = rob_id_counter[0] + UInt(ROB_ID_BITS)(1)
            log("RAT Update: rd={}, rob_id={}, rob_slot={}, old_valid={}, old_tag={}", rd, allocated_rob_id, rob_slot, rat_valid[rd], rat_tag[rd])
        
        # Phase 3: 将 Dispatch 所需信息写入寄存器（供 DispatchIssueStage 读取）
        dispatch_valid = ~rob_full
        dispatch_valid_reg[0] = dispatch_valid
        dispatch_rob_id_reg[0] = allocated_rob_id
        dispatch_pc_reg[0] = if_id_pc_in
        dispatch_rs1_value[0] = rs1_value
        dispatch_rs1_tag[0] = rs1_tag_out
        dispatch_rs1_ready[0] = rs1_ready
        dispatch_rs2_value[0] = rs2_value
        dispatch_rs2_tag[0] = rs2_tag_out
        dispatch_rs2_ready[0] = rs2_ready

        # OoO: 不再手动触发 dispatch_issue_stage，由框架自动调度
        # dispatch_issue_stage.async_called() - 移除，避免重复触发

        # 简化的 decode_signals - 仅包含 HazardUnit 需要的信息
        # 结构: [control(42), imm(32), rob_id(16), rob_full(1)] = 91 bits
        decode_signals = concat(
            rob_full.bitcast(UInt(1)),  # ROB满标志
            allocated_rob_id,  # 分配的ROB ID (用于 Walk-back) - 16位全局唯一ID
            immediate,               # 立即数
            control_signals.bitcast(UInt(CONTROL_LEN)),  # 控制信号
        )
        return decode_signals

# ==================== Phase 3: 分派阶段 ===================
# ==================== Phase 3: 分派发射阶段 (合并) ===================
class DispatchIssueStage(Module):
    """指令分派与发射阶段 - 将解码后的指令放入 RS，并选择就绪指令发射"""
    def __init__(self):
        super().__init__(ports={})
    
    @module.combinational
    def build(self, 
              # Dispatch 中间寄存器 (从 DecodeStage 写入)
              dispatch_valid_reg, decode_control, decode_immediate, 
              dispatch_rob_id_reg, dispatch_pc_reg,
              dispatch_rs1_value, dispatch_rs1_tag, dispatch_rs1_ready,
              dispatch_rs2_value, dispatch_rs2_tag, dispatch_rs2_ready,
              # RS 相关
              rs_busy, rs_op, rs_vj, rs_vk, rs_qj, rs_qk, rs_qj_valid, rs_qk_valid, 
              rs_dest, rs_imm, rs_func, rs_control, rs_lsq_id, rs_pc,
              # Phase 5: LSQ 相关参数
              lsq_valid, lsq_is_store, lsq_addr_ready, lsq_data_ready,
              lsq_addr, lsq_data, lsq_rob_id, lsq_done,
              lsq_head, lsq_tail,
              # Phase 5: ROB Store 信息
              rob_is_store, rob_lsq_id,
              # MulDiv FU 发射寄存器
              md_fu_valid, md_fu_op, md_fu_vj, md_fu_vk, md_fu_dest, md_fu_imm, md_fu_control, md_fu_func,
              md_busy,  # Phase 4: MulDiv 忙状态
              # 多 FU 并行: 各 FU 独立寄存器
              alu_fu_valid, alu_fu_op, alu_fu_vj, alu_fu_vk, alu_fu_dest, alu_fu_imm, alu_fu_control, alu_fu_pc,
              branch_fu_valid, branch_fu_vj, branch_fu_vk, branch_fu_dest, branch_fu_imm, branch_fu_control, branch_fu_pc,
              lsq_fu_valid, lsq_fu_lsq_id, lsq_fu_vj, lsq_fu_vk, lsq_fu_imm, lsq_fu_dest, lsq_fu_is_store, lsq_fu_control,
              execute_stage):
        
        # ==================== Part 1: Dispatch 逻辑 ====================
        # 从寄存器数组读取（在本模块内部读取，避免跨模块表达式问题）
        dispatch_valid = dispatch_valid_reg[0]
        dispatch_control = decode_control[0]
        dispatch_immediate = decode_immediate[0]
        dispatch_rob_id = dispatch_rob_id_reg[0]
        dispatch_pc = dispatch_pc_reg[0]
        rs1_value = dispatch_rs1_value[0]
        rs1_tag = dispatch_rs1_tag[0]
        rs1_ready = dispatch_rs1_ready[0]
        rs2_value = dispatch_rs2_value[0]
        rs2_tag = dispatch_rs2_tag[0]
        rs2_ready = dispatch_rs2_ready[0]
        
        # 解析控制信号
        alu_op = dispatch_control[0:4]
        mem_read = dispatch_control[5:5]
        mem_write = dispatch_control[6:6]
        reg_write = dispatch_control[7:7]
        alu_src = dispatch_control[9:10]  # [10:9] ALU输入选择: 00=reg, 01=imm, 10=PC
        branch_op = dispatch_control[17:19]
        jump_op = dispatch_control[20:20]    # JAL 指令标志
        jumpr_op = dispatch_control[21:21]   # JALR 指令标志
        
        # 确定功能单元类型
        # 指令分类：
        # - LUI/AUIPC: alu_src=01/10, 不需要rs1/rs2, 发到 ALU (默认)
        # - JAL: jump_op=1, 不需要rs1/rs2, 发到 Branch FU
        # - JALR: jumpr_op=1, 需要rs1, 发到 Branch FU
        # - Branch: branch_op!=0, 需要rs1/rs2, 发到 Branch FU
        # - Load/Store: mem_read/mem_write, 发到 LSQ FU
        # - MulDiv: alu_op[4:3]=10, 发到 MulDiv FU
        # - ALU: 其他, 发到 ALU FU
        
        # 乘除法检测：alu_op[4:3] == 0b10 表示 M 扩展指令
        is_muldiv = (alu_op[3:4] == UInt(2)(0b10))
        is_mul = is_muldiv & ~alu_op[2:2]  # alu_op[2]=0 是乘法 (MUL/MULH/MULHSU/MULHU)
        is_div = is_muldiv & alu_op[2:2]   # alu_op[2]=1 是除法 (DIV/DIVU/REM/REMU)
        
        # 跳转指令检测
        is_jump = jump_op | jumpr_op  # JAL 或 JALR
        is_branch_type = (branch_op != UInt(3)(0))  # 条件分支
        
        fu_type = UInt(3)(FU_ALU)  # 默认为 ALU (包括 LUI, AUIPC, 普通 ALU 指令)
        fu_type = is_mul.select(UInt(3)(FU_MUL), fu_type)
        fu_type = is_div.select(UInt(3)(FU_DIV), fu_type)
        fu_type = is_branch_type.select(UInt(3)(FU_BRANCH), fu_type)  # 条件分支
        fu_type = is_jump.select(UInt(3)(FU_BRANCH), fu_type)  # JAL/JALR 也发到 Branch FU
        fu_type = mem_read.select(UInt(3)(FU_LOAD), fu_type)
        fu_type = mem_write.select(UInt(3)(FU_STORE), fu_type)
        
        # Phase 5: 判断是否为访存指令
        is_load = mem_read
        is_store = mem_write
        is_mem_op = is_load | is_store
        
        # Phase 5: 计算 LSQ 满 (仅访存指令需要 LSQ)
        lsq_next_tail = (lsq_tail[0] + UInt(LSQ_ID_BITS)(1)) & UInt(LSQ_ID_BITS)(LSQ_SIZE - 1)
        lsq_full = (lsq_next_tail == lsq_head[0]) & is_mem_op  # 非访存指令时 lsq_full=0
        
        # 找空闲 RS (简单优先级编码) - 所有指令都需要 RS
        rs_free = UInt(RS_ID_BITS)(0)
        rs_found = UInt(1)(0)

        for i in range(RS_SIZE):
            rs_free = (~rs_busy[i] & ~rs_found).select(UInt(RS_ID_BITS)(i), rs_free)
            rs_found = (~rs_busy[i] & ~rs_found).select(UInt(1)(1), rs_found)
        
        # RS 满检测 - 所有指令都需要 RS
        rs_full = ~rs_found
        
        # Phase 5: 综合 Stall 条件 (按指令类型分类)
        # - ALU/Branch 指令: 只需要 RS，stall = rs_full
        # - Load/Store 指令: 需要 RS + LSQ，stall = rs_full | lsq_full
        # 由于 lsq_full 已包含 is_mem_op，非访存指令时 lsq_full=0，所以可以统一处理
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
        dispatch_rob_slot = dispatch_rob_id[0:ROB_SLOT_BITS - 1].bitcast(UInt(ROB_SLOT_BITS))  # 转换为槽位索引
        with Condition(dispatch_valid & ~stall_condition & is_mem_op):
            lsq_id = lsq_tail[0]
            lsq_valid[lsq_id] = UInt(1)(1)
            lsq_is_store[lsq_id] = is_store
            lsq_addr_ready[lsq_id] = UInt(1)(0)
            lsq_data_ready[lsq_id] = UInt(1)(0)
            lsq_rob_id[lsq_id] = dispatch_rob_id  # 存储全局 ROB ID
            lsq_done[lsq_id] = UInt(1)(0)
            lsq_tail[0] = lsq_next_tail
            # Phase 5: 在 ROB 中记录 Store 信息（用于 Commit 阶段写内存）- 使用槽位索引
            rob_is_store[dispatch_rob_slot] = is_store
            rob_lsq_id[dispatch_rob_slot] = lsq_id
            log("Dispatch: LSQ[{}] allocated, is_store={}, ROB id={} slot={}", lsq_id, is_store, dispatch_rob_id, dispatch_rob_slot)
        
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
            alu_fu_pc[0] = rs_pc[alu_issue_idx]  # AUIPC 需要 PC
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
                
        # 将 MulDiv 发射信息写入 md_fu (MulDiv 走 ExecuteStage 路径)
        with Condition(muldiv_issue_found):
            md_fu_valid[0] = UInt(1)(1)
            md_fu_op[0] = rs_op[muldiv_issue_idx]
            md_fu_vj[0] = rs_vj[muldiv_issue_idx]
            md_fu_vk[0] = rs_vk[muldiv_issue_idx]
            md_fu_dest[0] = rs_dest[muldiv_issue_idx]
            md_fu_imm[0] = rs_imm[muldiv_issue_idx]
            md_fu_control[0] = rs_control[muldiv_issue_idx]
            md_fu_func[0] = rs_func[muldiv_issue_idx]
            rs_busy[muldiv_issue_idx] = UInt(1)(0)
            log("Issue MulDiv: RS[{}] -> MulDiv_FU, ROB[{}], op={:05b}", muldiv_issue_idx, rs_dest[muldiv_issue_idx], rs_op[muldiv_issue_idx])
        
        with Condition(~muldiv_issue_found):
            md_fu_valid[0] = UInt(1)(0)
            md_fu_op[0] = UInt(5)(0)
            md_fu_vj[0] = UInt(XLEN)(0)
            md_fu_vk[0] = UInt(XLEN)(0)
            md_fu_dest[0] = UInt(ROB_ID_BITS)(0)
            md_fu_imm[0] = UInt(XLEN)(0)
            md_fu_control[0] = UInt(CONTROL_LEN)(0)
            md_fu_func[0] = UInt(3)(0)
        
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
        
        # 保持原有 issue_valid 兼容性 (用于统计)
        issue_valid = alu_issue_found | branch_issue_found | muldiv_issue_found | lsq_issue_found
        
        execute_stage.async_called()
        
        # 返回 stall 信号给 HazardUnit 用于 Stall
        # 使用 concat 组合成单个信号: [stall_condition(1), issue_valid(1)]
        dispatch_signals = concat(issue_valid, stall_condition)
        return dispatch_signals

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
        """乘除计算单元 - 仅计算结果，多周期由状态机控制
        注意：除法/取模需要多周期硬件实现，这里暂用占位符
        """
        result = UInt(XLEN)(0)
        a_signed = a.bitcast(Int(XLEN))
        b_signed = b.bitcast(Int(XLEN))
        
        # MUL: result = (a * b)[31:0]
        mul_result = (a * b).bitcast(UInt(XLEN))
        # MULH: result = (signed(a) * signed(b))[63:32]
        mulh_result = ((a_signed * b_signed) >> Int(32)(32)).bitcast(UInt(XLEN))
        
        # DIV/REM: Assassyn 不支持直接除法，需要多周期硬件实现
        # 暂时用 0 占位，后续需要实现硬件除法器
        div_result = UInt(XLEN)(0)  # TODO: 实现多周期除法器
        rem_result = UInt(XLEN)(0)  # TODO: 实现多周期除法器
        
        # 根据 op 选择结果 (使用 alu_op 的低 3 位区分 M 扩展指令)
        result = (op[0:2] == UInt(3)(0b000)).select(mul_result, result)   # MUL
        result = (op[0:2] == UInt(3)(0b001)).select(mulh_result, result)  # MULH
        result = (op[0:2] == UInt(3)(0b100)).select(div_result, result)   # DIV
        result = (op[0:2] == UInt(3)(0b110)).select(rem_result, result)   # REM
        
        log("MULDIV: OP={:05b}, A={:08x}, B={:08x}, Result={:08x}", op, a, b, result)
        
        return result

    @module.combinational
    def build(self,
              # Phase 4: MulDiv 状态寄存器
              md_busy, md_cnt, md_op, md_vj, md_vk, md_dest,
              # Phase 5: LSQ 相关
              lsq_addr, lsq_addr_ready, lsq_data, lsq_data_ready,
              # 多 FU 并行: 各 FU 输入寄存器
              alu_fu_valid, alu_fu_op, alu_fu_vj, alu_fu_vk, alu_fu_dest, alu_fu_imm, alu_fu_control, alu_fu_pc,
              branch_fu_valid, branch_fu_vj, branch_fu_vk, branch_fu_dest, branch_fu_imm, branch_fu_control, branch_fu_pc,
              lsq_fu_valid, lsq_fu_lsq_id, lsq_fu_vj, lsq_fu_vk, lsq_fu_imm, lsq_fu_dest, lsq_fu_is_store, lsq_fu_control,
              # MulDiv FU 发射寄存器
              md_fu_valid, md_fu_op, md_fu_vj, md_fu_vk, md_fu_dest, md_fu_func,
              # 多 FU 并行: 4条独立CDB
              cdb_alu_valid, cdb_alu_tag, cdb_alu_value,
              cdb_branch_valid, cdb_branch_tag, cdb_branch_value,
              cdb_md_valid, cdb_md_tag, cdb_md_value,
              cdb_lsq_valid, cdb_lsq_tag, cdb_lsq_value,
              memory_stage, complete_stage):
        # ========== OoO: 多 FU 并行执行 + CDB 广播 ==========
        # 传统 id_ex_* → ex_mem_* 流水线已移除，所有执行通过 FU 完成
        
        # ========== MulDiv FU 启动逻辑 ==========
        # 当 md_fu_valid=1 且 md_busy=0 时，启动 MulDiv 操作
        with Condition(md_fu_valid[0] & ~md_busy[0]):
            md_busy[0] = UInt(1)(1)
            md_cnt[0] = UInt(4)(4)  # 4 周期延迟
            md_op[0] = md_fu_op[0]
            md_vj[0] = md_fu_vj[0]
            md_vk[0] = md_fu_vk[0]
            md_dest[0] = md_fu_dest[0]
            md_fu_valid[0] = UInt(1)(0)  # 清除发射寄存器
            log("MulDiv Start: op={:05b}, vj={:08x}, vk={:08x}, dest=ROB[{}]", md_fu_op[0], md_fu_vj[0], md_fu_vk[0], md_fu_dest[0])
        
        # ========== MulDiv FU 多周期状态机 ==========
        # 递减计数器
        with Condition(md_busy[0] & (md_cnt[0] > UInt(4)(1))):
            md_cnt[0] = md_cnt[0] - UInt(4)(1)
        
        # MulDiv 完成检测
        md_done = md_busy[0] & (md_cnt[0] == UInt(4)(1))
        md_result = self.muldiv_unit(md_op[0], md_vj[0], md_vk[0])
        
        with Condition(md_done):
            md_busy[0] = UInt(1)(0)
            log("MulDiv Done: dest=ROB[{}], result={:08x}", md_dest[0], md_result)
        
        # ========== 多 FU 并行执行 + CDB 广播 ==========
        # ALU FU: 单周期执行，立即广播到 CDB_ALU
        # 根据 alu_src 选择操作数:
        # - alu_src=00: op1=Vj(rs1), op2=Vk(rs2) (R-type)
        # - alu_src=01: op1=Vj(rs1), op2=imm (I-type, LUI uses op1=0)
        # - alu_src=10: op1=PC, op2=imm (AUIPC)
        with Condition(alu_fu_valid[0]):
            alu_control = alu_fu_control[0]
            alu_src = alu_control[9:10]  # [10:9] ALU输入选择
            
            # 第一操作数: alu_src=10 时用 PC，否则用 Vj
            alu_op1 = (alu_src == UInt(2)(0b10)).select(alu_fu_pc[0], alu_fu_vj[0])
            
            # 第二操作数: alu_src=00 时用 Vk，否则用立即数
            alu_op2 = (alu_src == UInt(2)(0b00)).select(alu_fu_vk[0], alu_fu_imm[0])
            
            alu_fu_result = self.alu_unit(alu_fu_op[0], alu_op1, alu_op2)
            cdb_alu_valid[0] = UInt(1)(1)
            cdb_alu_tag[0] = alu_fu_dest[0]
            cdb_alu_value[0] = alu_fu_result
            alu_fu_valid[0] = UInt(1)(0)  # 清除 FU 占用
            log("CDB_ALU: tag=ROB[{}], op1={:08x}, op2={:08x}, result={:08x}, alu_src={}", alu_fu_dest[0], alu_op1, alu_op2, alu_fu_result, alu_src)
        with Condition(~alu_fu_valid[0]):
            cdb_alu_valid[0] = UInt(1)(0)
        
        # Branch FU: 单周期执行，广播分支结果到 CDB_Branch
        # 处理三种类型的指令:
        # - 条件分支 (BEQ/BNE/BLT/BGE/BLTU/BGEU): branch_op != 0, rd=x0, 不写回
        # - JAL: jump_op = 1, 写 PC+4 到 rd, 跳转到 PC+imm
        # - JALR: jumpr_op = 1, 写 PC+4 到 rd, 跳转到 rs1+imm
        with Condition(branch_fu_valid[0]):
            branch_fu_control_in = branch_fu_control[0]
            branch_fu_branch_op = branch_fu_control_in[17:19]
            branch_fu_jump_op = branch_fu_control_in[20:20]
            branch_fu_jumpr_op = branch_fu_control_in[21:21]
            
            # 条件分支判断
            branch_taken = self.branch_unit(branch_fu_branch_op, branch_fu_vj[0], branch_fu_vk[0])
            
            # 计算跳转目标
            # - 条件分支/JAL: PC + imm
            # - JALR: rs1 + imm (& ~1 按规范)
            branch_target = branch_fu_pc[0] + branch_fu_imm[0]  # 默认: PC + imm
            jalr_target = (branch_fu_vj[0] + branch_fu_imm[0]) & UInt(XLEN)(0xFFFFFFFE)  # JALR: rs1+imm, 低位清零
            final_target = branch_fu_jumpr_op.select(jalr_target, branch_target)
            
            # 计算返回值 (写入 rd / ROB)
            link_addr = branch_fu_pc[0] + UInt(XLEN)(4)
            is_jump_instr = branch_fu_jump_op | branch_fu_jumpr_op
            is_cond_branch = (branch_fu_branch_op != UInt(3)(0))
            
            # ROB value (写入寄存器的值):
            # - JAL/JALR: PC+4 (link address)
            # - 条件分支: 跳转目标 (供 HazardUnit 检查)
            rob_write_value = is_jump_instr.select(link_addr, branch_taken.select(final_target, link_addr))
            
            # CDB value 用于 HazardUnit 判断是否需要跳转:
            # - 所有情况都传递实际跳转目标地址 (taken ? target : PC+4)
            cdb_value = (is_jump_instr | branch_taken).select(final_target, link_addr)
            
            cdb_branch_valid[0] = UInt(1)(1)
            cdb_branch_tag[0] = branch_fu_dest[0]
            cdb_branch_value[0] = cdb_value  # 跳转目标地址
            cdb_branch_link[0] = link_addr   # JAL/JALR 的 link address (PC+4)
            branch_fu_valid[0] = UInt(1)(0)  # 清除 FU 占用
            log("CDB_Branch: tag=ROB[{}], branch_op={}, jump={}, jumpr={}, taken={}, target={:08x}, rob_val={:08x}, cdb_val={:08x}", 
                branch_fu_dest[0], branch_fu_branch_op, branch_fu_jump_op, branch_fu_jumpr_op, branch_taken, final_target, rob_write_value, cdb_value)
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
            
            # 只有 LSQ 指令需要访问 MemoryStage
            memory_stage.async_called()
        
        # CDB_LSQ: Load 结果广播 (由 MemoryStage 或 LSQ 前递设置)
        # 这里暂时保持空，Load 结果在 MemoryStage 完成后通过其他路径广播
        # TODO: 完整实现需要 Load 完成后的 CDB 广播逻辑
        
        # 触发 Complete 阶段（处理 CDB → ROB 写回）
        complete_stage.async_called()

        # OoO 架构不再需要返回流水线信号，返回空信号
        execute_signals = UInt(1)(0)

        return execute_signals

# ==================== MEM阶段：内存访问 (OoO 重构) ===================
class MemoryStage(Module):
    """内存访问阶段(MEM) - OoO 架构：处理 LSQ 的 Load/Store 请求
    
    注意: data_sram 有一周期延迟，所以:
    - MemoryStage: 发起读取请求 + 设置 load_pending 寄存器
    - CompleteStage: 读取 data_sram.dout 并广播到 CDB
    """
    def __init__(self):
        super().__init__(ports={})
    
    @module.combinational
    def build(self,
              # LSQ FU 输入寄存器 (由 ExecuteStage 填充)
              lsq_fu_valid, lsq_fu_lsq_id, lsq_fu_vj, lsq_fu_imm, lsq_fu_dest, lsq_fu_is_store, lsq_fu_control,
              # LSQ 状态
              lsq_valid, lsq_is_store, lsq_addr_ready, lsq_data_ready,
              lsq_addr, lsq_data, lsq_rob_id, lsq_done,
              # Load 待处理寄存器 (SRAM 一周期延迟)
              load_pending, load_pending_lsq_id, load_pending_rob_id,
              # CDB_LSQ 输出 (用于广播前递结果，内存读取结果由 CompleteStage 处理)
              cdb_lsq_valid, cdb_lsq_tag, cdb_lsq_value,
              # 内存
              data_sram):
        
        # 从 LSQ FU 寄存器读取当前请求
        lsq_id = lsq_fu_lsq_id[0]
        addr = lsq_addr[lsq_id]
        is_store = lsq_fu_is_store[0]
        is_load = ~is_store
        control_in = lsq_fu_control[0]
        
        # 解析控制信号中的存储类型
        store_type = control_in[22:23]  # 存储类型: 00=SB, 01=SH, 10=SW
        load_type = control_in[11:13]   # 加载类型
        
        word_addr = addr >> UInt(XLEN)(2)
        
        # Store-to-Load 前递检查
        forward_hit, forward_data, load_blocked = lsq_forward_check(
            lsq_valid, lsq_is_store, lsq_addr_ready, lsq_data_ready,
            lsq_addr, lsq_data, lsq_rob_id,
            lsq_id, addr, is_load & lsq_fu_valid[0])
        
        # 处理 Load (仅当 LSQ FU 请求有效时)
        with Condition(lsq_fu_valid[0] & is_load & lsq_addr_ready[lsq_id]):
            with Condition(forward_hit):
                # 前递命中，使用前递数据，直接广播到 CDB
                cdb_lsq_valid[0] = UInt(1)(1)
                cdb_lsq_tag[0] = lsq_fu_dest[0]
                cdb_lsq_value[0] = forward_data
                lsq_done[lsq_id] = UInt(1)(1)
                load_pending[0] = UInt(1)(0)  # 无需等待 SRAM
                log("MEM: Load LSQ[{}] forwarded data={:08x} -> ROB[{}]", lsq_id, forward_data, lsq_fu_dest[0])
            with Condition(~forward_hit & ~load_blocked):
                # 无前递，发起内存读取请求 (SRAM 有一周期延迟)
                data_sram.build(we=UInt(1)(0), re=UInt(1)(1), addr=word_addr, wdata=UInt(XLEN)(0))
                # 设置待处理寄存器，下一周期由 CompleteStage 读取结果
                load_pending[0] = UInt(1)(1)
                load_pending_lsq_id[0] = lsq_id
                load_pending_rob_id[0] = lsq_fu_dest[0]
                # 本周期不广播到 CDB (等待 SRAM 返回)
                cdb_lsq_valid[0] = UInt(1)(0)
                log("MEM: Load LSQ[{}] req mem addr={:08x}, waiting SRAM...", lsq_id, addr)
            with Condition(load_blocked):
                # Load 被阻塞，等待前面的 Store 完成
                cdb_lsq_valid[0] = UInt(1)(0)
                load_pending[0] = UInt(1)(0)
                log("MEM: Load LSQ[{}] blocked by earlier store", lsq_id)
        
        # 处理 Store (只标记 done，不写内存，内存写入由 RetireStage 在 Commit 时执行)
        with Condition(lsq_fu_valid[0] & is_store & lsq_addr_ready[lsq_id] & lsq_data_ready[lsq_id]):
            lsq_done[lsq_id] = UInt(1)(1)
            # Store 不需要广播到 CDB (rd = x0)
            cdb_lsq_valid[0] = UInt(1)(0)
            load_pending[0] = UInt(1)(0)
            log("MEM: Store LSQ[{}] ready for commit, addr={:08x} data={:08x}", lsq_id, addr, lsq_data[lsq_id])

        with Condition(~(lsq_fu_valid[0] & is_load & lsq_addr_ready[lsq_id]) & ~(lsq_fu_valid[0] & is_store & lsq_addr_ready[lsq_id] & lsq_data_ready[lsq_id])):
            cdb_lsq_valid[0] = UInt(1)(0)
            load_pending[0] = UInt(1)(0)


# ==================== Phase 5: LSQ 前递函数 ===================
def lsq_forward_check(lsq_valid, lsq_is_store, lsq_addr_ready, lsq_data_ready,
                      lsq_addr, lsq_data, lsq_rob_id,
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
    
    log("LSQForward: load_lsq={}, load_addr={:08x}, fwd_hit={}, fwd_data={:08x}, blocked={}",
        load_lsq_id, load_addr, forward_hit, forward_data, load_blocked)
    
    return forward_hit, forward_data, load_blocked


# ==================== Complete 阶段：CDB → ROB ===================
class CompleteStage(Module):
    """Complete 阶段 - 接收 4 条 CDB 广播，更新 ROB 并唤醒 RS
    
    另外处理 SRAM 一周期延迟的 Load 结果读取
    """
    def __init__(self):
        super().__init__(ports={})
    
    @module.combinational
    def build(self,
              # 4 条独立 CDB
              cdb_alu_valid, cdb_alu_tag, cdb_alu_value,
              cdb_branch_valid, cdb_branch_tag, cdb_branch_value, cdb_branch_link,
              cdb_md_valid, cdb_md_tag, cdb_md_value,
              cdb_lsq_valid, cdb_lsq_tag, cdb_lsq_value,
              # ROB 数组
              rob_ready, rob_value, rob_is_branch, rob_branch_target,
              # RS 数组 (用于唤醒)
              rs_busy, rs_vj, rs_vk, rs_qj, rs_qk, rs_qj_valid, rs_qk_valid,
              # Load 待处理寄存器 (SRAM 一周期延迟)
              load_pending, load_pending_lsq_id, load_pending_rob_id,
              # LSQ 状态 (用于标记 Load 完成)
              lsq_done,
              # SRAM 读取结果
              data_sram,
              # 下游模块
              retire_stage):
        
        # ========== ALU CDB 广播 ==========
        cdb_alu_slot = cdb_alu_tag[0][0:ROB_SLOT_BITS - 1].bitcast(UInt(ROB_SLOT_BITS))  # 转换为槽位索引
        with Condition(cdb_alu_valid[0]):
            # CDB -> ROB (使用槽位索引)
            rob_ready[cdb_alu_slot] = UInt(1)(1)
            rob_value[cdb_alu_slot] = cdb_alu_value[0]
            log("Complete ALU: ROB id={} slot={} = {:08x}", cdb_alu_tag[0], cdb_alu_slot, cdb_alu_value[0])
            # CDB -> RS (唤醒) - 使用全局 ROB ID 匹配
            for i in range(RS_SIZE):
                with Condition(rs_busy[i] & rs_qj_valid[i] & (rs_qj[i] == cdb_alu_tag[0])):
                    rs_vj[i] = cdb_alu_value[0]
                    rs_qj_valid[i] = UInt(1)(0)
                with Condition(rs_busy[i] & rs_qk_valid[i] & (rs_qk[i] == cdb_alu_tag[0])):
                    rs_vk[i] = cdb_alu_value[0]
                    rs_qk_valid[i] = UInt(1)(0)
        
        # ========== Branch CDB 广播 ==========
        cdb_branch_slot = cdb_branch_tag[0][0:ROB_SLOT_BITS - 1].bitcast(UInt(ROB_SLOT_BITS))
        with Condition(cdb_branch_valid[0]):
            # CDB -> ROB (使用槽位索引)
            rob_ready[cdb_branch_slot] = UInt(1)(1)
            rob_value[cdb_branch_slot] = cdb_branch_link[0]  # JAL/JALR 写入 link address (PC+4)
            # 标记为分支指令，存储分支目标
            rob_is_branch[cdb_branch_slot] = UInt(1)(1)
            rob_branch_target[cdb_branch_slot] = cdb_branch_value[0]  # 跳转目标地址
            log("Complete Branch: ROB id={} slot={}, target={:08x}, link={:08x}", 
                cdb_branch_tag[0], cdb_branch_slot, cdb_branch_value[0], cdb_branch_link[0])
            # CDB -> RS (唤醒) - 使用全局 ROB ID 匹配，唤醒的值是 link address
            for i in range(RS_SIZE):
                with Condition(rs_busy[i] & rs_qj_valid[i] & (rs_qj[i] == cdb_branch_tag[0])):
                    rs_vj[i] = cdb_branch_link[0]
                    rs_qj_valid[i] = UInt(1)(0)
                with Condition(rs_busy[i] & rs_qk_valid[i] & (rs_qk[i] == cdb_branch_tag[0])):
                    rs_vk[i] = cdb_branch_link[0]
                    rs_qk_valid[i] = UInt(1)(0)
        
        # ========== MulDiv CDB 广播 ==========
        cdb_md_slot = cdb_md_tag[0][0:ROB_SLOT_BITS - 1].bitcast(UInt(ROB_SLOT_BITS))
        with Condition(cdb_md_valid[0]):
            # CDB -> ROB (使用槽位索引)
            rob_ready[cdb_md_slot] = UInt(1)(1)
            rob_value[cdb_md_slot] = cdb_md_value[0]
            log("Complete MulDiv: ROB id={} slot={} = {:08x}", cdb_md_tag[0], cdb_md_slot, cdb_md_value[0])
            # CDB -> RS (唤醒) - 使用全局 ROB ID 匹配
            for i in range(RS_SIZE):
                with Condition(rs_busy[i] & rs_qj_valid[i] & (rs_qj[i] == cdb_md_tag[0])):
                    rs_vj[i] = cdb_md_value[0]
                    rs_qj_valid[i] = UInt(1)(0)
                with Condition(rs_busy[i] & rs_qk_valid[i] & (rs_qk[i] == cdb_md_tag[0])):
                    rs_vk[i] = cdb_md_value[0]
                    rs_qk_valid[i] = UInt(1)(0)
        
        # ========== LSQ Load 结果处理 ==========
        # 两种情况：1) 前递命中 (cdb_lsq_valid 由 MemoryStage 设置)
        #          2) SRAM 延迟读取 (load_pending 由 MemoryStage 设置)
        
        # 计算最终的 LSQ 结果
        # SRAM 延迟读取优先（因为 load_pending 表示上周期发起的请求）
        load_data = data_sram.dout[0]
        pending_lsq_id = load_pending_lsq_id[0]
        pending_rob_id = load_pending_rob_id[0]
        
        # 最终的 tag 和 value
        lsq_result_valid = load_pending[0] | cdb_lsq_valid[0]
        lsq_result_tag = load_pending[0].select(pending_rob_id, cdb_lsq_tag[0])
        lsq_result_value = load_pending[0].select(load_data, cdb_lsq_value[0])
        lsq_result_lsq_id = pending_lsq_id  # 仅 load_pending 时需要标记 lsq_done
        lsq_result_slot = lsq_result_tag[0:ROB_SLOT_BITS - 1].bitcast(UInt(ROB_SLOT_BITS))  # 转换为槽位索引
        
        with Condition(lsq_result_valid):
            # 更新 ROB (使用槽位索引)
            rob_ready[lsq_result_slot] = UInt(1)(1)
            rob_value[lsq_result_slot] = lsq_result_value
            log("Complete LSQ: ROB id={} slot={} = {:08x}", lsq_result_tag, lsq_result_slot, lsq_result_value)
            
            # 唤醒 RS (使用全局 ROB ID 匹配)
            for i in range(RS_SIZE):
                with Condition(rs_busy[i] & rs_qj_valid[i] & (rs_qj[i] == lsq_result_tag)):
                    rs_vj[i] = lsq_result_value
                    rs_qj_valid[i] = UInt(1)(0)
                with Condition(rs_busy[i] & rs_qk_valid[i] & (rs_qk[i] == lsq_result_tag)):
                    rs_vk[i] = lsq_result_value
                    rs_qk_valid[i] = UInt(1)(0)
        
        # SRAM 延迟读取时，标记 LSQ 条目完成并清除 pending
        with Condition(load_pending[0]):
            lsq_done[lsq_result_lsq_id] = UInt(1)(1)
            load_pending[0] = UInt(1)(0)
            log("Complete: Load SRAM result LSQ[{}] done", lsq_result_lsq_id)
        
        # 触发 Retire 阶段
        retire_stage.async_called()


# ==================== Retire 阶段：ROB → RegFile/Memory ===================
class RetireStage(Module):
    """Retire 阶段 - 按顺序提交 ROB 头部指令"""
    def __init__(self):
        super().__init__(ports={})
    
    @module.combinational
    def build(self,
              # ROB 相关
              rob_head, rob_valid, rob_ready, rob_value, rob_dest, rob_pc, rob_id,
              rob_is_store, rob_lsq_id,
              rob_is_branch, rob_branch_target,
              # ROB/RAT Walk-back 相关
              rob_tail, rob_old_tag_valid, rob_old_tag,
              rat_valid, rat_tag,
              # LSQ Store 提交
              lsq_valid, lsq_addr, lsq_data, lsq_head,
              # RS/LSQ/MulDiv for Walk-back
              rs_busy, rs_dest, lsq_rob_id, lsq_tail, md_busy, md_dest,
              # PC 和 IF/ID 寄存器 (分支 Commit 时修改)
              pc, if_id_instruction, decode_control,
              # 输出
              reg_file, data_sram):
        
        head_id = rob_head[0]
        head_valid = rob_valid[head_id]
        head_ready = rob_ready[head_id]
        head_dest = rob_dest[head_id]
        head_value = rob_value[head_id]
        head_rob_id = rob_id[head_id]  # 全局唯一 ROB ID
        head_pc = rob_pc[head_id]
        
        # 分支相关
        head_is_branch = rob_is_branch[head_id]
        head_branch_target = rob_branch_target[head_id]
        # 分支是否被采纳（目标 PC != PC+4）
        branch_taken = head_is_branch & (head_branch_target != (head_pc + UInt(XLEN)(4)))
        
        with Condition(head_valid & head_ready):
            # 1. 写入 RegFile（x0 不写，分支指令也可能写寄存器如 JAL/JALR）
            with Condition(head_dest != UInt(5)(0)):
                reg_file[head_dest] = head_value
            
            # 2. 清除 RAT 映射（仅当 RAT 仍指向此 ROB ID）
            with Condition(rat_valid[head_dest] & (rat_tag[head_dest] == head_rob_id)):
                rat_valid[head_dest] = UInt(1)(0)
            
            # 3. 释放 ROB 条目
            rob_valid[head_id] = UInt(1)(0)
            rob_ready[head_id] = UInt(1)(0)
            
            # 4. Store Commit - 写入内存
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
                log("Retire Store: ROB[{}] LSQ[{}] addr={:08x} data={:08x}", 
                    head_id, store_lsq_id, store_addr, store_data)
            
            # 5. 分支 Commit - 修改 PC 和执行 Flush
            with Condition(branch_taken):
                # 修改 PC 到分支目标
                pc[0] = head_branch_target
                # 清空 IF/ID 流水线寄存器（插入 NOP）
                if_id_instruction[0] = UInt(XLEN)(0x00000013)  # NOP = ADDI x0, x0, 0
                decode_control[0] = UInt(CONTROL_LEN)(0)
                
                # Walk-back: 清除所有后续指令（ROB 中 head 之后的所有条目）
                # 由于 head 已经被释放，只需要处理 head+1 到 tail-1 的条目
                # 但实际上，分支执行时后续指令可能已经分配到 ROB，需要全部清除
                
                # 回滚 ROB tail 到 head+1（清除所有推测指令）
                next_head = (head_id + UInt(ROB_SLOT_BITS)(1)) & UInt(ROB_SLOT_BITS)(ROB_SIZE - 1)
                rob_tail[0] = next_head
                
                # 清除所有 ROB 条目（从 next_head 到当前 tail）
                for i in range(ROB_SIZE):
                    slot = UInt(ROB_SLOT_BITS)(i)
                    with Condition(rob_valid[slot]):
                        rob_valid[slot] = UInt(1)(0)
                        rob_ready[slot] = UInt(1)(0)
                        # 恢复 RAT
                        flush_dest = rob_dest[slot]
                        flush_rob_id = rob_id[slot]
                        with Condition(rat_valid[flush_dest] & (rat_tag[flush_dest] == flush_rob_id)):
                            rat_valid[flush_dest] = rob_old_tag_valid[slot]
                            rat_tag[flush_dest] = rob_old_tag[slot]
                
                # 清除所有 RS 条目
                for i in range(RS_SIZE):
                    rs_busy[i] = UInt(1)(0)
                
                # 清除所有 LSQ 条目（Store 已经被 Commit，只需清除推测的）
                for i in range(LSQ_SIZE):
                    lsq_rob_slot = lsq_rob_id[i][0:ROB_SLOT_BITS - 1].bitcast(UInt(ROB_SLOT_BITS))
                    with Condition(lsq_valid[i] & ~rob_valid[lsq_rob_slot]):
                        lsq_valid[i] = UInt(1)(0)
                lsq_tail[0] = lsq_head[0]  # 重置 LSQ tail
                
                # 清除 MulDiv FU
                md_busy[0] = UInt(1)(0)
                
                log("Branch Commit: ROB[{}] taken, target={:08x}, flush pipeline", head_id, head_branch_target)
            
            # 6. 前移 ROB head (槽位索引循环)
            rob_head[0] = (head_id + UInt(ROB_SLOT_BITS)(1)) & UInt(ROB_SLOT_BITS)(ROB_SIZE - 1)
            
            log("Retire: ROB[{}] -> x{} = {:08x}, is_branch={}, target={:08x}", 
                head_id, head_dest, head_value, head_is_branch, head_branch_target)


class HazardUnit(Downstream):
    """OoO 架构的 Hazard Unit - 主要处理 Stall（分支恢复已移至 RetireStage）"""
    def __init__(self):
        super().__init__()

    @downstream.combinational
    def build(self, pc, if_id_instruction, decode_control, decode_immediate,
              rob_valid, rob_ready, rob_tail, rob_dest, rob_old_tag_valid, rob_old_tag, rat_valid, rat_tag,
              rs_busy, rs_dest,  # Phase 3: RS for Walk-back
              dispatch_signals,  # DispatchIssueStage 返回的 (stall_condition, issue_valid)
              fetch_signals, decode_signals):

        # decode_signals 结构（从低位到高位）:
        # [control(42), imm(32), rob_id(16), rob_full(1)] = 91 bits
        DECODE_SIGNALS_WIDTH = CONTROL_LEN + XLEN + ROB_ID_BITS + 1  # 42+32+16+1 = 91
        decode_signals = decode_signals.optional(Bits(DECODE_SIGNALS_WIDTH)(0))
        fetch_signals = fetch_signals.optional(Bits(XLEN)(0))

        instruction = fetch_signals.bitcast(UInt(XLEN))
        
        # 解析 decode_signals（从低位到高位）
        control_in = decode_signals[0:CONTROL_LEN - 1].bitcast(UInt(CONTROL_LEN))  # [0:41]
        immediate = decode_signals[CONTROL_LEN:CONTROL_LEN + XLEN - 1].bitcast(UInt(XLEN))  # [42:73]
        rob_full = decode_signals[DECODE_SIGNALS_WIDTH - 1:DECODE_SIGNALS_WIDTH - 1].bitcast(UInt(1))  # [90]
        
        # 当 ROB 满且当前指令需要写寄存器时，产生 Stall
        reg_write_decode = control_in[7:7]
        rob_stall = rob_full & reg_write_decode
        
        # Phase 3: 从 DispatchIssueStage 获取 RS/LSQ Stall 信号
        # dispatch_signals = (stall_condition, issue_valid)
        dispatch_signals = dispatch_signals.optional(Bits(2)(0))
        rs_lsq_stall = dispatch_signals[0:0].bitcast(UInt(1))  # stall_condition = rs_full | lsq_full
        rs_stall = rs_lsq_stall
        
        # Stall 条件
        stall = rob_stall | rs_stall
        
        nop_control = UInt(CONTROL_LEN)(0)

        # 更新 PC 和 IF/ID 寄存器（仅处理 Stall，分支跳转由 RetireStage 处理）
        pc[0] = stall.select(pc[0], pc[0] + UInt(XLEN)(4))
        if_id_instruction[0] = stall.select(if_id_instruction[0], instruction)
        
        # 更新解码控制寄存器（用于后续阶段）
        decode_control[0] = stall.select(nop_control, control_in)
        decode_immediate[0] = stall.select(UInt(XLEN)(0), immediate)
        
        log("Hazard Unit: Stall={}, Immediate={:08x}, Control={:042b}", stall, immediate, control_in)

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

        # OoO: 解码阶段输出寄存器
        decode_control = RegArray(UInt(CONTROL_LEN), 1, initializer=[0])  # 控制信号 (42位)
        decode_immediate = RegArray(UInt(XLEN), 1, initializer=[0])    # 立即数 (32位)

        # ==================== OoO 相关寄存器 ====================
        # RAT (Register Alias Table) - 32项
        rat_valid = RegArray(UInt(1), REG_COUNT, initializer=[0]*REG_COUNT)
        rat_tag = RegArray(UInt(ROB_ID_BITS), REG_COUNT, initializer=[0]*REG_COUNT)  # 存储全局唯一 ROB ID
        
        # ROB 指针
        rob_head = RegArray(UInt(ROB_SLOT_BITS), 1, initializer=[0])  # 队头(Commit点) - 槽位索引
        rob_tail = RegArray(UInt(ROB_SLOT_BITS), 1, initializer=[0])  # 队尾(分配点) - 槽位索引
        rob_id_counter = RegArray(UInt(ROB_ID_BITS), 1, initializer=[0])  # 全局唯一递增 ROB ID 计数器
        
        # ROB 数据数组 (每个ROB条目的字段)
        rob_valid = RegArray(UInt(1), ROB_SIZE, initializer=[0]*ROB_SIZE)      # 条目是否有效
        rob_ready = RegArray(UInt(1), ROB_SIZE, initializer=[0]*ROB_SIZE)      # 结果是否就绪
        rob_value = RegArray(UInt(XLEN), ROB_SIZE, initializer=[0]*ROB_SIZE)   # 执行结果
        rob_dest = RegArray(UInt(5), ROB_SIZE, initializer=[0]*ROB_SIZE)       # 目标寄存器号
        rob_pc = RegArray(UInt(XLEN), ROB_SIZE, initializer=[0]*ROB_SIZE)      # 指令PC
        rob_id = RegArray(UInt(ROB_ID_BITS), ROB_SIZE, initializer=[0]*ROB_SIZE)  # 全局唯一 ROB ID
        rob_is_store = RegArray(UInt(1), ROB_SIZE, initializer=[0]*ROB_SIZE)   # Phase 5: 是否为Store
        rob_lsq_id = RegArray(UInt(LSQ_ID_BITS), ROB_SIZE, initializer=[0]*ROB_SIZE)  # Phase 5: LSQ ID
        # 分支相关字段
        rob_is_branch = RegArray(UInt(1), ROB_SIZE, initializer=[0]*ROB_SIZE)   # 是否为分支/跳转指令
        rob_branch_target = RegArray(UInt(XLEN), ROB_SIZE, initializer=[0]*ROB_SIZE)  # 分支目标 PC
        # Walk-back 恢复所需字段
        rob_old_tag_valid = RegArray(UInt(1), ROB_SIZE, initializer=[0]*ROB_SIZE)  # 旧 RAT valid
        rob_old_tag = RegArray(UInt(ROB_ID_BITS), ROB_SIZE, initializer=[0]*ROB_SIZE)  # 旧 RAT tag (全局 ID)

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
        cdb_branch_value = RegArray(UInt(XLEN), 1, initializer=[0])  # 分支目标 PC
        cdb_branch_link = RegArray(UInt(XLEN), 1, initializer=[0])   # JAL/JALR 的 link address (PC+4)
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
        
        # MulDiv FU 发射寄存器
        md_fu_valid = RegArray(UInt(1), 1, initializer=[0])
        md_fu_op = RegArray(UInt(5), 1, initializer=[0])
        md_fu_vj = RegArray(UInt(XLEN), 1, initializer=[0])
        md_fu_vk = RegArray(UInt(XLEN), 1, initializer=[0])
        md_fu_dest = RegArray(UInt(ROB_ID_BITS), 1, initializer=[0])
        md_fu_imm = RegArray(UInt(XLEN), 1, initializer=[0])
        md_fu_control = RegArray(UInt(CONTROL_LEN), 1, initializer=[0])
        
        # Dispatch 阶段中间寄存器 (用于跨模块传递)
        dispatch_valid_reg = RegArray(UInt(1), 1, initializer=[0])
        dispatch_rob_id_reg = RegArray(UInt(ROB_ID_BITS), 1, initializer=[0])
        dispatch_pc_reg = RegArray(UInt(XLEN), 1, initializer=[0])
        dispatch_rs1_value = RegArray(UInt(XLEN), 1, initializer=[0])
        dispatch_rs1_tag = RegArray(UInt(ROB_ID_BITS), 1, initializer=[0])
        dispatch_rs1_ready = RegArray(UInt(1), 1, initializer=[0])
        dispatch_rs2_value = RegArray(UInt(XLEN), 1, initializer=[0])
        dispatch_rs2_tag = RegArray(UInt(ROB_ID_BITS), 1, initializer=[0])
        dispatch_rs2_ready = RegArray(UInt(1), 1, initializer=[0])
        md_fu_func = RegArray(UInt(3), 1, initializer=[0])  # Phase 4: MulDiv func

        # ==================== Phase 4: MulDiv 状态寄存器 ====================
        md_busy = RegArray(UInt(1), 1, initializer=[0])        # 是否忙
        md_cnt = RegArray(UInt(4), 1, initializer=[0])         # 剩余周期计数
        md_op = RegArray(UInt(5), 1, initializer=[0])          # 操作类型
        md_vj = RegArray(UInt(XLEN), 1, initializer=[0])       # 源操作数1
        md_vk = RegArray(UInt(XLEN), 1, initializer=[0])       # 源操作数2
        md_dest = RegArray(UInt(ROB_ID_BITS), 1, initializer=[0])  # 目标 ROB ID

        # ==================== Load 待处理寄存器 (SRAM 一周期延迟) ====================
        load_pending = RegArray(UInt(1), 1, initializer=[0])           # 是否有待处理的 Load
        load_pending_lsq_id = RegArray(UInt(LSQ_ID_BITS), 1, initializer=[0])  # Load 的 LSQ ID
        load_pending_rob_id = RegArray(UInt(ROB_ID_BITS), 1, initializer=[0])  # Load 的 ROB ID

        # 创建指令内存
        test_program = init_memory(program_file)
        instruction_memory = RegArray(UInt(XLEN), 2048, initializer=test_program + [0]*(2048 - len(test_program)))
        
        # 创建寄存器文件
        reg_file = RegArray(UInt(XLEN), REG_COUNT, initializer=[0]*REG_COUNT)

        pc = RegArray(UInt(XLEN), 1, initializer=[0])
        
        data_sram = SRAM(width=XLEN, depth=65536, init_file="data.hex")
        hazard_unit = HazardUnit()
        dispatch_issue_stage = DispatchIssueStage()  # Phase 3: 合并的分派发射阶段
        fetch_stage = FetchStage()
        decode_stage = DecodeStage()
        execute_stage = ExecuteStage()
        memory_stage = MemoryStage()
        complete_stage = CompleteStage()  # Phase 6: CDB → ROB + RS 唤醒
        retire_stage = RetireStage()      # Phase 6: ROB → RegFile/Memory
        driver = Driver()

        # 按照流水线顺序构建模块
        
        # Phase 6: Complete 阶段 - 接收 CDB 更新 ROB 并唤醒 RS，处理 SRAM 延迟读取
        complete_stage.build(cdb_alu_valid, cdb_alu_tag, cdb_alu_value,
                             cdb_branch_valid, cdb_branch_tag, cdb_branch_value, cdb_branch_link,
                             cdb_md_valid, cdb_md_tag, cdb_md_value,
                             cdb_lsq_valid, cdb_lsq_tag, cdb_lsq_value,
                             rob_ready, rob_value, rob_is_branch, rob_branch_target,
                             # RS 数组 (用于唤醒)
                             rs_busy, rs_vj, rs_vk, rs_qj, rs_qk, rs_qj_valid, rs_qk_valid,
                             # Load 待处理寄存器 (SRAM 一周期延迟)
                             load_pending, load_pending_lsq_id, load_pending_rob_id,
                             # LSQ done 标记
                             lsq_done,
                             # SRAM 读取结果
                             data_sram,
                             retire_stage)
        
        # Phase 6: Retire 阶段 - 按顺序提交（包括分支 Commit 和 Flush）
        retire_stage.build(rob_head, rob_valid, rob_ready, rob_value, rob_dest, rob_pc, rob_id,
                           rob_is_store, rob_lsq_id,
                           rob_is_branch, rob_branch_target,
                           # ROB/RAT Walk-back 相关
                           rob_tail, rob_old_tag_valid, rob_old_tag,
                           rat_valid, rat_tag,
                           lsq_valid, lsq_addr, lsq_data, lsq_head,
                           # RS/LSQ/MulDiv for Walk-back
                           rs_busy, rs_dest, lsq_rob_id, lsq_tail, md_busy, md_dest,
                           # PC 和 IF/ID 寄存器
                           pc, if_id_instruction, decode_control,
                           reg_file, data_sram)
        
        memory_stage.build(
                             # LSQ FU 输入寄存器
                             lsq_fu_valid, lsq_fu_lsq_id, lsq_fu_vj, lsq_fu_imm, lsq_fu_dest, lsq_fu_is_store, lsq_fu_control,
                             # LSQ 状态
                             lsq_valid, lsq_is_store, lsq_addr_ready, lsq_data_ready,
                             lsq_addr, lsq_data, lsq_rob_id, lsq_done,
                             # Load 待处理寄存器 (SRAM 一周期延迟)
                             load_pending, load_pending_lsq_id, load_pending_rob_id,
                             # CDB_LSQ 输出 (仅用于前递)
                             cdb_lsq_valid, cdb_lsq_tag, cdb_lsq_value,
                             # 内存
                             data_sram)
        execute_signals = execute_stage.build(
                                                   # Phase 4: MulDiv 状态寄存器
                                                   md_busy, md_cnt, md_op, md_vj, md_vk, md_dest,
                                                   # Phase 5: LSQ 相关
                                                   lsq_addr, lsq_addr_ready, lsq_data, lsq_data_ready,
                                                   # 多 FU 并行: 各 FU 输入和 CDB 输出
                                                   alu_fu_valid, alu_fu_op, alu_fu_vj, alu_fu_vk, alu_fu_dest, alu_fu_imm, alu_fu_control, alu_fu_pc,
                                                   branch_fu_valid, branch_fu_vj, branch_fu_vk, branch_fu_dest, branch_fu_imm, branch_fu_control, branch_fu_pc,
                                                   lsq_fu_valid, lsq_fu_lsq_id, lsq_fu_vj, lsq_fu_vk, lsq_fu_imm, lsq_fu_dest, lsq_fu_is_store, lsq_fu_control,
                                                   # MulDiv FU 发射寄存器
                                                   md_fu_valid, md_fu_op, md_fu_vj, md_fu_vk, md_fu_dest, md_fu_func,
                                                   # CDB 输出
                                                   cdb_alu_valid, cdb_alu_tag, cdb_alu_value,
                                                   cdb_branch_valid, cdb_branch_tag, cdb_branch_value,
                                                   cdb_md_valid, cdb_md_tag, cdb_md_value,
                                                   cdb_lsq_valid, cdb_lsq_tag, cdb_lsq_value,
                                                   memory_stage, complete_stage)
        decode_signals = decode_stage.build(if_id_pc, if_id_instruction,
                                          rat_valid, rat_tag, rob_head, rob_tail, rob_valid, rob_ready, rob_value, rob_dest, rob_pc,
                                          rob_old_tag_valid, rob_old_tag, rob_id, rob_id_counter,
                                          # Dispatch 中间寄存器
                                          dispatch_valid_reg, dispatch_rob_id_reg, dispatch_pc_reg,
                                          dispatch_rs1_value, dispatch_rs1_tag, dispatch_rs1_ready,
                                          dispatch_rs2_value, dispatch_rs2_tag, dispatch_rs2_ready,
                                          # 控制和立即数寄存器
                                          decode_control, decode_immediate,
                                          reg_file)
        
        # Phase 3: 分派发射阶段
        dispatch_signals = dispatch_issue_stage.build(
                                          dispatch_valid_reg, decode_control, decode_immediate,
                                          dispatch_rob_id_reg, dispatch_pc_reg,
                                          dispatch_rs1_value, dispatch_rs1_tag, dispatch_rs1_ready,
                                          dispatch_rs2_value, dispatch_rs2_tag, dispatch_rs2_ready,
                                          rs_busy, rs_op, rs_vj, rs_vk, rs_qj, rs_qk, rs_qj_valid, rs_qk_valid, rs_dest, rs_imm, rs_func, rs_control, rs_lsq_id, rs_pc,
                                          lsq_valid, lsq_is_store, lsq_addr_ready, lsq_data_ready, lsq_addr, lsq_data, lsq_rob_id, lsq_done, lsq_head, lsq_tail,
                                          rob_is_store, rob_lsq_id,
                                          md_fu_valid, md_fu_op, md_fu_vj, md_fu_vk, md_fu_dest, md_fu_imm, md_fu_control, md_fu_func,
                                          md_busy,
                                          # 多 FU 并行: 各 FU 寄存器
                                          alu_fu_valid, alu_fu_op, alu_fu_vj, alu_fu_vk, alu_fu_dest, alu_fu_imm, alu_fu_control, alu_fu_pc,
                                          branch_fu_valid, branch_fu_vj, branch_fu_vk, branch_fu_dest, branch_fu_imm, branch_fu_control, branch_fu_pc,
                                          lsq_fu_valid, lsq_fu_lsq_id, lsq_fu_vj, lsq_fu_vk, lsq_fu_imm, lsq_fu_dest, lsq_fu_is_store, lsq_fu_control,
                                          execute_stage)
        
        fetch_signals = fetch_stage.build(pc, if_id_pc, if_id_instruction, instruction_memory, decode_stage)
        # Phase 3: RS 唤醒 - 已合并到 CompleteStage
        
        # HazardUnit 现在只处理 Stall，分支恢复已移至 RetireStage
        hazard_unit.build(pc, if_id_instruction, decode_control, decode_immediate,
                          rob_valid, rob_ready, rob_tail, rob_dest, rob_old_tag_valid, rob_old_tag, rat_valid, rat_tag,
                          rs_busy, rs_dest,  # Phase 3: RS for Walk-back
                          dispatch_signals,  # RS/LSQ Stall 信号
                          fetch_signals, decode_signals)
        
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