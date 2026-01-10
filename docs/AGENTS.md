# RV32I CPU 项目 - Agent 指南

## 项目概述

本项目是一个基于 RISC-V rv32i 指令集的五级流水线 CPU 实现，使用 assassyn 语言编写。assassyn 是一门基于 Python 的硬件描述语言（RTL language），旨在统一硬件建模、实现和验证。

### 项目特点

- **指令集架构**: RISC-V RV32I（32位基础整数指令集）
- **流水线架构**: 五级流水线（IF-ID-EX-MEM-WB）
- **编程语言**: assassyn（基于 Python 的硬件描述语言）
- **主要功能**: 完整的指令解码、执行、内存访问和写回机制

### 项目文件结构

```
.
├── rv32i_cpu.py              # 主 CPU 实现文件（五级流水线）
├── test.py                   # 简单的 assassyn 测试程序
├── gen_hex.py                # 生成测试数据的十六进制文件
├── run_benchmark.py          # 运行基准测试的脚本
├── test_rv32i.py             # RV32I CPU 测试文件
├── test_rv32i_adapter.py     # RV32I CPU 适配器测试
├── test_downstream.py         # Downstream 模块测试
├── simple_counter.py         # 简单计数器示例
├── array_increment.py        # 数组递增示例
├── process_hex.py            # 处理十六进制文件
├── update_hex_files.py       # 更新十六进制文件
└── benchmarks/               # 基准测试程序
    ├── add_while/            # while 循环加法测试
    ├── multiply/             # 乘法测试
    └── vvadd/                # 向量向量加法测试
```

## CPU 架构说明

### 五级流水线架构

本 CPU 采用经典的五级流水线设计，每个阶段负责不同的任务：

```mermaid
graph LR
    IF[IF: 指令获取] --> ID[ID: 指令解码]
    ID --> EX[EX: 执行]
    EX --> MEM[MEM: 内存访问]
    MEM --> WB[WB: 写回]
    WB -.-> IF
```

### 流水线阶段详解

#### 1. IF 阶段（指令获取）

**类**: [`FetchStage`](rv32i_cpu.py:19)

**功能**:
- 从指令内存中读取指令
- 计算下一条指令的 PC（PC + 4）
- 处理流水线暂停（stall）信号
- 将指令和 PC 传递到 ID 阶段

**关键信号**:
- `pc`: 程序计数器
- `stall`: 流水线暂停信号
- `if_id_pc`: IF/ID 流水线寄存器（PC）
- `if_id_instruction`: IF/ID 流水线寄存器（指令）
- `if_id_valid`: IF/ID 流水线寄存器（有效标志）

#### 2. ID 阶段（指令解码）

**类**: [`DecodeStage`](rv32i_cpu.py:46)

**功能**:
- 解析指令格式（R型、I型、S型、B型、U型、J型）
- 提取操作码、功能码、寄存器索引
- 生成控制信号（ALU操作、内存读写、分支判断等）
- 提取并符号扩展立即数
- 检测数据冒险

**支持的指令格式**:
- **R型**: `add`, `sub`, `and`, `or`, `xor`, `sll`, `srl`, `sra`, `slt`, `sltu`
- **I型**: `addi`, `andi`, `ori`, `xori`, `lw`, `jalr`
- **S型**: `sw`, `sb`, `sh`
- **B型**: `beq`, `bne`, `blt`, `bge`, `bltu`, `bgeu`
- **U型**: `lui`, `auipc`
- **J型**: `jal`

**控制信号** (42位):
```
[41:30]  - 立即数低12位
[29:25]  - rd地址
[24]     - 保留位
[23:22]  - 存储类型: 00=SB, 01=SH, 10=SW
[21]     - 保留位
[20]     - 跳转指令标志
[19:17]  - 分支操作类型
[16:11]  - 保留位
[10:9]   - ALU输入选择: 00=寄存器, 01=立即数, 10=PC
[8]      - 内存到寄存器
[7]      - 寄存器写使能
[6]      - 内存写使能
[5]      - 内存读使能
[4:0]    - ALU操作码
```

