# Third-Party Notices

rfauto depends on the following open-source packages. Each package is subject to its own license.

## Direct Dependencies

| Package | Version | License |
|---------|---------|---------|
| about-time | 4.2.1 | See package |
| aiofile | 3.12.3 | See package |
| alembic | 1.19.1 | See package |
| alive-progress | 3.3.0 | See package |
| annotated-doc | 0.0.5 | See package |
| annotated-types | 0.8.0 | See package |
| ansys-api-edb | 0.3.2 | See package |
| ansys-edb-core | 0.3.3 | See package |
| ansys-tools-common | 0.5.2 | See package |
| antlr4-python3-runtime | 4.9.3 | See package |
| anyio | 4.14.2 | See package |
| ast_serialize | 0.8.0 | See package |
| attrs | 26.1.0 | See package |
| Authlib | 1.7.2 | See package |
| autograd | 1.9.1 | See package |
| beartype | 0.22.9 | See package |
| cachetools | 7.1.7 | See package |
| caio | 0.12.2 | See package |
| certifi | 2026.7.22 | See package |
| cffi | 2.1.1 | See package |
| cfgv | 3.5.0 | See package |
| charset-normalizer | 3.5.1 | See package |
| click | 8.5.0 | See package |
| cma | 4.4.4 | See package |
| cmaes | 0.13.1 | MIT |
| colorama | 0.4.6 | See package |
| colorlog | 6.12.0 | See package |
| contourpy | 1.3.3 | See package |
| coverage | 7.15.4 | See package |
| cryptography | 50.0.1 | See package |
| CSXCAD | 0.7.0rc1.post1.dev12+gd607c9ba2 | See package |
| cycler | 0.12.1 | See package |
| cyclopts | 4.23.3 | See package |
| Cython | 3.3.0 | See package |
| defusedxml | 0.7.1 | PSF |
| Deprecated | 1.3.1 | See package |
| distlib | 0.4.3 | See package |
| dnspython | 2.8.0 | See package |
| docstring_parser | 0.18.0 | See package |
| email-validator | 2.3.0 | See package |

## GPL Boundary Statement

rfauto (GPL-3.0-only) drives GPL-licensed openEMS only through a separate subprocess; the openEMS bindings themselves are not included in this repository.

openEMS/CSXCAD Python bindings (GPL-3.0) are used ONLY within subprocess execution
(`simulation.py` child process). The main rfauto process never imports these bindings.
Users compile bindings separately from the openEMS source repository.

This separation keeps the optional openEMS integration cleanly isolated; rfauto itself is distributed under GPL-3.0-only (see LICENSE).

## Commercial Software

- Ansys AEDT (HFSS): Requires valid license from Ansys. rfauto does not provide or circumvent any license mechanisms.
- Keysight ADS: Requires valid license from Keysight. rfauto does not distribute any Keysight-protected content.
