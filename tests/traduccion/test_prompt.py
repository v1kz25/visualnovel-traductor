"""Tests de la construcción del prompt (plantillas oficiales de Hy-MT2)."""

from vn_audiolibro.traduccion.prompt import construir


def test_prompt_por_defecto() -> None:
    assert construir("無邊無垠的永劫之火。") == (
        "Translate the following text into Spanish. Note that you should only output the translated "
        "result without any additional explanation:\n\n無邊無垠的永劫之火。"
    )


def test_prompt_con_terminos() -> None:
    texto = construir("沒錯——櫻，死了。", terminos=[("櫻", "Sakura"), ("羅格之火", "Fuego de Rogue")])

    assert texto.startswith(
        "Reference the following translations:\n"
        "櫻 translates to Sakura\n羅格之火 translates to Fuego de Rogue\n\n"
        "Translate the following text into Spanish."
    )
    assert texto.endswith("\n\n沒錯——櫻，死了。")


def test_prompt_con_contexto_y_terminos() -> None:
    texto = construir(
        "「櫻……！！」", contexto=["他呢喃著。", "沒錯——她，死了。"], terminos=[("櫻", "Sakura")]
    )

    assert texto == (
        "[Background Information]\n他呢喃著。\n沒錯——她，死了。\n\n"
        "Reference the following translations:\n櫻 translates to Sakura\n\n"
        "Please translate the following text into Spanish, taking the provided background information "
        "into consideration. Only output the translated result without any additional explanation.\n\n"
        "[Source Text]\n「櫻……！！」"
    )


def test_prompt_en_ingles() -> None:
    assert construir("無邊無垠的永劫之火。", destino="en").startswith(
        "Translate the following text into English."
    )
    con_contexto = construir("「櫻……！！」", contexto=["他呢喃著。"], destino="en")
    assert "Please translate the following text into English," in con_contexto