#### 3. EX 阶段（执行）

**类**: [`ExecuteStage`](rv32i_cpu.py:235)

**功能**:
- ALU 操作（加减、逻辑、移位、比较）
- 分支条件判断
- 跳转目标地址计算
- PC 更新控制

**ALU 操作码**:
```
00000 - ADD
00001 - SUB
00010 - SLL
00011 - SLT
00100 - XOR
00101 - SRL
00110 - SRA
00111 - SLTU
01000 - OR
01001 - AND
```

**分支操作码**:
```
001 - BEQ
010 - BNE
011 - BLT
100 - BGE
101 - BLTU
110 - BGEU
```

#### 4. MEM 阶段（内存访问）

**类**: [`MemoryStage`](rv32i_cpu.py:361)

**功能**:
- 处理内存读写操作（lw, sw, sb, sh）
- 与数据 SRAM 交互
- 将内存读取的数据传递到 WB 阶段

**关键信号**:
- `mem_read`: 内存读使能
- `mem_write`: 内存写使能
- `store_type`: 存储类型（字节/半字/字）

#### 5. WB 阶段（写回）

**类**: [`WriteBackStage`](rv32i_cpu.py:406)

**功能**:
- 选择写回数据（ALU结果或内存数据）
- 将结果写回寄存器文件
- 处理 x0 寄存器（不写入）

### Hazard Unit（冒险检测单元）

**类**: [`HazardUnit`](rv32i_cpu.py:435)

**类型**: `Downstream`

**功能**:
- 检测数据冒险（Data Hazard）
- 生成流水线暂停信号
- 处理控制冒险（分支和跳转）
- 更新 PC 和流水线寄存器

**冒险类型**:
1. **数据冒险**: 当指令需要读取的寄存器正在被前序指令写入时
2. **控制冒险**: 分支和跳转指令导致的 PC 变化

**冒险处理策略**:
- 使用流水线暂停（stall）来处理数据冒险
- 使用控制信号清空流水线来处理控制冒险

### 寄存器文件

- **通用寄存器**: 32个32位寄存器（x0-x31）
- **x0 寄存器**: 硬连线为0，不可写入
- **初始化**: 所有寄存器初始值为0

### 内存系统

- **指令内存**: `RegArray(UInt(32), 2048)` - 2048条指令空间
- **数据内存**: `SRAM(width=32, depth=65536)` - 64KB 数据空间
- **内存访问**: 支持字节、半字、字读写

## Assassyn 语言使用指南

### 基本概念

Assassyn 是一门基于 Python 的硬件描述语言，它通过装饰器和操作符重载提供了类似软件编程的硬件设计体验。

#### 核心组件

1. **SysBuilder**: 系统构建器，用于创建顶层硬件系统
2. **Module**: 硬件模块，类似于 Verilog 中的 module
3. **Downstream**: 下游模块，用于处理组合逻辑
4. **RegArray**: 寄存器数组，用于存储状态
5. **Port**: 端口，用于模块间通信
6. **SRAM**: 静态随机存取存储器

### Module 定义

Module 是硬件设计的基本构建块，使用装饰器来定义构造函数和组合逻辑。

```python
from assassyn.frontend import *

class MyModule(Module):
    @module.constructor
    def __init__(self):
        super().__init__()
        # 声明端口
        self.a = Port(Int(32))
        self.b = Port(Int(32))
    
    @module.combinational
    def build(self):
        # 组合逻辑
        a, b = self.pop_all_ports(True)
        c = a + b
        log("Result: {}", c)
```

**关键装饰器**:
- `@module.constructor`: 定义模块构造函数，声明端口
- `@module.combinational`: 定义组合逻辑

### Downstream 定义

