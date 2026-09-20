# PyAEDT Application Types & Special Modules Reference

## Table of Contents
1. [Application Types](#application-types)
2. [Special Modules](#special-modules)
3. [Quick Decision Guide](#quick-decision-guide)

---

## Application Types

### 1. Circuit
**File:** `circuit.py` | **Class:** `Circuit`

**Purpose:** Interface to AEDT Circuit design for schematic-based simulation of electronic circuits, signal integrity, and power integrity.

**When to use:**
- Signal integrity analysis (TDR, eye diagrams, S-parameters)
- Power integrity analysis
- Creating schematics from SPICE netlists
- IBIS/AMI simulations
- Circuit-level electromagnetic co-simulation

**Constructor:**
```python
Circuit(
    project=None,           # Project name or path to .aedt file
    design=None,            # Design name
    solution_type=None,     # e.g., "NexximLNA", "NexximTransient"
    setup=None,             # Setup name
    version=None,           # AEDT version (e.g., "2026.1")
    non_graphical=False,    # Run in non-graphical mode
    new_desktop=False,      # Launch new AEDT instance
    close_on_exit=False,    # Close AEDT on exit
    student_version=False,
    machine="", port=0, aedt_process_id=None, remove_lock=False
)
```

**Key Methods:**
- `create_schematic_from_netlist(input_file)` -- Create schematic from HSPICE/SPICE netlist
- `create_schematic_from_mentor_netlist(input_file)` -- Create schematic from Mentor netlist
- `import_touchstone_solution(input_file, solution)` -- Import Touchstone S-parameter data
- `export_fullwave_spice(...)` -- Export full-wave SPICE model
- `create_touchstone_report(...)` -- Generate S-parameter report
- `push_excitations(...)` -- Push excitation settings to linked designs
- `create_source(source_type, name)` -- Create circuit excitation source
- `set_differential_pair(...)` -- Configure differential pairs
- `import_edb_in_circuit(input_dir)` -- Import EDB design into Circuit
- `create_tdr_schematic_from_snp(...)` -- Create TDR analysis schematic
- `create_lna_schematic_from_snp(...)` -- Create LNA schematic
- `create_ami_schematic_from_snp(...)` -- Create AMI serial link schematic
- `create_ibis_schematic_from_snp(...)` -- Create IBIS schematic
- `create_schematic_from_asc_file(input_file)` -- Create schematic from .asc file
- `add_netlist_datablock(input_file, name)` -- Add netlist as data block

**Example:**
```python
from ansys.aedt.core import Circuit
circuit = Circuit(project="my_circuit", version="2026.1")
circuit.create_schematic_from_netlist("my_netlist.sp")
circuit.analyze()
```

---

### 2. CircuitNetlist
**File:** `circuit_netlist.py` | **Class:** `CircuitNetlist`

**Purpose:** Lightweight netlist-only circuit interface for text-based circuit definitions without full schematic GUI.

**When to use:**
- Quick circuit simulation from netlist files
- Automated batch circuit simulations
- When schematic GUI is not needed

**Constructor:**
```python
CircuitNetlist(project=None, design=None, solution_type=None,
               setup=None, version=None, non_graphical=False,
               new_desktop=False, close_on_exit=False,
               student_version=False, machine="", port=0, aedt_process_id=None)
```

---

### 3. Maxwell3d / Maxwell2d
**File:** `maxwell.py` | **Classes:** `Maxwell3d`, `Maxwell2d`, `Maxwell` (base mixin)

**Purpose:** Electromagnetic field simulation for electric machines, transformers, actuators, and other EM devices.

**When to use:**
- Motor and generator design (rotating machines)
- Transformer analysis
- Electromagnetic actuator design
- Eddy current analysis
- Magnetostatic and electrostatic simulations
- Transient electromagnetic analysis

**Solution Types:**
- `Magnetostatic` -- Static magnetic fields
- `EddyCurrent` -- AC magnetic / eddy current
- `Transient` -- Time-varying electromagnetic
- `Electric` -- Electrostatic
- `DCConduction` / `ACConduction`

**Constructor (Maxwell3d):**
```python
Maxwell3d(project=None, design=None, solution_type=None,
          setup=None, version=None, non_graphical=False,
          new_desktop=False, close_on_exit=False,
          student_version=False, machine="", port=0,
          aedt_process_id=None, remove_lock=False)
```

**Key Methods:**
- `assign_winding(...)` -- Create electromagnetic winding excitation
- `assign_coil(...)` -- Assign coil excitation
- `assign_current(winding, current)` -- Set current excitation
- `assign_voltage(winding, voltage)` -- Set voltage excitation
- `assign_voltage_drop(...)` -- Apply voltage drop boundary
- `assign_floating(...)` -- Apply floating conductor
- `assign_rotate_motion(...)` -- Set up rotational motion (Transient)
- `assign_translate_motion(...)` -- Set up translational motion
- `assign_force(...)` / `assign_torque(...)` -- Assign force/torque parameters
- `assign_matrix(...)` -- Assign inductance/resistance matrix
- `set_core_losses(assignment)` -- Enable core loss calculation
- `eddy_effects_on(assignment)` -- Enable eddy current effects
- `change_symmetry_multiplier(value)` -- Set design symmetry multiplier
- `change_inductance_computation(...)` -- Configure inductance calculation
- `apply_skew(...)` -- Apply skew to 2D model
- `assign_symmetry(assignment, ...)` -- Apply symmetry boundary
- `assign_current_density(...)` -- Apply current density
- `assign_radiation(assignment)` -- Apply radiation boundary
- `enable_harmonic_force(...)` -- Enable harmonic force calculation
- `create_external_circuit(...)` -- Link to external circuit design
- `export_matrix(...)` -- Export RL/CG matrix data
- `create_setup(name, setup_type)` -- Create analysis setup
- `assign_insulating(assignment)` -- Apply insulating boundary (3D)
- `assign_impedance(...)` -- Apply impedance boundary (3D)
- `assign_master_slave(...)` -- Apply master/slave boundary (3D/2D)
- `assign_balloon(...)` -- Apply balloon boundary (2D only)
- `assign_end_connection(...)` -- Apply end connection (2D only)
- `assign_vector_potential(...)` -- Apply vector potential (2D)

**Example:**
```python
from ansys.aedt.core import Maxwell3d
m3d = Maxwell3d(solution_type="Transient", version="2026.1")
m3d.modeler.create_cylinder(cs_axis="Z", position=[0,0,0], radius=10, height=20, name="Rotor")
m3d.assign_winding(winding_type="Current", current="10A")
m3d.assign_rotate_motion("Band", positive_limit=360)
m3d.create_setup(name="Setup1", setup_type="Transient")
m3d.analyze()
```

---

### 4. Icepak
**File:** `icepak.py` | **Class:** `Icepak`

**Purpose:** Thermal simulation and conjugate heat transfer analysis for electronics cooling.

**When to use:**
- Electronics thermal management
- PCB-level thermal analysis
- Heat sink design and optimization
- Fan and blower modeling
- Multi-physics thermal-EM coupling
- Transient thermal analysis

**Solution Types:** `SteadyState`, `Transient`

**Constructor:**
```python
Icepak(project=None, design=None, solution_type=None,
       setup=None, version=None, non_graphical=False,
       new_desktop=False, close_on_exit=False,
       student_version=False, machine="", port=0,
       aedt_process_id=None, remove_lock=False)
```

**Key Methods:**
- `assign_grille(...)` -- Apply grille boundary (fan/filter)
- `assign_openings(air_faces)` -- Set opening boundary
- `assign_free_opening(...)` -- Free opening boundary
- `assign_pressure_free_opening(...)` -- Pressure-free opening
- `assign_velocity_free_opening(...)` -- Velocity-specified opening
- `assign_mass_flow_free_opening(...)` -- Mass flow opening
- `assign_source_blocks_from_list(...)` -- Create power source blocks
- `assign_source(...)` -- Assign power/heat source
- `assign_solid_block(...)` -- Create solid block with material
- `assign_hollow_block(...)` -- Create hollow block for fluid
- `assign_stationary_wall(...)` -- Apply stationary wall
- `assign_stationary_wall_with_heat_flux(...)` -- Wall with heat flux
- `assign_stationary_wall_with_temperature(...)` -- Wall with fixed temp
- `assign_stationary_wall_with_htc(...)` -- Wall with HTC
- `assign_conducting_plate(...)` -- Thin conducting plate
- `assign_resistance(...)` -- Resistance model
- `assign_recirculation_opening(...)` -- Recirculation boundary
- `assign_blower_type1/type2(...)` -- Blower models
- `assign_symmetry_wall(...)` -- Symmetry boundary
- `assign_adiabatic_plate(...)` -- Adiabatic plate
- `create_fan(...)` -- Create fan component
- `create_ipk_3dcomponent_pcb(...)` -- Create 3D component PCB
- `create_pcb_from_3dlayout(...)` -- Import PCB from 3D layout
- `assign_em_losses(...)` -- Import EM losses from HFSS
- `assign_2way_coupling(...)` -- 2-way thermal-flow coupling
- `eval_surface_quantity_from_field_summary(...)` -- Surface field evaluation
- `eval_volume_quantity_from_field_summary(...)` -- Volume field evaluation
- `export_summary(...)` -- Export thermal summary
- `generate_fluent_mesh(...)` -- Generate Fluent mesh
- `import_idf(...)` -- Import IDF board file
- `create_two_resistor_network_block(...)` -- 2-resistor compact model
- `create_resistor_network_from_matrix(...)` -- Network from matrix
- `assign_surface_material(obj, mat)` -- Surface material properties
- `create_parametric_heatsink_on_face(...)` -- Parametric heat sink
- `create_setup(name, setup_type)` -- Create analysis setup
- `clear_linked_data()` -- Clear linked design data

**Example:**
```python
from ansys.aedt.core import Icepak
ipk = Icepak(project="thermal_design", version="2026.1")
ipk.modeler.create_box([0,0,0], [100,100,10], name="Board", material="FR-4")
ipk.assign_solid_block("Board", power="5W")
ipk.assign_openings(air_faces)
ipk.create_setup(name="Setup1")
ipk.analyze()
```

---

### 5. Q3d / Q2d
**File:** `q3d.py` | **Classes:** `Q3d`, `Q2d`, `QExtractor` (base)

**Purpose:** Parasitic extraction of RLC parameters for IC packages, PCBs, and interconnects.

**When to use:**
- IC package parasitic extraction
- PCB interconnect extraction
- Power/ground plane analysis
- RLCG matrix extraction
- Signal integrity for packages/PCBs

**Solution Types:** `Q3D` (3D), `Q2D`/`EXTRACTOR2D` (2D cross-section)

**Constructor (Q3d):**
```python
Q3d(project=None, design=None, solution_type=None,
    setup=None, version=None, non_graphical=False,
    new_desktop=False, close_on_exit=False,
    student_version=False, machine="", port=0,
    aedt_process_id=None, remove_lock=False)
```

**Key Methods:**
- `auto_identify_nets()` -- Auto-identify nets in design
- `assign_net(net_name, net_type)` -- Assign net to objects
- `source(assignment, net_name)` -- Assign source terminal
- `sink(assignment, net_name)` -- Assign sink terminal
- `assign_single_conductor(...)` -- Single conductor (Q2D)
- `assign_huray_finitecond_to_edges(...)` -- Huray roughness model
- `auto_assign_conductors()` -- Auto-assign conductor types
- `assign_thin_conductor(...)` -- Thin conductor boundary
- `set_material_thresholds(...)` -- Material conductivity thresholds
- `toggle_net(net_name, net_type)` -- Toggle net type
- `insert_reduced_matrix(...)` -- Insert reduced matrix
- `insert_em_field_line/rectangle/box/sphere(...)` -- Near-field setups
- `export_matrix_data(...)` -- Export RL/CG matrix data
- `export_equivalent_circuit(...)` -- Export equivalent circuit model
- `export_w_elements(...)` -- Export W-element models (Q2D)
- `get_mutual_coupling(...)` -- Mutual coupling between nets
- `create_setup(name, **kwargs)` -- Create analysis setup

**Example:**
```python
from ansys.aedt.core import Q3d
q3d = Q3d(project="package_extraction", version="2026.1")
q3d.auto_identify_nets()
q3d.source("Pin1", "VDD")
q3d.sink("Pin2", "GND")
q3d.create_setup(name="Setup1")
q3d.analyze()
q3d.export_matrix_data("output_matrix.txt")
```

---

### 6. Hfss3dLayout
**File:** `hfss3dlayout.py` | **Class:** `Hfss3dLayout`

**Purpose:** Full-wave EM simulation for PCB, IC package, and interconnect layouts using the HFSS 3D Layout engine.

**When to use:**
- PCB-level full-wave EM simulation
- Package-level EM analysis
- Multi-board co-simulation
- Signal integrity on routed PCBs
- DCIR (DC resistance) analysis
- Import from common PCB formats (ODB++, BRD, GDS, DXF, Gerber)

**Constructor:**
```python
Hfss3dLayout(project=None, design=None, solution_type=None,
             setup=None, version=None, non_graphical=True,  # Note: default True
             new_desktop=False, close_on_exit=False,
             student_version=False, machine="", port=0,
             aedt_process_id=None, ic_mode=None, remove_lock=False)
```

**Key Methods:**
- `create_edge_port(...)` -- Create edge port
- `create_wave_port(...)` -- Create wave port
- `create_wave_port_from_two_conductors(...)` -- Wave port from two conductors
- `create_differential_port(...)` -- Differential port
- `create_coax_port(...)` -- Coaxial port
- `create_pin_port(...)` -- Pin port
- `create_ports_by_nets(...)` -- Auto-create ports by net
- `create_ports_on_component_by_nets(...)` -- Ports on component nets
- `delete_port(name)` -- Delete a port
- `import_edb(input_folder)` -- Import EDB project
- `import_gds/dxf/gerber/brd/awr/ipc2581/odb(...)` -- Import layout formats
- `create_linear_count_sweep(...)` -- Linear frequency sweep
- `create_linear_step_sweep(...)` -- Linear step sweep
- `create_single_point_sweep(...)` -- Single frequency point
- `set_differential_pair(...)` -- Configure differential pairs
- `set_export_touchstone(...)` -- Configure Touchstone export
- `set_meshing_settings(...)` -- Configure mesh settings
- `edit_cosim_options(...)` -- Edit co-simulation options
- `export_3d_model(output_file)` -- Export 3D model
- `enable_rigid_flex()` -- Enable rigid-flex design
- `edit_hfss_extents(...)` -- Modify simulation extents
- `get_dcir_solution_data(...)` -- DCIR simulation results
- `validate_full_design(...)` -- Full design validation
- `create_scattering(...)` -- S-parameter report
- `dissolve_component(component)` -- Dissolve to primitives

**Example:**
```python
from ansys.aedt.core import Hfss3dLayout
h3d = Hfss3dLayout(project="my_pcb.aedt", version="2026.1")
h3d.create_linear_count_sweep("Setup1", "Sweep1", 0.1, 10, 1001)
h3d.analyze()
```

---

### 7. Mechanical
**File:** `mechanical.py` | **Class:** `Mechanical`

**Purpose:** Structural and thermal-mechanical FEA, typically coupled with electromagnetic solvers.

**When to use:**
- Structural stress analysis from EM forces
- Thermal-mechanical deformation
- EM loss mapping to thermal solver
- Vibration and modal analysis
- Multiphysics EM-thermal-structural coupling

**Solution Types:** `Thermal`, `Structural`, `Modal`

**Constructor:**
```python
Mechanical(project=None, design=None, solution_type=None,
           setup=None, version=None, non_graphical=False,
           new_desktop=False, close_on_exit=False,
           student_version=False, machine="", port=0,
           aedt_process_id=None, remove_lock=False)
```

**Key Methods:**
- `assign_em_losses(design, setup, ...)` -- Map EM losses from HFSS/Maxwell
- `assign_thermal_map(...)` -- Thermal mapping from Icepak
- `assign_uniform_convection(...)` -- Uniform convection condition
- `assign_uniform_temperature(...)` -- Uniform temperature boundary
- `assign_frictionless_support(assignment)` -- Frictionless support
- `assign_fixed_support(assignment)` -- Fixed support boundary
- `assign_thermal_condition_uniform(...)` -- Uniform thermal condition
- `assign_heat_flux(assignment, value)` -- Heat flux boundary
- `assign_heat_generation(assignment, value)` -- Heat generation source
- `assign_2way_coupling(setup, iterations)` -- 2-way thermal-structural coupling
- `create_setup(name, setup_type)` -- Create analysis setup

---

### 8. Rmxprt
**File:** `rmxprt.py` | **Classes:** `Rmxprt`, `RMXprtModule`, `Machine`, `Stator`, `Rotor`, `Shaft`, `Circuit`

**Purpose:** Electric machine design and analysis using the RMxprt analytical motor/generator solver.

**When to use:**
- Rapid motor/generator design exploration
- Analytical machine performance estimation
- Motor sizing and preliminary design
- Export to Maxwell for detailed FEA

**Constructor:**
```python
Rmxprt(project=None, design=None, solution_type=None,
       model_units="mm",       # "mm" or "in"
       setup=None, version=None, non_graphical=False,
       new_desktop=False, close_on_exit=False,
       student_version=False, machine="", port=0,
       aedt_process_id=None, remove_lock=False)
```

**Key Methods:**
- `create_setup(name, setup_type)` -- Create analysis setup
- `export_configuration(output_file)` -- Export design to JSON config
- `import_configuration(input_file)` -- Import design from JSON config

**Sub-objects:**
- `app.general` -- Machine general parameters
- `app.stator` -- Stator design parameters
- `app.rotor` -- Rotor design parameters
- `app.shaft` -- Shaft parameters
- `app.circuit` -- Circuit/winding parameters

**Example:**
```python
from ansys.aedt.core import Rmxprt
rm = Rmxprt(project="motor_design", version="2026.1")
rm.design_type = "BLDC"
rm.stator["Slot Type"] = 2
rm.create_setup()
rm.analyze()
rm.export_configuration("motor_config.json")
```

---

### 9. TwinBuilder
**File:** `twinbuilder.py` | **Class:** `TwinBuilder`

**Purpose:** Digital twin creation and system-level simulation for model-based systems engineering.

**When to use:**
- Creating digital twins of physical systems
- System-level simulation with ROM (Reduced Order Models)
- Co-simulation with Simulink, FMI/FMU
- Model-based design and validation
- Connecting multiphysics simulations

**Constructor:**
```python
TwinBuilder(project=None, design=None, solution_type=None,
            setup=None, version=None, non_graphical=False,
            new_desktop=False, close_on_exit=False,
            student_version=False, machine="", port=0,
            aedt_process_id=None, remove_lock=False)
```

**Key Methods:**
- `create_schematic_from_netlist(input_file)` -- Create schematic from HSpice netlist
- `set_end_time(expression)` -- Set simulation end time
- `set_hmin(expression)` -- Set minimum time step
- `set_hmax(expression)` -- Set maximum time step
- `set_sim_setup_parameter(...)` -- Configure simulation parameters
- `create_subsheet(name, design_name)` -- Create hierarchical sub-sheet
- `add_q3d_dynamic_component(...)` -- Add Q3D dynamic component (ROM)
- `add_excitation_model(...)` -- Add excitation model

---

### 10. Emit
**File:** `emit.py` | **Class:** `Emit`

**Purpose:** EMIT electromagnetic interference analysis for RF systems -- analyzes interference between radios, antennas, and transceivers.

**When to use:**
- RF co-site interference analysis
- EMI/EMC analysis for multi-radio platforms
- Antenna-to-antenna coupling
- Radio frequency interference prediction
- Platform-level RF system analysis

**Constructor:**
```python
Emit(project=None, design=None, solution_type=None,
     version=None, non_graphical=False,
     new_desktop=True,       # Note: default True (unique to EMIT)
     close_on_exit=True,     # Note: default True
     student_version=False, machine="", port=0,
     aedt_process_id=None, remove_lock=False)
```

**Key Properties:**
- `app.modeler` -- Access to `ModelerEmit`
- `app.couplings` -- Access to `CouplingsEmit`
- `app.schematic` -- Access to `EmitSchematic`
- `app.results` -- Access to `Results` (interference analysis)

**Key Methods:**
- `set_units(unit_type, unit_value)` -- Set analysis units
- `get_units(unit_type)` -- Get current units
- `save_project(file_name, overwrite)` -- Save project
- `close_project(name, save)` -- Close project
- `version(detailed)` -- Get version info

---

## Special Modules

### 11. common_rpc (Remote RPC)
**File:** `common_rpc.py`

**Purpose:** Remote procedure call infrastructure for running PyAEDT on a remote server.

**When to use:**
- Running PyAEDT on a remote server (HPC, cloud)
- Controlling AEDT on a different machine
- Building client-server architectures
- Multi-machine co-simulation

#### `pyaedt_service_manager()` -- Start service manager on SERVER
```python
from ansys.aedt.core.common_rpc import pyaedt_service_manager
pyaedt_service_manager(
    host=None,             # Server hostname/IP (default: AEDT_HOST or hostname)
    port=17878,            # Listening port
    aedt_version=None,     # AEDT version
    student_version=False
)
```

#### `launch_server()` -- Start RPyC server on SERVER
```python
from ansys.aedt.core.common_rpc import launch_server
launch_server(
    host=None, port=18000, ansysem_path=None,
    non_graphical=False, threaded=True, secure=True, listen_all=False
)
```

#### `create_session()` -- Connect from CLIENT
```python
from ansys.aedt.core.common_rpc import create_session
client = create_session(
    host="server-hostname",        # Server address
    client_port=None,              # Auto-assigned if None
    launch_aedt_on_server=True,    # Launch AEDT on server
    aedt_port=None,                # AEDT gRPC port
    non_graphical=False, secure=True, listen_all=False
)
```

#### `connect()` -- Connect to existing session
```python
from ansys.aedt.core.common_rpc import connect
connection = connect(host="server-hostname", aedt_client_port=18000)
```

**Typical Remote Workflow:**
```
SERVER MACHINE                          CLIENT MACHINE
--------------                          --------------
pyaedt_service_manager(port=17878)      client = create_session(
                                            host="server.com",
                                            launch_aedt_on_server=True
                                        )
                                        # Use client object for remote AEDT ops
```

---

### 12. EDB (Electronics Database)
**File:** `edb.py` | **Function:** `Edb()`

**Purpose:** Programmatic access to Ansys Electronics Database (AEDB) for PCB/package layout manipulation without AEDT GUI.

**When to use:**
- PCB/package layout manipulation before simulation
- Stackup and layer definition
- Net and via editing
- Importing board files (BRD, XML, GDS, DXF)
- Pre-processing for HFSS 3D Layout or Q3D
- Fast, GUI-free layout access

**Constructor (factory function):**
```python
from ansys.aedt.core import Edb
app = Edb(
    edbpath=None,           # Path to .aedb folder or layout file
    cellname=None,          # Cell name to select
    isreadonly=False,       # Read-only mode
    version=None,           # EDB version (e.g., "2026.1")
    isaedtowned=False,      # Launched from HFSS 3D Layout
    oproject=None,          # Reference to AEDT project
    student_version=False,
    use_ppe=False,          # Parallel processing engine
    technology_file=None    # Technology file (GDS only)
)
```

**Note:** `Edb()` is a **factory function** that returns a `pyedb.Edb` object (lazy import).

**Example:**
```python
from ansys.aedt.core import Edb
edb = Edb("/path/to/myboard.aedb", version="2026.1")
edb["s1"] = "0.25 mm"
edb.stackup.import_stackup("stackup.xml")
edb.save()
edb.close()
```

**Siwave integration:**
```python
from ansys.aedt.core import Siwave
siwave = Siwave(specified_version="2026.1")
```

---

### 13. FilterSolutions
**File:** `filtersolutions.py` | **Classes:** `FilterDesignBase`, `LumpedDesign`, `DistributedDesign`

**Purpose:** RF/microwave filter synthesis and design -- lumped element and distributed filter design.

**When to use:**
- RF filter design and synthesis
- Lumped element filter design
- Distributed filter design (microstrip, stripline, waveguide)
- Filter optimization
- Export filter designs to AEDT (Circuit, HFSS 3D Layout)

**Design Types:**

#### `LumpedDesign` -- Lumped element filters
```python
from ansys.aedt.core.filtersolutions import LumpedDesign
design = LumpedDesign(version="2026.1")
```

#### `DistributedDesign` -- Distributed element filters (requires 2025 R2+)
```python
from ansys.aedt.core.filtersolutions import DistributedDesign
design = DistributedDesign(version="2026.1")
```

**Sub-objects (both types):**
- `design.attributes` -- Filter type, class, order
- `design.topology` -- Filter topology
- `design.parasitics` -- Parasitic element models
- `design.ideal_response` -- Ideal frequency response
- `design.export_to_aedt` -- Export to AEDT

**LumpedDesign additional objects:**
- `design.source_impedance_table` -- Source impedance
- `design.load_impedance_table` -- Load impedance
- `design.multiple_bands_table` -- Multi-band config
- `design.optimization_goals_table` -- Optimization goals
- `design.leads_and_nodes` -- Lead and node models

**DistributedDesign additional objects:**
- `design.substrate` -- Substrate material/geometry
- `design.geometry` -- Physical geometry parameters
- `design.radial` -- Radial stub parameters

**Example:**
```python
from ansys.aedt.core.filtersolutions import LumpedDesign
filt = LumpedDesign(version="2026.1")
filt.attributes.filter_class = FilterClass.BAND_PASS
filt.attributes.filter_type = FilterType.ELLIPTIC
filt.export_to_aedt.export_design()
```

---

### 14. Help (Documentation)
**File:** `help.py` | **Class:** `Help`

**Purpose:** Utility to open PyAEDT documentation, examples, and resources in a browser.

**Constructor:**
```python
from ansys.aedt.core.help import Help
help_util = Help(version="stable", silent=False, browser=None)
```

**Key Methods:**
- `api_reference()` -- Open API reference
- `user_guide()` -- Open user guide
- `getting_started()` -- Open getting started guide
- `installation_guide()` -- Open installation guide
- `examples()` -- Open examples gallery
- `release_notes()` -- Open release notes
- `github()` -- Open GitHub repository
- `changelog(version)` -- Open changelog
- `issues()` -- Open GitHub issues
- `ansys_forum()` -- Open Ansys community forum
- `developer_forum()` -- Open developer forum
- `search(query)` -- Search documentation

---

### 15. PyAedtBase (Base Class)
**File:** `base.py` | **Classes:** `DirMixin`, `PyAedtBase`

**Purpose:** Root base class for all PyAEDT application classes.

**Key Features:**
- `public_dir` -- Returns sorted list of public attributes (no underscore prefix)
- `__dir__` -- Reorders dir() output: public first, private last
- `__repr__` / `__str__` -- Returns `Class: module.classname`

**Usage (automatic inheritance):**
```python
from ansys.aedt.core import Hfss
hfss = Hfss()
hfss.public_dir  # List all public methods/properties
```

---

### 16. CreateBoundaryMixin
**File:** `mixins.py` | **Class:** `CreateBoundaryMixin`

**Purpose:** Mixin providing boundary condition creation methods to application classes.

**Key Method:**
```python
def _create_boundary(self, name, props, boundary_type) -> BoundaryObject
```
Creates a boundary condition and registers it in `self._boundaries`.

**Used by:** Maxwell, Icepak, Q3d, and other classes that need boundary conditions.

---

### 17. AedtLogger
**File:** `aedt_logger.py` | **Classes:** `AedtLogger`, `MessageList`, `Msg`

**Purpose:** Logging configuration for PyAEDT -- captures messages from AEDT.

**Access via application:**
```python
from ansys.aedt.core import Hfss
hfss = Hfss()
hfss.logger.info("Info message")
hfss.logger.warning("Warning message")
hfss.logger.error("Error message")
```

**Access AEDT messages:**
```python
msgs = hfss.logger.messages
msgs.info_level     # List of info messages
msgs.warning_level  # List of warnings
msgs.error_level    # List of errors
```

**Logger settings:**
```python
from ansys.aedt.core import settings
settings.enable_logger = True
settings.enable_screen_logs = True
settings.enable_local_log_file = True
settings.logger_file_path = "/path/to/log.log"
```

---

## Quick Decision Guide

### Which Application Type Should I Use?

| I want to... | Use this class |
|---|---|
| Simulate an electronic circuit or schematic | `Circuit` |
| Run signal/power integrity on PCBs | `Circuit` or `Hfss3dLayout` |
| Design an electric motor/generator (FEM) | `Maxwell3d` / `Maxwell2d` |
| Analyze transformer/inductor performance | `Maxwell3d` |
| Do thermal analysis of electronics | `Icepak` |
| Extract parasitic RLC from IC packages | `Q3d` / `Q2d` |
| Full-wave EM simulation of a PCB | `Hfss3dLayout` |
| Structural/thermal-mechanical FEA | `Mechanical` |
| Design motor analytically first | `Rmxprt` (export to Maxwell later) |
| Build a digital twin model | `TwinBuilder` |
| Analyze RF interference between radios | `Emit` |
| Manipulate PCB layout data (no GUI) | `Edb()` |
| Design RF filters | `FilterSolutions.LumpedDesign` / `DistributedDesign` |

### How to Connect Remotely

```
SERVER MACHINE                          CLIENT MACHINE
--------------                          --------------
1. pyaedt_service_manager(port=17878)   2. client = create_session(
                                            host="server.com",
                                            launch_aedt_on_server=True
                                        )
                                        3. Use client object for remote AEDT
```

### Constructor Parameters (Common to All App Types)

All application types share these constructor parameters:
- `project` -- Project name or path to .aedt file
- `design` -- Design name
- `solution_type` -- Solution type
- `setup` -- Setup name
- `version` -- AEDT version (e.g., "2026.1")
- `non_graphical` -- Run without GUI
- `new_desktop` -- Launch new AEDT instance
- `close_on_exit` -- Close AEDT when script exits
- `student_version` -- Use student license
- `machine` -- Remote machine hostname
- `port` -- gRPC port number
- `aedt_process_id` -- Attach to existing AEDT process
- `remove_lock` -- Remove project lock before opening