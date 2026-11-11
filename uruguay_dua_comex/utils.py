"""Rutas a las carpetas del proyecto.

Las rutas se calculan a partir de la ubicación de este archivo, no del
directorio actual, así que funcionan igual desde cualquier carpeta (CLI,
notebooks o GitHub Actions). Cada función recibe partes opcionales que se
agregan al final, por ejemplo `data_processed_dir("archivo.parquet")`.

Este módulo es idéntico en argentina_afip_comex y uruguay_dua_comex.
"""

from collections.abc import Callable
from pathlib import Path

# Raíz del proyecto: este archivo vive en <raíz>/<paquete>/utils.py.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def make_dir_function(*parts: str) -> Callable[..., Path]:
    """Build a function returning a path under the project root, extended by any given parts."""

    def dir_path(*args: str) -> Path:
        return PROJECT_ROOT.joinpath(*parts, *args)

    return dir_path


project_dir = make_dir_function()
data_dir = make_dir_function("data")
data_raw_dir = make_dir_function("data", "raw")
data_processed_dir = make_dir_function("data", "processed")
data_interim_dir = make_dir_function("data", "interim")
outputs_dir = make_dir_function("outputs")
outputs_figures_dir = make_dir_function("outputs", "figures")
outputs_tables_dir = make_dir_function("outputs", "tables")
assets_dir = make_dir_function("assets")
docs_dir = make_dir_function("docs")
