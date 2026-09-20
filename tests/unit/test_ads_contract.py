r"""P3: 契约端口顺序形式化规则 + ADS 侧对拍（验收项 2）。

规则（定案口径）:
  1. port_order 每个 token 匹配 ^(input|output_\d+)$;
  2. input 恰好出现一次;
  3. output_N 序号严格递增 -> [input, output_2, output_1] 判非法。
"""

import pytest
from pydantic import ValidationError

from rfauto.core.contracts import AdsExchangeContract, TouchstoneContract
from rfauto.core.errors import ContractViolationError


def _make(port_order):
    return AdsExchangeContract(touchstone=TouchstoneContract(port_order=port_order))


class TestPortOrderRules:
    """port_order 形式化规则（验收项 2 的核心）。"""

    @pytest.mark.parametrize(
        "port_order",
        [
            ["input", "output_1", "output_2"],
            ["input", "output_1", "output_2", "output_3"],
            ["input", "output_1"],
        ],
    )
    def test_valid_orders(self, port_order):
        _make(port_order)  # 不应抛错

    @pytest.mark.parametrize(
        "port_order",
        [
            ["input", "output_2", "output_1"],  # 序号倒置
            ["input", "output_1", "output_1"],  # 重复
            ["input", "output_1", "output_2", "output_1"],  # 重复
            ["in", "out1"],  # 非法 token
            ["input", "output_1", "o2"],  # 非法 token
            ["output_1", "output_2"],  # 缺 input
            ["input", "input", "output_1"],  # input 重复
            [],  # 空
        ],
    )
    def test_invalid_orders_raise(self, port_order):
        with pytest.raises(ValidationError):
            _make(port_order)

    def test_default_contract_is_valid(self):
        c = AdsExchangeContract()
        assert c.touchstone.port_order == ["input", "output_1", "output_2"]


class TestContractValidateAgainstAds:
    """契约对 ADS .ds 回读结果的对拍校验（验收项 2 的 ADS 侧落点）。"""

    def setup_method(self):
        self.c = _make(["input", "output_1", "output_2"])

    def test_ok_all_good(self):
        self.c.check_against_ads_output(
            n_ports=3, port_names=["P1", "P2", "P3"], port_z=[50, 50, 50],
        )

    def test_wrong_port_count_rejected(self):
        with pytest.raises(ContractViolationError):
            self.c.check_against_ads_output(
                n_ports=2, port_names=["P1", "P2"], port_z=[50, 50],
            )

    def test_wrong_port_names_rejected(self):
        with pytest.raises(ContractViolationError):
            self.c.check_against_ads_output(
                n_ports=3, port_names=["P2", "P1", "P3"], port_z=[50, 50, 50],
            )

    def test_wrong_impedance_rejected(self):
        with pytest.raises(ContractViolationError):
            self.c.check_against_ads_output(
                n_ports=3, port_names=["P1", "P2", "P3"], port_z=[50, 100, 50],
            )

    def test_complex_port_z_uses_real_part(self):
        self.c.check_against_ads_output(
            n_ports=3, port_names=["P1", "P2", "P3"], port_z=[50 + 0.005j, 50 - 0.003j, 50 + 0j],
        )
