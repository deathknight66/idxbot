import os
from pathlib import Path
import yaml


def load_env(path=".env"):
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def load_config(path="config.yaml") -> dict:
    load_env()
    with open(path) as f:
        return yaml.safe_load(f)
