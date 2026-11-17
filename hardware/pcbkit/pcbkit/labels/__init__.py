"""Designator placement and the readability test. See placer.py and ../CONFIG.md."""
from .model import Part, LabelBoard
from .placer import effective_config, place, check_two_way, validate, ConfigError, Plan, kind_of, lab_box
from .bnc import bnc_layout
from .names import place_names, validate_names
from .outline_lines import outline_segments, validate_outline
from . import from_board
