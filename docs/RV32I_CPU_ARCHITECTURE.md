# RV32I CPU 架构分析 (RV32I CPU Architecture Analysis)

> **作者**: Claude
> **日期**: 2026-01-09
> **文件**: `src/rv32i_cpu.py` (1540 lines)

---

## 目录

1. [总体架构](#1-总体架构)
2. [流水线阶段](#2-流水线阶段)
3. [关键特性](#3-关键特性)
4. [数据通路](#4-数据通路)
5. [控制信号](#5-控制信号)
6. [冒险处理](#6-冒险处理)

---

## 1. 总体架构

### 1.1 CPU 类型

**五级流水线 RV32IM 处理器**
- RV32I: 基础整数指令集
- RV32M: 乘除法扩展
- 5级流水线: IF → ID → EX → MEM → WB

### 1.2 关键参数

```python
XLEN = 32                    # 32位架构
REG_COUNT = 32               # 32个通用寄存器
CONTROL_LEN = 48             # 控制信号长度 (42+3+3)
BTB_SIZE = 64                # 分支目标缓冲区大小
```

### 1.3 模块组成

| 模块 | 类名 | 功能 |
|------|------|------|
| IF | `FetchStage` | 指令获取 + BTB预测 |
| ID | `DecodeStage` | 指令解码 + 寄存器读取 |
| EX | `ExecuteStage` | 执行 + ALU + 乘法器 + 除法器 |
| MEM | `MemoryStage` | 内存访问 |
| WB | `WriteBackStage` | 写回 |
| Hazard | `HazardUnit` (Downstream) | 冒险检测 + 流水线控制 |
| Driver | `Driver` | 系统时钟源 |

---

## 2. 流水线阶段

### 2.1 IF 阶段 (FetchStage)

**功能**:
1. 从指令存储器取指令
2. BTB分支预测
3. 更新IF/ID流水线寄存器

**BTB预测逻辑**:
```python
# 使用PC[2:7]索引BTB (6位, 64条目)
btb_index = current_pc[2:7]

# 读取BTB和BHT
btb_entry = btb[btb_index]      # 预测目标PC
bht_entry = bht[btb_index]      # 2-bit饱和计数器
btb_valid = btb_valid[btb_index] # 有效位

# 预测决策
btb_hit = btb_valid
predict_taken = (bht_entry >= 2)  # BHT>=2 预测跳转

# 预测PC
predicted_pc = (btb_hit & predict_taken).select(btb_entry, pc + 4)
```

**IF/ID流水线寄存器**:
- `if_id_pc`: 当前PC
- `if_id_instruction`: 指令
- `if_id_valid`: 有效位
- `if_id_prediction_info`: 预测信息 (34位)

**关键点**:
- ✅ 遵循规则: Condition中只写寄存器
- ✅ stall时清零流水线寄存器

### 2.2 ID 阶段 (DecodeStage)

**功能**:
1. 指令解码
2. 立即数生成与符号扩展
3. 控制信号生成
4. 寄存器文件读取
5. 传递预测信息

**指令格式支持**:
- R-type: rs1, rs2, rd, funct7, func3
- I-type: rs1, rd, imm[11:0]
- S-type: rs1, rs2, imm[11:0]
- B-type: imm[12:1], imm[11], imm[10:5], imm[4:1], imm[11]
- U-type: rd, imm[31:12]
- J-type: rd, imm[20:1], imm[11], imm[10:1], imm[20], imm[19:12], imm[12]

**控制信号生成** (48位):
```
[41:0]  - 基础控制信号 (reg_write, mem_read, mem_write, etc.)
[44:42] - mul_op (乘法操作码: 000=无, 001=MUL, 010=MULH, 011=MULHSU, 100=MULHU)
[47:45] - div_op (除法操作码: 000=无, 001=DIV, 010=DIVU, 011=REM, 100=REMU)
```

**ID/EX流水线寄存器**:
- `id_ex_pc`: PC
- `id_ex_control`: 控制信号
- `id_ex_rs1_idx`, `id_ex_rs2_idx`: 寄存器索引
- `id_ex_immediate`: 立即数
- `id_ex_prediction_info`: 预测信息

### 2.3 EX 阶段 (ExecuteStage)

**功能**:
1. ALU运算
2. 分支计算与预测验证
3. 乘法运算 (Wallace Tree, 3周期)
4. 除法运算 (Radix-4 SRT, 18周期)
5. 更新EX/MEM流水线寄存器

**ALU操作**:
- ADD, SUB, AND, OR, XOR, SLL, SRL, SRA, SLT, SLTU

**分支处理**:
```python
# 计算实际分支目标
actual_target = pc + immediate

# 验证预测
is_branch = (opcode == BRANCH)
predicted_taken = prediction_info[1:1]
actual_taken = (condition True)

need_flush = (predicted_taken != actual_taken)  # 预测错误需要flush
```

**Wallace Tree乘法器** (3周期):
- Cycle 1: 部分积生成 + CSA压缩 (32→10)
- Cycle 2: CSA压缩 (10→2)
- Cycle 3: 最终加法 + 结果选择

**Radix-4 SRT除法器** (18周期):
- Cycle 1: 初始化
- Cycle 2-17: 16次迭代 (每次产生2位商)
- Cycle 18: 最终修正

### 2.4 MEM 阶段 (MemoryStage)

**功能**:
1. 内存读写 (通过SRAM)
2. 更新MEM/WB流水线寄存器

**内存操作**:
```python
with Condition(mem_read):
    data = data_sram[addr]

with Condition(mem_write):
    data_sram[addr] = data
```

### 2.5 WB 阶段 (WriteBackStage)

**功能**:
1. 选择写回数据 (ALU结果或内存数据)
2. 写回寄存器文件

**写回逻辑**:
```python
write_data = reg_write.select(mem_data, alu_result)  # MUX
with Condition(reg_write & (rd != 0)):
    reg_file[rd] = write_data
```

---

## 3. 关键特性

### 3.1 动态分支预测

**BTB (Branch Target Buffer)**:
- 64条目, 使用PC[2:7]索引
- 存储预测的目标PC

**BHT (Branch History Table)**:
- 2-bit饱和计数器
- 状态: 00(强不跳), 01(弱不跳), 10(弱跳), 11(强跳)
- 更新规则:
  - 实际跳转: counter = min(counter+1, 3)
  - 实际不跳: counter = max(counter-1, 0)

**预测流程**:
1. IF阶段: 查询BTB/BHT, 生成预测
2. EX阶段: 计算实际分支, 验证预测
3. 预测错误: flush流水线, 更新BTB/BHT

### 3.2 乘法器 (Wallace Tree)

**特性**:
- 3周期延迟
- 支持有符号/无符号乘法
- 返回高32位或低32位

**指令**:
- `MUL`:  signed × signed → low 32
- `MULH`: signed × signed → high 32
- `MULHSU`: signed × unsigned → high 32
- `MULHU`: unsigned × unsigned → high 32

### 3.3 除法器 (Radix-4 SRT)

**特性**:
- 18周期延迟
- 商数字集合: {-2, -1, 0, +1, +2}
- 每次迭代产生2位商
- 16次迭代产生32位商

**指令**:
- `DIV`:  signed / signed → quotient
- `DIVU`: unsigned / unsigned → quotient
- `REM`:  signed % signed → remainder
- `REMU`: unsigned % unsigned → remainder

---

## 4. 数据通路

### 4.1 正常数据流

```
PC → IF → [if_id] → ID → [id_ex] → EX → [ex_mem] → MEM → [mem_wb] → WB
     ↑                                                                  |
     |                                                                  ↓
     +----------------------------------------- reg_file[rd] <-----------+
```

### 4.2 转发路径 (Bypassing)

**从EX阶段转发**:
- EX/MEM.result → ID/EX.rs1/rs2

**从MEM阶段转发**:
- EX/MEM.result → ID/EX.rs1/rs2
- MEM/WB.result → ID/EX.rs1/rs2

---

## 5. 控制信号

### 5.1 控制信号字段 (48位)

```
[0]    - reg_write       (寄存器写使能)
[1]    - mem_read        (内存读使能)
[2]    - mem_write       (内存写使能)
[3]    - mem_to_reg      (内存到寄存器)
[4:8]  - alu_op          (ALU操作码)
[9]    - alu_src_imm     (ALU源为立即数)
[10]   - is_branch       (分支指令)
[11]   - is_jump         (跳转指令)
[12]   - is_jalr         (JALR指令)
[13]   - is_lui          (LUI指令)
[14]   - is_auipc        (AUIPC指令)
[15]   - is_load         (加载指令)
[16]   - is_store        (存储指令)
[17]   - need_rs1        (需要rs1)
[18]   - need_rs2        (需要rs2)
[19:41] - 保留
[42:44] - mul_op          (乘法操作码)
[45:47] - div_op          (除法操作码)
```

---

## 6. 冒险处理

### 6.1 HazardUnit (Downstream模块)

**功能**:
- 检测数据冒险
- 生成stall信号
- 处理分支预测错误
- 处理乘/除法指令的多周期执行

**stall条件**:
1. 数据冒险: ID阶段需要的数据还未就绪
2. 结构冒险: 乘/除法器忙

**数据冒险检测**:
```python
# EX阶段有load/div/mul 且 ID阶段依赖于其结果
if (ex_mem_control.is_load | mul_in_progress | div_busy) &&
   (id_ex_needs_rs1 && (id_ex_rs1 == ex_rd) ||
    id_ex_needs_rs2 && (id_ex_rs2 == ex_rd)):
    stall = 1
```

**flush条件**:
- 分支预测错误
- JALR指令

### 6.2 流水线控制

**stall时**:
- IF/ID寄存器清零
- PC保持不变

**flush时**:
- 清空相关流水线寄存器
- PC更新为正确目标

---

## 7. 总结

### 7.1 优点

✅ **完整实现**: RV32IM + 分支预测
✅ **性能优化**: BTB预测, 转发, 多周期乘除法
✅ **清晰结构**: 五级流水线, 模块化设计
✅ **遵循规范**: 严格遵守Assassyn语法规则

### 7.2 性能指标

- **主频**: 取决于关键路径 (ALU + 分支判断)
- **CPI**:
  - 基础指令: 1 CPI
  - Load: 1 CPI (有转发)
  - 乘法: 3 CPI
  - 除法: 18 CPI
  - 分支预测错误: ~3-4 CPI (flush开销)

### 7.3 可能的优化方向

1. **更高级的分支预测**: 2-level adaptive predictor
2. **乱序执行**: 超标量架构
3. **缓存**: I-Cache, D-Cache
4. **更多转发路径**: 减少stall

---

**文档版本**: v1.0
**最后更新**: 2026-01-09
