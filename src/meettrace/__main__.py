"""CLI entry point for running MeetTrace with `python -m meettrace`."""

import sys

from meettrace.ui.app import main

if __name__ == "__main__":
    sys.exit(main())
