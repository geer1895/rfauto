# =========================================================================
# SDC 样例约束文件（tests/unit/fixtures/sdc/sample.sdc）
# aurora_q Q-X36 席位测试夹具——数模混合 RF 上下文（演示值，非真实设计）：
#   1. 变量定义与 $ 替换（set clk_period / ${io_ref_clk} 引用）；
#   2. 主时钟x2（-name 显式 + 无名自动派生 auto_named；-waveform；
#      多 pattern 源 {clk_p, clk_n} 逗号形）；
#   3. 生成时钟x2（-divide_by / -multiply_by+master_clock；行连续）；
#   4. 时钟网络约束（set_clock_latency -source/-late 与
#      set_clock_uncertainty -setup）；
#   5. IO 延迟（input min/max 成对 + 无旗标双边形 + output 成对）；
#   6. 路径例外（false_path from/to、multicycle -setup/-end from/to、
#      max_delay、min_delay -through 三点）；
#   7. 负载/驱动/扇出/案例分析（set_load 两形态、set_driving_cell
#      -lib_cell+-pin、set_fanout_load、set_case_analysis 0/1）；
#   8. Tcl 词法面：行注释、;# 行尾注释、花括号列表、行连续反斜杠、
#      顶层独立 get_ports 命令、面外命令（current_design）走 warnings。
# 数字为夹具演示值（非任何真实设计），仅供结构化断言。
# =========================================================================

set clk_period 10.0
set io_ref_clk sys_clk

# ---- 时钟定义 -----------------------------------------------------------
create_clock -name sys_clk -period $clk_period -waveform {0.0 5.0} [get_ports {clk_p, clk_n}]

# 无名时钟：名字从源对象首 pattern 派生（auto_named=true）
create_clock -period 25.0 [get_ports ref_in]

create_generated_clock -name div2_clk -divide_by 2 \
  -source [get_ports clk_p] [get_ports {div2_out}]
create_generated_clock -name x2_clk -multiply_by 2 -master_clock sys_clk \
  [get_ports {pll_out}]

# ---- 时钟网络 -----------------------------------------------------------
set_clock_latency -source -late 0.35 [get_clocks {sys_clk, div2_clk}]
set_clock_uncertainty -setup 0.12 [get_clocks {sys_clk}]

# ---- IO 延迟 ------------------------------------------------------------
set_input_delay -clock sys_clk -max 3.2 [get_ports {rf_in}]
set_input_delay -clock sys_clk -min 1.1 [get_ports {rf_in}]
set_input_delay 2.4 -clock ${io_ref_clk} [get_ports {data_bus}]
set_output_delay -max 1.8 [get_ports {rf_out}]
set_output_delay -min 0.6 [get_ports {rf_out}]

# ---- 路径例外 -----------------------------------------------------------
set_false_path -from [get_ports async_rst] -to [get_cells {rst_sync*}]
set_multicycle_path -setup 3 -end -from [get_pins prescaler/Q] -to [get_pins {capture/D}]
set_max_delay 6.5 -from [get_cells {u_pll}] -to [get_ports {rf_out}]
set_min_delay 0.8 -from [get_ports {rf_in}] -through [get_cells {u_amp}] -to [get_ports {rf_out}]

# ---- 负载与驱动 ---------------------------------------------------------
set_load -capacitance 0.08 [get_nets {ant_net, mixer_out}]
set_load -pin_count 4 [get_nets bus_internal]
set_driving_cell -lib_cell BUFX4 -pin Z [get_ports {data_bus}]
set_fanout_load 3 [get_ports {test_en}]
set_case_analysis 1 [get_ports {band_sel0}]
set_case_analysis 0 [get_ports {band_sel1}]

# ---- 顶层独立访问器 + 面外命令 -------------------------------------------
get_ports {aux_pad, cal_pad}
current_design rf_top_demo ;# 面外命令：进 warnings 如实披露
