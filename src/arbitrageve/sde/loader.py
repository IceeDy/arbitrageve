from pathlib import Path

def load_sde(path:Path):
    if not path.exists(): raise FileNotFoundError(path)
