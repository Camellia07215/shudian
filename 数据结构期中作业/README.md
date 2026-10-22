# dsh-digital-logic-expert

> 把「数字逻辑全流程智能助教」Skill 封装为 **DeepSeek Harness（dsh）** Cordis 插件：
> 在 dsh 对话里直接完成数字逻辑课程的**知识点问答 + 电路分析 → 设计 → 调优 → 验证 → 评估全流程闭环**。
> 适配教材：《数字逻辑（第七版·立体化教材）》（欧阳星明主编，华中科技大学出版社）。

## 这是什么

本仓库是一个 **dsh Cordis 插件**，它把 Skill `digital-logic-expert` 打包进 dsh。安装后，
当你在 dsh 中提出数字逻辑相关问题（化简、分析电路、设计表决器、排查冒险、写 Verilog 等），
dsh 会加载该 Skill，由 Agent 按 `SKILL.md` 的工作流编排调用**本地确定性引擎**完成计算，
再结合 `references/` 十章知识库输出讲解。

设计原则（与传统大模型"口算化简"划清界限）：

- 所有确定性计算（真值表、Quine-McCluskey 化简、卡诺图、冒险检测、等价验证、评分、
  Verilog 生成）在**本地纯 Python 引擎** `scripts/dlengine.py` 中运行，零依赖、结果可复现。
- 模型负责：多模态输入理解、意图路由、功能判定、知识点关联讲解；**不替引擎做算术**。
- 每个计算结果回链教材章节，实现"结果 ↔ 知识点"双向对应。

## 覆盖知识点（对应教材全部章节）

| references/ 文件 | 内容 |
|---|---|
| 01-number-systems-codes.md | 数制转换、原反补码、BCD/格雷码/奇偶校验 |
| 02-logic-algebra.md | 逻辑代数公理定理、德摩根、共识定理、卡诺图规则 |
| 03-gates.md | TTL/CMOS 门电路、OC门、三态门、接口 |
| 04-combinational-logic.md | 组合电路分析/设计、典型电路特征表、**竞争冒险** |
| 05-flipflops.md | RS/D/JK/T 触发器、特性方程、触发方式、波形 |
| 06-sequential-logic.md | 时序分析、74161 任意模计数器、状态机设计、自启动 |
| 07-verilog-hdl.md | Verilog 三种建模、可综合规则、三段式 FSM、testbench |
| 08-memory.md | SRAM/DRAM/ROM/Flash、容量扩展、ROM 实现逻辑 |
| 09-pld.md | PLA/PAL/GAL/CPLD/FPGA 对比与选型 |
| 10-controller.md | ASM 图、小型控制器、微程序控制、设计实例 |

## 能力层级（对应课程考核）

| 考核层级 | 本插件对应能力 |
|---|---|
| 基础（≈60） | 十章知识库问答、例题解析 |
| 进阶（≈70） | 零代码分析：表达式/电路图 → 真值表、卡诺图、最简式、功能判定 |
| 高阶（≈80） | 多模态工作流：图片/文字需求 → 自动设计（三方案 + Verilog + testbench） |
| **顶尖（90+）** | **全流程闭环：自动调优（冒险检测+冗余项消除）+ 自动验证（全覆盖等价比对）+ 三维评估（成本/复杂度/可靠性评分）** |

## 安装到 dsh

```bash
dsh plugin add github:<你的用户名>/dsh-digital-logic-expert
```

该命令会把插件加入当前 profile 的 `package.json`（`dependencies` + `dsh.profile.bundles`）。
重启 `dsh web` 后即可在对话中使用。

> 手动安装：把 `"dsh-digital-logic-expert": "github:<你的用户名>/dsh-digital-logic-expert"`
> 同时加入 profile 的 `dependencies` 与 `dsh.profile.bundles`，再重新安装依赖。

## 在 dsh 中怎么用

自然语言即可，例如：

- "什么是格雷码？8421BCD 和余 3 码有什么区别？"（知识问答）
- "分析 F = AB + A'C，给出真值表、卡诺图和最简式"（自动分析）
- "设计一个三人多数表决器，给我 Verilog 和 testbench"（自动设计）
- "F = AB + A'C 有冒险吗？给出消险方案并验证改进前后等价"（调优 + 验证闭环）
- "用 74161 设计一个模 24 计数器"（时序设计，知识库引导）

## 仓库结构

```
lib/index.js        # dsh 插件入口：递归发现 skills/ 下 SKILL.md，ctx.skills.registerProvider 注册
skills/
  digital-logic-expert/
    SKILL.md        # 技能主入口：触发词、路由、六模块全流程工作流、红线
    references/     # 十章知识库（对应教材全部章节）
    scripts/
      dlengine.py   # 本地确定性引擎（Python 3.8+，零第三方依赖）
    examples/       # 3 个递进式演示案例（课堂演示脚本）
cordis.patch.yml    # dsh bundle 注册描述（id: digital-logic-expert）
package.json
_selftest.mjs       # 契约自测
docs/开发报告.md     # 课程大作业开发报告
```

## 引擎 CLI 参考

```bash
python scripts/dlengine.py analyze  --expr "F = AB + A'C"          # 真值表/卡诺图/化简/冒险
python scripts/dlengine.py design   --vars A,B,C --minterms 3,5,6,7 --module voter3 [--dontcares 0,2]
python scripts/dlengine.py hazard   --expr "AB + A'C"              # 冒险检测 + 冗余项消除
python scripts/dlengine.py verify   --expr1 "AB+A'C" --expr2 "AB+A'C+BC"   # 全覆盖等价验证
python scripts/dlengine.py evaluate --expr "AB+A'C"                # 三维评分（JSON）
```

表达式语法：单个大写变量；`'`/`~` 取反，并置或 `*` 为与，`+` 为或，`^` 为异或，支持括号。

## 开发 / 自测

```bash
node _selftest.mjs     # 用 mock ctx.skills 验证「发现 SKILL.md + get() 返回正文」契约
python skills/digital-logic-expert/scripts/dlengine.py analyze --expr "F=AB+A'C"  # 引擎冒烟
```

## 演示案例

`examples/` 内置 3 个递进式演示脚本：基础电路分析（进阶层）→ 表决器多方案设计（高阶层）→
冒险调优与验证评估（顶尖层），可直接用于课堂演示。

## 许可证

MIT
