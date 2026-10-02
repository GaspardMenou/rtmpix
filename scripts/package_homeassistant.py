"""Assemble l'application HA locale avec le code courant, sans données privées."""

from pathlib import Path
from shutil import copy2, copytree, ignore_patterns, rmtree

root = Path(__file__).resolve().parents[1]
target = root / "dist" / "homeassistant" / "rtmpix"
if target.exists():
    rmtree(target)
target.parent.mkdir(parents=True, exist_ok=True)
copytree(root / "homeassistant" / "rtmpix", target)
copytree(root / "rtmpix", target / "rtmpix", ignore=ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
copy2(root / "requirements.txt", target / "requirements.txt")
copy2(root / "rtmpix" / "static" / "logo.png", target / "icon.png")
print(target)
