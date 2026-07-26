from __future__ import annotations

import sys
from time import perf_counter


def main() -> None:
    start = perf_counter()

    import ipywidgets
    import ipycanvas

    package_time = perf_counter()

    from nmrpaint import app

    app_time = perf_counter()

    print(f"Python: {sys.executable}")
    print(f"ipywidgets: {ipywidgets.__version__}")
    print(f"ipycanvas: {ipycanvas.__version__}")
    print(f"Dependency import: {package_time - start:.3f} s")
    print(f"NMRpaint import: {app_time - package_time:.3f} s")
    print(f"Total: {app_time - start:.3f} s")
    print("Environment OK")


if __name__ == "__main__":
    main()