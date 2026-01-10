# Assassyn RV32IM CPU Project

五级流水线 RISC-V RV32IM CPU 实现，包含完整的乘法和除法扩展支持。

## 📁 项目结构 (Project Structure)

```
assassyn/
├── src/                      # 源代码 (Source Code)
│   ├── rv32i_cpu.py         # 主CPU实现 (82KB) - RV32IM with BTB, Mul, Div
│   └── rv32i_cpu_backup.py  # CPU备份文件 (44KB)
│
├── tests/                    # 测试文件 (Tests)
│   ├── test_rv32i.py        # RV32I测试套件
│   ├── test_rv32i_adapter.py
│   ├── test.py
│   ├── test_downstream.py
│   ├── array_increment.py   # 示例: 数组递增
│   └── simple_counter.py    # 示例: 简单计数器
│
├── benchmarks/              # 基准测试 (Benchmarks)
│   └── self_test/          # 自测试程序
│       ├── mul.c, mul.hex  # 乘法测试
│       ├── div.c, div.hex  # 除法测试
│       ├── mod.c, mod.hex  # 取模测试
│       ├── fac.c, fac.hex  # 阶乘测试
│       └── t1.c, t2.c, t3.c # 其他测试
│
├── utils/                   # 工具脚本 (Utilities)
│   ├── gen_hex.py          # 生成hex文件
│   ├── process_hex.py      # 处理hex文件
│   ├── update_hex_files.py # 更新hex文件
│   └── run_benchmark.py    # 运行基准测试
│
├── docs/                    # 文档 (Documentation)
│   ├── AGENTS.md           # Agent文档 (24KB)
│   └── my_doc/             # 额外文档
│       ├── DIVIDER_ARCHITECTURE.md      # 除法器架构
│       ├── branch_prediction_rules.md   # 分支预测规则
│       ├── bypass_rules.md              # 旁路规则
│       └── assassyn语言与编码规范.md    # 编码规范
│
├── output/                  # 输出文件 (Output Files)
│   ├── data.hex            # 数据内存文件
│   ├── result.out          # 测试结果 (2.3MB)
│   └── test_program.txt    # 测试程序
│
├── backup/                  # 备份 (Backups)
│   └── backup_with_new_comments/  # 带有[NEW]注释的版本
│       ├── rv32i_cpu.py    # 标注了新增功能的版本
│       └── changes.patch   # 完整的差异补丁
│
├── riscv-gnu-toolchain/    # RISC-V工具链
├── assassyn.sif            # Apptainer镜像文件 (3.1GB)
└── README.md               # 本文件
```

## 🎯 主要特性 (Key Features)

### ✅ 已实现的指令扩展
1. **RV32I Base Integer ISA**
   - 所有基础整数指令

2. **RV32M 乘法扩展**
   - MUL, MULH, MULHSU, MULHU
   - 使用Wallace Tree 3周期流水线乘法器

3. **RV32M 除法扩展**
   - DIV, DIVU (有符号/无符号除法)
   - REM, REMU (有符号/无符号取模)
   - 使用Radix-4 SRT 18周期除法器

4. **动态分支预测**
   - BTB (Branch Target Buffer): 64条目
   - BHT (Branch History Table): 2-bit饱和计数器
   - 支持分支目标预测和方向预测

## 🚀 快速开始 (Quick Start)

### 运行测试
```bash
cd tests
python test_rv32i.py
```

### 运行基准测试
```bash
cd benchmarks
python ../utils/run_benchmark.py
```

### 生成Hex文件
```bash
python utils/gen_hex.py your_program.c
```

## 📊 性能指标

- **流水线级数**: 5级 (IF, ID, EX, MEM, WB)
- **乘法延迟**: 3周期
- **除法延迟**: 18周期
- **分支预测**: BTB + 2-bit饱和计数器

## 📝 更新历史

- **2026-01-09**: 从 bojuzhang/assassyn 合并最新版本
  - 新增 DIV/MOD 指令支持
  - 新增 Radix-4 SRT 除法器
  - 完整的测试套件和文档

## 🔗 相关链接

- GitHub: https://github.com/bojuzhang/assassyn
- 分支预测规则: see `docs/my_doc/branch_prediction_rules.md`
- 除法器架构: see `docs/my_doc/DIVIDER_ARCHITECTURE.md`

## 💡 注意事项

- `assassyn.sif` (3.1GB) 是Apptainer容器镜像，用于隔离的构建环境
- `riscv-gnu-toolchain/` 包含完整的RISC-V交叉编译工具链
- `backup/backup_with_new_comments/` 包含了带有详细[NEW]注释的旧版本，便于理解新增功能
