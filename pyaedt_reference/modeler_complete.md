# PyAEDT Modeler Complete Reference

This document provides a comprehensive reference for the PyAEDT Modeler module, covering all key classes, properties, and methods for working with 3D geometry in AEDT (Ansys Electronics Desktop).

## Table of Contents

1. [Object3d Class](#object3d-class)
2. [FacePrimitive Class](#faceprimitive-class)
3. [EdgePrimitive Class](#edgeprimitive-class)
4. [VertexPrimitive Class](#vertexprimitive-class)
5. [Primitives3D Class](#primitives3d-class)
6. [Modeler3D Class](#modeler3d-class)
7. [GeometryOperators Class](#geometryoperators-class)
8. [Usage Examples](#usage-examples)

---

## Object3d Class

The `Object3d` class manages object attributes for the AEDT 3D Modeler. It represents 3D objects (solids, sheets, lines) and provides comprehensive access to their properties and operations.

### Basic Usage

```python
from ansys.aedt.core import Hfss
from ansys.aedt.core.modeler.cad.object_3d import Object3d

aedtapp = Hfss()
prim = aedtapp.modeler

# Create a box and get the Object3d instance
id = prim.create_box([0, 0, 0], [10, 10, 5], "Mybox", "Copper")
part = prim[id]
```

### Properties

#### Identity and Classification

| Property | Type | Description |
|----------|------|-------------|
| `name` | `str` | Name of the object (get/set) |
| `id` | `int` | ID of the object |
| `object_type` | `str` | Type: "Solid", "Sheet", "Line", or "Unclassified" |
| `is_3d` | `bool` | True if object is a 3D solid |
| `is_model` | `bool` | True if object is a model (get/set) |
| `is_polyline` | `bool` | True if originated from a polyline (get/set) |
| `group_name` | `str` | Group the object belongs to (get/set) |

#### Geometry Information

| Property | Type | Description |
|----------|------|-------------|
| `faces` | `list[FacePrimitive]` | List of all faces |
| `edges` | `list[EdgePrimitive]` | List of all edges |
| `vertices` | `list[VertexPrimitive]` | List of all vertices |
| `bounding_box` | `list[list[float]]` | Six [x,y,z] positions: [Xmin, Ymin, Zmin, Xmax, Ymax, Zmax] |
| `bounding_dimension` | `list[float]` | Bounding box dimensions [dim_x, dim_y, dim_z] |
| `volume` | `float` | Object volume (0.0 for non-solids) |
| `mass` | `float` | Object mass in kg (0.0 for non-models) |

#### Face Properties (by Direction)

| Property | Type | Description |
|----------|------|-------------|
| `top_face_z` | `FacePrimitive` | Top face in Z direction |
| `bottom_face_z` | `FacePrimitive` | Bottom face in Z direction |
| `top_face_x` | `FacePrimitive` | Top face in X direction |
| `bottom_face_x` | `FacePrimitive` | Bottom face in X direction |
| `top_face_y` | `FacePrimitive` | Top face in Y direction |
| `bottom_face_y` | `FacePrimitive` | Bottom face in Y direction |
| `faces_on_bounding_box` | `list[FacePrimitive]` | Faces touching bounding box |
| `face_closest_to_bounding_box` | `FacePrimitive` | Face closest to bounding box |

#### Edge Properties (by Direction)

| Property | Type | Description |
|----------|------|-------------|
| `top_edge_z` | `EdgePrimitive` | Top edge in Z direction |
| `bottom_edge_z` | `EdgePrimitive` | Bottom edge in Z direction |
| `top_edge_x` | `EdgePrimitive` | Top edge in X direction |
| `bottom_edge_x` | `EdgePrimitive` | Bottom edge in X direction |
| `top_edge_y` | `EdgePrimitive` | Top edge in Y direction |
| `bottom_edge_y` | `EdgePrimitive` | Bottom edge in Y direction |

#### Material Properties

| Property | Type | Description |
|----------|------|-------------|
| `material_name` | `str` | Material name (get/set) |
| `surface_material_name` | `str` | Surface material name (get/set) |
| `material_appearance` | `bool` | Material appearance flag (get/set) |
| `solve_inside` | `bool` | Solve-inside flag (get/set) |

#### Display Properties

| Property | Type | Description |
|----------|------|-------------|
| `color` | `tuple[int, int, int]` | RGB color tuple (get/set) |
| `color_string` | `str` | Color as "(R G B)" string |
| `transparency` | `float` | Transparency 0.0-1.0 (get/set) |
| `display_wireframe` | `bool` | Wireframe display flag (get/set) |
| `object_units` | `str` | Object units |
| `part_coordinate_system` | `str` | Part coordinate system (get/set) |

#### Other Properties

| Property | Type | Description |
|----------|------|-------------|
| `valid_properties` | `list[str]` | List of valid properties |
| `touching_objects` | `list` | List of touching objects |
| `is_conductor` | `bool` | True if material is a conductor |

### Methods

#### Face and Edge Selection Methods

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `largest_face()` | `n=1` | `list[FacePrimitive]` | n largest faces by area |
| `smallest_face()` | `n=1` | `list[FacePrimitive]` | n smallest faces by area |
| `longest_edge()` | `n=1` | `list[EdgePrimitive]` | n longest edges |
| `shortest_edge()` | `n=1` | `list[EdgePrimitive]` | n shortest edges |

#### Boolean and Transformation Operations

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `unite()` | `assignment` | `Object3d` | Unite with other objects |
| `intersect()` | `assignment, keep_originals=False` | `Object3d` | Intersect with other objects |
| `split()` | `plane, sides="Both"` | `list[str]` | Split by coordinate plane |
| `mirror()` | `origin, vector, duplicate=False` | `Object3d` | Mirror object |
| `rotate()` | `axis, angle=90.0, units="deg"` | `Object3d` | Rotate object |
| `move()` | `vector` | `Object3d` | Move object |
| `duplicate_around_axis()` | `axis, angle=90, clones=2, create_new_objects=True` | `list[Object3d]` | Duplicate around axis |
| `duplicate_along_line()` | `vector, clones=2, attach=False` | `list[Object3d]` | Duplicate along line |

#### Export and Visualization Methods

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `plot()` | `show=True` | `ModelPlotter` | Plot with PyVista |
| `export_image()` | `output_file=None` | `str` | Export image to file |
| `history()` | None | `BinaryTreeNode` | Get object history tree |

#### Other Methods

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `touching_conductors()` | None | `list` | Get touching conductors |
| `get_touching_faces()` | `assignment` | `list` | Get faces touching another object |

---

## FacePrimitive Class

The `FacePrimitive` class represents a face of a 3D object.

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `id` | `int` | Face ID |
| `center` | `list[float]` | Center coordinates [x, y, z] |
| `area` | `float` | Face area |
| `normal` | `list[float]` | Normal vector [x, y, z] |
| `vertices` | `list[VertexPrimitive]` | List of vertices |
| `edges` | `list[EdgePrimitive]` | List of edges |
| `is_on_bounding_box` | `bool` | True if on bounding box |

### Methods

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `fillet()` | `radius=0.1, setback=0.0` | `bool` | Apply fillet to edge (3D only) |
| `chamfer()` | `left_distance=1, right_distance=None, angle=45, chamfer_type=0` | `bool` | Apply chamfer to edge (3D only) |

---

## EdgePrimitive Class

The `EdgePrimitive` class represents an edge of a 3D object.

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `id` | `int` | Edge ID |
| `midpoint` | `list[float]` | Midpoint coordinates [x, y, z] |
| `length` | `float` | Edge length |
| `vertices` | `list[VertexPrimitive]` | List of vertices |
| `segment_info` | `dict` | Segment information |

### Methods

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `fillet()` | `radius=0.1, setback=0.0` | `bool` | Apply fillet to edge |
| `chamfer()` | `left_distance=1, right_distance=None, angle=45, chamfer_type=0` | `bool` | Apply chamfer to edge |

---

## VertexPrimitive Class

The `VertexPrimitive` class represents a vertex of a 3D object.

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `id` | `int` | Vertex ID |
| `position` | `list[float]` | Position coordinates [x, y, z] |
| `name` | `str` | Name of the parent object |

---

## Primitives3D Class

The `Primitives3D` class manages primitives in 3D modeler applications. It provides methods for creating basic 3D shapes.

### Basic Usage

```python
from ansys.aedt.core import Hfss

app = Hfss()
box = app.modeler.create_box(
    origin=[0, 0, 0],
    sizes=[10, 5, 3],
    name="my_box",
    material="copper",
    color=(240, 120, 0),
    transparency=0.5
)
```

### Common Parameters for Creation Methods

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Name of the object |
| `material` | `str` | Material name |
| `color` | `tuple[int, int, int]` | RGB color tuple |
| `transparency` | `float` | Transparency (0.0-1.0) |
| `display_wireframe` | `bool` | Wireframe display |
| `model` | `bool` | Model flag |

### Creation Methods

#### create_box()

Creates a box primitive.

```python
box = modeler.create_box(
    origin=[0, 0, 0],
    sizes=[10, 5, 3],
    name="my_box",
    material="copper"
)
```

**Parameters:**
- `origin`: List [x, y, z] - Anchor point
- `sizes`: List [x, y, z] - Box dimensions
- `name`: str - Name (optional)
- `material`: str - Material name (optional)

**Returns:** `Object3d` or `False`

---

#### create_cylinder()

Creates a cylinder primitive.

```python
cylinder = modeler.create_cylinder(
    orientation="Z",
    origin=[0, 0, 0],
    radius=5,
    height=10,
    name="my_cylinder",
    material="aluminum"
)
```

**Parameters:**
- `orientation`: str - Axis orientation ("X", "Y", "Z")
- `origin`: List [x, y, z] - Center base
- `radius`: float - Radius
- `height`: float - Height
- `name`: str - Name (optional)
- `material`: str - Material (optional)

**Returns:** `Object3d` or `False`

---

#### create_sphere()

Creates a sphere primitive.

```python
sphere = modeler.create_sphere(
    center=[0, 0, 0],
    radius=5,
    name="my_sphere",
    material="pec"
)
```

**Parameters:**
- `center`: List [x, y, z] - Center coordinates
- `radius`: float - Radius
- `name`: str - Name (optional)
- `material`: str - Material (optional)

**Returns:** `Object3d` or `False`

---

#### create_rectangle()

Creates a rectangle sheet primitive.

```python
rect = modeler.create_rectangle(
    orientation="Z",
    origin=[0, 0, 0],
    sizes=[10, 5],
    name="my_rectangle"
)
```

**Parameters:**
- `orientation`: str - Plane orientation ("XY", "YZ", "ZX")
- `origin`: List [x, y, z] - Start point
- `sizes`: List [x, y] - Dimensions
- `name`: str - Name (optional)

**Returns:** `Object3d` or `False`

---

#### create_circle()

Creates a circle sheet primitive.

```python
circle = modeler.create_circle(
    orientation="Z",
    center=[0, 0, 0],
    radius=5,
    name="my_circle"
)
```

**Parameters:**
- `orientation`: str - Plane orientation
- `center`: List [x, y, z] - Center coordinates
- `radius`: float - Radius
- `name`: str - Name (optional)

**Returns:** `Object3d` or `False`

---

#### create_polyline()

Creates a polyline object.

```python
polyline = modeler.create_polyline(
    points=[[0, 0, 0], [10, 0, 0], [10, 10, 0]],
    name="my_polyline"
)
```

**Parameters:**
- `points`: List of [x, y, z] coordinates
- `name`: str - Name (optional)

**Returns:** `Object3d` or `False`

---

## Modeler3D Class

The `Modeler3D` class provides the Modeler 3D application interface. It inherits from `Primitives3D` and provides advanced modeling operations.

### Basic Usage

```python
from ansys.aedt.core import Hfss

hfss = Hfss()
my_modeler = hfss.modeler
```

### 3D Component Operations

#### create_3dcomponent()

Creates a 3D component file (A3DCOMP format).

```python
modeler.create_3dcomponent(
    input_file="component.a3dcomp",
    name="my_component",
    assignment=["Box1", "Cylinder1"],
    boundaries=["Boundary1"],
    excitations=["Port1"]
)
```

**Key Parameters:**
- `input_file`: str - Path to A3DCOMP file
- `name`: str - Component name
- `variables_to_include`: list - Variables to include
- `assignment`: list - Object names to export
- `boundaries`: list - Boundary names
- `excitations`: list - Excitation names
- `coordinate_systems`: list - Coordinate systems
- `is_encrypted`: bool - Encryption flag
- `password`: str - Security password

**Returns:** `bool`

---

### Import/Export Operations

| Method | Description |
|--------|-------------|
| `import_3d_cad()` | Import 3D CAD files (STEP, IGES, etc.) |
| `export_3d_model()` | Export 3D model to various formats |
| `import_gdsii()` | Import GDSII files |

---

### Coordinate System Operations

| Method | Description |
|--------|-------------|
| `create_coordinate_system()` | Create a new coordinate system |
| `set_working_coordinate_system()` | Set the working coordinate system |
| `get_coordinate_system()` | Get coordinate system properties |

---

### Boolean Operations

| Method | Description |
|--------|-------------|
| `unite()` | Unite multiple objects |
| `subtract()` | Subtract one object from another |
| `intersect()` | Intersect objects |
| `split()` | Split objects by plane |

---

## GeometryOperators Class

The `GeometryOperators` class provides static utility methods for geometric calculations.

### Rotation Methods

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `rot_2d()` | `x, y, cosa, sina` | `tuple` | 2D rotation |
| `rot_3d()` | `xyz, ro_1, ro_2` | `list` | 3D rotation |
| `rotate_point()` | `point, axis, angle` | `list` | Rotate point around axis |
| `rotate_face_around_axis()` | `face_id, axis, angle` | - | Rotate face around axis |

### Translation Methods

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `translate()` | `point, vector` | `list` | Translate point by vector |
| `move_point_to_global_cs()` | `point, cs_origin` | `list` | Move point to global CS |

### Intersection Methods

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `is_segment_intersecting_polygon()` | `polygon, start, end` | `bool` | Check segment-polygon intersection |
| `is_point_in_polygon()` | `point, polygon` | `bool` | Check if point is in polygon |
| `is_vector_length_null()` | `vector` | `bool` | Check if vector length is zero |

### Vector Operations

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `v_prod()` | `v1, v2` | `float` | Vector dot product |
| `v_cross()` | `v1, v2` | `list` | Vector cross product |
| `v_norm()` | `v` | `float` | Vector magnitude |
| `v_sub()` | `v1, v2` | `list` | Vector subtraction |
| `v_add()` | `v1, v2` | `list` | Vector addition |

### Coordinate Transformations

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `cart2sph()` | `x, y, z` | `tuple` | Cartesian to spherical |
| `sph2cart()` | `r, theta, phi` | `tuple` | Spherical to Cartesian |
| `cart2cylind()` | `x, y, z` | `tuple` | Cartesian to cylindrical |
| `cylind2cart()` | `r, theta, z` | `tuple` | Cylindrical to Cartesian |
| `rect2polar()` | `x, y` | `tuple` | Rectangular to polar |
| `polar2rect()` | `r, theta` | `tuple` | Polar to rectangular |

### Geometric Calculations

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `distance_vector()` | `p1, p2` | `float` | Distance between points |
| `distance_vector_squared()` | `p1, p2` | `float` | Squared distance |
| `pointing_to_ellipse()` | `focus1, focus2, point` | `list` | Point on ellipse from focus |
| `triangle_area()` | `p1, p2, p3` | `float` | Triangle area |
| `quaternion_rotation()` | `point, axis, angle` | `list` | Quaternion rotation |

---

## Usage Examples

### Example 1: Creating Basic Shapes

```python
from ansys.aedt.core import Hfss

# Initialize HFSS
hfss = Hfss()

# Create a box
box = hfss.modeler.create_box(
    origin=[0, 0, 0],
    sizes=[10, 5, 3],
    name="substrate",
    material="FR4_epoxy"
)

# Create a cylinder
cylinder = hfss.modeler.create_cylinder(
    orientation="Z",
    origin=[5, 2.5, 0],
    radius=1,
    height=3,
    name="via",
    material="copper"
)

# Create a sphere
sphere = hfss.modeler.create_sphere(
    center=[5, 2.5, 1.5],
    radius=0.5,
    name="ball",
    material="pec"
)
```

### Example 2: Working with Object Properties

```python
# Get object properties
print(f"Name: {box.name}")
print(f"ID: {box.id}")
print(f"Type: {box.object_type}")
print(f"Volume: {box.volume}")
print(f"Material: {box.material_name}")
print(f"Color: {box.color}")

# Modify properties
box.color = (255, 0, 0)  # Red
box.transparency = 0.5
box.material_name = "copper"
```

### Example 3: Working with Faces

```python
# Get all faces
faces = box.faces
print(f"Number of faces: {len(faces)}")

# Get specific faces
top_face = box.top_face_z
bottom_face = box.bottom_face_z

# Get face properties
print(f"Top face center: {top_face.center}")
print(f"Top face area: {top_face.area}")
print(f"Top face normal: {top_face.normal}")

# Get largest face
largest = box.largest_face(n=1)[0]
print(f"Largest face area: {largest.area}")
```

### Example 4: Working with Edges

```python
# Get all edges
edges = box.edges
print(f"Number of edges: {len(edges)}")

# Get longest edge
longest = box.longest_edge(n=1)[0]
print(f"Longest edge length: {longest.length}")
print(f"Longest edge midpoint: {longest.midpoint}")

# Apply fillet to edge
longest.fillet(radius=0.5)
```

### Example 5: Boolean Operations

```python
# Unite objects
united = box.unite([cylinder])

# Intersect objects
intersected = box.intersect([sphere])

# Split object
split_objects = box.split(plane="XY", sides="Both")
```

### Example 6: Transformations

```python
# Move object
box.move(vector=[1, 0, 0])

# Rotate object
box.rotate(axis="Z", angle=45, units="deg")

# Mirror object
box.mirror(origin=[0, 0, 0], vector=[1, 0, 0])

# Duplicate
duplicates = box.duplicate_around_axis(
    axis="Z",
    angle=90,
    clones=4
)
```

### Example 7: Coordinate Transformations

```python
from ansys.aedt.core.modeler.geometry_operators import GeometryOperators

# Convert Cartesian to Spherical
r, theta, phi = GeometryOperators.cart2sph(1, 1, 1)

# Convert Spherical to Cartesian
x, y, z = GeometryOperators.sph2cart(r, theta, phi)

# Rotate a point
point = [1, 0, 0]
axis = [0, 0, 1]
angle = 90  # degrees
rotated = GeometryOperators.rotate_point(point, axis, angle)
```

### Example 8: Exporting and Visualization

```python
# Export object image
box.export_image(output_file="box_image.png")

# Plot object with PyVista
box.plot(show=True)

# Get object history
history = box.history()
```

---

## Important Notes

1. **Units**: All coordinates and dimensions are in model units unless specified otherwise.

2. **Coordinate System**: The default coordinate system is "Global". Use `part_coordinate_system` property to work with local coordinate systems.

3. **Material Assignment**: Materials must exist in the material library. Use `material_name` setter to assign materials.

4. **Boolean Operations**: Boolean operations modify the original objects. Use `keep_originals=True` parameter where available to preserve originals.

5. **Performance**: Accessing `faces`, `edges`, and `vertices` properties involves API calls to AEDT. Cache these values when possible for better performance.

6. **Version Compatibility**: Some methods have minimum AEDT version requirements. Check the `@min_aedt_version` decorator in the source code.

7. **Error Handling**: Methods typically return `False` on failure. Check return values before proceeding with operations.

---

## Quick Reference Card

### Object3d Properties Cheat Sheet

```
Identity:     name, id, object_type, is_3d, is_model
Geometry:     faces, edges, vertices, bounding_box, volume, mass
Position:     top_face_z, bottom_face_z, top_edge_z, bottom_edge_z
Material:     material_name, surface_material_name, is_conductor
Display:      color, transparency, display_wireframe, material_appearance
Coordinate:   part_coordinate_system, object_units
```

### Common Operations Cheat Sheet

```
Create:       create_box(), create_cylinder(), create_sphere()
Modify:       move(), rotate(), mirror(), scale()
Boolean:      unite(), intersect(), subtract(), split()
Duplicate:    duplicate_around_axis(), duplicate_along_line()
Export:       export_image(), plot()
```

---

## References

- **Object3d**: `ansys.aedt.core.modeler.cad.object_3d.Object3d`
- **FacePrimitive**: `ansys.aedt.core.modeler.cad.elements_3d.FacePrimitive`
- **EdgePrimitive**: `ansys.aedt.core.modeler.cad.elements_3d.EdgePrimitive`
- **VertexPrimitive**: `ansys.aedt.core.modeler.cad.elements_3d.VertexPrimitive`
- **Primitives3D**: `ansys.aedt.core.modeler.cad.primitives_3d.Primitives3D`
- **Modeler3D**: `ansys.aedt.core.modeler.modeler_3d.Modeler3D`
- **GeometryOperators**: `ansys.aedt.core.modeler.geometry_operators.GeometryOperators`

---

*This reference document was generated from PyAEDT source code analysis. For the most up-to-date information, refer to the official PyAEDT documentation and source code.*