Downstream 模块用于处理组合逻辑，通常作为 Module 的子模块。

```python
class MyDownstream(Downstream):
    def __init__(self):
        super().__init__()
    
    @downstream.combinational
    def build(self, input_signal, reg_array):
        # 组合逻辑处理
        result = input_signal + Int(32)(1)
        reg_array[0] = result
        return result
```

**关键装饰器**:
- `@downstream.combinational`: 定义下游模块的组合逻辑

### 类型系统

Assassyn 支持多种数据类型：

#### 基本类型

```python
# 无符号整数
UInt(32)    # 32位无符号整数
UInt(8)     # 8位无符号整数

# 有符号整数
Int(32)     # 32位有符号整数
Int(8)      # 8位有符号整数

# 位向量
Bits(32)    # 32位向量
Bits(1)     # 1位向量（布尔值）

# 浮点数
Float(32)   # 32位浮点数
```

#### 复合类型

```python
# Record 类型 - 字段打包
my_record = Record([
    ('field1', UInt(32)),
    ('field2', UInt(16)),
    ('field3', UInt(8))
])
```

#### 类型转换

```python
# bitcast - 位级转换
value_uint = UInt(32)(42)
value_bits = value_uint.bitcast(Bits(32))

# sext - 符号扩展
value_int8 = Int(8)(-1)
value_int32 = value_int8.sext(Int(32))

# concat - 拼接
high_bits = Bits(16)(0xABCD)
low_bits = Bits(16)(0x1234)
result = concat(high_bits, low_bits)  # 0xABCD1234
```

### 表达式和操作

#### 算术运算

```python
result = a + b      # 加法
result = a - b      # 减法
result = a * b      # 乘法
result = a / b      # 除法
result = a % b      # 取模
result = a ** b     # 幂运算
```

#### 位运算

```python
result = a & b      # 按位与
result = a | b      # 按位或
result = a ^ b      # 按位异或
result = ~a         # 按位取反
result = a << n     # 左移
result = a >> n     # 右移
```

#### 比较运算

```python
result = a == b     # 等于
result = a != b     # 不等于
result = a > b      # 大于
result = a >= b     # 大于等于
result = a < b      # 小于
result = a <= b     # 小于等于
```

#### 选择操作

```python
# 三元选择器
result = condition.select(value_if_true, value_if_false)

# 多路选择器
result = selector.select(option0, option1, option2, option3)
```

#### 位操作

```python
# 位切片
byte = word[0:7]        # 提取低8位（包含两端）
half_word = word[16:31] # 提取高16位

# 拼接
combined = a.concat(b)  # a为高位，b为低位
```

### 数组操作

#### RegArray（寄存器数组）

```python
# 创建寄存器数组
reg_array = RegArray(UInt(32), 32)  # 32个32位寄存器
reg_array = RegArray(UInt(32), 32, initializer=[0]*32)  # 带初始化

# 读取
value = reg_array[5]  # 读取第5个寄存器

# 写入
reg_array[5] = UInt(32)(42)  # 写入第5个寄存器

# 注意：寄存器写入在下一个周期才可见
```

**重要规则**:
- 寄存器数组每个周期只能写入一次
- 写入的数据在下一个周期才能读取
- 违反规则会导致运行时错误

#### SRAM（静态随机存取存储器）

```python
from assassyn.ir.memory.sram import SRAM

# 创建 SRAM
sram = SRAM(width=32, depth=1024, init_file="data.hex")
sram.name = 'my_sram'

# 构建 SRAM
sram.build(
    we=write_enable,    # 写使能
    re=read_enable,     # 读使能
    addr=address,       # 地址
    wdata=write_data,   # 写数据
    user=user_module    # 用户模块
)

# 读取数据
read_data = sram.dout[0]
```

### 控制流

#### 条件执行

