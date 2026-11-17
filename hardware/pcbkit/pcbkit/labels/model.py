"""What the placer reads: a board reduced to boxes. Built by `from_board` from a `pcbkit.board` read or, in the tests, by hand."""
from dataclasses import dataclass, field


@dataclass
class Part:
    ref: str
    x: float                      # footprint origin
    y: float
    cour: tuple                   # courtyard box, or None when the footprint has none
    body: tuple = None            # F.Fab outline box (the part's body), or None
    pads: list = field(default_factory=list)      # pad boxes
    rot: float = 0.0
    top: bool = True
    silk: tuple = None            # box of the footprint's own F.SilkS graphics, or None

    def solid(self):
        """the part's solid: its body box and each pad box"""
        return list(self.pads) + ([self.body] if self.body else [])


@dataclass
class LabelBoard:
    parts: dict                                   # ref -> Part
    vias: list = field(default_factory=list)      # via boxes
    silk: list = field(default_factory=list)      # footprint silk and board silk, as thin boxes
    outline_lines: list = field(default_factory=list)  # the block-outline segments (x0, y0, x1, y1) as drawn
    outline_silk: list = field(default_factory=list)  # board-level silk lines (block outlines), thin boxes: obstacles for every label, or only after the edge labels
    texts: list = field(default_factory=list)     # other board texts (pin labels, markings), boxes
    fixed: dict = field(default_factory=dict)     # label key -> box of a text that is already there and stays (block names, a BNC's function text)
    edge: tuple = None                            # board outline bounding box
    labels: dict = field(default_factory=dict)    # ref -> (x, y, angle, visible): the reference text as the board has it now
