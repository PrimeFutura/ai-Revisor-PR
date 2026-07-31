#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────
#  Agente revisor con IA REAL (agnóstico de proveedor) — Python
# ─────────────────────────────────────────────────────────────
# Compara el TÍTULO y la DESCRIPCIÓN del PR (por separado) contra el
# DIFF y decide si el código coincide con lo prometido.
#
# Sin dependencias externas: usa solo la librería estándar (urllib).
# Todo es configurable por entorno para poder migrar sin reescribir:
#   IA_CLAVE_API -> credencial (hoy tu clave de OpenAI; en la oficina
#                   podría ser el GITHUB_TOKEN con GitHub Models).
#   IA_URL_BASE  -> endpoint base (compatible OpenAI). Por defecto OpenAI.
#   IA_MODELO    -> nombre del modelo (por defecto: gpt-4o-mini).
#
# Si NO hay credencial, cae a un motor SIMULADO para no romper el flujo.

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

VERSION_ESQUEMA = "1.0"
MAX_CARACTERES_DIFF = 60000  # límite para no disparar el consumo de tokens
MODELO_POR_DEFECTO = "gpt-4o-mini"
URL_BASE_POR_DEFECTO = "https://api.openai.com/v1"


def leer_archivo_seguro(ruta):
    """Lee un archivo tolerando la codificación (UTF-8, o UTF-16/UTF-8 con
    BOM, como el que genera PowerShell con '>'). Nunca lanza excepción por
    caracteres inválidos."""
    try:
        with open(ruta, "rb") as archivo:
            datos = archivo.read()
    except OSError:
        return ""

    for bom, codificacion in (
        (b"\xff\xfe", "utf-16-le"),
        (b"\xfe\xff", "utf-16-be"),
        (b"\xef\xbb\xbf", "utf-8-sig"),
    ):
        if datos.startswith(bom):
            return datos.decode(codificacion, errors="replace")

    return datos.decode("utf-8", errors="replace")


def entero_env(nombre):
    try:
        return int(os.environ.get(nombre) or 0)
    except ValueError:
        return 0


def recopilar_entrada():
    diff = leer_archivo_seguro(os.environ.get("ARCHIVO_DIFF") or "pr.diff")
    lista = leer_archivo_seguro(os.environ.get("ARCHIVO_LISTA") or "archivos_cambiados.txt")
    archivos_cambiados = [linea.strip() for linea in lista.split("\n") if linea.strip()]

    return {
        "repositorio": os.environ.get("PR_REPOSITORIO", ""),
        "numero_pr": entero_env("PR_NUMERO"),
        "titulo": os.environ.get("PR_TITULO", ""),
        "descripcion": (os.environ.get("PR_DESCRIPCION") or "").strip(),
        "autor": os.environ.get("PR_AUTOR", ""),
        "adiciones": entero_env("PR_ADICIONES"),
        "eliminaciones": entero_env("PR_ELIMINACIONES"),
        "archivos_cambiados": archivos_cambiados,
        "diff": diff,
    }


def truncar(texto, maximo):
    if len(texto) <= maximo:
        return texto, False
    return texto[:maximo], True


# Asegura que la respuesta del modelo respete nuestro contrato.
def normalizar_resultado(r):
    validos = ["aprobado", "cambios_requeridos", "comentario"]
    coherencia = r.get("coherencia") if isinstance(r.get("coherencia"), dict) else {}
    return {
        "veredicto": r.get("veredicto") if r.get("veredicto") in validos else "comentario",
        "alineado": bool(r.get("alineado")),
        "coherencia": {
            "titulo": coherencia.get("titulo") if isinstance(coherencia.get("titulo"), bool) else None,
            "descripcion": coherencia.get("descripcion") if isinstance(coherencia.get("descripcion"), bool) else None,
        },
        "confianza": r.get("confianza") if isinstance(r.get("confianza"), (int, float)) and not isinstance(r.get("confianza"), bool) else None,
        "resumen": r.get("resumen") if isinstance(r.get("resumen"), str) else "",
        "hallazgos": r.get("hallazgos") if isinstance(r.get("hallazgos"), list) else [],
    }


# ── Motor SIMULADO (respaldo si no hay credenciales) ───────────
def evaluar_simulado(entrada):
    hallazgos = []
    if len(entrada["descripcion"]) < 15:
        hallazgos.append({
            "tipo": "descripcion_faltante",
            "severidad": "alta",
            "mensaje": "La descripción del PR está vacía o es demasiado corta para verificar el código.",
            "archivos": [],
        })
    alineado = len(hallazgos) == 0
    return {
        "motor": "simulado",
        "veredicto": "aprobado" if alineado else "cambios_requeridos",
        "alineado": alineado,
        "coherencia": {"titulo": True, "descripcion": alineado},
        "confianza": 0.5,
        "resumen": (
            "Verificación superficial superada (motor simulado, sin IA)."
            if alineado
            else "Se encontraron observaciones (motor simulado, sin IA)."
        ),
        "hallazgos": hallazgos,
    }