```python
# 编译时条件（生成不同的硬件）
if compile_time_condition:
    # 这段代码只在条件为真时生成硬件
    result = a + b
else:
    result = a - b

# 运行时条件（生成多路选择器）
with Condition(runtime_condition):
    result = a + b
```

#### 循环

Assassyn 不支持传统的循环，而是使用展开的方式：

```python
# 手动展开
result = UInt(32)(0)
result = result + UInt(32)(1)
result = result + UInt(32)(1)
result = result + UInt(32)(1)
```

#### 状态机

```python
from assassyn.frontend import fsm

class MyFSM(Module):
    @module.combinational
    def build(self, state_reg):
        # 定义状态转换表
        t_table = {
            "IDLE":   {default_cond: "RUNNING"},
            "RUNNING": {done_cond: "DONE", ~done_cond: "RUNNING"},
            "DONE":   {default_cond: "DONE"},
        }
        
        # 定义状态体
        def idle_body():
            log("IDLE state")
        
        def running_body():
            log("RUNNING state")
        
        def done_body():
            log("DONE state")
            finish()
        
        body_table = {
            "IDLE": idle_body,
            "RUNNING": running_body,
            "DONE": done_body
        }
        
        # 生成状态机
        my_fsm = fsm.FSM(state_reg, t_table)
        my_fsm.generate(body_table)
```

### 模块通信

#### 端口通信

```python
# 定义带端口的模块
class Producer(Module):
    @module.constructor
    def __init__(self):
        super().__init__()
        self.data = Port(UInt(32))
    
    @module.combinational
    def build(self):
        data = self.pop_all_ports(True)
        log("Produced: {}", data)

class Consumer(Module):
    @module.constructor
    def __init__(self):
        super().__init__()
        self.data = Port(UInt(32))
    
    @module.combinational
    def build(self):
        data = self.pop_all_ports(True)
        log("Consumed: {}", data)

# 连接模块
producer = Producer()
consumer = Consumer()
producer.build()
consumer.build()

# 异步调用
producer.async_called(data=UInt(32)(42))
```

#### 异步调用

```python
# async_called - 异步调用模块
module.async_called(param1=value1, param2=value2)

# bind - 绑定参数（部分应用）
bound = module.bind(param1=value1)
bound.async_called(param2=value2)
```

#### FIFO 操作

```python
# 端口 FIFO 方法
value = port.pop()           # 弹出数据
port.push(value)             # 推入数据
value = port.peek()          # 查看数据但不弹出
valid = port.valid           # 检查是否有有效数据
```

### 日志和调试

```python
# 日志输出
log("Simple message")
log("Value: {}", value)
log("Multiple values: {} {} {}", a, b, c)

# 格式化输出
log("PC=0x{:08x}, Instruction=0x{:08x}", pc, instruction)
log("Register x{:02} = {}", reg_idx, reg_value)

# 完成模拟
finish()

# 断言
assume(condition)
```

### 系统构建

```python
from assassyn.frontend import SysBuilder
from assassyn.backend import elaborate
from assassyn import utils

# 创建系统
sys = SysBuilder('my_system')

with sys:
    # 在系统上下文中构建模块
    module1 = MyModule()
    module1.build()
    
    module2 = MyDownstream()
    module2.build(input_signal, reg_array)
    
    # 暴露顶层信号
    sys.expose_on_top(reg_array, kind='Output')

# 生成模拟器和 Verilog
config = assassyn.backend.config(
    verilog=True,              # 生成 Verilog
    sim_threshold=1000,        # 模拟阈值
    idle_threshold=1000,       # 空闲阈值
    random=False               # 是否随机化
)

simulator_path, verilator_path = elaborate(sys, **config)

# 运行模拟器
raw = utils.run_simulator(simulator_path)
print(raw)

# 运行 Verilator（如果可用）
if verilator_path:
    raw = utils.run_verilator(verilator_path)
    print(raw)
```

### 测试框架

