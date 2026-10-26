"""PyInstaller's entry script for the sidecar.

dawnmaker/__main__.py uses relative imports (`from .app import ...`), which only
work when it runs as part of its package (`python -m dawnmaker`). Handed to
PyInstaller directly it is a bare script, and the frozen daemon died at launch
with "attempted relative import with no known parent package". Importing the
package the normal way keeps both paths working.

The same executable is also the app's gallery-dl: PyInstaller ships the
`gallery_dl` module but no console script, and a user's PATH has none, so
`coreflame.sources.twitter.gallery_dl_command()` runs `<this exe> --gallery-dl
<args>` in the frozen build. That branch is taken before the daemon imports
(FastAPI, the classifier) so each gallery-dl call stays a plain subprocess.
"""

import sys

if sys.argv[1:2] == ["--gallery-dl"]:
    from gallery_dl import main as gallery_dl_main

    sys.argv = ["gallery-dl", *sys.argv[2:]]
    sys.exit(gallery_dl_main())

from dawnmaker.__main__ import main  # noqa: E402  -- after the dispatch on purpose

sys.exit(main())
