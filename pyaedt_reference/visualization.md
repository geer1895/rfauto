# PyAEDT Visualization Reference

> Comprehensive reference for PyAEDT visualization, post-processing, reporting, and data analysis APIs.
> Source: `ansys.aedt.core.visualization.*` — PyAEDT (Ansys AEDT Python API)

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [PostProcessorCommon](#postprocessorcommon)
3. [PostProcessorHFSS](#postprocessorhfss)
4. [SolutionData](#solutiondata)
5. [Standard Report Classes](#standard-report-classes)
6. [Field Report Classes](#field-report-classes)
7. [TouchstoneData](#touchstonedata)
8. [ReportPlotter](#reportplotter)
9. [ModelPlotter](#modelplotter)
10. [Reports Helper Class](#reports-helper-class)
11. [Important Constants](#constants)
12. [Usage Patterns](#usage-patterns)

---

## Architecture Overview

```
PostProcessorCommon          <- Base class (all tools)
  +-- PostProcessor3D        <- 3D tool enhancements
       +-- PostProcessorHFSS <- HFSS-specific methods
           +-- post_3dlayout <- 3D Layout sub-processor

Reports (reports_by_category)
  |-- Standard               <- Most report types (S-param, modal, terminal...)
  |-- Fields                 <- Field along polyline/point
  |-- FarField               <- Far-field radiation patterns
  |-- NearField              <- Near-field reports
  |-- AntennaParameters      <- Antenna parameter reports
  |-- Spectral               <- Spectrum/spectral analysis
  |-- EyeDiagram             <- Eye diagram
  |-- AMIEyeDiagram          <- Statistical eye (AMI)
  |-- AMIConturEyeDiagram    <- AMI contour eye
  |-- EMIReceiver            <- EMI receiver analysis
  +-- CircuitNetlistReport   <- Circuit netlist

SolutionData                 <- Data container returned by get_solution_data()
TouchstoneData               <- Touchstone (.sNp) file parser (skrf-based)
ReportPlotter                <- Matplotlib 2D/3D chart engine
ModelPlotter                 <- PyVista 3D model visualization
```

**Access pattern:**
```python
from ansys.aedt.core import Hfss
hfss = Hfss(...)
data = hfss.post.get_solution_data(...)     # Returns SolutionData
report = hfss.post.create_report(...)       # Returns report object
hfss.post.reports_by_category.standard(...) # Alternative report creation
```

---

## PostProcessorCommon

**Module:** `ansys.aedt.core.visualization.post.common`
**Class:** `PostProcessorCommon(PyAedtBase)`

Base class inherited by all design-specific post-processors. Accessed via `app.post`.

### Constructor

```python
PostProcessorCommon(app)
# app: FieldAnalysis3D - the parent AEDT application object
```

### Key Properties

| Property | Type | Description |
|----------|------|-------------|
| `plots` | `list` | All report objects in the active design |
| `available_report_types` | `list[str]` | Report types available for the current setup |
| `update_report_dynamically` | `bool` | Auto-update reports on design edits (get/set) |
| `all_report_names` | `list[str]` | Names of all reports in the design |
| `oreportsetup` | `object` | AEDT ReportSetup module handle |
| `post_solution_type` | `str` | Design solution type |
| `reports_by_category` | `Reports` | Helper for creating reports by category |

### Key Methods

#### get_solution_data

```python
def get_solution_data(
    self,
    expressions: str | list = None,        # e.g. "dB(S(1,1))"
    setup_sweep_name: str | None = None,    # "Setup1 : LastAdaptive"
    domain: str | None = None,              # "Sweep" or "Time"
    variations: dict | None = None,         # {"Freq": ["All"]}
    primary_sweep_variable: str | None = None,  # "Freq", "Time", "Theta"
    report_category: str | None = None,     # "Modal Solution Data", "Far Fields"
    context: str | dict | None = None,      # Far-field sphere, matrix, etc.
    subdesign_id: int | None = None,
    polyline_points: int = 1001,
    math_formula: str | None = None,
) -> SolutionData | bool
```

**Example:**
```python
data = hfss.post.get_solution_data("dB(S(1,1))", hfss.nominal_sweep)
```

#### create_report

```python
def create_report(
    self,
    expressions: str | list = None,
    setup_sweep_name: str = None,
    domain: str = "Sweep",
    variations: dict = None,
    primary_sweep_variable: str = None,
    secondary_sweep_variable: str = None,
    report_category: str = None,
    plot_type: str = "Rectangular Plot",
    context: str | dict = None,
    subdesign_id: int = None,
    polyline_points: int = 1001,
    plot_name: str = None,
    matplotlib: bool = False,
    show: bool = True,
    hide_legend: bool = False,
    snapshot_path: str = None,
    width: int = 800,
    height: int = 450,
) -> Standard | ReportPlotter | bool
```

**plot_type options:** `"Rectangular Plot"`, `"Smith Chart"`, `"Polar Plot"`, `"3D Polar Plot"`, `"3D Spherical Plot"`, `"Radiation Pattern"`, `"Rectangular Contour Plot"`, `"Data Table"`, `"Antenna Parameters"`

#### get_solution_data_per_variation

```python
def get_solution_data_per_variation(
    self,
    solution_type: str = "Far Fields",
    setup_sweep_name: str = "",
    context: str | dict = None,
    sweeps: dict = None,
    expressions: str | list = "",
) -> SolutionData | None
```

#### Query Available Quantities

```python
def available_quantities_categories(self, report_category=None, display_type=None,
    solution=None, context=None, is_siwave_dc=False) -> list

def available_report_quantities(self, report_category=None, display_type=None,
    solution=None, quantities_category=None, context=None,
    is_siwave_dc=False, differential_pairs=False) -> list

def available_report_solutions(self, report_category=None) -> list
def available_display_types(self, report_category=None) -> list[str]
def get_all_report_quantities(self, solution=None, context=None, is_siwave_dc=False) -> dict
```

#### Export Methods

```python
def export_report_to_file(self, output_dir, plot_name, extension,
    unique_file=False, uniform=False, start=None, end=None, step=None,
    use_trace_number_format=False) -> str

def export_report_to_csv(self, project_dir, plot_name, ...) -> str
def export_report_to_jpg(self, project_path, plot_name, width=800, height=450,
    image_format="jpg") -> bool
```

#### Report Management

```python
def delete_report(self, plot_name=None) -> bool
def rename_report(self, plot_name, new_name) -> bool
def copy_report_data(self, plot_name, paste=True) -> bool
def paste_report_data(self) -> bool
```

---

## PostProcessorHFSS

**Module:** `ansys.aedt.core.visualization.post.post_hfss`
**Class:** `PostProcessorHFSS(PostProcessor3D, PyAedtBase)`

HFSS-specific post-processing. Inherits all PostProcessorCommon and PostProcessor3D methods.

### Far Field Data

```python
def get_far_field_data(
    self,
    expressions: str = "GainTotal",
    setup_sweep_name: str = "",
    domain: str = "Infinite Sphere1",
    sweeps: dict = None,  # Default: {"Theta":["All"],"Phi":["All"],"Freq":["All"]}
) -> SolutionData
```

### Visual Ray Tracing (SBR / Creeping Wave)

```python
def create_sbr_plane_visual_ray_tracing(self, max_frequency="1GHz",
    ray_density=2, number_of_bounces=5, multi_bounce=False,
    incident_theta=0, incident_phi=0, is_vertical_polarization=False,
    shoot_filter_type="All Rays", ray_box=None) -> VRTFieldPlot

def create_sbr_point_visual_ray_tracing(self, max_frequency="1GHz",
    custom_location=None, ...) -> VRTFieldPlot

def create_creeping_plane_visual_ray_tracing(self, max_frequency="1GHz",
    ray_density=1, sample_density=10, ray_cutoff=40) -> VRTFieldPlot

def create_creeping_point_visual_ray_tracing(self, max_frequency="1GHz",
    custom_location=None) -> VRTFieldPlot
```

### Field Plot (3D Layout Layers)

```python
def create_fieldplot_layers(self, layers, quantity, setup=None,
    nets=None, plot_on_surface=True, intrinsics=None, name=None) -> FieldPlot

def create_fieldplot_layers_nets(self, layers_nets, quantity,
    setup=None, intrinsics=None, plot_on_surface=True, plot_name=None) -> FieldPlot
```

### Tuning

```python
def set_tuning_offset(self, setup: str, offsets: dict) -> bool
```

---

## SolutionData

**Module:** `ansys.aedt.core.visualization.post.solution_data`
**Class:** `SolutionData(PyAedtBase)`

Container for simulation solution data.

### Key Properties

| Property | Type | Description |
|----------|------|-------------|
| `expressions` | `list[str]` | Available expression names |
| `primary_sweep` | `str` | Primary sweep variable (e.g. "Freq") |
| `primary_sweep_values` | `np.array` | Values of primary sweep |
| `active_expression` | `str` | Currently active expression |
| `active_variation` | `dict` | Active design variation |
| `active_intrinsic` | `dict` | Active intrinsic values |
| `variations` | `list[dict]` | All design variations |
| `number_of_variations` | `int` | Count of variations |
| `intrinsics` | `dict` | Intrinsic sweep values |
| `units_sweeps` | `dict` | Sweep variable units |
| `units_data` | `dict` | Data expression units |
| `full_matrix_real_imag` | `tuple` | (real_dict, imag_dict) |
| `full_matrix_mag_phase` | `tuple` | (mag_dict, phase_dict) |
| `enable_pandas_output` | `bool` | Return pandas DataFrames |

### Key Methods

#### get_expression_data

```python
def get_expression_data(
    self,
    expression: str = None,
    formula: str = "real",  # "real","imag","mag","db10","db20",
                            # "phase","phaserad","phasedeg","magnitude"
    convert_to_SI: bool = False,
    use_quantity: bool = False,
    sweeps: list | str = None,
) -> tuple[np.ndarray, np.ndarray]
```

**Example:**
```python
freq, s11_db = data.get_expression_data("S(1,1)", formula="db20")
freq, s11_phase = data.get_expression_data("S(1,1)", formula="phasedeg")
```

#### plot

```python
def plot(self, curves=None, formula=None, size=(1920,1440),
    show_legend=True, x_label="", y_label="", title="",
    snapshot_path=None, is_polar=False, show=True) -> ReportPlotter
```

#### plot_3d

```python
def plot_3d(self, curve=None, primary_sweep="Theta",
    secondary_sweep="Phi", formula=None, size=(1920,1440), snapshot_path=None)
```

#### get_report_plotter

```python
def get_report_plotter(self, curves=None, formula=None,
    to_radians=False, props=None) -> ReportPlotter
```

#### Other Methods

```python
def set_active_variation(self, var_id=0) -> bool
def variation_values(self, variation: str) -> list
def is_real_only(self, expression=None) -> bool
def export_data_to_csv(self, output, delimiter=";") -> bool
def init_solutions_data(self) -> None

# Static
SolutionData.to_degrees(input_list)
SolutionData.to_radians(input_list)
SolutionData.lookup_column_value(array, match_columns, match_values, output_column)
```

---

## Standard Report Classes

**Module:** `ansys.aedt.core.visualization.report.standard`

### Standard

```python
class Standard(CommonReport, PyAedtBase)
Standard(app, report_category, setup_name, expressions=None)
```

| Property | Type | Description |
|----------|------|-------------|
| `sub_design_id` | `int` | Sub-design ID |
| `time_start` | `str` | Time start (default "0ps") |
| `time_stop` | `str` | Time stop (default "10ns") |
| `thinning` | `int` | Transient windowing |
| `thinning_points` | `int` | Thinning points (default 500000000) |
| `dy_dx_tolerance` | `float` | Thinning tolerance (default 0.001) |

### Spectral

```python
class Spectral(Standard)
```

### CommonReport Properties (inherited by all)

```python
expressions: list          # Report expressions
domain: str                # "Sweep", "Time"
primary_sweep: str         # Primary sweep variable
secondary_sweep: str       # Secondary sweep variable
variations: dict           # Variation families
report_type: str           # Display type
plot_name: str             # Report name in AEDT
differential_pairs: bool   # Differential pairs context
polyline: str              # Polyline name
matrix: str                # Matrix name (Q3D/Maxwell)
reduced_matrix: str        # Reduced matrix name
```

---

## Field Report Classes

**Module:** `ansys.aedt.core.visualization.report.field`

### FarField

```python
class FarField(CommonReport)
FarField(app, report_category, setup_name, expressions=None, **variations)
```

- `far_field_sphere: str` - Far field sphere name
- `source_context: str` - Source context
- `source_group: str` - Source group
- Defaults: `{"Phi":["All"], "Theta":["All"], "Freq":["Nominal"]}`
- Primary sweep: "Phi", Secondary: "Theta"

### NearField

```python
class NearField(CommonReport)
# near_field: str - Near field setup name
```

### Fields

```python
class Fields(CommonReport)
# point_number: int - Sample points (default 1001)
# Primary sweep: "Distance"
```

### AntennaParameters

```python
class AntennaParameters(Standard)
# far_field_sphere: str
```

### Emission

```python
class Emission(CommonReport)
```

---

## TouchstoneData

**Module:** `ansys.aedt.core.visualization.advanced.touchstone_parser`
**Class:** `TouchstoneData(_TouchstoneBase, PyAedtBase)`

> Requires: `pip install scikit-rf`

### Constructor

```python
TouchstoneData(solution_data=None, touchstone_file=None)
```

### Key Properties

- `port_names: list[str]` - Port names
- `s_db: np.ndarray` - S-parameters in dB [freq, port_i, port_j]
- `s: np.ndarray` - Complex S-parameters
- `frequency: skrf.Frequency`
- `number_of_ports: int`
- `port_tuples: list`
- `f: np.ndarray` - Frequency array (Hz)

### Constants

```python
REAL_IMAG = "RI"
MAG_ANGLE = "MA"
DB_ANGLE = "DB"
keys = {REAL_IMAG: ("real","imag"), MAG_ANGLE: ("mag","deg"), DB_ANGLE: ("db20","deg")}
```

### Key Methods

#### Port Reduction

```python
def reduce(self, ports, output_file=None, reordered=True) -> str
```

#### Coupling Analysis

```python
def get_coupling_in_range(self, start_frequency=1e9, stop_frequency=10e9,
    low_loss=-40.0, high_loss=-60.0, include_same_component=True,
    component_filter=None, include_filter=True,
    frequency_sample=5, output_file=None) -> list[tuple]
```

#### Loss Index Methods

```python
def get_insertion_loss_index(self, threshold=-3) -> list
def get_return_loss_index(self, excitation_name_prefix="") -> list
def get_insertion_loss_index_from_prefix(self, tx_prefix, rx_prefix) -> list
def get_next_xtalk_index(self, tx_prefix="") -> list
def get_fext_xtalk_index_from_prefix(self, tx_prefix, rx_prefix,
    skip_same_index_couples=True) -> list
```

#### Plotting

```python
def plot(self, index_couples=None, show=True) -> bool
def plot_return_losses(self) -> bool
def plot_insertion_losses(self, threshold=-3, plot=True) -> list
def plot_next_xtalk_losses(self, tx_prefix="") -> bool
```

#### Mixed Mode

```python
def get_mixed_mode_touchstone_data(self, num_of_diff_ports=None,
    port_ordering="1234") -> TouchstoneData
```

---

## ReportPlotter

**Module:** `ansys.aedt.core.visualization.plot.matplotlib`
**Class:** `ReportPlotter(PyAedtBase)`

### Constructor

```python
ReportPlotter(solution_data=None)
```

### Key Properties

| Property | Type | Default |
|----------|------|---------|
| `title` | `str` | `""` |
| `show_legend` | `bool` | `True` |
| `dpi` | `int` | `100` |
| `width` | `int` | `1200` |
| `height` | `int` | `800` |
| `x_scale` | `str` | `"linear"` |
| `y_scale` | `str` | `"linear"` |
| `text_size` | `int` | `12` |
| `title_size` | `int` | `16` |
| `grid_color` | `tuple` | `(0.8,0.8,0.8)` |
| `general_back_color` | `tuple` | `(1,1,1)` |
| `general_plot_color` | `tuple` | `(1,1,1)` |
| `traces` | `dict` | Named traces |
| `limit_lines` | `dict` | Limit lines |

### Adding Data

```python
def add_trace(self, plot_data, data_type=0, properties=None, name="") -> bool
# plot_data: [[x_data], [y_data]] or [[x],[y],[z]]
# data_type: 0=cartesian, 1=spherical
```

**Properties keys:**
```python
{"x_label", "y_label", "z_label", "trace_style", "trace_width",
 "trace_color", "show_symbol", "symbol_style", "fill_symbol", "symbol_color"}
```

### Limit Lines & Notes

```python
def add_limit_line(self, plot_data, hatch_above=True, properties=None, name="") -> bool
def add_note(self, text, position=(0,1), back_color=None, font="Arial",
    font_size=12, bold=False, italic=False, color=(0.2,0.2,0.2))
def add_eye_mask(self, properties)
```

### Plotting Methods

```python
def plot_2d(self, traces=None, snapshot_path=None, show=True, figure=None) -> plt.Figure
def plot_polar(self, traces=None, to_polar=False, snapshot_path=None,
    show=True, is_degree=True, figure=None) -> plt.Figure
def plot_3d(self, trace=0, snapshot_path=None, show=True,
    color_map_limits=None, is_polar=True) -> plt.Figure
def plot_eye_diagram(self, snapshot_path=None, show=True, is_contour=False,
    filter_colormap=1e-6, plot_max_height=True, plot_eye_mask=True)
def animate_2d(self, traces=None, snapshot_path=None, show=True,
    figure=None) -> plt.Figure
def apply_style(self, style_name) -> bool
```

---

## ModelPlotter

**Module:** `ansys.aedt.core.visualization.plot.pyvista`

### Key Functions

```python
def get_structured_mesh(theta, phi, ff_data) -> pv.StructuredGrid
def is_float(istring: str) -> float
```

---

## Reports Helper Class

**Module:** `ansys.aedt.core.visualization.post.common`
**Class:** `Reports`

Accessible via `app.post.reports_by_category`.

```python
def standard(self, expressions=None, setup=None) -> Standard
def far_field(self, expressions=None, setup=None, sphere=None) -> FarField
def near_field(self, expressions=None, setup=None) -> NearField
def fields(self, expressions=None, setup=None, polyline=None) -> Fields
def antenna_parameters(self, expressions=None, setup=None, sphere=None) -> AntennaParameters
def eye_diagram(self, expressions=None, setup=None, unit_interval="1ns",
    quantity_type=3, statistical_analysis=True) -> EyeDiagram | AMIEyeDiagram
def ami_contour_eye(self, expressions=None, setup=None, quantity_type=3) -> AMIConturEyeDiagram
def spectral(self, expressions=None, setup=None) -> Spectral
def emi_receiver(self, expressions=None, setup_name=None) -> EMIReceiver
def circuit_netlist(self, setup, expressions=None, domain=None) -> CircuitNetlistReport
```

---

## Constants

### Report Template Map

```python
TEMPLATES_BY_NAME = {
    "Standard": Standard, "EddyCurrent": Standard,
    "AC Magnetic": Standard, "Modal Solution Data": Standard,
    "Terminal Solution Data": Standard, "Fields": Fields,
    "CG Fields": Fields, "DC R/L Fields": Fields,
    "AC R/L Fields": Fields, "Matrix": Standard,
    "Monitor": Standard, "Far Fields": FarField,
    "Near Fields": NearField, "Eye Diagram": EyeDiagram,
    "Statistical Eye": AMIEyeDiagram, "AMI Contour": AMIConturEyeDiagram,
    "Eigenmode Parameters": Standard, "Spectrum": Spectral,
    "EMIReceiver": EMIReceiver, "Netlist": CircuitNetlistReport,
}
```

### Touchstone Format Constants

```python
REAL_IMAG = "RI"
MAG_ANGLE = "MA"
DB_ANGLE = "DB"
keys = {"RI": ("real","imag"), "MA": ("mag","deg"), "DB": ("db20","deg")}
```

---

## Usage Patterns

### Pattern 1: S-Parameter Analysis

```python
from ansys.aedt.core import Hfss
hfss = Hfss(projectname="my_project", designname="my_design")

data = hfss.post.get_solution_data(
    expressions=["dB(S(1,1))", "dB(S(2,1))"],
    setup_sweep_name="Setup1 : LastAdaptive",
)
data.plot(curves=["dB(S(1,1))", "dB(S(2,1))"], title="S-Parameters")

freq, s11 = data.get_expression_data("S(1,1)", formula="db20")
data.export_data_to_csv("s_parameters.csv")

report = hfss.post.create_report("dB(S(1,1))", plot_type="Rectangular Plot",
    snapshot_path="C:/temp/sparam.png")
```

### Pattern 2: Touchstone File Analysis

```python
from ansys.aedt.core.visualization.advanced.touchstone_parser import TouchstoneData

ts = TouchstoneData(touchstone_file="design.s16p")
ts.plot_return_losses()
ts.plot_insertion_losses(threshold=-3)

coupling = ts.get_coupling_in_range(
    start_frequency=2e9, stop_frequency=5e9,
    high_loss=-60.0, low_loss=-64.0,
    component_filter=["U1", "X1"], include_filter=True,
)

reduced = ts.reduce(ports=[0, 1, 2, 3], output_file="reduced.s4p")
mm_ts = ts.get_mixed_mode_touchstone_data(num_of_diff_ports=4)
```

### Pattern 3: Far-Field Visualization

```python
variations = hfss.available_variations.nominal_values
variations.update({"Theta":["All"], "Phi":["All"], "Freq":["30GHz"]})

data = hfss.post.get_solution_data("GainTotal", hfss.nominal_adaptive,
    variations=variations, primary_sweep_variable="Phi",
    report_category="Far Fields", context="Infinite Sphere1")

data.plot(curves="GainTotal", is_polar=True)
data.plot_3d(curves="GainTotal", primary_sweep="Theta", secondary_sweep="Phi")
```

### Pattern 4: Custom Matplotlib Report

```python
from ansys.aedt.core.visualization.plot.matplotlib import ReportPlotter

rp = ReportPlotter()
rp.add_trace([freq, s11], name="S11", properties={
    "x_label": "Frequency (GHz)", "y_label": "dB",
    "trace_color": (0.8, 0.1, 0.1), "trace_width": 2.0,
})
rp.add_trace([freq, s21], name="S21", properties={
    "x_label": "Frequency (GHz)", "y_label": "dB",
    "trace_color": (0.1, 0.1, 0.8), "trace_style": "--",
})
rp.title = "S-Parameters"
rp.x_scale = "log"
rp.plot_2d(snapshot_path="sparams.png")
```

### Pattern 5: Report by Category

```python
ff = hfss.post.reports_by_category.far_field("db(GainTotal)",
    setup="Setup1 : LastAdaptive", sphere="Infinite Sphere1")
ff.variations["Freq"] = ["28GHz"]
ff.create()

report = hfss.post.reports_by_category.standard("dB(S(1,1))")
report.create()
```

### Pattern 6: Export Workflow

```python
report = hfss.post.create_report("dB(S(1,1))")
hfss.post.export_report_to_file("C:/temp", "S11_Plot", ".csv")
hfss.post.export_report_to_jpg("C:/temp", "S11_Plot", width=1920, height=1080)
```

---

> Source files analyzed: visualization/post/common.py (3268 lines), post/solution_data.py (1269 lines), post/post_hfss.py (561 lines), report/standard.py (998 lines), report/field.py (254 lines), advanced/touchstone_parser.py (949 lines), plot/matplotlib.py (2648 lines), plot/pyvista.py (2047 lines)
