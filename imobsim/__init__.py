"""imobsim: modelo de estoque e fluxo para incorporadoras sob cenários macro.

Três eixos independentes (macro, praça, incorporadora) e um loop mensal que
os combina. Ver README.md para a lógica e os parâmetros.
"""
from .incorporadora import ARQUETIPOS
from .macro import CENARIOS
from .praca import PRACAS
from .sim import crescimento_minimo, grade, resumo, run, vso_minima

__version__ = "0.1.0"
__all__ = [
    "ARQUETIPOS", "CENARIOS", "PRACAS",
    "run", "grade", "resumo", "vso_minima", "crescimento_minimo",
]