```python
from assassyn.test import run_test

def test_my_module():
    def top():
        module = MyModule()
        module.build()
    
    def check_raw(raw):
        # 检查输出
        assert "Expected message" in raw
    
    run_test('my_module', top, check_raw, 
             sim_threshold=100, 
             idle_threshold=100,
             random=True)

if __name__ == '__main__':
    test_my_module()
```

### 重要注意事项

1. **写一次规则**: 寄存器数组每个周期只能写入一次
2. **时序延迟**: 寄存器写入的数据在下一个周期才能读取
3. **类型匹配**: 所有操作必须类型匹配，使用 bitcast 进行转换
4. **位宽一致**: 拼接和切片操作要注意位宽
5. **条件编译**: 使用 `if` 进行编译时条件，使用 `with Condition()` 进行运行时条件

## 代码结构说明

### 主文件

#### [`rv32i_cpu.py`](rv32i_cpu.py:1)

主 CPU 实现文件，包含完整的五级流水线实现：

**主要类**:
- [`FetchStage`](rv32i_cpu.py:19) - IF 阶段
- [`DecodeStage`](rv32i_cpu.py:46) - ID 阶段
- [`ExecuteStage`](rv32i_cpu.py:235) - EX 阶段
- [`MemoryStage`](rv32i_cpu.py:361) - MEM 阶段
- [`WriteBackStage`](rv32i_cpu.py:406) - WB 阶段
- [`HazardUnit`](rv32i_cpu.py:435) - 冒险检测单元
- [`Driver`](rv32i_cpu.py:502) - 顶层驱动模块

**主要函数**:
- [`init_memory()`](rv32i_cpu.py:511) - 初始化指令内存
- [`build_cpu()`](rv32i_cpu.py:539) - 构建 CPU 系统
- [`test_rv32i_cpu()`](rv32i_cpu.py:605) - 测试 CPU

### 辅助文件

#### [`test.py`](test.py:1)

简单的 assassyn 测试程序，演示基本功能：
- Module 和 Downstream 的使用
- RegArray 的读写
- 日志输出

#### [`gen_hex.py`](gen_hex.py:1)

生成测试数据的十六进制文件：
- 创建输入数据
- 生成验证数据
- 写入 `data.hex` 文件

#### [`run_benchmark.py`](run_benchmark.py:1)

运行基准测试的脚本：
- 加载基准测试程序
- 生成模拟器
- 运行并输出结果

#### [`simple_counter.py`](simple_counter.py:1)

简单计数器示例，演示：
- RegArray 的使用
- 递增操作
- 日志输出

#### [`array_increment.py`](array_increment.py:1)

数组递增示例，演示：
- 动态索引
- 循环展开
- 复杂数据结构

#### [`process_hex.py`](process_hex.py:1)

处理十六进制文件的辅助脚本。

#### [`update_hex_files.py`](update_hex_files.py:1)

更新十六进制文件的辅助脚本。

### 测试文件

#### [`test_rv32i.py`](test_rv32i.py:1)

RV32I CPU 的主要测试文件：
- 测试各种指令
- 验证 CPU 功能
- 检查输出结果

#### [`test_rv32i_adapter.py`](test_rv32i_adapter.py:1)

RV32I CPU 适配器测试：
- 测试适配器功能
- 验证接口正确性

#### [`test_downstream.py`](test_downstream.py:1)

Downstream 模块测试：
- 测试下游模块功能
- 验证组合逻辑

### 基准测试

#### [`benchmarks/add_while/`](benchmarks/add_while/)

while 循环加法测试：
- 测试循环控制
- 验证加法运算
- 检查结果正确性

**文件**:
- `test.c` - C 源代码
- `test.hex` - 十六进制机器码
- `program.txt` - 程序文本格式

#### [`benchmarks/multiply/`](benchmarks/multiply/)

乘法测试：
- 测试乘法运算
- 验证乘法结果
- 检查边界情况

