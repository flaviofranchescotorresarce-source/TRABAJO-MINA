# -*- coding: utf-8 -*-
"""
Radar Minero - puntaje por perfil
---------------------------------
Compara cada oferta con perfil.json y le pone una nota de 0 a 100, con los
motivos a la vista para que se pueda auditar y corregir.

Es codigo determinista: mismas ofertas y mismo perfil -> mismo resultado.
No consulta ningun modelo, no necesita clave de API y no cuesta nada.
"""

import json
import os
import re
import unicodedata

AQUI = os.path.dirname(os.path.abspath(__file__))
RUTA_PERFIL = os.path.join(AQUI, "perfil.json")


def sin_tildes(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def cargar_perfil():
    try:
        with open(RUTA_PERFIL, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  ! No se pudo leer perfil.json ({e}); se omite el puntaje")
        return None


# cargos que por si solos no dicen de que area es el puesto
GENERICO = re.compile(r"practicante|practicas|trainee|becario|"
                      r"^asistente$|^auxiliar$|^analista$|^coordinador$")


def puntuar(ofertas, perfil):
    """Nota 0-100 por oferta + los motivos que la explican."""
    cargos = [sin_tildes(c) for c in perfil.get("cargos_que_busco", [])]
    extras = [sin_tildes(c) for c in perfil.get("palabras_clave_extra", [])]
    fuera = [sin_tildes(c) for c in perfil.get("cargos_que_no_me_sirven", [])]
    regiones = [sin_tildes(r) for r in perfil.get("regiones_preferidas", [])]
    solo_con_cierre = bool(perfil.get("solo_con_fecha_de_cierre"))

    for o in ofertas:
        puesto = sin_tildes(o.get("puesto", ""))
        empresa = sin_tildes(o.get("empresa", ""))
        texto = f"{puesto} {empresa} {sin_tildes(o.get('resumen', ''))}"
        n, motivos = 0, []

        # el cargo es lo que mas pesa
        aciertos = [c for c in cargos if c in puesto]
        hits_extra = [c for c in extras if c in texto]
        # "practicante profesional" o "trainee" no dicen de que es la practica:
        # sin una senal del area, valen la mitad que un cargo concreto
        concretos = [c for c in aciertos if not GENERICO.search(c)]
        if concretos:
            n += min(45, 30 + 5 * (len(concretos) - 1))
            motivos.append("cargo: " + concretos[0])
        elif aciertos:
            if hits_extra or any(c in puesto for c in extras):
                n += 28
                motivos.append("practica del area: " + aciertos[0])
            else:
                n += 14
                motivos.append("cargo generico: " + aciertos[0])

        # palabras del rubro que domina el perfil
        if hits_extra:
            n += min(15, 6 * len(hits_extra))
            motivos.append("afin: " + ", ".join(hits_extra[:3]))

        # region preferida
        if sin_tildes(o.get("region", "")) in regiones:
            n += 10
            motivos.append("region preferida")

        # portal oficial de la empresa: postulacion directa, mas confiable
        if o.get("oficial"):
            n += 8
            motivos.append("portal oficial")

        # fecha de cierre confirmada por el portal
        if o.get("cierra_exacta"):
            n += 4
            motivos.append("cierre confirmado")

        # urgencia: si cierra pronto conviene verla ya
        d = o.get("dias")
        if d is not None:
            if d <= 3:
                n += 12
                motivos.append("cierra en %d dia(s)" % d)
            elif d <= 7:
                n += 7
                motivos.append("cierra esta semana")
            elif d <= 15:
                n += 3
        elif solo_con_cierre:
            n -= 15
            motivos.append("sin fecha de cierre")

        # practicas: solo suman si el perfil las busca
        if "practicas" in (o.get("cats") or []):
            if any("practicante" in c or "trainee" in c for c in cargos):
                n += 6
                motivos.append("programa de formacion")

        # cargos que el perfil descarta explicitamente
        descarta = [c for c in fuera if c in puesto]
        if descarta:
            n -= 40
            motivos.append("fuera de perfil: " + descarta[0])

        o["puntaje"] = max(0, min(100, n))
        o["motivos"] = motivos
    return ofertas


def aplicar(ofertas):
    """Devuelve (ofertas puntuadas, resumen para la bitacora)."""
    perfil = cargar_perfil()
    if not perfil:
        return ofertas, None
    ofertas = puntuar(ofertas, perfil)
    # el conteo mira solo el sector: las convocatorias del Estado van aparte
    sector = [o for o in ofertas if not o.get("estatal")]
    encajan = sum(1 for o in sector if o.get("puntaje", 0) >= 25)
    return ofertas, "%d ofertas del sector puntuadas, %d encajan con tu perfil" % (
        len(sector), encajan)
