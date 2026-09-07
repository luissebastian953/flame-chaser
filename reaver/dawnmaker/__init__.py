"""dawnmaker -- the localhost HTTP/SSE daemon that the desktop shell talks to.

Dependency direction is one-way and enforced by convention: dawnmaker imports
coreflame; coreflame never imports dawnmaker. That is what keeps the CLI working
as an escape hatch while the UI is mid-refactor.
"""

__version__ = "0.1.0"
