"""The gate-3 package generator: `python3 -B -m pcbtools.gate3 --config <cfg> --table <table> --out <dir>`. See README.md."""
from .engine import generate, build_doc, bridge_table, hop_table, classify_net, margin_rows, fnum, md_table, tpl  # noqa: F401
from .table import REQUIRED, check_table, check_config  # noqa: F401
