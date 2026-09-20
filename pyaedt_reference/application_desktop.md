# pyAEDT Application & Desktop Reference

> **Source:** pyaedt-main/src/ansys/aedt/core/
> **Scope:** AEDT connection lifecycle, project management, multi-physics analysis

---

## Table of Contents

1. [Desktop - AEDT Session Manager](#1-desktop---aedt-session-manager)
2. [Design - Base Project & Design Class](#2-design---base-project--design-class)
3. [AedtObjects - AEDT API Module Access](#3-aedtobjects---aedt-api-module-access)
4. [DesignSolution - Solution Type Configuration](#4-designsolution---solution-type-configuration)
5. [AedtUnits - Unit Handling](#5-aedtunits---unit-handling)
6. [aedt_file_management - File Operations](#6-aedt_file_management---file-operations)
7. [job_manager - HPC Configuration](#7-job_manager---hpc-configuration)
8. [FieldAnalysis3D - 3D Field Solver Base](#8-fieldanalysis3d---3d-field-solver-base)
9. [FieldAnalysisCircuit - Circuit/Nexxim Analysis](#9-fieldanalysiscircuit---circuitnexxim-analysis)
10. [FieldAnalysisIcepak - Thermal/CFD Analysis](#10-fieldanalysisicepak---thermalcfd-analysis)
11. [Class Hierarchy & Inheritance](#11-class-hierarchy--inheritance)

---

## 1. Desktop - AEDT Session Manager

**File:** `desktop.py`
**Class:** `Desktop(PyAedtBase)`

Manages the AEDT process lifecycle: launching, connecting, releasing, and shutting down Electronics Desktop sessions via gRPC (or legacy COM).

### Constructor

```python
Desktop(
    version: str | None = None,         # "2026.1", 261, 26.1, etc.
    non_graphical: bool | None = False,  # headless mode
    new_desktop: bool | None = True,     # launch new AEDT process
    close_on_exit: bool | None = None,   # auto-close behavior (None = smart default)
    student_version: bool | None = False,
    machine: str | None = None,          # remote host ("" for localhost)
    port: int | None = 0,                # gRPC port (0 = auto)
    aedt_process_id: int | None = None,  # attach to existing PID
)
```

**Key behaviors:**
- `__new__` implements singleton-like reuse via `_desktop_sessions` registry
- If `use_multi_desktop=True`, new sessions are created independently
- Session is registered in `_desktop_sessions[pid]` after init
- `atexit` handler auto-releases on interpreter shutdown
- `close_on_exit=None` -> smart: closes if PyAEDT started AEDT, preserves if attached

### Key Properties

| Property | Type | Description |
|----------|------|-------------|
| `odesktop` | object | Raw AEDT desktop COM/gRPC handle |
| `aedt_version_id` | str | Normalized version string, e.g. "2026.1" |
| `aedt_version` | str | Full version from oDesktop.GetVersion() |
| `aedt_process_id` | int | AEDT process ID |
| `port` | int | gRPC port number |
| `machine` | str | Remote machine name |
| `is_grpc_api` | bool | True when using gRPC transport |
| `non_graphical` | bool | Headless mode flag |
| `student_version` | bool | Student license flag |
| `launched_by_pyaedt` | bool | Whether PyAEDT started this AEDT |
| `close_on_exit` | bool | Whether to close AEDT on cleanup |
| `logger` | Logger | AEDT-aware logger |
| `personallib` | str | PersonalLib directory path |
| `syslib` | str | SysLib directory path |
| `userlib` | str | UserLib directory path |
| `temp_directory` | str | AEDT temp directory |
| `global_project_directory` | str | Default project directory |
| `installed_versions` | dict | All installed AEDT versions |
| `aedt_install_dir` | str | Current AEDT installation path |

### Key Methods

```python
# --- Session Lifecycle ---
release_desktop(close_projects=True, close_on_exit=True) -> bool
close_desktop() -> bool

# --- Project Management ---
project_list -> list[str]                          # List all open projects
active_project(name=None) -> object                # Get/set active project
active_project_name -> str | None                  # Active project name
save_project(project_name=None, project_path=None) -> bool
load_project(project_file, design_name=None) -> bool | object
project_path(project_name=None) -> str | None

# --- Design Management ---
design_list(project=None) -> list[str]
design_type(project_name=None, design_name=None) -> str
active_design_name -> str | None

# --- Simulation ---
analyze_all(project=None, design=None) -> bool

# --- Configuration ---
change_license_type(license_type="Pool") -> bool
enable_optimetrics() -> bool
disable_optimetrics() -> bool
change_registry_key(key_full_name, key_value) -> bool
enable_autosave() / disable_autosave()
clear_messages() -> bool
close_windows() -> bool
get_example(example_name, folder_name=".") -> Path

# --- Item Access ---
desktop[["ProjectName", "DesignName"]]  # returns pyaedt app object
```

### Transport Modes

```python
class TransportMode(str, Enum):
    INSECURE = "insecure"    # No encryption
    UDS = "uds"              # Unix Domain Socket (Linux local)
    MTLS = "mtls"            # Mutual TLS (remote with certs)
    WNUA = "wnua"            # Windows Named Pipe (Windows local)
```

### Connection Flow

```
Desktop.__new__  ->  check _desktop_sessions for existing match
                 ->  reuse existing or create new instance
Desktop.__init__ ->  check_starting_mode() -> "grpc" / "com" / "console"
                 ->  __init_grpc() -> launch_aedt() or connect to existing port
                 ->  __set_logger_file()
                 ->  __init_desktop()
                 ->  register in _desktop_sessions[pid]
```

---

## 2. Design - Base Project & Design Class

**File:** `application/design.py`
**Class:** `Design(AedtObjects, PyAedtBase)`

Base class for all AEDT application types (Hfss, Icepak, Maxwell3D, etc.). Manages projects, designs, variables, and provides the foundation for all tool-specific classes.

### Constructor

```python
Design(
    design_type: str,              # "HFSS", "Icepak", "Maxwell 3D", etc.
    project_name: str | Path,      # Project path or name
    design_name: str,              # Design name to select/create
    solution_type: str,            # e.g. "Modal", "Terminal", "DrivenModal"
    version: str | int | float,    # AEDT version
    non_graphical: bool = False,
    new_desktop: bool = False,
    close_on_exit: bool = False,
    student_version: bool = False,
    machine: str = "",
    port: int = 0,
    aedt_process_id: int = None,
    ic_mode: bool = None,          # IC mode for Hfss3dLayout
    remove_lock: bool = False,     # Remove .aedt.lock before opening
)
```

**Init sequence:**
1. Starts background thread to load .aedt file metadata
2. Initializes Desktop connection via `__init_desktop_from_design()`
3. Sets up DesignSolution based on design type
4. Sets oproject -> triggers project open/create
5. Sets odesign -> triggers design selection/create
6. Initializes AedtObjects with full AEDT handle chain
7. Creates VariableManager and DesignSettings

### Key Properties

| Property | Type | Description |
|----------|------|-------------|
| `project_name` | str | Current project name |
| `project_path` | str | Directory containing .aedt file |
| `project_file` | str | Full path: project_path/project_name.aedt |
| `design_name` | str | Current design name (settable -> rename or switch) |
| `design_type` | str | "HFSS", "Icepak", "Maxwell 3D", etc. |
| `design_list` | list[str] | All designs in current project |
| `solution_type` | str | Current solution type |
| `oproject` | object | Raw AEDT project handle (setter opens/creates) |
| `odesign` | object | Raw AEDT design handle (setter selects/creates) |
| `desktop_class` | Desktop | Desktop session reference |
| `variable_manager` | VariableManager | Project/design variable access |
| `design_solutions` | DesignSolution | Solution type configuration |
| `info` | dict | Session info (version, platform, PID, port) |

### Key Methods

```python
# --- Project Management ---
save_project(file_name=None, overwrite=True, refresh_ids=False) -> bool
close_project(name=None, save=True) -> bool
copy_project(destination, name) -> bool
create_new_project(name) -> bool
delete_project(name) -> bool
archive_project(project_path=None, ...) -> bool

# --- Design Management ---
design_name = "new_name"             # Rename or switch design
delete_design(name=None, fallback_design=None) -> bool
rename_design(name, save=True) -> bool

# --- Variable Access ---
app["var_name"]                      # Get variable value
app["var_name"] = "10mm"             # Set variable value

# --- Validation ---
validate_simple(log_file=None) -> int  # Returns number of validation errors
```

### Context Manager Support

```python
with Hfss() as hfss:
    # ... work with HFSS ...
# automatically releases or closes desktop on exit
```

---

## 3. AedtObjects - AEDT API Module Access

**File:** `application/aedt_objects.py`
**Class:** `AedtObjects(PyAedtBase)`

Provides lazy-loaded properties for all AEDT design modules. Acts as a bridge between Python and AEDT internal module API (`oDesign.GetModule(...)`).

### AEDT Module Properties

| Property | AEDT API Call | Applicable Designs |
|----------|---------------|-------------------|
| `oboundary` | GetModule("BoundarySetup") | HFSS, Maxwell, Q3D (not Circuit) |
| `oimport_export` | oDesktop.GetTool("ImportExport") | All |
| `ooptimetrics` | GetModule("Optimetrics") | All except EMIT, Circuit Netlist |
| `ooutput_variable` | GetModule("OutputVariable") | Most 3D apps |
| `oanalysis` | GetModule("AnalysisSetup") | Design-dependent |
| `odefinition_manager` | oProject.GetDefinitionManager() | All |
| `omaterial_manager` | definition_manager.GetManager("Material") | All |
| `omodelsetup` | GetModule("ModelSetup") | HFSS, Maxwell Transient |
| `omaxwell_parameters` | GetModule("MaxwellParameterSetup") | Maxwell only |
| `omonitor` | GetModule("Monitor") | Icepak only |
| `osolution` | GetModule("Solutions") | Most 3D apps |
| `oexcitation` | GetModule("Excitations") | HFSS 3D Layout |
| `omatrix` | GetModule("ReduceMatrix") | Q3D, 2D Extractor |
| `ofieldsreporter` | GetModule("FieldsReporter") | HFSS, Maxwell, Q3D, Icepak |
| `oreportsetup` | GetModule("ReportSetup") | All |
| `omeshmodule` | GetModule("MeshRegion") | Icepak |
| `oradfield` | GetModule("RadField") | HFSS (non-Eigenmode) |
| `units` | AedtUnits | All |

```python
get_module(module_name: str) -> object   # Generic module getter
```

---

## 4. DesignSolution - Solution Type Configuration

**File:** `application/design_solutions.py`

### Base: DesignSolution(PyAedtBase)

| Property | Type | Description |
|----------|------|-------------|
| `solution_type` | str | Get/set active solution type |
| `report_type` | str | Default report type for this solution |
| `default_setup` | str | Default setup ID |
| `default_adaptive` | str | Default adaptive pass name |
| `solution_types` | list[str] | All available solution types |
| `intrinsics` | list[str] | Intrinsic variables (freq, time, etc.) |

### HFSSDesignSolution

| Property | Type | Description |
|----------|------|-------------|
| `hybrid` | bool | Enable/disable hybrid solver |
| `composite` | bool | Enable/disable composite mode |

```python
set_auto_open(enable=True, opening_type="Radiation") -> bool
```

**Solution types:** Modal, Terminal, Transient Network, Transient Composite, Eigenmode, Characteristic Mode

### Maxwell2DDesignSolution

| Property | Type | Description |
|----------|------|-------------|
| `xy_plane` | bool | True for XY, False for "about Z" |

### IcepakDesignSolution

| Property | Type | Description |
|----------|------|-------------|
| `problem_type` | str | "TemperatureAndFlow", "TemperatureOnly", "FlowOnly" |

**Solution types:** SteadyState, Transient

### RmXprtDesignSolution

| Property | Type | Description |
|----------|------|-------------|
| `solution_type` | str | Machine type (via GetMachineType()) |
| `design_type` | str | Machine design type |

---

## 5. AedtUnits - Unit Handling

**File:** `application/aedt_units.py`
**Class:** `AedtUnits(PyAedtBase)`

Provides default AEDT unit values. Read-only except length and rescale_model.

```python
hfss = Hfss()
hfss.units.frequency       # "GHz"
hfss.units.length          # "mm"
hfss.units.length = "mil"  # changes AEDT default
```

| Property | Type | Writable | Description |
|----------|------|----------|-------------|
| `frequency` | str | No | Frequency unit |
| `length` | str | Yes | Length unit (changes AEDT default) |
| `resistance` | str | No | Resistance unit |
| `angle` | str | No | Angle unit |
| `power` | str | No | Power unit |
| `inductance` | str | No | Inductance unit |
| `time` | str | No | Time unit |
| `voltage` | str | No | Voltage unit |
| `capacitance` | str | No | Capacitance unit |
| `temperature` | str | No | Temperature unit |
| `current` | str | No | Current unit |
| `force` | str | No | Force unit |
| `speed` | str | No | Speed unit |
| `angular_speed` | str | No | Angular speed unit |
| `mass` | str | No | Mass unit |
| `conductance` | str | No | Conductance unit |
| `rescale_model` | bool | Yes | Rescale model on unit change |

```python
get_unit_by_system(unit_system: str) -> str | None
```

---

## 6. aedt_file_management - File Operations

**File:** `application/aedt_file_management.py`

Utility functions that directly edit .aedt project files:

```python
change_objects_visibility(input_file: str | Path, assignment: list) -> bool
    # Edit .aedt file to show only specified solids

change_model_orientation(input_file: str | Path, bottom_dir: str) -> bool
    # Edit .aedt file to set camera orientation
    # bottom_dir: "+X", "-X", "+Y", "-Y", "+Z", "-Z"
```

> Warning: These require the project to be closed (no .lock file).

---

## 7. job_manager - HPC Configuration

**File:** `application/job_manager.py`

Functions for reading/modifying AEDT HPC configuration files (.acf):

```python
get_hpc_info(filename) -> tuple[str, str]              # (config_name, design_type)
update_hpc_option(filename, propertyname, value, ...) -> bool
update_simulation_cores(name, nc) -> None              # Set NumCores
update_simulation_engines(name, nc) -> None            # Set NumEngines
update_machine_name(name, machinename) -> None
update_config_name(name, machinename) -> None
update_cluster_cores(file_name, param_name, param_val) -> None
update_hpc_template(file_name, param_name, param_val) -> None
```

---

## 8. FieldAnalysis3D - 3D Field Solver Base

**File:** `application/analysis_3d.py`
**Class:** `FieldAnalysis3D(Analysis, PyAedtBase)`

Base for HFSS, Maxwell 3D, Q3D. Extends Design with modeler, mesh, post-processing.

### Key Properties

| Property | Type | Description |
|----------|------|-------------|
| `modeler` | Modeler3D / Modeler2D | Geometry modeler (auto-selects 2D/3D) |
| `mesh` | Mesh | Mesh operations |
| `post` | PostProcessor* | Post-processing (auto-selects by design type) |
| `configurations` | Configurations | Import/export design configurations |
| `components3d` | dict | Available 3D components in libraries |

### Key Methods

```python
import_3d_cad(file_path, ...) -> bool        # Import STEP, STL, SAT, etc.
export_3d_model(file_name, ...) -> bool       # Export geometry
plot(assignment=None, show=True, ...) -> ModelPlotter  # PyVista 3D plot
get_all_conductors_names() -> list[str]
get_all_dielectrics_names() -> list[str]
```

---

## 9. FieldAnalysisCircuit - Circuit/Nexxim Analysis

**File:** `application/analysis_nexxim.py`
**Class:** `FieldAnalysisCircuit(Analysis, PyAedtBase)`

Used by Circuit, Twin Builder, and Maxwell Circuit applications.

### Key Properties

| Property | Type | Description |
|----------|------|-------------|
| `modeler` | ModelerNexxim | Schematic modeler |
| `post` | PostProcessorCircuit | Circuit post-processor |
| `configurations` | ConfigurationsNexxim | Configuration import/export |
| `setup_names` | list | All solution setup names |
| `source_names` | list | All source names |
| `sources` | list[Sources] | Source objects |

### Key Methods

```python
push_down(component) -> bool     # Navigate into sub-circuit
pop_up() -> bool                 # Navigate back to parent circuit
create_setup(name, setup_type, **kwargs) -> SetupCircuit
delete_setup(name) -> bool
```

### Source Types

- VoltageDCSource
- VoltageSinSource
- VoltageFrequencyDependentSource
- CurrentSinSource
- PowerSinSource
- PowerIQSource

---

## 10. FieldAnalysisIcepak - Thermal/CFD Analysis

**File:** `application/analysis_icepak.py`
**Class:** `FieldAnalysisIcepak(FieldAnalysis3D, PyAedtBase)`

Specialized for Icepak thermal/flow simulation.

### Key Properties

| Property | Type | Description |
|----------|------|-------------|
| `mesh` | IcepakMesh | Icepak-specific mesh (overrides base) |
| `post` | PostProcessorIcepak | Icepak post-processor |
| `monitor` | Monitor | Monitor point/surface/volume management |
| `configurations` | ConfigurationsIcepak | Icepak-specific configurations |

### Design Settings

```python
icepak.design_settings["AmbTemp"] = 25            # auto-adds "cel" units
icepak.design_settings["AmbGaugePressure"] = 0     # auto-adds "n_per_meter_sq"
icepak.design_settings["GravityVec"] = 3           # maps to Global::Z, Negative
```

**Problem types:** TemperatureAndFlow, TemperatureOnly, FlowOnly
**Solution types:** SteadyState, Transient

---

## 11. Class Hierarchy & Inheritance

```
PyAedtBase
+-- Desktop                          # desktop.py
+-- AedtObjects                      # aedt_objects.py
|   +-- Design                       # design.py
|       +-- Analysis                 # analysis.py
|           +-- FieldAnalysis3D      # analysis_3d.py
|           |   +-- FieldAnalysisIcepak
|           |   +-- [Hfss, Maxwell3d, Q3d, ...]
|           +-- FieldAnalysisCircuit
|               +-- [Circuit, TwinBuilder, MaxwellCircuit]
+-- DesignSolution
|   +-- HFSSDesignSolution
|   +-- Maxwell2DDesignSolution
|   +-- IcepakDesignSolution
|   +-- RmXprtDesignSolution
+-- AedtUnits
```

### Typical Usage

```python
from ansys.aedt.core import Desktop, Hfss

# Direct - Desktop manages everything
desktop = Desktop(version="2026.1", non_graphical=True)
hfss = Hfss(project="MyProject", design="MyDesign", solution_type="DrivenModal")

# Context manager - auto cleanup
with Hfss() as hfss:
    hfss.modeler.create_box([0,0,0], [10,10,10], "Box1", "vacuum")
    hfss.save_project()

# Access AEDT internals
hfss.oboundary       # BoundarySetup module
hfss.oanalysis       # AnalysisSetup module
hfss.oreportsetup    # ReportSetup module
hfss.desktop_class   # Desktop session
```

### Multi-Physics Coupling Notes

- **HFSS to Icepak:** Use push_excitations to pass EM losses as thermal sources
- **HFSS to Circuit:** FieldAnalysisCircuit supports push_down()/pop_up() for hierarchical designs
- **Icepak monitors:** icepak.monitor provides add/delete/modify for temperature/velocity/pressure probes
- **Configurations:** Each solver has a Configurations class for JSON-based design export/import