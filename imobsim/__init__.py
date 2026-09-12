"""imobsim: modelo de estoque e fluxo para incorporadoras sob cenários macro.

Três eixos independentes (macro, praça, incorporadora) e um loop mensal que
os combina. Ver README.md para a lógica e os parâmetros.
"""
from .crises import EPISODIOS, grade_stress, resumo_stress, stress
from .incorporadora import ARQUETIPOS
from .macro import CENARIOS, cenario, focus, historico
from .praca import PRACAS, TEMPLATES, Praca, from_dados, from_toml, praca
from .sim import Choque, crescimento_minimo, grade, resumo, run, vso_minima

__version__ = "0.1.0"
__all__ = [
    "ARQUETIPOS", "CENARIOS", "PRACAS",
    "run", "grade", "resumo", "vso_minima", "crescimento_minimo",
    "cenario", "historico", "focus",
    "Choque", "EPISODIOS", "stress", "grade_stress", "resumo_stress",
    "Praca", "TEMPLATES", "from_dados", "from_toml", "praca",
]
