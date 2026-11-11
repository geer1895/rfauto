// sample.v — Q-X47 Verilog 网表解析器测试夹具（结构子集全要素覆盖面）。
// 两模块：top（ANSI 2001 头内全声明）+ adder（1995 头列名+体内方向声明
// 混合形态）——门级原语/模块实例/assign/parameter/defparam/编译器指令/
// 行为块跳过盲区/孤立网两桶/树深度链全在此钉。
`timescale 1ns / 1ps
`default_nettype none

// ── top：ANSI 2001 形态（头内方向+范围全声明）────────────────────────────
module top (
    input  wire       clk,
    input  wire [3:0] d,
    output wire [3:0] q,
    output wire       co
);
  parameter W = 4;
  localparam HALF = W / 2;

  wire [3:0] n1, n2;          // 内部两级网
  wire        carry_orphan;   // 孤立网钉：有驱动无读者（unloaded）
  wire        floating_net;   // 孤立网钉：无驱动无读者（undriven+unloaded）
  reg  [3:0]  r_q;            // reg 类网（行为驱动盲区，不判 undriven）

  // 外部单元库实例（类型未在本文件定义→拓扑外部边界豁免面）
  adder u_add (
      .a   (d),
      .b   (n1),
      .s   (n2),
      .cout(co)
  );

  // 门级原语：位置连接→注册表命名归一（out/in1..inN/ctrl）
  and  g1 (carry_orphan, d[0], d[1]);     // 2 输入与门
  not  g2 (n1[0], d[2]);                  // 反相器（单出单入）
  buf  b1 (q[0], q[1], n2[0]);            // 多输出缓冲（out1/out2/in）
  xor  x1 (q[2], n2[1], d[3]);            // 异或门
  bufif1 tri1 (n2[2], n2[3], clk);        // 三态缓冲（out/in/ctrl）
  pullup pu (co);                          // 上拉（单输出）

  // 模块实例位置连接形态（连接序=子模块端口声明序，拓扑层对位；尾逗号
  // =末位 cout 未连接的宽容形态）
  wire [1:0] scratch;
  adder u_scratch (scratch, d[1:0], scratch, );

  // 连续赋值：位选拼接 lhs + 位宽字面量 rhs + #delay 形态
  assign #2 n1[3:1] = 3'b000;
  assign {q[3], q[0]} = {n2[3], n2[2]};

  // 行为块（结构解析整块跳过+warning 如实；r_q 的过程驱动不可见）
  always @(posedge clk) begin
    r_q <= n2;
  end

  // defparam：覆盖子模块参数（target/param/value 三元组钉）
  defparam u_add.W = 8;

endmodule

// ── adder：1995 混合形态（头列名+体内方向声明）+参数化位宽 ───────────────
module adder (a, b, s, cout);
  parameter W = 4;
  input [W-1:0] a, b;
  output [W-1:0] s;
  output cout;
  wire [W:0] full;

  assign full = a + b;
  assign s    = full[W-1:0];
  assign cout = full[W];
endmodule

// ── dff_cell：外部单元库引用的代表形态（无端口体+endmodule 即收）────────
module dff_cell (d, clk, q);
  input d, clk;
  output reg q;
endmodule
