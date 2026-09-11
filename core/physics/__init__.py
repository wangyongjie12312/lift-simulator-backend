"""
core.physics
============

从 LabVIEW 逐节点移植过来的物理模块，每个都带自检
（``python -m core.physics.<name>`` 或在本目录下直接 ``python <name>.py``）。

======================================  ===================================
模块                                    对应 VI
======================================  ===================================
:mod:`~core.physics.calculate_pressure`          calculate pressure.vi (PR EOS)
:mod:`~core.physics.peng_robinson_isothermal_moles`  Peng-Robinson Isothermal moles.vi
:mod:`~core.physics.sea_temperature`             sea temperature.vi
:mod:`~core.physics.select_adjustment_mode_xs`   select adjustment mode XS.vi
:mod:`~core.physics.gas_transfer`                gas transfer / equalise
:mod:`~core.physics.booster_energy_consumption`  booster energy consumption.vi
======================================  ===================================

这些是**真实现**，已经和 LabVIEW 框图逐节点对过并通过自检。
:mod:`core.engine` 目前还没用上它们全部 —— 见那个模块顶部的替换指南。
"""
