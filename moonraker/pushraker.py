# zmod_pushraker: Moonraker's pushraker component. install.sh links this
# file into Zmod's Moonraker as components/pushraker.py; it puts the
# plugin's python/ (the pushraker package, tools/vendor.py) on sys.path and
# hands over to the package. Apprise, Pillow, Jinja2 and requests come
# from Zmod's Moonraker environment.
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import os
import sys

_PY = os.path.join(os.path.dirname(os.path.dirname(
    os.path.realpath(__file__))), "python")
if _PY not in sys.path:
    sys.path.append(_PY)

from pushraker.component import load_component  # noqa: E402,F401
