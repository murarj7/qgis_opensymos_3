def classFactory(iface):
    """Load OpenSymos plugin."""
    from .opensymos import Opensymos
    return Opensymos(iface)