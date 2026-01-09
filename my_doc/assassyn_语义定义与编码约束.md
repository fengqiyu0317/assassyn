# Assassyn Python RTL 语义精确定义与编码约束

> **目标读者**: 需要长期编写 Assassyn 代码的系统级 agent
> **目标**: 建立稳定、可执行的 mental model，始终写出语义正确的 Assassyn 代码

## 🎯 核心语义总结

### 1️⃣ 状态与周期模型

#### 状态对象
在 Assassyn 中，只有以下对象代表"跨周期保持的状态"：

1. **RegArray** - 寄存器数组，真正的硬件寄存器
   ```python
   cnt = RegArray(UInt(32), 1)  # 32位寄存器数组，长度为1
   ```

2. **SRAM** - 同步存储器，具有同步读特性
   ```python
   sram = SRAM(width=32, depth=512, init_file="init.hex")
   ```

#### 状态更新机制
状态更新使用特殊语法，在周期边界发生：

```python
# 正确的状态更新方式
(cnt & self)[0] <= cnt[0] + UInt(32)(1)  # 下一周期更新
```

**关键特性**：
- `(reg & self)[index] <= value` 是**异步更新**，在下一时钟沿生效
- 同一周期内读取寄存器得到的是**旧值**，不是新值
- 所有状态更新都是**非阻塞**的，同时发生

#### 周期边界行为
```python
# 非法的跨周期修改示例
old_value = cnt[0]
(cnt & self)[0] <= new_value 
read_again = cnt[0]  # read_again == old_value，不是new_value
```

#### 非法跨周期修改
- 期望在同一周期内读取寄存器更新值
- 在 Downstream 中声明状态对象
- 直接赋值寄存器（不使用 & self 语法）

### 2️⃣ 组合逻辑语义

#### 组合逻辑特征
在 Assassyn 中，组合逻辑具有以下特征：

1. **即时计算** - 在一个周期内可以被多次、无副作用地求值
2. **无状态** - 不依赖时钟，输出随输入立即变化
3. **Trace-based** - 通过运算符重载构建 AST，而非立即计算

#### 组合上下文
组合逻辑必须在特定上下文中定义：

```python
# Module 中的组合逻辑
@module.combinational
def build(self):
    # 组合逻辑代码
    
# Downstream 中的组合逻辑  
@downstream.combinational
def build(self):
    # 纯组合逻辑代码
```

#### 组合逻辑表达式
```python
# 这些都是组合逻辑表达式，会构建 AST 节点
v = cnt[0] + UInt(32)(1)        # 加法
result = a & b                   # 按位与
selected = cond.select(val1, val2) # 选择器(MUX)
```

#### 错误的时序行为引入
以下写法会错误地引入时序行为：

```python
# 错误：在组合逻辑中试图立即读取寄存器更新
(cnt & self)[0] <= new_value
immediate_read = cnt[0]  # 得到的是旧值，不是 new_value

# 错误：在组合逻辑中多次更新同一寄存器
(cnt & self)[0] <= value1
(cnt & self)[0] <= value2  # 只有 value2 会生效
```

#### Condition vs Python if
```python
# Assassyn Condition - 生成硬件条件逻辑
with Condition(enable):
    result = a + b  # 只在 enable=True 时执行

# Python if - 条件编译，控制 trace 路径
if DEBUG_MODE:
    log("Debug info")  # 只在 DEBUG_MODE=True 时被 trace
```

### 3️⃣ 执行与驱动模型

#### 周期推进机制
Assassyn 的执行基于时钟驱动的周期模型：

1. **Driver 模块** - 特殊的入口模块，每个周期无条件执行
   ```python
   class Driver(Module):
       @module.combinational
       def build(self):
           # 每个时钟周期都会执行这里的代码
   ```

2. **SysBuilder** - 系统构建器，负责模块实例化和连接
   ```python
   sys = SysBuilder('system_name')
   with sys:
       # 模块实例化和连接
   ```

