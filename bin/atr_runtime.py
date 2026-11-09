"""Fixed storage interface for atr-owned sibling tools; roots are selected or explicitly registered."""
import importlib.machinery
import importlib.util
from pathlib import Path
import threading

_bound = None
_stores = {}
_registry_lock = threading.RLock()


def bind(api):
    global _bound
    _bound = api


def _contains(root, path):
    return Path(path).absolute().is_relative_to(Path(root).absolute())


def api_for(path=None, *, root=None):
    # A path containing a room/evidence directory named 'rooms' never changes store identity.
    if root is None and _bound is not None and (path is None or _contains(_bound.ROOT, path)):
        return _bound
    if root is not None and _bound is not None and Path(root).resolve() == _bound.ROOT.resolve():
        return _bound
    with _registry_lock:
        if root is None and path is not None:
            for api in sorted(_stores.values(), key=lambda item: len(item.ROOT.parts), reverse=True):
                if _contains(api.ROOT, path):
                    return api
        key = str(Path(root).absolute().resolve()) if root is not None else 'selected'
        if key not in _stores:
            source = Path(__file__).with_name('atr')
            spec = importlib.util.spec_from_loader('atr_storage_runtime', importlib.machinery.SourceFileLoader('atr_storage_runtime', str(source)))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if root is not None:
                module.ROOT, module.ROOMS = Path(key), Path(key) / 'rooms'
            _stores[key] = module
        api = _stores[key]
        if path is not None and not _contains(api.ROOT, path):
            raise ValueError(f'{path} is outside the selected store; pass an explicit validated root')
        return api


def write_text(path, text, **kwargs):
    return api_for(path).durable_write(path, text, **kwargs)


def append(path, text):
    return api_for(path).durable_append(path, text)


def mkdir(path, **kwargs):
    return api_for(path).durable_mkdir(path, **kwargs)


def replace(source, destination):
    return api_for(destination).durable_replace(source, destination)
