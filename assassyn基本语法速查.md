# Assassyn 基本语法速查表

> **快速参考：** 这是一份简明的 Assassyn 语法速查表，适合初学者快速上手。详细教程请参考 [`assassyn入门教程.md`](assassyn入门教程.md)。

## 目录
- [最小可运行示例](#最小可运行示例)
- [核心语法](#核心语法)
- [常用操作](#常用操作)
- [完整示例](#完整示例)

---

## 最小可运行示例

```python
from assassyn.frontend import *
from assassyn.backend import elaborate
from assassyn import utils

# 1. 定义模块
class Counter(Module):
    def __init__(self):
        super().__init__(ports={})
    
    @module.combinational
    def build(self):
        # 定义寄存器
        cnt = RegArray(UInt(32), 1)
        
        # 更新寄存器
        (cnt & self)[0] <= cnt[0] + UInt(32)(1)
        
        # 打印日志
        log("计数: {}", cnt[0])

# 2. 运行仿真
def test():
    sys = SysBuilder('my_system')
    with sys:
        counter = Counter()
        counter.build()
    
    simulator_path, _ = elaborate(sys, verilog=False)
    raw = utils.run_simulator(simulator_path)
    print(raw)

if __name__ == "__main__":
    test()
```

---

## 核心语法

### 1. 导入必要模块

```python
from assassyn.frontend import *
from assassyn.backend import elaborate
from assassyn import utils
```

### 2. 定义模块

```python
class MyModule(Module):
    def __init__(self):
        super().__init__(ports={
            'input1': Port(UInt(32)),    # 32位无符号整数输入
            'output1': Port(Bits(8))      # 8位输出
        })
```

### 3. 定义组合逻辑

```python
@module.combinational
def build(self):
    # 模块逻辑写在这里
    pass
```

### 4. 定义寄存器（状态）

```python
# 语法：RegArray(类型, 数量)
cnt = RegArray(UInt(32), 1)        # 1个32位计数器
flags = RegArray(Bits(1), 4)       # 4个标志位
buffer = RegArray(UInt(8), 256)    # 256个8位数据
```

### 5. 读取寄存器

```python
current_value = cnt[0]             # 读取第0个寄存器
flag = flags[2]                    # 读取第2个标志位
```

### 6. 更新寄存器

```python
# 重要：寄存器更新在下一个时钟周期才生效！
(cnt & self)[0] <= new_value       # 安排在下一周期更新
```

### 7. 读取端口

```python
@module.combinational
def build(self):
    # 读取所有端口（按定义顺序）
    input1, output1 = self.pop_all_ports(True)
```

### 8. 条件执行

```python
# 使用 with Condition，不要用 Python 的 if
with Condition(cnt[0] < UInt(32)(100)):
    log("计数小于100")
    (cnt & self)[0] <= cnt[0] + UInt(32)(1)
```

### 9. 模块间通信

```python
# 调用其他模块（异步调用，下一周期执行）
other_module.async_called(
    param1=value1,
    param2=value2
)
```

### 10. 打印日志

```python
log("调试信息: {}", variable)
log("多个值: {}, {}", value1, value2)
```

---

## 常用操作

### 数据类型

```python
# 无符号整数
UInt(8)     # 8位无符号整数
UInt(32)    # 32位无符号整数

# 有符号整数
Int(8)      # 8位有符号整数
Int(32)     # 32位有符号整数

# 位向量
Bits(1)     # 1位
Bits(32)    # 32位向量
```

### 创建常量

```python
UInt(32)(0)      # 32位无符号整数 0
UInt(32)(100)    # 32位无符号整数 100
Bits(1)(1)       # 1位值 1
Int(32)(-5)      # 32位有符号整数 -5
```

### 算术运算

```python
result = a + b          # 加法
result = a - b          # 减法
result = a * b          # 乘法
result = a / b          # 除法
```

### 位运算

```python
result = a & b          # 按位与
result = a | b          # 按位或
result = ~a             # 按位取反
result = a ^ b          # 按位异或
result = a << 2         # 左移2位
result = a >> 2         # 右移2位
```

### 比较运算

```python
is_equal = (a == b)     # 相等
not_equal = (a != b)    # 不等
greater = (a > b)       # 大于
less = (a < b)          # 小于
gte = (a >= b)          # 大于等于
lte = (a <= b)          # 小于等于
```

### 类型转换

```python
# 位向量转换
bits_val = int_val.bitcast(Bits(32))

# 整数转换
int_val = bits_val.bitcast(Int(32))
uint_val = bits_val.bitcast(UInt(32))
```

### 条件选择

```python
# 三元选择：condition.select(true_value, false_value)
result = condition.select(UInt(32)(1), UInt(32)(0))
```

---

## 完整示例

### 示例 1: 简单计数器

```python
from assassyn.frontend import *
from assassyn.backend import elaborate
from assassyn import utils

class SimpleCounter(Module):
    def __init__(self):
        super().__init__(ports={})
    
    @module.combinational
    def build(self):
        # 定义计数器
        cnt = RegArray(UInt(32), 1)
        
        # 计算新值
        new_cnt = cnt[0] + UInt(32)(1)
        
        # 更新计数器
        (cnt & self)[0] <= new_cnt
        
        # 打印当前值
        log("计数器: {}", cnt[0])

def test_counter():
    sys = SysBuilder('counter')
    with sys:
        counter = SimpleCounter()
        counter.build()
    
    simulator_path, _ = elaborate(sys, verilog=False)
    raw = utils.run_simulator(simulator_path)
    print(raw)

if __name__ == "__main__":
    test_counter()
```

### 示例 2: 带条件的计数器

```python
from assassyn.frontend import *
from assassyn.backend import elaborate
from assassyn import utils

class ConditionalCounter(Module):
    def __init__(self):
        super().__init__(ports={})
    
    @module.combinational
    def build(self):
        # 定义计数器和标志
        cnt = RegArray(UInt(32), 1)
        done = RegArray(Bits(1), 1)
        
        # 只在未完成时计数
        with Condition(done[0] == Bits(1)(0)):
            new_cnt = cnt[0] + UInt(32)(1)
            (cnt & self)[0] <= new_cnt
            
            # 达到100时设置完成标志
            with Condition(new_cnt >= UInt(32)(100)):
                (done & self)[0] <= Bits(1)(1)
                log("计数完成！")
            
            log("计数中: {}", cnt[0])

def test_conditional():
    sys = SysBuilder('conditional')
    with sys:
        counter = ConditionalCounter()
        counter.build()
    
    simulator_path, _ = elaborate(sys, verilog=False)
    raw = utils.run_simulator(simulator_path)
    print(raw)

if __name__ == "__main__":
    test_conditional()
```

### 示例 3: 模块间通信

```python
from assassyn.frontend import *
from assassyn.backend import elaborate
from assassyn import utils

class DataProcessor(Module):
    """数据处理模块"""
    def __init__(self):
        super().__init__(ports={
            'data': Port(UInt(32))
        })
    
    @module.combinational
    def build(self):
        data = self.pop_all_ports(True)
        
        # 数据翻倍
        result = data * UInt(32)(2)
        log("处理数据: {} -> {}", data, result)

class Driver(Module):
    """驱动模块"""
    def __init__(self):
        super().__init__(ports={})
    
    @module.combinational
    def build(self, processor: DataProcessor):
        # 定义计数器
        cnt = RegArray(UInt(32), 1)
        (cnt & self)[0] <= cnt[0] + UInt(32)(1)
        
        # 每个周期发送数据给处理器
        processor.async_called(data=cnt[0])
        log("发送数据: {}", cnt[0])

def test_communication():
    sys = SysBuilder('communication')
    with sys:
        processor = DataProcessor()
        driver = Driver()
        
        processor.build()
        driver.build(processor)
    
    simulator_path, _ = elaborate(sys, verilog=False)
    raw = utils.run_simulator(simulator_path)
    print(raw)

if __name__ == "__main__":
    test_communication()
```

### 示例 4: 使用 SRAM

```python
from assassyn.frontend import *
from assassyn.backend import elaborate
from assassyn import utils

class SRAMReader(Module):
    """SRAM 读取模块"""
    def __init__(self):
        super().__init__(ports={
            'rdata': Port(Bits(32))
        })
    
    @module.combinational
    def build(self):
        rdata = self.pop_all_ports(False)
        log("读取数据: {}", rdata)

class SRAMDriver(Module):
    """SRAM 驱动模块"""
    def __init__(self):
        super().__init__(ports={})
    
    @module.combinational
    def build(self, sram, reader: SRAMReader):
        cnt = RegArray(UInt(32), 1)
        (cnt & self)[0] <= cnt[0] + UInt(32)(1)
        
        # 地址
        addr = (cnt[0] & UInt(32)(7)).bitcast(Int(9))
        
        # 前8个周期写入，后面读取
        we = (cnt[0] < UInt(32)(8)).bitcast(Bits(1))
        re = (cnt[0] >= UInt(32)(8)).bitcast(Bits(1))
        
        # 写入数据
        wdata = (cnt[0] * UInt(32)(10)).bitcast(Bits(32))
        
        # 调用 SRAM
        sram.build(we=we, re=re, addr=addr, wdata=wdata, user=reader)
        
        log("SRAM 操作: addr={}, we={}, re={}", addr, we, re)

def test_sram():
    sys = SysBuilder('sram_test')
    with sys:
        sram = SRAM(width=32, depth=16, init_file=None)
        reader = SRAMReader()
        driver = SRAMDriver()
        
        reader.build()
        driver.build(sram, reader)
        
        sys.expose_on_top(sram.dout)
    
    simulator_path, _ = elaborate(sys, verilog=False)
    raw = utils.run_simulator(simulator_path)
    print(raw)

if __name__ == "__main__":
    test_sram()
```

---

## 重要注意事项

### ✅ 正确做法

```python
# 1. 先计算，再更新
new_value = cnt[0] + UInt(32)(1)
(cnt & self)[0] <= new_value
result = new_value  # 使用计算的新值

# 2. 使用 with Condition
with Condition(enable == Bits(1)(1)):
    do_something()

# 3. 使用 pop_all_ports 读取端口
a, b = self.pop_all_ports(True)
```

### ❌ 错误做法

```python
# 1. 更新后立即读取（读到的还是旧值！）
(cnt & self)[0] <= cnt[0] + UInt(32)(1)
result = cnt[0]  # 错误！这是旧值

# 2. 使用 Python 的 if（不是硬件条件！）
if enable:  # 错误！
    do_something()

# 3. 直接访问端口
a = self.port_a  # 错误！
```

---

## 调试技巧

1. **使用日志**：在关键位置添加 `log()` 语句
   ```python
   log("当前状态: cnt={}, flag={}", cnt[0], flag[0])
   ```

2. **检查类型**：确保类型匹配
   ```python
   # 需要 Bits(1)，但可能有 UInt(1)
   bits_val = uint_val.bitcast(Bits(1))
   ```

3. **验证时序**：记住寄存器更新延迟一个周期
   ```python
   # 周期 N：cnt[0] = 5
   (cnt & self)[0] <= UInt(32)(10)
   # 周期 N：cnt[0] 还是 5
   # 周期 N+1：cnt[0] 变成 10
   ```

4. **简化测试**：从最简单的模块开始
   ```python
   # 先确保简单计数器工作
   # 再添加复杂逻辑
   ```

---

## 学习路径

1. **第一步**：运行并理解[示例 1: 简单计数器](#示例-1-简单计数器)
2. **第二步**：修改计数器，尝试不同的增量值
3. **第三步**：添加条件逻辑，参考[示例 2: 带条件的计数器](#示例-2-带条件的计数器)
4. **第四步**：学习模块通信，参考[示例 3: 模块间通信](#示例-3-模块间通信)
5. **第五步**：阅读 [`assassyn入门教程.md`](assassyn入门教程.md) 了解详细概念
6. **第六步**：查看 [`assassyn_example.py`](assassyn_example.py) 学习更多实例
7. **第七步**：开始编写自己的模块！

---

## 更多资源

- **详细教程**：[`assassyn入门教程.md`](assassyn入门教程.md) - 深入理解概念
- **完整文档**：[`assassyn_documentation.md`](assassyn_documentation.md) - API 参考
- **示例代码**：[`assassyn_example.py`](assassyn_example.py) - 实际应用
- **项目说明**：[`README.md`](README.md) - 项目概述

---

## 常见问题 (FAQ)

**Q: 为什么寄存器更新不立即生效？**  
A: 这是硬件的特性。硬件中寄存器在时钟边沿更新，模拟了真实硬件的行为。

**Q: 什么时候用 `UInt`，什么时候用 `Bits`？**  
A: `UInt` 用于数值计算，`Bits` 用于位操作。可以用 `.bitcast()` 互相转换。

**Q: `async_called` 是做什么的？**  
A: 用于模块间通信，调用会在下一个周期执行，类似于硬件中的信号传递。

**Q: 如何调试我的代码？**  
A: 使用 `log()` 打印关键变量，检查时序是否正确，确保类型匹配。

---

**开始你的 Assassyn 之旅吧！** 🚀

如有疑问，请参考详细教程或查看示例代码。