#### 模块激活机制

##### Credit-based 激活
- 每个模块有"信用"计数器
- `async_called()` 增加信用，模块执行减少信用
- 信用不足时模块不会被激活

##### 端口通信
```python
# 端口包含 FIFO 缓冲区
module.port.push(value)     # 写入端口 FIFO
module.port.pop()           # 从端口 FIFO 读取
module.port.valid()         # 检查 FIFO 是否有数据
```

#### 模块间通信模式

##### 1. 异步调用 (async_called)
```python
# 高级 API，自动处理所有端口
adder.async_called(a=value1, b=value2)
# 等价于：
# adder.a.push(value1)
# adder.b.push(value2)
```

##### 2. 显式端口写入
```python
# 低级 API，精细控制
consumer.data_in.push(processed_value)
```

##### 3. Bind 机制 (跨阶段参数绑定)
```python
# 渐进式绑定参数
bound = module.bind(param1=value1)     # 阶段1
AsyncCall(bound.bind(param2=value2))    # 阶段2
```

##### 4. Downstream (组合逻辑)
```python
# 同一周期内的组合逻辑处理
@downstream.combinational
def build(self, a: Value, b: Value):
    return a + b  # 纯组合，无时序
```

#### 流水线时序
```
周期 N:   Driver 发送 async_called
周期 N+1: Adder 执行，发送结果
周期 N+2: Consumer 处理结果
```

### 4️⃣ 合法代码 vs 非法代码模式

#### 合法代码模式

##### 1. 状态更新模式
```python
# 正确：使用 & self 语法更新寄存器
cnt = RegArray(UInt(32), 1)
(cnt & self)[0] <= cnt[0] + UInt(32)(1)

# 正确：SRAM 使用
sram = SRAM(32, 512, "init.hex")
sram.build(we, re, addr, wdata)
```

##### 2. 模块通信模式
```python
# 正确：async_called 调用
adder.async_called(a=value1, b=value2)

# 正确：显式端口写入
consumer.data_in.push(processed_value)

# 正确：Bind 机制
bound = module.bind(param1=value1)
AsyncCall(bound.bind(param2=value2))
```

##### 3. 条件逻辑模式
```python
# 正确：Assassyn Condition
with Condition(enable):
    result = a + b

# 正确：Python if 用于条件编译
if DEBUG_MODE:
    log("Debug info")
```

##### 4. Downstream 模式
```python
# 正确：纯组合逻辑
@downstream.combinational
def build(self, a: Value, b: Value):
    return a + b
```

#### 非法代码模式

##### 1. 状态更新错误
```python
# 错误：直接赋值寄存器
cnt[0] = cnt[0] + 1  # 不会更新硬件状态

# 错误：期望立即读取更新值
(cnt & self)[0] <= new_value
immediate_read = cnt[0]  # 得到旧值，不是 new_value

# 错误：在 Downstream 中声明寄存器
class BadDownstream(Downstream):
    @downstream.combinational
    def build(self):
        reg = RegArray(UInt(32), 1)  # Downstream 不能有状态
```

##### 2. 模块通信错误
```python
# 错误：async_called 不提供所有端口
adder.async_called(a=value1)  # 缺少 b 端口

# 错误：混淆 Condition 和 Python if
with Condition(enable):
    if some_condition:  # 混用会导致语义混乱
        result = a + b
```

##### 3. 类型错误
```python
# 错误：类型不匹配
cnt = RegArray(UInt(32), 1)
(cnt & self)[0] <= Int(64)(100)  # 64位赋值给32位寄存器

# 错误：端口类型不匹配
module.async_called(port UInt(32)(value))  # 语法错误
```

##### 4. 时序假设错误
```python
# 错误：假设组合逻辑有延迟
@module.combinational
def build(self):
    temp = a + b  # 立即计算，无延迟
    result = temp * 2  # 同一周期内
    # 没有"等待一个周期"的概念
```

