# 分支预测功能实现规则

## 一、新增硬件模块

### BranchPredictor 模块
- 创建 BTB（Branch Target Buffer）：存储分支目标地址，使用 RegArray(UInt(32), 64)
- 创建 BHT（Branch History Table）：存储2-bit饱和计数器，使用 RegArray(UInt(2), 64)
- 创建 BTB 有效位：RegArray(UInt(1), 64)

## 二、IF 阶段修改规则

### FetchStage.build 参数扩展
- 新增输入参数：branch_predictor（BranchPredictor 实例）
- 新增输出信号：prediction_info（包含 BTB 命中标志、预测跳转标志、预测目标地址）

### BTB 查询逻辑
- 使用 PC[2:7] 作为 BTB 索引
- 读取 btb[index]、bht[index]、btb_valid[index]
- 根据 bht 值判断预测方向：bht >= 2 预测跳转，否则预测不跳转
- 预测 PC = btb_hit ? (predict_taken ? btb_entry : PC+4) : PC+4

### 预测信息传递
- 将 prediction_info 传递到 ID 阶段
- prediction_info 格式：[btb_hit, predict_taken, predicted_pc]

## 三、ID 阶段修改规则

### DecodeStage.build 参数扩展
- 新增输入参数：id_ex_prediction_info（来自 IF 阶段的预测信息）
- 新增输出参数：id_ex_prediction_info（传递到 EX 阶段）

### 流水线寄存器扩展
- 在 ID/EX 流水线寄存器中添加 id_ex_prediction_info：RegArray(UInt(34), 1)
  - [0]: btb_hit
  - [1]: predict_taken
  - [2:33]: predicted_pc

## 四、EX 阶段修改规则

### ExecuteStage.build 参数扩展
- 新增输入参数：id_ex_prediction_info（来自 ID 阶段的预测信息）
- 新增输出信号：prediction_result（包含预测错误标志、正确 PC、实际跳转标志、实际目标地址）

### 预测验证逻辑
- 解析预测信息：btb_hit、predict_taken、predicted_pc
- 计算实际分支结果：actual_taken = branch_unit(branch_op, rs1_data, rs2_data)
- 计算实际目标地址：actual_target_pc = pc_in + immediate_in
- 判断预测正确性：
  - BTB 命中：prediction_correct = (predict_taken == actual_taken) && (predicted_pc == actual_target_pc)
  - BTB 未命中：prediction_correct = !actual_taken
- 生成预测错误标志：mispredict = is_branch && !prediction_correct

### prediction_result 格式
- [0]: mispredict（预测错误标志）
- [1:32]: correct_pc（正确的 PC）
- [33]: actual_taken（实际跳转标志）
- [34:65]: actual_target_pc（实际目标地址）
- [66]: btb_hit
- [67]: predict_taken

### 跳转指令处理（JAL/JALR）
- is_jump 和 is_jumpr 始终触发流水线刷新
- 不进行预测验证，直接使用计算的目标地址

## 五、HazardUnit 修改规则

### HazardUnit.build 参数扩展
- 新增输入参数：branch_predictor（BranchPredictor 实例）
- 新增输入信号：prediction_result（来自 EX 阶段的预测结果）

### PC 更新逻辑
- 解析 prediction_result：mispredict、correct_pc、actual_taken、actual_target_pc、btb_hit、predict_taken
- 解析控制信号：is_jump、is_jumpr
- 计算需要刷新标志：need_flush = mispredict || is_jump || is_jumpr

#### PC 更新规则
1. **need_flush == 1**：
   - JALR 指令：pc[0] = (rs1_data + immediate_in) & ~1
   - 其他情况：pc[0] = correct_pc
2. **need_flush == 0**：
   - 数据冒险：pc[0] = pc[0]（保持不变）
   - 无数据冒险：pc[0] = pc[0] + 4

### 流水线刷新逻辑

#### IF/ID 阶段刷新
- if_id_valid[0] = 0
- if_id_pc[0] = 0
- if_id_instruction[0] = 0x00000013（NOP）

