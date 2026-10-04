"""Catch shared-contract import errors even while components remain stubs."""

import importlib
import pkgutil

import pytest

import bittorrent_lite


@pytest.mark.parametrize(
    "module_name",
    sorted(item.name for item in pkgutil.walk_packages(
        bittorrent_lite.__path__, bittorrent_lite.__name__ + "."
    )),
)
def test_package_module_imports(module_name):
    importlib.import_module(module_name)
