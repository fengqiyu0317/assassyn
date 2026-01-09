# Fully Bypass（Forwarding）机制实现规则

## 规则 1：EX 阶段添加前递逻辑

**文件**：[`rv32i_cpu.py`](rv32i_cpu.py:1)  
**位置**：[`ExecuteStage.build()`](rv32i_cpu.py:314) 方法，第322-324行之后

**修改逻辑**：
1. 从 EX/MEM 寄存器解析 MEM 阶段控制信号：`mem_reg_write`（第7位）、`mem_rd`（第25-29位）
2. 从新增参数解析 WB 阶段控制信号：`wb_reg_write`、`wb_rd`、`wb_data`（根据 `mem_to_reg` 选择 `mem_wb_mem_data` 或 `mem_wb_ex_result`）
3. 实现 rs1 前递：优先级 MEM > WB > reg_file
   - 若 `mem_reg_write=1` 且 `rs1_idx=mem_rd`，使用 `ex_mem_result[0]`
   - 否则若 `wb_reg_write=1` 且 `rs1_idx=wb_rd`，使用 `wb_data`
   - 否则使用 `reg_file[rs1_idx]`
4. 实现 rs2 前递：优先级 MEM > WB > reg_file（逻辑同 rs1）
5. 将前递后的 `rs1_data`、`rs2_data` 用于 ALU 和分支单元

## 规则 2：HazardUnit 修改数据冒险检测

**文件**：[`rv32i_cpu.py`](rv32i_cpu.py:1)  
**位置**：[`HazardUnit.build()`](rv32i_cpu.py:527) 方法，第573-595行

**修改逻辑**：
1. 解析 MEM 阶段 `mem_read` 信号（控制信号第5位）
2. 解析 WB 阶段 `mem_read`、`mem_to_reg` 信号
3. 检测 Load-Use 冒险（必须暂停）：
   - MEM 阶段：`mem_mem_read & mem_reg_write & ((needs_rs1 & (rs1=rd_mem)) | (needs_rs2 & (rs2=rd_mem)))`
   - WB 阶段：`wb_mem_read & wb_reg_write & ((needs_rs1 & (rs1=rd_wb)) | (needs_rs2 & (rs2=rd_wb)))`
4. 修改 `data_hazard` 逻辑：仅当 Load-Use 冒险且非控制冒险时暂停
   - `data_hazard = (load_use_hazard | load_use_hazard_wb) & ~need_flush`
5. 移除原有的 `data_hazard_ex`、`data_hazard_wb` 检测（这些可通过前递解决）

## 规则 3：ExecuteStage 添加 WB 阶段参数

**文件**：[`rv32i_cpu.py`](rv32i_cpu.py:1)  
**位置**：[`ExecuteStage.build()`](rv32i_cpu.py:314) 方法签名

**修改逻辑**：
1. 在方法参数中添加：
   - `mem_wb_control`：WB 阶段控制信号
   - `mem_wb_valid`：WB 阶段有效标志
   - `mem_wb_mem_data`：WB 阶段内存数据
   - `mem_wb_ex_result`：WB 阶段 EX 结果
2. 在方法内部解析 WB 阶段控制信号用于前递逻辑

## 规则 4：build_cpu 传递 WB 阶段数据

**文件**：[`rv32i_cpu.py`](rv32i_cpu.py:1)  
**位置**：[`build_cpu()`](rv32i_cpu.py:698) 函数，第761行

**修改逻辑**：
1. 修改 `execute_stage.build()` 调用，添加 WB 阶段参数：
   - `mem_wb_control`
   - `mem_wb_valid`
   - `mem_wb_mem_data`
   - `mem_wb_ex_result`

## 规则 5：前递优先级

**优先级顺序**：MEM 阶段 > WB 阶段 > 寄存器文件

**判断条件**：
- MEM 阶段前递：`mem_reg_write=1` 且 `rs_idx=mem_rd`
- WB 阶段前递：`wb_reg_write=1` 且 `rs_idx=wb_rd`
- 否则使用寄存器文件

## 规则 6：Load-Use 冒险处理

**必须暂停的情况**：
- MEM 阶段为 Load 指令（`mem_read=1`）
- MEM 阶段目标寄存器与 ID 阶段源寄存器相同
- WB 阶段为 Load 指令（理论上不应发生，但需检测）

**暂停周期**：1 个周期（等待 MEM 阶段完成内存读取）

## 规则 7：WB 阶段数据选择

**选择逻辑**：
- 若 `wb_mem_to_reg=1`，使用 `mem_wb_mem_data`（Load 指令）
- 否则使用 `mem_wb_ex_result`（ALU 指令）