#### [`benchmarks/vvadd/`](benchmarks/vvadd/)

向量向量加法测试：
- 测试向量运算
- 验证内存访问
- 检查并行性

## 待实现的 Bonus 功能

### 1. Fully Associative Cache（全相联缓存）

**目标**: 实现全相联缓存机制，提高数据访问效率。

**功能要求**:
- 全相联映射策略
- 替换算法（LRU 或 FIFO）
- 写策略（写回或写通）
- 缓存一致性

**实现位置**:
- 在 MEM 阶段集成缓存控制器
- 修改 [`MemoryStage`](rv32i_cpu.py:361) 类
- 添加缓存管理模块

**技术要点**:
- 标签比较
- 命中/未命中处理
- 替换策略实现
- 与 SRAM 的接口

### 2. BTB Branch Predictor（分支目标缓冲区预测器）

**目标**: 实现分支预测器，减少控制冒险带来的流水线停顿。

**功能要求**:
- 分支目标地址缓存
- 分支方向预测
- 预测更新机制
- 预测失败恢复

**实现位置**:
- 在 IF 阶段集成 BTB
- 修改 [`FetchStage`](rv32i_cpu.py:19) 类
- 添加 BTB 管理模块

**技术要点**:
- BTB 表结构（PC 到目标地址的映射）
- 预测算法（静态或动态）
- 预测准确率统计
- 预测失败时的流水线刷新

**参考示例**:
- `/home/zhangboju/assassyn/examples/minor-cpu/src/br_pre_main.py`

### 3. RV32IM ISA（乘法和除法指令）

**目标**: 扩展指令集，支持 RV32IM（乘法和除法）指令。

**功能要求**:
- 实现乘法指令（mul, mulh, mulhsu, mulhu）
- 实现除法指令（div, divu, rem, remu）
- 使用 Wallace Tree 乘法器
- 使用 SRT 除法器

**实现位置**:
- 在 EX 阶段集成乘除法单元
- 修改 [`ExecuteStage`](rv32i_cpu.py:235) 类
- 添加乘除法模块

**技术要点**:

#### Wallace Tree 乘法器
- 并行乘法算法
- 减少关键路径延迟
- 提高乘法运算速度

**实现步骤**:
1. 设计 Wallace Tree 结构
2. 实现部分积生成
3. 实现压缩和加法
4. 集成到 ALU

#### SRT 除法器
- Sweeney-Robertson-Tocher 算法
- 每次迭代产生多位商
- 提高除法运算速度

**实现步骤**:
1. 设计 SRT 除法器结构
2. 实现商位选择
3. 实现余数更新
4. 集成到 ALU

**新增指令**:
```
mul     - 32位乘法（低32位）
mulh    - 有符号乘法（高32位）
mulhsu  - 有符号×无符号乘法（高32位）
mulhu   - 无符号乘法（高32位）
div     - 有符号除法
divu    - 无符号除法
rem     - 有符号取余
remu    - 无符号取余
```

**参考示例**:
- `/home/zhangboju/assassyn/python/assassyn/ip/multiply.py`

## 开发指南

### 环境设置

本项目使用 apptainer 容器运行，无需依赖外部 assassyn 仓库。所有必要的 assassyn 环境已打包在 `assassyn.sif` 容器镜像中。

### 运行程序

使用 apptainer 运行项目中的任何 Python 程序：

```bash
# 运行简单测试
apptainer exec ./assassyn.sif python ./test.py

# 运行其他示例程序
apptainer exec ./assassyn.sif python ./simple_counter.py
apptainer exec ./assassyn.sif python ./array_increment.py
```

### 运行 rv32i_cpu.py

运行 [`rv32i_cpu.py`](rv32i_cpu.py:1) 时，目录下必须包含以下两个文件：

