"""Permite correr la CLI con `python -m uruguay_dua_comex`.

Alternativa al comando `uruguay-dua-query`, útil cuando Windows bloquea el
ejecutable que genera uv.
"""

from uruguay_dua_comex.query import main

raise SystemExit(main())
