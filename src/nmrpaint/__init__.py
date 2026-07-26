"""NMRpaint package."""

__version__ = "0.1.0"


def create_app():
    """Create and return the NMRpaint widget application."""
    from .app import create_app as _create_app

    return _create_app()


__all__ = [
    "create_app",
    "__version__",
]