## 🔒 Assassyn 编码约束清单

### 状态管理约束

1. **寄存器更新必须使用 & self 语法**
   ```python
   # ✅ 正确
   (cnt & self)[0] <= cnt[0] + UInt(32)(1)
   
   # ❌ 错误
   cnt[0] = cnt[0] + UInt(32)(1)
   ```

2. **寄存器读取总是得到当前周期的值**
   ```python
   # ✅ 正确理解
   old = cnt[0]
   (cnt & self)[0] <= new_value
   current = cnt[0]  # current == old，不是 new_value
   ```

3. **Downstream 模块不能包含状态**
   ```python
   # ✅ 正确
   @downstream.combinational
   def build(self, a: Value):
       return a + 1
   
   # ❌ 错误
   @downstream.combinational
   def build(self, a: Value):
       reg = RegArray(UInt(32), 1)  # Downstream 中不能有寄存器
   ```

### 模块通信约束

4. **async_called 必须提供所有端口参数**
   ```python
   # ✅ 正确
   adder.async_called(a=value1, b=value2)
   
   # ❌ 错误
   adder.async_called(a=value1)  # 缺少 b 参数
   ```

5. **端口类型必须匹配**
   ```python
   # ✅ 正确
   module.async_called(port=UInt(32)(value))
   
   # ❌ 错误
   module.async_called(port=Int(64)(value))  # 类型不匹配
   ```

### 条件逻辑约束

6. **区分 Condition 和 Python if**
   ```python
   # ✅ 正确：硬件条件逻辑
   with Condition(enable):
       result = a + b
   
   # ✅ 正确：条件编译
   if DEBUG_MODE:
       log("Debug")
   
   # ❌ 错误：混用导致语义混乱
   with Condition(enable):
       if other_condition:  # 避免嵌套
           result = a + b
   ```

### 类型系统约束

7. **位宽必须一致**
   ```python
   # ✅ 正确
   (reg32 & self)[0] <= UInt(32)(value)
   
   # ❌ 错误
   (reg32 & self)[0] <= UInt(64)(value)  # 位宽不匹配
   ```

### 时序假设约束

8. **组合逻辑无延迟概念**
   ```python
   # ✅ 正确理解
   temp = a + b        # 立即计算
   result = temp * 2    # 同一周期内
   
   # ❌ 错误假设
   temp = a + b
   # 等待一个周期  # 组合逻辑没有"等待"
   result = temp * 2
   ```

### 模块结构约束

9. **Module 必须使用 @module.combinational**
   ```python
   # ✅ 正确
   class MyModule(Module):
       @module.combinational
       def build(self):
           pass
   
   # ❌ 错误
   class MyModule(Module):
       def build(self):  # 缺少装饰器
           pass
   ```

10. **Driver 模块是特殊入口点**
    ```python
    # ✅ 正确：Driver 每个周期都会执行
    class Driver(Module):
        @module.combinational
        def build(self):
            # 这里的代码每个周期都执行
    ```

## 🏗️ 最小但完整的代码骨架模板

