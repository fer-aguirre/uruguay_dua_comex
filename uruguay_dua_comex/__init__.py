"""Paquete uruguay_dua_comex: herramientas para analizar comercio exterior uruguayo."""

from uruguay_dua_comex.consulta import Consulta
from uruguay_dua_comex.query import export_query_result, query_data

__all__ = ["Consulta", "export_query_result", "query_data"]
