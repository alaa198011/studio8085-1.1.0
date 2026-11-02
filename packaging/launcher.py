"""Entry script for PyInstaller (it needs a plain script, not a package)."""

import sys

from studio8085.app import main

if __name__ == "__main__":
    sys.exit(main())
