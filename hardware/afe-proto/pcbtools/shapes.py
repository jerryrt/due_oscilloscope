"""pcbtools.shapes is pcbkit.geom (the kernels and the copper shapes were one module there): the same module object, so
`pcbtools.shapes.f` is `pcbkit.geom.f` and a patch to one is a patch to the other."""
import sys

from pcbkit import geom

sys.modules[__name__] = geom
