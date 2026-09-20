"""Spike A: PyAEDT -> microstrip -> solve -> export S-params"""
import os
from pathlib import Path

os.chdir(str(Path(__file__).resolve().parents[1]))

from ansys.aedt.core import Hfss

hfss = Hfss(
    project="spike_a_microstrip", design="microstrip",
    solution_type="DrivenModal", version="2023.1", new_desktop=True,
)

hfss["w"] = "1.1mm"
hfss["l"] = "20mm"
hfss["h"] = "0.508mm"
hfss["t"] = "0.035mm"
hfss["pad"] = "5mm"

hfss.modeler.create_box(
    ["-pad", "-pad", "0"], ["l+2*pad", "2*pad+w", "h"],
    name="substrate", material="Rogers RO4350 (tm)")
hfss.modeler.create_box(
    ["-pad", "-pad", "0"], ["l+2*pad", "2*pad+w", "0mm"],
    name="ground", material="pec")
hfss.modeler.create_box(
    ["0", "-w/2", "h"], ["l", "w", "t"],
    name="trace", material="pec")
hfss.modeler.create_box(
    ["-pad", "-pad", "0"], ["l+2*pad", "2*pad+w", "h+t+5mm"],
    name="airbox", material="vacuum")

# Radiation boundary on top face of airbox
air_faces = hfss.modeler.get_object_faces("airbox")
top_face = None
for f in air_faces:
    c = hfss.modeler.get_face_center(f)
    if c[2] > 5:
        top_face = f
        break
if top_face:
    hfss.assign_radiation_boundary_to_faces(top_face)

# Port sheets
p1_sheet = hfss.modeler.create_rectangle(
    orientation=1, origin=["0", "-pad", "0"],
    sizes=["2*pad+w", "h+t+0.1mm"], name="port1_sheet")
p2_sheet = hfss.modeler.create_rectangle(
    orientation=1, origin=["l", "-pad", "0"],
    sizes=["2*pad+w", "h+t+0.1mm"], name="port2_sheet")

hfss.wave_port(assignment=p1_sheet, name="port1", impedance=50, renormalize=True)
hfss.wave_port(assignment=p2_sheet, name="port2", impedance=50, renormalize=True)

setup = hfss.create_setup(name="main_setup")
setup.props["Frequency"] = "2.4GHz"
setup.props["MaximumPasses"] = 15
setup.props["DeltaS"] = 0.02
setup.update()

hfss.create_linear_count_sweep(
    setup="main_setup", unit="GHz",
    start_frequency=1.0, stop_frequency=4.0, num_of_freq_points=201,
    name="sweep_1_4GHz", save_fields=False,
)

# Auto-export touchstone BEFORE solving (gRPC may drop after long solve)
hfss.export_touchstone_on_completion(export=True, output_dir=os.getcwd())

# Solve
hfss.analyze(setup="main_setup")

# Save project
hfss.save_project()

print("=" * 50)
print("Spike A DONE!")
print("Touchstone auto-exported to cwd: spike_a_microstrip*.s2p")
print(f"Project: {hfss.project_path}")
print("=" * 50)

hfss.release_desktop()