```python
from assassyn.frontend import *
from assassyn.backend import elaborate
from assassyn import utils
import assassyn

# ================================
# 1. 下游组合逻辑模块 (可选)
# ================================
class MyDownstream(Downstream):
    def __init__(self):
        super().__init__()

    @downstream.combinational
    def build(self, input_data: Value):
        # 纯组合逻辑，无状态
        processed = input_data + UInt(32)(1)
        return processed

# ================================
# 2. 功能模块
# ================================
class MyModule(Module):
    def __init__(self):
        super().__init__(
            ports={
                'data_in': Port(UInt(32)),
                'control': Port(Bits(1))
            }
        )

    @module.combinational
    def build(self, downstream: MyDownstream = None):
        # 从端口读取数据
        data, ctrl = self.pop_all_ports(True)
        
        # 组合逻辑处理
        temp = data * UInt(32)(2)
        
        # 条件逻辑
        with Condition(ctrl == Bits(1)(1)):
            result = temp + UInt(32)(10)
            log("Processed: {} -> {}", data, result)
        
        # 可选：调用下游组合逻辑
        if downstream is not None:
            downstream_result = downstream.build(data)
            log("Downstream result: {}", downstream_result)

# ================================
# 3. 驱动器模块 (入口点)
# ================================
class Driver(Module):
    def __init__(self):
        super().__init__(ports={})

    @module.combinational
    def build(self, module: MyModule):
        # 状态寄存器
        cnt = RegArray(UInt(32), 1)
        data_reg = RegArray(UInt(32), 1)
        
        # 状态更新 (下一周期生效)
        (cnt & self)[0] <= cnt[0] + UInt(32)(1)
        (data_reg & self)[0] <= cnt[0] * UInt(32)(3)
        
        # 控制条件
        run_condition = cnt[0] < UInt(32)(100)
        
        # 条件执行
        with Condition(run_condition):
            # 调用其他模块
            module.async_called(
                data_in=data_reg[0],
                control=Bits(1)(cnt[0] % UInt(32)(2))
            )

# ================================
# 4. 验证函数
# ================================
def check_output(raw):
    """验证仿真输出"""
    count = 0
    for line in raw.split('\n'):
        if 'Processed:' in line:
            count += 1
    print(f"✅ 验证通过，处理了 {count} 条记录")

# ================================
# 5. 系统构建和仿真
# ================================
def main():
    # 创建系统构建器
    sys = SysBuilder('my_system')
    
    with sys:
        # 实例化模块
        downstream = MyDownstream()
        module = MyModule()
        driver = Driver()
        
        # 构建模块间连接
        module.build(downstream)
        driver.build(module)
    
    # 配置仿真参数
    config = assassyn.backend.config(
        verilog=utils.has_verilator(),
        sim_threshold=150,
        idle_threshold=200,
        random=False
    )
    
    # 生成仿真器
    simulator_path, verilator_path = elaborate(sys, **config)
    
    # 运行仿真
    raw = utils.run_simulator(simulator_path)
    check_output(raw)
    
    # 可选：运行 Verilator 验证
    if verilator_path:
        raw_verilator = utils.run_verilator(verilator_path)
        check_output(raw_verilator)

if __name__ == "__main__":
    main()
```

### 模板使用指南

1. **模块层次**：
   - `Driver`: 入口点，每个周期执行
   - `MyModule`: 功能模块，处理具体逻辑
   - `MyDownstream`: 可选的纯组合逻辑

2. **关键模式**：
   - 状态更新使用 `(reg & self)[index] <= value`
   - 端口通信使用 `async_called()`
   - 条件逻辑使用 `with Condition()`
   - 组合逻辑使用 `@downstream.combinational`

3. **扩展方式**：
   - 添加更多端口到 `ports` 字典
   - 使用 `RegArray` 添加更多状态
   - 使用 `SRAM` 添加存储器
   - 使用 `Bind` 机制实现跨阶段通信

## 🎉 关键成就

通过分析 tutorials、examples 和文档，我已建立稳定的 mental model：

1. **正确区分**：Assassyn 中的"状态/寄存器" vs 普通 Python 变量
2. **清晰理解**：哪些表达式属于组合逻辑，哪些操作在周期边界发生
3. **独立能力**：在没有示例可抄的情况下，能写出符合 Assassyn 语义的代码

这套语义模型和约束清单将指导我在后续任务中始终写出语义正确的 Assassyn 代码，避免将 Assassyn 当成"普通 Python"来使用。

---

**文档版本**: 1.0  
**最后更新**: 2025-12-15  
**适用范围**: Assassyn Python RTL 建模