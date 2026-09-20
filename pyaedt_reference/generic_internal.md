# PyAEDT `generic` + `internal` Modules Reference

> Comprehensive reference for the utility, infrastructure, and internal modules in `ansys.aedt.core`.
> These modules provide the foundation layer that all higher-level PyAEDT tools (HFSS, Maxwell, etc.) are built on.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [generic/ Modules](#2-generic-modules)
3. [internal/ Modules](#3-internal-modules)
4. [gRPC Communication Flow](#4-grpc-communication-flow)
5. [Key Patterns & Conventions](#5-key-patterns--conventions)

---

## 1. Architecture Overview

```
User Code
    |
    v
+-----------------------------------------------+
|  Application Layer (Hfss, Maxwell...)          |   <- High-level design APIs
+-----------------------------------------------+
|  design_types.py  (app_map)                    |   <- Maps design types -> app classes
|  configurations.py (Configurations)            |   <- Import/export JSON config
+-----------------------------------------------+
|  settings.py  (Settings singleton)             |   <- Global PyAEDT settings
|  scheduler.py (HPC job submission)             |   <- HPC configuration & AEDT exe
+-----------------------------------------------+
|  data_handlers.py                              |   <- Dict<->AEDT-arg serialization
|  file_utils.py                                 |   <- File I/O abstractions
|  math_utils.py                                 |   <- Numerical utilities
+-----------------------------------------------+
|  grpc_plugin_dll_class.py                      |   <- gRPC DLL wrapper
|  load_aedt_file.py                             |   <- .aedt file parser
|  desktop_sessions.py                           |   <- Session registry
|  filesystem.py                                 |   <- Scratch / temp dirs
|  errors.py / checks.py                         |   <- Error types & decorators
+-----------------------------------------------+
```

---

## 2. `generic/` Modules

### 2.1 `data_handlers.py`

**Module:** `ansys.aedt.core.generic.data_handlers`

Serialization layer between Python dicts and the AEDT native argument format.

#### Key Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `_dict2arg` | `(d: dict, arg_out: list) -> None` | Recursively converts a Python dict into the nested list format expected by the AEDT native API. Handles special keys (`Point`, `DimUnits`, `Points`, `Range`), nested dicts, `Quantity` objects, and geometry primitives. |
| `_arg2dict` | `(arg: list, dict_out: dict) -> None` | Reverse of `_dict2arg` - parses AEDT native argument list back into a Python dict. Handles `NAME:` prefixed keys, `:=` assignments, `DimUnits`, `Ranges`, and nested structures. |
| `format_decimals` | `(el: float\|int\|str) -> str` | Formats a decimal number with appropriate precision. |
| `random_string` | `(length=6, only_digits=False, char_set=None) -> str` | Generates a cryptographically random string using `secrets.choice`. |
| `unique_string_list` | `(element_list, only_string=True) -> list` | Returns deduplicated list from input. |
| `string_list` | `(element_list) -> list` | Wraps a single string in a list. |
| `ensure_list` | `(element_list) -> list` | Forces any object into a list. |
| `variation_string_to_dict` | `(variation_string, separator="=") -> dict` | Parses `"Freq='5GHz' Temp='25cel'"` into a dict. |
| `from_rkm` | `(code: str) -> str` | Converts RKM notation to decimal string (e.g. `"4K7"` -> `"4.7k"`). |
| `to_aedt` | `(code: str) -> str` | Converts Unicode mu to ASCII u for AEDT compatibility. |
| `from_rkm_to_aedt` | `(code: str) -> str` | Combines `from_rkm` + `to_aedt`. |
| `float_units` | `(val_str, units="") -> float` | Converts value string with unit suffix to float in target unit system. |
| `str_to_bool` | `(s: str\|int) -> bool\|str` | Converts `"true"/"yes"/"y"/"1"` to `True`, etc. |
| `normalize_string_format` | `(text: str) -> str` | Removes accents, replaces special chars, normalizes to `snake_case`. |

#### Key Data

- **`RKM_MAPS`**: Dict mapping RKM code characters to unit suffixes.
- **`unit_val`**: Dict mapping unit strings to float multipliers (e.g. `"mm"` -> `1e-3`, `"MHz"` -> `1e6`).

---

### 2.2 `file_utils.py`

**Module:** `ansys.aedt.core.generic.file_utils`

File I/O abstractions supporting both local and remote (RPyC) sessions.

#### Key Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `generate_unique_name` | `(root_name, suffix="", n=6) -> str` | Appends `_<random_n_chars>` to `root_name`. |
| `generate_unique_folder_name` | `(root_name=None, folder_name=None) -> str` | Creates a unique temp folder. |
| `generate_unique_project_name` | `(root_name, folder_name, project_name, project_format="aedt") -> str` | Generates a unique `.aedt` project path. |
| `open_file` | `(file_path, file_options="r", encoding=None, override_existing=True) -> IO\|None` | Smart file opener for local/remote files. |
| `read_json` | `(input_file, encoding="utf-8") -> dict` | Loads JSON -> dict. |
| `read_toml` | `(input_file) -> dict` | Loads TOML -> dict. |
| `read_csv` | `(input_file, encoding="utf-8") -> list` | Reads CSV -> list of rows. |
| `read_csv_pandas` | `(input_file, encoding="utf-8") -> DataFrame\|None` | Reads CSV via pandas. |
| `read_configuration_file` | `(input_file) -> dict\|list` | **Universal reader** - dispatches by extension. |
| `write_configuration_file` | `(input_data, output_file) -> bool` | Writes dict -> JSON or TOML. |
| `check_if_path_exists` | `(path) -> bool` | Checks local or remote path existence. |
| `is_project_locked` | `(input_file) -> bool` | Checks for `.lock` file. |
| `remove_project_lock` | `(input_file) -> bool` | Removes the `.lock` file. |
| `check_and_download_file` | `(remote_path, overwrite=True) -> str` | Downloads remote file to local temp. |
| `recursive_glob` | `(path, file_pattern) -> list` | Recursive glob, supports remote sessions. |
| `available_file_name` | `(full_file_name) -> Path` | Returns non-colliding filename. |
| `compute_fft` | `(time_values, data_values, window=None) -> tuple\|bool` | FFT with optional windowing. |
| `parse_excitation_file` | `(input_file, is_time_domain=True, ...) -> tuple\|bool` | Parses excitation CSV. |
| `available_license_feature` | `(feature="electronics_desktop", ...) -> int` | Checks available license count. |

#### Key Types

- **`StrPath`**: `str | Path` - type alias for path parameters.
- **`is_linux` / `is_windows`**: Module-level platform flags.

---

### 2.3 `settings.py`

**Module:** `ansys.aedt.core.generic.settings`

The `Settings` singleton manages all PyAEDT environment variables and global configuration.

#### Usage

```python
from ansys.aedt.core.generic.settings import settings

settings.enable_screen_logs = False
settings.use_grpc_api = True
settings.aedt_version = "2026.1"
settings.load_yaml_configuration(r"C:\config\pyaedt_settings.yaml")
settings.write_yaml_configuration(r"C:\config\pyaedt_settings.yaml")
```

#### Key Properties

**gRPC Settings:**

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `grpc_secure_mode` | `bool` | `True` | Use TLS for gRPC |
| `grpc_local` | `bool` | `True` | Local gRPC connection |
| `grpc_listen_all` | `bool` | `False` | Listen on all interfaces |
| `use_grpc_api` | `bool\|None` | `None` | Force gRPC vs COM |
| `pyedb_use_grpc` | `bool\|None` | `None` | Use gRPC for PyEDB |

**Logging Settings:**

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `enable_logger` | `bool` | `True` | Master logging toggle |
| `enable_screen_logs` | `bool` | `True` | Log to STDOUT |
| `enable_file_logs` | `bool` | `True` | Log to file |
| `enable_desktop_logs` | `bool` | `False` | Log to AEDT message window |
| `enable_debug_grpc_api_logger` | `bool` | `False` | Debug gRPC calls |
| `global_log_file_name` | `str` | auto-generated | Log file path |
| `global_log_file_size` | `int` | `10` | Max log size (MB) |

**LSF Scheduler Settings:**

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `use_lsf_scheduler` | `bool` | `False` | Use LSF |
| `lsf_queue` | `str\|None` | `None` | Queue name |
| `lsf_ram` | `int` | `1000` | RAM allocation (MB) |
| `lsf_timeout` | `int` | `3600` | Launch timeout (s) |

**General Settings:**

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `aedt_version` | `str\|None` | `None` | AEDT version (e.g. `"2026.1"`) |
| `desktop_launch_timeout` | `int` | `120` | Desktop launch timeout (s) |
| `number_of_grpc_api_retries` | `int` | `6` | gRPC retry count |
| `retry_n_times_time_interval` | `float` | `0.1` | Retry interval (s) |
| `enable_error_handler` | `bool` | `False` | Internal error handling |
| `release_on_exception` | `bool` | `True` | Release AEDT on exception |
| `use_multi_desktop` | `bool` | `False` | Multiple desktop sessions |
| `lazy_load` | `bool` | `True` | Lazy loading |
| `enable_pandas_output` | `bool` | `False` | Return pandas objects |
| `skip_license_check` | `bool` | `True` | Skip license check |
| `num_cores` | `int` | `4` | Scheduler cores |

**Environment Variables:**

| Property | Type | Description |
|----------|------|-------------|
| `aedt_environment_variables` | `dict` | Beta feature flags set before AEDT launch |
| `remote_rpc_session` | `Any\|None` | Active RPyC connection |
| `remote_rpc_session_temp_folder` | `str` | Remote temp folder |
| `remote_rpc_service_manager_port` | `int` | RPyC port (default 17878) |
| `remote_api` | `bool` | Remote API active |
| `pyaedt_server_path` | `str` | Env var PYAEDT_SERVER_AEDT_PATH |

#### YAML Configuration

```python
settings.load_yaml_configuration("pyaedt_settings.yaml", raise_on_wrong_key=False)
settings.write_yaml_configuration("pyaedt_settings.yaml")
```

---

### 2.4 `configurations.py`

**Module:** `ansys.aedt.core.generic.configurations`

Provides JSON-based configuration export/import for AEDT designs.

#### `ConfigurationsOptions`

Controls which sections to export/import. Accessed via `app.configurations.options`.

```python
from ansys.aedt.core import Hfss
hfss = Hfss()
hfss.configurations.options.export_variables = False
hfss.configurations.options.import_boundaries = True
hfss.configurations.options.object_mapping_tolerance = 1e-6
```

**Export flags** (all default `True`): `export_variables`, `export_setups`, `export_optimizations`, `export_parametrics`, `export_boundaries`, `export_mesh_operations`, `export_coordinate_systems`, `export_materials`, `export_object_properties`, `export_datasets`

**Import flags** (all default `True`): `import_variables`, `import_setups`, `import_optimizations`, `import_parametrics`, `import_boundaries`, `import_mesh_operations`, `import_coordinate_systems`, `import_materials`, `import_output_variables`, `import_object_properties`, `import_datasets`

**Methods:** `set_all_export()`, `unset_all_export()`, `set_all_import()`, `unset_all_import()`

#### `Configurations`

Main class attached to each application object.

```python
hfss.configurations.import_config(r"C:\Temp\hfss_config.json")
hfss.configurations.export_config(r"C:\Temp\hfss_config.json")
hfss.configurations.validate(r"C:\Temp\hfss_config.json")
```

#### `ImportResults`

Tracks success/failure of each import section via `hfss.configurations.results.global_import_success`.

---

### 2.5 `design_types.py`

**Module:** `ansys.aedt.core.generic.design_types`

Maps AEDT design types to PyAEDT application classes.

#### `launch_desktop()`

```python
from ansys.aedt.core.generic.design_types import launch_desktop

desktop = launch_desktop(version="2026.1", non_graphical=True, new_desktop=True)
```

#### `app_map`

```python
app_map = {
    "Maxwell 2D": Maxwell2d, "Maxwell 3D": Maxwell3d,
    "Maxwell Circuit": MaxwellCircuit, "Twin Builder": TwinBuilder,
    "Circuit Design": Circuit, "Circuit Netlist": CircuitNetlist,
    "2D Extractor": Q2d, "Q3D Extractor": Q3d, "HFSS": Hfss,
    "Mechanical": Mechanical, "Icepak": Icepak, "Rmxprt": Rmxprt,
    "HFSS 3D Layout Design": Hfss3dLayout, "EMIT": Emit,
}
```

#### `get_pyaedt_app()`

```python
from ansys.aedt.core.generic.design_types import get_pyaedt_app
app = get_pyaedt_app(project_name="MyProject", design_name="HFSSDesign1", desktop=desktop)
```

Retrieves the correct PyAEDT app object for an open design. Falls back to `_desktop_sessions` or IronPython `oDesktop`.

---

### 2.6 `math_utils.py`

**Module:** `ansys.aedt.core.generic.math_utils`

Static utility class for numerical comparisons.

```python
from ansys.aedt.core.generic.math_utils import MathUtils

MathUtils.is_zero(1e-16)            # True
MathUtils.is_equal(2.0, 2.0)       # True
MathUtils.is_close(1.0, 1.0+1e-10) # True
MathUtils.atan2(-0.0, -0.0)         # 0.0
MathUtils.is_scalar_number(3.14)    # True
MathUtils.fix_negative_zero([-0.0]) # [0.0]
```

| Method | Signature | Description |
|--------|-----------|-------------|
| `is_zero` | `(x, eps=EPSILON) -> bool` | `abs(x) < eps` |
| `is_close` | `(a, b, relative_tolerance=1e-9, absolute_tolerance=0.0) -> bool` | Relative+absolute comparison |
| `is_equal` | `(a, b, eps=EPSILON) -> bool` | `abs(a-b) < eps` |
| `atan2` | `(y, x) -> float` | `math.atan2` with signed-zero cleanup |
| `is_scalar_number` | `(x) -> bool` | `isinstance(x, (int, float))` |
| `fix_negative_zero` | `(value) -> object` | Converts `-0.0` -> `0.0`, supports nested lists |

**`EPSILON`**: `sys.float_info.epsilon * 10.0`

---

### 2.7 `python_optimizers.py`

**Module:** `ansys.aedt.core.generic.python_optimizers`

#### `ThreadTrace`

A killable thread subclass using `sys.settrace`.

```python
from ansys.aedt.core.generic.python_optimizers import ThreadTrace
worker = ThreadTrace(target=my_function)
worker.start()
worker.join(timeout=10)
if worker.is_alive():
    worker.kill()
    worker.join()
```

#### `GeneticAlgorithm`

Elitist genetic algorithm for optimization with integer, continuous, boolean, or mixed variables.

```python
import numpy as np
from ansys.aedt.core.generic.python_optimizers import GeneticAlgorithm

def objective(X): return np.sum(X**2)
bounds = np.array([[-5, 5]] * 3)
ga = GeneticAlgorithm(function=objective, dim=3, var_type="real", boundaries=bounds,
    algorithm_parameters={"max_num_iteration": 100, "population_size": 50, "crossover_prob": 0.5,
        "parents_portion": 0.3, "crossover_type": "uniform", "mutation_prob": 0.2, "elite_ratio": 0.05})
ga.run()
print(ga.best_variable, ga.best_function)
```

**Key attributes after `run()`:** `best_variable`, `best_function`, `report`, `pop`, `output_dict`

**Crossover types:** `"uniform"`, `"one_point"`, `"two_point"`

---

### 2.8 `scheduler.py`

**Module:** `ansys.aedt.core.generic.scheduler`

HPC job submission configuration for AEDT simulations.

#### `HPCMethod` (IntEnum)

| Value | Name | Description |
|-------|------|-------------|
| 1 | `USE_TASKS_AND_CORES` | Tasks + cores distribution |
| 2 | `USE_RAM_CONSTRAINED` | RAM-constrained distribution |
| 3 | `USE_NODES_AND_CORES` | Nodes + cores distribution |
| 4 | `USE_AUTO_HPC` | AEDT auto-detect resources |

#### `JobConfigurationData`

```python
from ansys.aedt.core.generic.scheduler import JobConfigurationData

config = JobConfigurationData(aedt_version="2026.1", num_cores=16, num_tasks=4,
    num_nodes=2, ram_per_core=4.0, job_name="MySimulation", ng_solve=True)
config.save_areg("Job_Settings.areg")
config.to_json("job_config.json")
config2 = JobConfigurationData.from_json("job_config.json")
```

**Key properties:** `num_cores`, `num_tasks`, `num_nodes`, `num_gpus`, `ram_limit`, `ram_per_core`, `exclusive`, `auto_hpc`, `job_name`, `monitor`, `ng_solve`, `cluster_name`, `product_full_path`, `use_ppe`, `wait_for_license`

#### `get_aedt_exe()`

```python
from ansys.aedt.core.generic.scheduler import get_aedt_exe
exe_path = get_aedt_exe("25.1")  # Returns Path to ansysedt.exe
```

#### Constants

| Constant | Default |
|----------|---------|
| `DEFAULT_NUM_CORES` | `4` |
| `DEFAULT_NUM_GPUS` | `0` |
| `DEFAULT_NUM_NODES` | `1` |
| `DEFAULT_NUM_TASKS` | `1` |
| `DEFAULT_RAM_LIMIT` | `90` |
| `DEFAULT_RAM_PER_CORE` | `2.0` |

---

## 3. `internal/` Modules

### 3.1 `errors.py`

**Module:** `ansys.aedt.core.internal.errors`

Three exception types, all inheriting from `RuntimeError`:

| Exception | Description |
|-----------|-------------|
| `GrpcApiError` | gRPC API communication failures |
| `MethodNotSupportedError` | Unsupported method calls |
| `AEDTRuntimeError` | General AEDT runtime errors |

---

### 3.2 `checks.py`

**Module:** `ansys.aedt.core.internal.checks`

#### `min_aedt_version(min_version: str)`

Decorator that raises `AEDTRuntimeError` if the connected AEDT version is below `min_version`.

```python
from ansys.aedt.core.internal.checks import min_aedt_version

class MyDesign:
    @min_aedt_version("2026.1")
    def new_feature(self):
        ...
```

Resolves `odesktop` from `self` by checking: `odesktop`, `_odesktop`, `_desktop`, `__<ClassName>__app.odesktop`, `desktop_class.odesktop`.

#### `requires_graphical_dependency(*dependencies)`

Decorator ensuring graphics packages are installed.

```python
@requires_graphical_dependency("pyvista", "vtk")
def plot_results(self): ...
```

#### `check_dependency_available(dependency, warning=False)`

Checks if a graphics dependency is available. Caches results in `_GRAPHICS_DEPENDENCIES`.

#### `install_message(dependency, target, level="method")`

Generates user-friendly install instructions like: `"Dependency pyvista is required. Please install the graphics target...`

#### `is_notebook()`

Returns `True` if running in Jupyter.

---

### 3.3 `load_aedt_file.py`

**Module:** `ansys.aedt.core.internal.load_aedt_file`

Parses binary/ASCII `.aedt` project files into Python dicts.

#### `load_entire_aedt_file(filename) -> dict`

```python
from ansys.aedt.core.internal.load_aedt_file import load_entire_aedt_file
data = load_entire_aedt_file(r"C:\Projects\filter_design.aedt")
```

#### `load_keyword_in_aedt_file(filename, keyword, design_name=None) -> dict`

```python
from ansys.aedt.core.internal.load_aedt_file import load_keyword_in_aedt_file
preview = load_keyword_in_aedt_file("project.aedt", "ProjectPreview")
```

#### `get_designs(filename) -> list[str]`

```python
from ansys.aedt.core.internal.load_aedt_file import get_designs
names = get_designs("project.aedt")  # ["HFSSDesign1", "HFSSDesign2"]
```

#### Internal Details

- Pre-compiled regex patterns: `_remove_quotes`, `_split_list_elements`, `_round_bracket_list`, `_square_bracket_list`, `_key_parse`, `_begin_search`
- Recognized keywords: `CurvesInfo`, `Sweep Operations`, `PropDisplayMap`, `Cells`, `Active`, `Rotation`, `PostProcessingCells`
- Recognized sub-keys: `simple(`, `IDMap(`, `WireSeg(`, `PC(`, `Range(`
- Values parsed as C# types: `true`/`false` -> `bool`, int/float auto-detected

---

### 3.4 `grpc_plugin_dll_class.py`

**Module:** `ansys.aedt.core.internal.grpc_plugin_dll_class`

The core gRPC communication layer - wraps AEDT `PyDesktopPlugin.dll`/`.so`.

#### Class Hierarchy

```
list
 +-- AedtBlockObj          - Named key-value block from AEDT API

AedtObjWrapper              - Proxy for any AEDT COM-like object
 +-- AedtPropServer         - AEDT object with property get/set support

AEDT                        - Top-level DLL wrapper / connection manager
```

#### `AEDT` - Connection Manager

```python
from ansys.aedt.core.internal.grpc_plugin_dll_class import AEDT
aedt = AEDT(path_dir="/path/to/AEDT/install")
aedt.CreateAedtApplication(machine="", port=0, NGmode=False, alwaysNew=True)
desktop = aedt.odesktop
```

| Method | Description |
|--------|-------------|
| `__init__(pathDir)` | Loads `PyDesktopPlugin.dll`/`.so`, sets up function signatures |
| `CreateAedtApplication(machine, port, NGmode, alwaysNew)` | Creates the AEDT gRPC session |
| `recreate_application(force=False)` | Reconnects to AEDT |
| `InvokeAedtObjMethod(objectID, funcName, argv)` | Calls a method on an AEDT object by ID |
| `ReleaseAedtObject(objectID)` | Releases a single AEDT object |
| `ReleaseAll()` | Releases all AEDT objects |

#### `AedtObjWrapper` - AEDT Object Proxy

Wraps an AEDT object identified by `objectID`. All method calls are dynamically dispatched to AEDT via gRPC.

| Mechanism | Description |
|-----------|-------------|
| `__getattr__(funcName)` | Returns a bound method that calls `__Invoke__` |
| `__Invoke__(funcName, argv)` | Calls `dllapi.AedtAPI.InvokeAedtObjMethod` with retry |
| `__dir__()` | Returns available method names |
| `match(patternStr)` | Regex-filtered method list (IronPython compat) |

#### `AedtPropServer` - Property Server

Extends `AedtObjWrapper` with property get/set via `GetPropNames`, `GetPropValue`, `SetPropValue`.

#### `AedtBlockObj` - Block Object

A `list` subclass that supports named key access:

```python
block = AedtBlockObj(["NAME:Settings", "Frequency:=", "1GHz", "Ports:=", 2])
block.GetName()           # "Settings"
block["Frequency"]         # "1GHz"
block.keys()               # ["Frequency", "Ports"]
```

---

### 3.5 `desktop_sessions.py`

**Module:** `ansys.aedt.core.internal.desktop_sessions`

Simple session registry - module-level dicts.

```python
from ansys.aedt.core.internal.desktop_sessions import _desktop_sessions
# _desktop_sessions: dict[int, Desktop] = {}
# Maps AEDT process IDs to Desktop instances.
```

- `_desktop_sessions: dict[int, Desktop]` - Active desktop sessions indexed by process ID.
- `_edb_sessions: list` - Active EDB sessions.

---

### 3.6 `filesystem.py`

**Module:** `ansys.aedt.core.internal.filesystem`

#### `Scratch`

Context-manager-enabled scratch directory with auto-cleanup.

```python
from ansys.aedt.core.internal.filesystem import Scratch

with Scratch(local_path=r"C:\Temp") as scratch:
    dst = scratch.copyfile(r"C:\data\input.aedt")
    sub = scratch.create_sub_folder("results")
# Auto-removed on exception or if volatile=True
```

| Method | Description |
|--------|-------------|
| `__init__(local_path, permission=0o777, volatile=False)` | Creates scratch directory |
| `path` (property) | Returns the scratch directory path |
| `remove()` | Deletes the scratch directory |
| `copyfile(src_file, dst_filename=None)` | Copies file into scratch |
| `copyfolder(src_folder, destfolder)` | Copies folder |
| `create_sub_folder(name="")` | Creates a subfolder |

#### Utility Functions

| Function | Description |
|----------|-------------|
| `search_files(dirname, pattern="*")` | Glob files in directory |
| `my_location()` | Returns the filesystem.py parent directory |
| `get_json_files(start_folder)` | Recursively finds all `.json` files |
| `is_safe_path(path, allowed_extensions=None)` | Validates path safety |

---

## 4. gRPC Communication Flow

```
User Code                          PyAEDT Internal                          AEDT Engine
----------                          ---------------                          ----------

hfss.create_box(                   1. Application layer validates args
  name="Box1",                        and converts units
  origin=[0,0,0],
  sizes=[1,1,1]                    2. _dict2arg() serializes args
)                                     into nested list format:
                                     ["NAME:BoxParameters",
                                      "XPosition:=", "0mm", ...]
                                        |
                                        v
                                  3. oeditor.CreateBox(arg_list)
                                     |
                                     v
                                  4. AedtObjWrapper.__getattr__("CreateBox")
                                     |
                                     v
                                  5. AedtObjWrapper.__Invoke__("CreateBox", args)
                                     |  - Checks debug_grpc_api_logger
                                     |  - If use_multi_desktop: recreates app
                                     |  - Calls _retry_ntimes()
                                     |
                                     v
                                  6. AEDT.AedtAPI.InvokeAedtObjMethod(
                                         objectID, "CreateBox", args)
                                     |
                                     v  (ctypes -> DLL)
                                  7. PyDesktopPlugin.dll/so
                                     |
                                     v  (gRPC protocol)
                                  8. AEDT Electronics Desktop
                                     |
                                     v
                                  9. HFSS Solver Engine
```

**Key insight:** `_dict2arg()` is the serialization bridge. It converts Python-friendly dicts into the nested list format that AEDT's native API expects.

**Error handling at each layer:**
- `_dict2arg` / `_arg2dict`: Data validation
- `AedtObjWrapper.__Invoke__`: Retry logic (`_retry_ntimes`), `GrpcApiError` on failure
- `AEDT.CreateAedtApplication`: Connection failure -> `GrpcApiError`
- `min_aedt_version` decorator: Version incompatibility -> `AEDTRuntimeError`

---

## 5. Key Patterns & Conventions

### `@pyaedt_function_handler()` Decorator

Nearly every public function in `generic/` is decorated with this. It provides error handling, logging, input validation, and consistent return types.

### Settings Singleton Pattern

```python
from ansys.aedt.core.generic.settings import settings
# Module-level singleton, imported everywhere
```

### Remote Session Abstraction

Many functions in `file_utils.py` check `settings.remote_rpc_session` to transparently handle remote files via RPyC:

```python
def check_if_path_exists(path):
    if settings.remote_rpc_session:
        return settings.remote_rpc_session.filemanager.pathexists(str(path))
    return Path(path).exists()
```

### Configuration Import/Export Flow

```
Export:  app.configurations.export_config(path)
         -> _export_general()     -> dict_out["general"]
         -> _export_variables()   -> dict_out["general"]["variables"]
         -> _export_boundaries()  -> dict_out["boundaries"]
         -> _export_setups()      -> dict_out["setups"]
         -> write_configuration_file(dict_out, path)

Import:  app.configurations.import_config(path)
         -> read_configuration_file(path)
         -> For each section:
           -> _convert_objects()  (remap IDs -> names)
           -> _update_*()         (create or update in AEDT)
         -> results tracks success/failure
```

### Type Aliases

| Alias | Definition |
|-------|------------|
| `StrPath` | `str | Path` |
| `AppType` | Protocol for PyAEDT application classes |

---

*Generated from the PyAEDT official source tree (MIT License).*
