"""PyInstaller's entry script for the sidecar.

dawnmaker/__main__.py uses relative imports (`from .app import ...`), which only
work when it runs as part of its package (`python -m dawnmaker`). Handed to
PyInstaller directly it is a bare script, and the frozen daemon died at launch
with "attempted relative import with no known parent package". Importing the
package the normal way keeps both paths working.
"""

import sys

from dawnmaker.__main__ import main

sys.exit(main())