1. **test_program.txt** - 存储程序反编译后的十六进制结果
   - 格式：每行一个十六进制数，包含 `0x` 前缀
   - 示例：
     ```
     0x00000013
     0x00000593
     0x00000513
     ```

2. **data.hex** - 存储数据的十六进制结果
   - 格式：每行一个十六进制数，**不包含** `0x` 前缀
   - 示例：
     ```
     00000001
     00000002
     00000003
     ```

运行命令：
```bash
apptainer exec ./assassyn.sif python ./rv32i_cpu.py
```

### 运行基准测试

基准测试程序位于 `benchmarks/` 目录下。每个基准测试目录包含：
- C 源代码（`test.c`）
- 十六进制机器码（`test.hex`）
- 程序文本格式（`program.txt`）

```bash
apptainer exec ./assassyn.sif python ./rv32i_cpu.py
```

**你总可以假设测试数据已被正确拷贝到 test_program.txt 以及 data.hex 中**

**程序所有日志的输出在 reslut.out 中，直接输出的为运行是否正确的信息**

**禁止通过任何方式向 result.out 中写入内容**

### 调试技巧

1. **使用日志输出**:
```python
log("Debug info: PC={}, Instruction={}", pc, instruction)
```

2. **检查中间结果**:
```python
log("ALU result: {}", alu_result)
log("Register file: {}", reg_file)
```

3. **使用断言**:
```python
assume(condition)  # 如果条件为假，模拟停止
```

4. **限制模拟周期**:
```python
config = assassyn.backend.config(
    sim_threshold=1000,  # 最多模拟1000个周期
    idle_threshold=1000  # 最多1000个空闲周期
)
```

### 代码规范

1. **命名规范**:
   - 类名使用 PascalCase: `MyModule`
   - 函数名使用 snake_case: `my_function`
   - 变量名使用 snake_case: `my_variable`

2. **注释规范**:
   - 模块类添加文档字符串
   - 复杂逻辑添加行内注释
   - 使用中文注释说明功能

3. **代码组织**:
   - 按功能分组代码
   - 使用空行分隔逻辑块
   - 保持代码缩进一致

### 性能优化

1. **减少流水线停顿**:
   - 优化 Hazard Unit 的冒险检测
   - 实现前递（forwarding）机制

2. **提高时钟频率**:
   - 优化关键路径
   - 使用流水线技术

3. **减少资源使用**:
   - 复用硬件资源
   - 优化数据通路宽度

## 参考资料

### Assassyn 文档

- **语言手册**: `/home/zhangboju/assassyn/docs/language.md`
- **开发者指南**: `/home/zhangboju/assassyn/docs/developer/`
- **示例代码**: `/home/zhangboju/assassyn/examples/`
- **测试用例**: `/home/zhangboju/assassyn/python/ci-tests/`

### RISC-V 规范

- **RV32I 基础整数指令集**: [RISC-V 规范卷一](https://riscv.org/technical/specifications/)
- **RV32M 乘法和除法指令集**: [RISC-V 规范卷一](https://riscv.org/technical/specifications/)

### CPU 架构参考

- **五级流水线设计**: `/home/zhangboju/assassyn/examples/minor-cpu/`
- **分支预测**: `/home/zhangboju/assassyn/examples/minor-cpu/src/br_pre_main.py`
- **乘法器实现**: `/home/zhangboju/assassyn/python/assassyn/ip/multiply.py`

## 总结

本项目提供了一个完整的 RISC-V RV32I 五级流水线 CPU 实现，使用 assassyn 语言编写。通过本指南，开发者可以：

1. 理解 CPU 的五级流水线架构
2. 掌握 assassyn 语言的基本用法
3. 了解代码结构和组织方式
4. 实现扩展功能（缓存、分支预测、乘除法）

项目具有良好的可扩展性，可以通过实现 Bonus 功能来提升 CPU 的性能和功能。建议开发者按照本指南逐步学习和实践，逐步完善和优化 CPU 实现。
