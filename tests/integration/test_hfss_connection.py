import os
from pathlib import Path

import pytest

from rfauto.adapters.hfss_session import HfssSession


@pytest.mark.real_edt
def test_connect_to_aedt():
    aedt_path = os.environ.get('RFAUTO_AEDT_PATH', '')
    if not aedt_path or not Path(aedt_path).exists():
        pytest.skip(f'RFAUTO_AEDT_PATH not set: {aedt_path}')
    version = '2023.1' if 'v231' in aedt_path else '2025.1'
    session = HfssSession.instance()
    session.connect({'desktop_version': version, 'non_graphical': True, 'new_desktop_session': True})
    assert session.is_connected, 'HfssSession should be connected'
    assert session.hfss is not None
    assert session.desktop is not None
    print(f'Connected to AEDT {version}')
@pytest.mark.real_edt
def test_health_check():
    aedt_path = os.environ.get('RFAUTO_AEDT_PATH', '')
    if not aedt_path or not Path(aedt_path).exists():
        pytest.skip(f'RFAUTO_AEDT_PATH not set: {aedt_path}')
    version = '2023.1' if 'v231' in aedt_path else '2025.1'
    session = HfssSession.instance()
    session.connect({'desktop_version': version, 'non_graphical': True, 'new_desktop_session': True})
    is_healthy = session.health_check()
    assert is_healthy, 'Health check should return True'
    print('Health check passed')

@pytest.mark.real_edt
def test_disconnect():
    aedt_path = os.environ.get('RFAUTO_AEDT_PATH', '')
    if not aedt_path or not Path(aedt_path).exists():
        pytest.skip(f'RFAUTO_AEDT_PATH not set: {aedt_path}')
    version = '2023.1' if 'v231' in aedt_path else '2025.1'
    session = HfssSession.instance()
    session.connect({'desktop_version': version, 'non_graphical': True, 'new_desktop_session': True})
    session.close(save=False)
    assert not session.is_connected, 'is_connected should be False'
    print('Disconnect passed')
