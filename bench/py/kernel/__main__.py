"""python -m kernel — same entry as the bench shim (needs bench/py on sys.path)."""
from kernel.cli import main

raise SystemExit(main())