#### ID/EX 阶段刷新
- id_ex_valid[0] = 0
- id_ex_control[0] = 0
- id_ex_rs1_idx[0] = 0
- id_ex_rs2_idx[0] = 0
- id_ex_immediate[0] = 0
- id_ex_prediction_info[0] = 0

#### EX/MEM 和 MEM/WB 阶段
- 不刷新，继续执行

### 预测器更新逻辑
- 仅在 is_branch == 1 时更新
- 更新 BTB：btb[index] = actual_target_pc, btb_valid[index] = 1
- 更新 BHT（2-bit饱和计数器）：
  - actual_taken == 1：bht[index] = (bht[index] == 3) ? 3 : bht[index] + 1
  - actual_taken == 0：bht[index] = (bht[index] == 0) ? 0 : bht[index] - 1

## 六、涉及 PC 变化但不是分支语句的处理

### JAL 指令
- 不查询 BTB，不进行预测
- 在 EX 阶段计算目标地址：target_pc = pc_in + immediate_in
- 在 EX 阶段计算返回地址：alu_result = pc_in + 4
- is_jump 标志置 1，触发流水线刷新
- PC 更新为 target_pc

### JALR 指令
- 不查询 BTB，不进行预测
- 在 EX 阶段计算目标地址：target_pc = (rs1_data + immediate_in) & ~1
- 在 EX 阶段计算返回地址：alu_result = pc_in + 4
- is_jumpr 标志置 1，触发流水线刷新
- PC 更新为 target_pc

### AUIPC 指令
- 不改变 PC，不触发流水线刷新
- 在 EX 阶段计算结果：alu_result = pc_in + immediate_u
- 正常执行，不涉及预测

## 七、回退逻辑规则

### 回退触发条件
- mispredict == 1（分支预测错误）
- is_jump == 1（JAL 指令）
- is_jumpr == 1（JALR 指令）

### 回退操作顺序
1. 更新 PC 到正确地址
2. 清空 IF/ID 流水线寄存器
3. 清空 ID/EX 流水线寄存器
4. 更新 BTB 和 BHT（仅分支指令）
5. EX/MEM 和 MEM/WB 继续执行

### 回退时流水线状态
- IF 阶段：从新 PC 重新取指
- ID 阶段：插入 NOP，等待新指令
- EX 阶段：被清空，不执行
- MEM 阶段：继续执行（已通过预测验证的指令）
- WB 阶段：继续执行（已通过预测验证的指令）

## 八、数据冒险与预测错误的优先级

### 冲突处理规则
- 预测错误优先级高于数据冒险
- 当 mispredict == 1 时，忽略数据冒险，直接刷新流水线
- 当 mispredict == 0 时，正常处理数据冒险

### stall 信号生成
- stall[0] = data_hazard && !mispredict && !is_jump && !is_jumpr

## 九、控制信号扩展

### ID/EX 流水线寄存器新增字段
- id_ex_prediction_info：RegArray(UInt(34), 1)

### EX/MEM 流水线寄存器新增字段
- ex_mem_prediction_result：RegArray(UInt(68), 1)
  - [0]: mispredict
  - [1:32]: correct_pc
  - [33]: actual_taken
  - [34:65]: actual_target_pc
  - [66]: btb_hit
  - [67]: predict_taken

### HazardUnit 输入信号扩展
- prediction_result：来自 EX 阶段的预测结果（68位）

## 十、指令分类处理规则

### 需要预测的指令
- B 系列指令（BEQ, BNE, BLT, BGE, BLTU, BGEU）
- 处理流程：IF查询BTB → ID传递预测 → EX验证预测 → HU更新预测器

### 不需要预测但改变PC的指令
- JAL：直接跳转，触发刷新
- JALR：直接跳转，触发刷新

### 不改变PC的指令
- AUIPC：正常执行
- 其他算术/逻辑/访存指令：正常执行