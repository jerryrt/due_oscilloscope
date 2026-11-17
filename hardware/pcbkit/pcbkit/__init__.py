"""pcbkit: general checks and tools for a two-layer KiCad 10 board. Imports nothing outside itself except numpy, scipy and pcbnew."""
from . import board, config, rules   # noqa: F401  (importing the modules fills config.DECLARED, the registry the typo guard reads)
