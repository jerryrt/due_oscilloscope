"""v1 on a ROUTED board: the same configuration as v1 (names and values), with the arms of v1r_arms (see there)"""
from .v1 import *  # noqa: F401,F403
from . import v1 as _v1


def __getattr__(name):          # names that start with an underscore or are not star-exported (sch_cfg, pcb_cfg, ...)
    return getattr(_v1, name)
