"""render.py BOARD OUT.png: render the top of a board from the project directory it lives in, after checking that every footprint's 3D model file exists.
The check and the render are pcbkit.render's (hardware/pcbkit/pcbkit/render.py); this is the AFE's command line for it."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'pcbkit'))
from pcbkit.render import render
render(sys.argv[1], sys.argv[2])
