# Assassyn 语法指南 (Assassyn Grammar Guide)

> **作者**: Claude (基于 Assassyn 官方文档)
> **日期**: 2026-01-09
> **版本**: v1.0

---

## 目录

1. [核心概念](#1-核心概念)
2. [数据类型](#2-数据类型)
3. [模块系统](#3-模块系统)
4. [表达式系统](#4-表达式系统)
5. [控制流](#5-控制流)
6. [数组与寄存器](#6-数组与寄存器)
7. [内存系统](#7-内存系统)
8. [构建器与装饰器](#8-构建器与装饰器)
9. [完整示例](#9-完整示例)

---

## 1. 核心概念

### 1.1 Trace-based DSL

Assassyn 采用 **trace-based DSL（领域特定语言）**嵌入在 Python 中，通过**运算符重载**构建硬件抽象语法树 (AST)。

**关键特性:**
- 在 tracing 作用域内，`a + b` 不计算结果，而是创建 `Add` IR 节点
- Python 代码执行过程 = IR 构建过程
- 自动注入: 使用 `@ir_builder` 装饰器自动将表达式加入 IR

### 1.2 Python `if` vs Assassyn `Condition`

| 特性 | Python `if` | Assassyn `Condition` |
|------|------------|---------------------|
| **求值时机** | 编译时 (Python 运行时) | 硬件运行时 |
| **作用** | 控制 trace 路径,条件编译 | 生成硬件条件逻辑 |
| **生成硬件** | 不生成,直接选择分支 | 生成 mux 和条件块 |
| **类比** | C/C++ 的 `#if` 预处理 | Verilog 的 `if` 语句 |

```python
# Python if - 编译时决定
ENABLE_FEATURE = True
if ENABLE_FEATURE:
    result = a * 2  # 只有这个分支被 trace

# Assassyn Condition - 运行时判断
with Condition(enable):
    result = a * 2  # 生成条件硬件
```

---

## 2. 数据类型

### 2.1 基础类型

#### `Int(bits)` - 有符号整数
```python
counter = Int(32)  # 32位有符号整数
value = counter(42)  # 创建常量
# 范围: -2^(bits-1) 到 2^(bits-1)-1
```

#### `UInt(bits)` - 无符号整数
```python
addr = UInt(32)  # 32位无符号整数
index = UInt(6)  # 6位无符号整数 (0-63)
# 范围: 0 到 2^bits - 1
```

#### `Bits(bits)` - 原始位向量
```python
data = Bits(64)  # 64位原始数据
flag = Bits(1)   # 单比特信号
# 无算术语义,纯位向量
```

#### `Float` - 浮点数
```python
fp = Float(32)  # 32位浮点数
```

### 2.2 复合类型

#### `Record` - 结构体
```python
class MyRecord(Record):
    def __init__(self):
        super().__init__([
            ('field1', UInt(32)),
            ('field2', Int(16)),
        ])
```

---

## 3. 模块系统

### 3.1 Module 基类

所有硬件模块继承自 `Module`:

```python
from assassyn.frontend import *

class MyModule(Module):
    def __init__(self):
        super().__init__(
            ports={
                'input1': Port(UInt(32)),
                'output1': Port(UInt(32)),
            }
        )

    @module.combinational  # 装饰器: 标记为组合逻辑
    def build(self, other_module):
        # 获取端口
        input1 = self.pop_all_ports(True)

        # 硬件逻辑
        result = input1 + UInt(32)(1)

        # 调用其他模块
        other_module.async_called(output1=result)
```

### 3.2 装饰器类型

#### `@module.combinational` - 组合逻辑
```python
@module.combinational
def build(self):
    # 立即求值,无状态
    result = a + b
```

#### `@module.sequential` - 时序逻辑 (Cycle-based)
```python
@module.sequential
def build(self):
    # 周期性行为
    with Condition(counter < UInt(32)(100)):
        counter[0] = counter[0] + UInt(32)(1)
```

---

## 4. 表达式系统

### 4.1 算术运算

```python
# 加法
result = a + b

# 减法
result = a - b

# 乘法
result = a * b

# 除法
result = a / b

# 位运算
result = a & b   # AND
result = a | b   # OR
result = a ^ b   # XOR
result = ~a      # NOT
result = a << b  # 左移
result = a >> b  # 右移
```

### 4.2 比较运算

```python
# 等于
condition = (a == b)

# 不等于
condition = (a != b)

# 大于/小于
condition = (a < b)
condition = (a > b)
condition = (a <= b)
condition = (a >= b)
```

### 4.3 位选择

```python
# 位切片
bits = data[7:0]      # 取低8位
bit = data[5:5]       # 取第5位

# Bitcast 转换
uint_val = int_val.bitcast(UInt(32))
```

### 4.4 拼接

```python
# 拼接操作
combined = concat(high_bits, low_bits)

# 示例: 32位 = 16位高 + 16位低
result = concat(data[31:16], data[15:0])
```

### 4.5 特殊表达式

```python
# 日志输出 (用于仿真调试)
log("Value: {}", value)

# 内存操作
send_read_request(addr, size)
send_write_request(addr, data, size)
has_mem_resp()  # 检查内存响应

# 等待条件
wait_until(condition)

# 假设 (用于验证)
assume(condition)
```

---

## 5. 控制流

### 5.1 Condition - 硬件条件语句

⚠️ **重要限制**: 在 `Condition` 内部**只允许写寄存器**，不允许组合逻辑赋值！

```python
# ✅ 正确: 在 Condition 中写寄存器
with Condition(enable):
    counter[0] = counter[0] + UInt(32)(1)

# ❌ 错误: 在 Condition 中写组合逻辑变量
with Condition(enable):
    result = a + b  # 这是组合逻辑,不允许!

# ✅ 正确: 使用 select 实现条件组合逻辑
result = enable.select(a + b, c + d)
```

**原因**:
- `Condition` 生成时序逻辑 (registers + enable logic)
- 组合逻辑应该在 Condition 外部使用 `select` 实现

```python
# 单分支 - 只能写寄存器
with Condition(enable):
    counter[0] = counter[0] + UInt(32)(1)

# 多分支 (if-else) - 只能写寄存器
with Condition(enable):
    reg_a[0] = input_value
with Condition(~enable):
    reg_b[0] = input_value

# 复杂条件 - 只能写寄存器
with Condition((a > UInt(32)(10)) & (b < UInt(32)(20))):
    counter[0] = counter[0] + UInt(32)(1)
```

### 5.2 select - 三元运算符

```python
# condition ? true_val : false_val
result = condition.select(true_val, false_val)

# 示例: MUX
output = enable.select(value1, value0)
```

---

## 6. 数组与寄存器

### 6.1 RegArray - 寄存器数组

```python
# 声明寄存器数组
reg_file = RegArray(UInt(32), 32)  # 32个32位寄存器

# 读写
reg_file[5] = reg_file[5] + UInt(32)(1)
value = reg_file[5]

# 单个寄存器
counter = RegArray(UInt(32), 1)
counter[0] = counter[0] + UInt(32)(1)
```

### 6.2 Array - 组合逻辑数组

```python
# 组合逻辑数组
memory = Array(UInt(8), 1024)  # 1KB组合逻辑存储
data = memory[addr]
```

---

## 7. 内存系统

### 7.1 SRAM - 静态随机存取存储器

```python
from assassyn.ir.memory.sram import SRAM

# 创建SRAM
data_sram = SRAM(width=32, depth=65536, init_file="data.hex")

# 读取
read_data = data_sram[addr]

# 写入
data_sram[addr] = write_data
```

### 7.2 DRAM - 动态随机存取存储器

```python
from assassyn.ir.memory.dram import DRAM

# 创建DRAM
dram = DRAM(width=64, addr_width=40)

# 异步读写
send_read_request(dram, addr, size)
send_write_request(dram, addr, data, size)
with Condition(has_mem_resp()):
    data = dram[addr]
```

---

## 8. 构建器与装饰器

### 8.1 SysBuilder - 系统构建器

```python
from assassyn.frontend import SysBuilder

# 创建系统
sys = SysBuilder('my_system')

with sys:
    # 在上下文中定义硬件
    reg = RegArray(UInt(32), 1)
    module = MyModule()
    module.build()

# 查看系统
print(sys)
```

### 8.2 @ir_builder - IR构建装饰器

```python
from assassyn.builder import ir_builder

@ir_builder
def my_function():
    return a + b  # 自动注入到IR

# 等价于手动:
@ir_builder
def my_function_manual():
    result = a + b
    return result  # 返回值自动加入IR
```

### 8.3 elaborate - 生成仿真器和Verilog

```python
from assassyn.backend import elaborate
from assassyn import utils

# 生成仿真器和Verilog
simulator_path, verilator_path = elaborate(
    sys,
    verilog=utils.has_verilator()  # 是否生成Verilog
)

# 运行仿真
raw_output = utils.run_simulator(simulator_path)

# 运行Verilator (如果可用)
if verilator_path:
    raw_output = utils.run_verilator(verilator_path)
```

---

## 9. Driver 模块

### 9.1 Driver 的角色

`Driver` 是 Assassyn 中的**特殊模块**,相当于硬件系统的"主函数"和"时钟源"。

**关键特性:**
- 📍 **系统的入口点**: 类似于软件的 `main()` 函数
- ⏰ **每个周期无条件激活**: 充当系统的"时钟"
- ♾️ **无限积分 (Infinite Credits)**: 可以无限次调用其他模块
- 🔄 **驱动流水线**: 通过 `async_called()` 激活下游模块

### 9.2 Driver 的工作原理

```python
class Driver(Module):
    def __init__(self):
        super().__init__(ports={})  # Driver 通常没有端口

    @module.combinational
    def build(self, first_stage):
        # 每个周期无条件执行
        first_stage.async_called()  # 激活流水线第一阶段
```

**执行流程:**
1. 每个时钟周期,Driver 自动激活
2. Driver 调用 `async_called()` 增加下游模块的 credit
3. 下游模块检查 credit,决定是否执行
4. 下游模块使用 `wait_until()` 消耗 credit

### 9.3 积分系统 (Credit System)

```
Driver (无限积分)
   |
   | async_called() → 增加 credit
   v
Stage 1 (credit counter)
   |
   | wait_until() → 消耗 credit
   v
Stage 2 (credit counter)
```

**规则:**
- `async_called()`: 增加目标模块的 credit
- `wait_until(condition)`: 消费当前模块的 credit,等待条件满足
- **Driver 拥有无限 credit**,可以无限调用其他模块

### 9.4 实际例子

```python
class SimpleCPU(Module):
    @module.combinational
    def build(self):
        pc = RegArray(UInt(32), 1)

class Driver(Module):
    @module.combinational
    def build(self, cpu):
        # 每个周期激活 CPU
        cpu.async_called()

# 构建系统
sys = SysBuilder('simple_cpu')
with sys:
    cpu = SimpleCPU()
    cpu.build()

    driver = Driver()
    driver.build(cpu)  # Driver 激活 CPU
```

### 9.5 Driver 在流水线中的应用

```python
class Driver(Module):
    """五级流水线 CPU 的 Driver"""
    @module.combinational
    def build(self, fetch_stage):
        # 每个周期激活 IF 阶段
        fetch_stage.async_called()
```

**流水线执行:**
```
周期 1: Driver → IF (credit++, 执行)
周期 2: Driver → IF (credit++, 执行)
         IF → ID (credit++, 执行)
周期 3: Driver → IF (credit++, 执行)
         IF → ID (credit++, 执行)
         ID → EX (credit++, 执行)
```

---

## 10. 完整示例

### 10.1 简单计数器

```python
from assassyn.frontend import *
from assassyn.backend import elaborate
from assassyn import utils

class Counter(Module):
    def __init__(self):
        super().__init__(
            ports={
                'enable': Port(Bits(1)),
                'reset': Port(Bits(1)),
            }
        )

    @module.combinational
    def build(self):
        enable, reset = self.pop_all_ports(True)

        # 32位计数器
        counter = RegArray(UInt(32), 1)

        # 复位逻辑 - Condition 中只能写寄存器
        with Condition(reset[0:0]):
            counter[0] = UInt(32)(0)

        # 计数逻辑 - Condition 中只能写寄存器
        with Condition(enable[0:0]):
            counter[0] = counter[0] + UInt(32)(1)

        # 日志输出 - 用于仿真调试
        with Condition(counter[0] == UInt(32)(10)):
            log("Counter reached 10!")

# 构建系统
sys = SysBuilder('counter_test')
with sys:
    counter = Counter()
    counter.build()

# 生成并运行
sim_path, _ = elaborate(sys, verilog=False)
raw = utils.run_simulator(sim_path)
print(raw)
```

### 10.2 多模块交互

```python
class Producer(Module):
    def __init__(self):
        super().__init__(ports={'data_out': Port(UInt(32))})

    @module.combinational
    def build(self, consumer):
        data = RegArray(UInt(32), 1)
        data[0] = data[0] + UInt(32)(1)

        # 调用消费者模块
        consumer.async_called(data_in=data[0])

class Consumer(Module):
    def __init__(self):
        super().__init__(ports={'data_in': Port(UInt(32))})

    @module.combinational
    def build(self):
        data_in = self.pop_all_ports(True)
        result = data_in * UInt(32)(2)

        with Condition(result == UInt(32)(100)):
            log("Result is 100!")

sys = SysBuilder('producer_consumer')
with sys:
    producer = Producer()
    consumer = Consumer()
    producer.build(consumer)
```

---

## 10. 关键规则与限制

### 10.1 ⚠️ Condition vs Select 的正确使用

这是 Assassyn 中**最重要的规则**！

#### 规则:

| 构造 | 用途 | 允许操作 | 硬件类型 |
|------|------|---------|---------|
| `Condition` | 时序控制 | **只写寄存器** | 时序逻辑 |
| `select` | 数据选择 | 组合逻辑计算 | 组合逻辑 |

#### ✅ 正确用法:

```python
# 场景1: 条件更新寄存器 - 使用 Condition
with Condition(enable):
    counter[0] = counter[0] + UInt(32)(1)  # ✅ 写寄存器

# 场景2: 条件选择数据 - 使用 select
result = enable.select(value_a, value_b)  # ✅ 组合逻辑 MUX

# 场景3: 复杂条件组合逻辑 - 使用 select
condition = (a > UInt(32)(10)) & (b < UInt(32)(20))
result = condition.select(a * b, c + d)  # ✅ 组合逻辑
```

#### ❌ 错误用法:

```python
# 错误1: 在 Condition 中写组合逻辑
with Condition(enable):
    result = a + b  # ❌ 不允许! 这是组合逻辑

# 错误2: 用 select 更新寄存器
counter[0] = enable.select(counter[0] + UInt(32)(1), counter[0])  # ❌ 语义错误
# 应该用:
with Condition(enable):
    counter[0] = counter[0] + UInt(32)(1)  # ✅
```

### 10.2 时序逻辑 vs 组合逻辑

#### 时序逻辑 (使用 Condition):

```python
# 寄存器更新 - 生成触发器 + 使能逻辑
register = RegArray(UInt(32), 1)
with Condition(enable):
    register[0] = new_value  # 生成: if (enable) register <= new_value
```

#### 组合逻辑 (使用 select):

```python
# 数据选择 - 生成多路选择器
result = condition.select(true_value, false_value)  # 生成: MUX
```

### 10.3 实际案例对比

#### 案例: 带使能的计数器

```python
class Counter(Module):
    @module.combinational
    def build(self):
        enable = self.pop_all_ports(True)
        counter = RegArray(UInt(32), 1)

        # ✅ 正确: 时序逻辑用 Condition
        with Condition(enable):
            counter[0] = counter[0] + UInt(32)(1)

        # ✅ 正确: 组合逻辑用 select
        next_count = counter[0] + UInt(32)(1)
        count_with_max_check = (next_count == UInt(32)(100)).select(
            UInt(32)(0),
            next_count
        )

        # 更好的写法 - 直接在 Condition 中判断
        with Condition(enable & (counter[0] < UInt(32)(100))):
            counter[0] = counter[0] + UInt(32)(1)
```

---

## 11. 最佳实践

### 11.1 命名规范

```python
# 模块名: PascalCase
class MyModule(Module):
    pass

# 变量名: snake_case
register_file = RegArray(UInt(32), 32)

# 常量: UPPER_SNAKE_CASE
MAX_COUNT = UInt(32)(100)
```

### 11.2 类型安全

```python
# 始终显式类型转换
result = UInt(32)(a) + UInt(32)(b)

# 不要依赖隐式转换
# bad: result = a + b  # 类型可能不明确
```

### 11.3 调试技巧

```python
# 使用 log 进行仿真时调试
log("PC={:08x}, Instruction={:08x}", pc, instruction)

# 检查条件
with Condition(debug_enable):
    log("Debug: counter={}", counter[0])
```

---

## 12. 参考资源

- **官方文档**: `assassyn-master/docs/`
- **教程**: `assassyn-master/tutorials/`
- **示例**: `assassyn-master/examples/`
- **IR设计**: `assassyn-master/python/assassyn/ir/**/*.md`

---

## 13. 附录: 常用导入

```python
# 标准导入
from assassyn.frontend import *
from assassyn.backend import elaborate
from assassyn import utils
import assassyn

# 类型系统
from assassyn.frontend import Module, Port, RegArray, Array
from assassyn.frontend import Int, UInt, Bits, Float
from assassyn.frontend import Condition, log, concat

# 内存
from assassyn.ir.memory.sram import SRAM
from assassyn.ir.memory.dram import DRAM

# 构建器
from assassyn.frontend import SysBuilder
from assassyn.builder import ir_builder
```

---

**文档版本**: v1.0
**最后更新**: 2026-01-09