# ── Motor IA (endpoint compatible con OpenAI, vía urllib) ──────
def evaluar_con_ia(entrada, clave_api, url_base, modelo):
    diff, truncado = truncar(entrada["diff"], MAX_CARACTERES_DIFF)

    sistema = "\n".join([
        "Eres un revisor automático de Pull Requests. Debes evaluar, de forma",
        "INDEPENDIENTE, si el TÍTULO y la DESCRIPCIÓN del PR se corresponden con",
        "los cambios reales del DIFF. Ambos campos deben ser coherentes por sí",
        "solos: si CUALQUIERA de los dos no coincide, el PR NO se aprueba.",
        "",
        "Un campo (título o descripción) es COHERENTE si resume fielmente la",
        "intención de los cambios del diff. NO exijas que enumere cada archivo ni",
        "cada detalle de implementación; basta con que refleje correctamente el",
        "objetivo. Un campo es INCOHERENTE si está vacío, es vago o genérico, es",
        "engañoso, o describe algo distinto/ajeno a lo que muestra el diff.",
        "",
        "Además marca 'invasion_alcance': funcionalidad NUEVA no relacionada o",
        "cambios de comportamiento presentes en el diff que NO estén reflejados ni",
        "en el título ni en la descripción. Los cambios de soporte naturales",
        "(documentación/README, configuración, CI/workflow, pruebas,",
        "refactorizaciones menores ligadas al objetivo) NO son invasión de alcance.",
        "",
        "Reglas de veredicto:",
        "- 'aprobado': el título Y la descripción son coherentes y no hay invasión",
        "  de alcance relevante.",
        "- 'cambios_requeridos': el título O la descripción son incoherentes, o hay",
        "  invasión de alcance relevante.",
        "- 'comentario': solo observaciones menores que no justifican bloquear.",
        "",
        "Por cada incoherencia añade un hallazgo con 'tipo':",
        "  'titulo_incoherente' | 'descripcion_incoherente' | 'invasion_alcance'.",
        "El campo 'coherencia' debe reflejar el juicio individual de cada campo.",
        "No inventes cambios que no estén en el diff.",
        "",
        "Responde EXCLUSIVAMENTE en formato JSON con este esquema:",
        '{ "veredicto": "aprobado"|"cambios_requeridos"|"comentario", "alineado": boolean,',
        '  "coherencia": { "titulo": boolean, "descripcion": boolean },',
        '  "confianza": number(0..1), "resumen": string(en español),',
        '  "hallazgos": [ { "tipo": string, "severidad": "baja"|"media"|"alta",',
        '                 "mensaje": string, "archivos": string[] } ] }',
    ])

    usuario = "\n".join([
        f"Repositorio: {entrada['repositorio']}",
        f"PR #{entrada['numero_pr']}",
        f"Título: {entrada['titulo']}",
        "",
        "DESCRIPCIÓN DEL PR:",
        entrada["descripcion"] or "(sin descripción)",
        "",
        f"ARCHIVOS CAMBIADOS ({len(entrada['archivos_cambiados'])}):",
        "\n".join(entrada["archivos_cambiados"]) or "(ninguno)",
        "",
        f"DIFF{' (TRUNCADO)' if truncado else ''}:",
        diff or "(vacío)",
    ])

    cuerpo = json.dumps({
        "model": modelo,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": sistema},
            {"role": "user", "content": usuario},
        ],
    }).encode("utf-8")

    url = url_base.rstrip("/") + "/chat/completions"
    peticion = urllib.request.Request(
        url,
        data=cuerpo,
        headers={
            "Authorization": f"Bearer {clave_api}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(peticion, timeout=60) as respuesta:
        datos = json.loads(respuesta.read().decode("utf-8"))

    crudo = datos["choices"][0]["message"]["content"] or "{}"
    resultado = normalizar_resultado(json.loads(crudo))
    resultado["motor"] = "ia"
    return resultado


def resultado_error(mensaje):
    # No tumbamos el workflow: devolvemos un veredicto válido que
    # deja claro que la IA no pudo ejecutarse.
    return {
        "motor": "error",
        "veredicto": "comentario",
        "alineado": False,
        "coherencia": {"titulo": None, "descripcion": None},
        "confianza": None,
        "resumen": f"El agente de IA no pudo completar la revisión: {mensaje}",
        "hallazgos": [
            {"tipo": "error_agente", "severidad": "alta", "mensaje": mensaje, "archivos": []},
        ],
    }


def evaluar(entrada):
    clave_api = os.environ.get("IA_CLAVE_API")
    url_base = os.environ.get("IA_URL_BASE") or URL_BASE_POR_DEFECTO
    modelo = os.environ.get("IA_MODELO") or MODELO_POR_DEFECTO

    if not clave_api:
        return evaluar_simulado(entrada)

    try:
        return evaluar_con_ia(entrada, clave_api, url_base, modelo)
    except urllib.error.HTTPError as error:
        detalle = error.read().decode("utf-8", "ignore")
        return resultado_error(f"HTTP {error.code}: {detalle[:300]}")
    except Exception as error:  # noqa: BLE001 (queremos capturar cualquier fallo)
        return resultado_error(str(error))


def principal():
    entrada = recopilar_entrada()
    resultado = evaluar(entrada)
    modelo = os.environ.get("IA_MODELO") or MODELO_POR_DEFECTO

    salida = {
        "version_esquema": VERSION_ESQUEMA,
        "veredicto": resultado["veredicto"],  # aprobado | cambios_requeridos | comentario
        "alineado": resultado["alineado"],
        "coherencia": resultado["coherencia"],  # { titulo, descripcion } por separado
        "confianza": resultado["confianza"],
        "resumen": resultado["resumen"],
        "hallazgos": resultado["hallazgos"],
        "metadatos": {
            "repositorio": entrada["repositorio"],
            "numero_pr": entrada["numero_pr"],
            "archivos_cambiados": len(entrada["archivos_cambiados"]),
            "adiciones": entrada["adiciones"],
            "eliminaciones": entrada["eliminaciones"],
            "motor": resultado["motor"],  # ia | simulado | error
            "modelo": modelo if resultado["motor"] == "ia" else None,
            "generado_en": datetime.now(timezone.utc).isoformat(),
        },
    }

    print(json.dumps(salida, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    principal()
