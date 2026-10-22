# 第7章 Verilog HDL

## 7.1 模块基本结构

```verilog
module 模块名(端口列表);
    input  a, b;          // 输入声明
    output f;             // 输出声明
    wire   t;             // 内部连线
    assign f = a & b;     // 功能描述
endmodule
```

- 标识符区分大小写；注释 `//` 与 `/* */`；数制表示 `4'b1010`、`8'hF0`、`10'd255`。
- 数据类型：**wire**（连线，assign 驱动）、**reg**（在 always/initial 块中赋值）、integer、parameter。

## 7.2 三种建模层次

| 层次 | 方法 | 例 |
|---|---|---|
| 结构（门级） | 调用门原语/子模块 | `and g1(f,a,b);` |
| 数据流 | assign 连续赋值 | `assign f = a & b \| ~c;` |
| 行为级 | always 过程块 | 见下 |

## 7.3 行为建模核心规则（可综合）

```verilog
// 组合逻辑：电平敏感，敏感表写全（或用 @*）
always @(*) begin
    if (sel) f = a; else f = b;   // 必须给所有分支赋值，否则推导出锁存器
end

// 时序逻辑：边沿敏感，非阻塞赋值 <=
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) q <= 1'b0;        // 异步复位
    else        q <= d;
end
```

**黄金规则**：
1. 组合逻辑用**阻塞赋值 `=`**，时序逻辑用**非阻塞赋值 `<=`**；
2. 同一变量只能在一个 always 块中赋值；
3. case 语句写 default，if 写 else，避免意外锁存；
4. 组合 always 敏感表用 `@(*)`，时序用 `@(posedge clk)`。

## 7.4 状态机（FSM）标准模板（三段式）

```verilog
parameter S0=2'b00, S1=2'b01, S2=2'b10;
reg [1:0] cur, nxt;
// 段1：状态寄存器
always @(posedge clk or negedge rst_n)
    if (!rst_n) cur <= S0; else cur <= nxt;
// 段2：次态组合逻辑
always @(*)
    case (cur)
        S0: nxt = in ? S1 : S0;
        S1: nxt = in ? S2 : S1;
        S2: nxt = in ? S0 : S2;
        default: nxt = S0;
    endcase
// 段3：输出逻辑
assign out = (cur == S2) & in;   // Mealy；去掉 &in 即 Moore
```

## 7.5 Testbench 模板

```verilog
`timescale 1ns/1ps
module tb_xxx;
    reg clk, rst_n;  reg  [...] 输入;  wire [...] 输出;
    xxx dut(...);                    // 例化被测模块
    initial begin clk = 0; forever #5 clk = ~clk; end   // 10ns 时钟
    initial begin
        rst_n = 0; #12 rst_n = 1;
        // 激励 + $display/$monitor 检查
        #100 $finish;
    end
endmodule
```

- `$display("fmt", vars)`、`$monitor` 自动跟踪、`$finish` 结束。
- 引擎 `design` 自动生成可综合模块 + 全覆盖 testbench（枚举全部输入组合）。

## 7.6 常见考点
1. 阻塞/非阻塞赋值差异（= 立即更新，<= 块末统一更新）；2. 锁存器推导条件；3. 三段式状态机；4. assign 只能驱动 wire；always 中只能赋值 reg；5. 全加器/计数器/译码器的 Verilog 描述。
