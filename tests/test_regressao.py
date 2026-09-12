"""Os cenários estilizados do README não podem mudar sem intenção."""
import pandas as pd

from imobsim import grade, resumo


def test_grade_estilizada_bate_com_docs():
    tab = resumo(grade())
    ref = pd.read_csv("docs/resumo_grade.csv")
    pd.testing.assert_frame_equal(tab, ref, check_exact=False, rtol=1e-6)
