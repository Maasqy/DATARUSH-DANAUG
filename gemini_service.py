"""
Integracion con la API de Gemini para el panel "Analisis con IA" de los
dashboards (ver MapaUS.py). Vive en un modulo aparte a proposito:

  - La API key SOLO se lee y se usa aqui, del lado servidor -- este codigo
    corre dentro del proceso de Streamlit (nunca en el navegador), asi que
    la clave jamas llega al frontend ni se envia al cliente. Se lee de la
    variable de entorno GEMINI_API_KEY (definida en .env, que esta en
    .gitignore) via python-dotenv.
  - MapaUS.py arma el contexto compacto (estado/condado + sus indicadores
    ya calculados, reutilizando get_state_entry/get_county_entry) y llama a
    generate_analysis(context); este modulo solo sabe convertir ese
    contexto en un prompt y hablar con el modelo. Asi no se duplica la
    logica de filtrado/agregacion de datos que ya vive en MapaUS.py.

No se manda nunca el dataset completo -- context es el objeto compacto
descrito en generate_analysis().
"""
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest").strip() or "gemini-flash-lite-latest"

REQUIRED_SECTIONS = [
    "Resumen de la situacion",
    "Indicadores relevantes",
    "Principales problemas o areas de oportunidad",
    "Sugerencias concretas de mejora",
    "Limitaciones de los datos",
]

_ERROR_MESSAGES = {
    "no_api_key": (
        "No hay una GEMINI_API_KEY configurada. Copia .env.example a .env, pega tu clave de "
        "https://aistudio.google.com/apikey y reinicia la app."
    ),
    "missing_dependency": "Falta instalar el paquete `google-genai` (revisa requirements.txt).",
    "invalid_key": "Gemini rechazo la clave configurada (invalida o sin permisos). Revisa GEMINI_API_KEY en .env.",
    "rate_limited": "Se alcanzo el limite de uso de la API de Gemini. Intenta de nuevo en unos minutos.",
    "server_error": "El servicio de Gemini no esta disponible en este momento. Intenta de nuevo mas tarde.",
    "network_error": "No se pudo conectar con Gemini (revisa tu conexion a internet).",
    "invalid_response": (
        "Gemini no devolvio una respuesta utilizable (puede haber sido bloqueada por los filtros "
        "de seguridad del modelo). Intenta de nuevo."
    ),
}


def build_prompt(context):
    """Arma el prompt en base al contexto compacto (nunca el dataset completo).

    context ya trae solo los indicadores de la seleccion activa -- ver el
    shape exacto en MapaUS.py (build_ai_context): selectionLevel
    "state"/"county", metrics de estado (y de condado si aplica), y
    dashboardContext con los filtros activos y la fuente de datos.
    """
    context_json = json.dumps(context, ensure_ascii=False, indent=2)
    level = context.get("selectionLevel")

    if level == "county":
        level_instructions = (
            'selectionLevel es "county": tu respuesta debe cubrir, dentro de las 5 secciones de '
            "abajo, TODO lo siguiente:\n"
            "  (a) un analisis general de la situacion del estado,\n"
            "  (b) un analisis especifico de la situacion del condado seleccionado,\n"
            "  (c) una comparacion directa condado vs. estado usando los indicadores equivalentes "
            "que esten presentes en el JSON (y contra la media nacional si 'nationalReference' "
            "esta disponible),\n"
            "  (d) sugerencias de mejora especificas para el condado,\n"
            "  (e) posibles acciones a nivel ESTATAL que podrian ayudar a resolver los problemas "
            "identificados en el condado."
        )
    elif level == "comparison":
        state_names = ", ".join(s.get("name", "?") for s in context.get("states", []))
        level_instructions = (
            f'selectionLevel es "comparison": el usuario eligio varios estados para comparar '
            f"({state_names}). Tu respuesta debe cubrir, dentro de las 5 secciones de abajo, TODO "
            "lo siguiente:\n"
            "  (a) un resumen breve de la situacion de CADA estado listado en 'states',\n"
            "  (b) una comparacion directa entre esos estados usando los indicadores equivalentes "
            "presentes en el JSON (y contra la referencia nacional si 'nationalReference' esta "
            "disponible),\n"
            "  (c) cual(es) estado(s) tienen mayor y cual(es) menor vulnerabilidad, y en que "
            "indicador puntual se nota mas esa diferencia,\n"
            "  (d) sugerencias de mejora comparativas -- por ejemplo, en que podria un estado con "
            "peor indicador fijarse de uno con mejor indicador equivalente, siempre basandote solo "
            "en los datos del JSON, nunca en informacion externa sobre politicas publicas reales."
        )
    else:
        level_instructions = (
            'selectionLevel es "state": analiza UNICAMENTE la situacion general de ese estado. '
            "No menciones, elijas ni inventes ningun condado especifico -- no hay uno seleccionado."
        )

    neighbor_instructions = ""
    if level in ("state", "county") and "contrastesVecinos" in context:
        pairs = context.get("contrastesVecinos") or []
        if pairs:
            neighbor_instructions = (
                "\nAdemas, al FINAL de la seccion \"Resumen de la situacion\" (como ultimo parrafo "
                "de esa misma seccion, no como una seccion nueva), menciona explicitamente los "
                "contrastes geograficos de 'contrastesVecinos': son pares de condados VECINOS "
                "(comparten borde o estan a pocos km) donde uno cae en banda Alta/Severa de "
                "vulnerabilidad y el de al lado en banda Baja. Nombralos tal cual aparecen en el "
                "JSON (condadoVulnerabilidadAlta vs. condadoVulnerabilidadBaja, con sus valores) -- "
                "no inventes otros pares que no esten en esa lista."
            )
        else:
            neighbor_instructions = (
                "\nAdemas, al FINAL de la seccion \"Resumen de la situacion\" (como ultimo parrafo de "
                "esa misma seccion), indica explicitamente que, segun 'contrastesVecinos' (que llego "
                "vacio), no se detectaron condados vecinos con un contraste fuerte entre banda Alta/"
                "Severa y banda Baja de vulnerabilidad en los datos disponibles."
            )

    return f"""Eres un analista de datos de salud publica y determinantes sociales de la salud
(SDOH) para un dashboard interactivo de Estados Unidos. Tu unica fuente de informacion es el
JSON de contexto de abajo: SOLO puedes usar esos datos. Nunca inventes cifras, causas,
comparaciones ni conclusiones que no se puedan derivar directamente de ese JSON. Si un dato
relevante no esta disponible (aparece como null, falta, o el objeto "metrics" es null), dilo
explicitamente en la seccion de limitaciones en vez de rellenarlo, suponerlo o estimarlo.

Contexto de la seleccion activa en el dashboard (JSON):
{context_json}

Instrucciones segun el nivel de seleccion:
{level_instructions}
{neighbor_instructions}

Responde en espanol, en Markdown, con EXACTAMENTE estas 5 secciones, en este orden y usando
esos titulos tal cual como encabezado con "####" (nada de secciones extra, nada de texto antes
de la primera seccion ni despues de la ultima):

#### Resumen de la situacion
#### Indicadores relevantes
#### Principales problemas o areas de oportunidad
#### Sugerencias concretas de mejora
#### Limitaciones de los datos

En "Indicadores relevantes" cita los numeros del JSON tal como estan (incluyendo unidades /
porcentajes). En "Limitaciones de los datos" menciona explicitamente cualquier metrica null o
faltante en el JSON, y cualquier limite de tu analisis (por ejemplo: es un snapshot sin serie
temporal por lo que no se puede hablar de tendencias, no hay relacion de causalidad comprobada
entre indicadores, etc.)."""


def generate_analysis(context):
    """Llama a Gemini con el contexto compacto ya armado por MapaUS.py.

    Devuelve siempre un dict:
      - exito:  {"ok": True, "text": "...", "model": "..."}
      - error:  {"ok": False, "code": "<categoria>", "message": "..."}
    nunca lanza una excepcion -- el llamador (el panel de IA en MapaUS.py)
    solo necesita mirar "ok" para decidir que mostrar.
    """
    if not GEMINI_API_KEY:
        return {"ok": False, "code": "no_api_key", "message": _ERROR_MESSAGES["no_api_key"]}

    try:
        from google import genai
        from google.genai import errors, types
    except ImportError:
        return {"ok": False, "code": "missing_dependency", "message": _ERROR_MESSAGES["missing_dependency"]}

    prompt = build_prompt(context)
    client = genai.Client(api_key=GEMINI_API_KEY)
    # OJO: no le pasamos thinking_config -- gemini-flash-lite-latest (el
    # modelo por defecto) lo rechaza con 400 "invalid argument". Si en algun
    # momento se configura GEMINI_MODEL a un modelo "thinking" (p. ej.
    # gemini-3.6-flash), ese SI puede gastar la mayoria de max_output_tokens
    # en razonamiento interno y cortar la respuesta a mitad de camino -- por
    # eso mas abajo igual detectamos finish_reason MAX_TOKENS y lo marcamos
    # como "truncated" en vez de fallar silenciosamente.
    generation_config = types.GenerateContentConfig(temperature=0.3, max_output_tokens=4096)

    # Google reporta seguido "modelo con alta demanda" (503) de forma
    # transitoria -- reintentamos un par de veces antes de rendirnos. Los
    # errores de CLIENTE (clave invalida, limite de uso) no se reintentan:
    # volver a mandar la misma solicitud no va a cambiar el resultado.
    max_attempts = 3
    response = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL, contents=prompt, config=generation_config,
            )
            break
        except errors.ClientError as e:
            code = getattr(e, "code", None)
            msg = (getattr(e, "message", None) or "").lower()
            if code == 429:
                return {"ok": False, "code": "rate_limited", "message": _ERROR_MESSAGES["rate_limited"]}
            # La API de Gemini devuelve la clave invalida como un 400 comun
            # (no 401/403), asi que hay que distinguirla por el mensaje.
            if code in (401, 403) or "api key" in msg:
                return {"ok": False, "code": "invalid_key", "message": _ERROR_MESSAGES["invalid_key"]}
            return {
                "ok": False,
                "code": "client_error",
                "message": f"Gemini rechazo la solicitud ({code}): {getattr(e, 'message', None) or e}",
            }
        except errors.ServerError:
            if attempt == max_attempts:
                return {"ok": False, "code": "server_error", "message": _ERROR_MESSAGES["server_error"]}
            time.sleep(1.5 * attempt)
        except Exception as e:  # red caida, timeout, DNS, etc.
            if attempt == max_attempts:
                return {"ok": False, "code": "network_error", "message": f"{_ERROR_MESSAGES['network_error']} ({e})"}
            time.sleep(1.5 * attempt)

    text = (getattr(response, "text", None) or "").strip()
    if not text:
        return {"ok": False, "code": "invalid_response", "message": _ERROR_MESSAGES["invalid_response"]}

    # Si el modelo se quedo sin presupuesto de tokens a mitad de la
    # respuesta (finish_reason MAX_TOKENS), el texto es real pero esta
    # incompleto -- lo devolvemos igual (mejor eso que nada) pero marcado,
    # para que la UI avise en vez de mostrarlo como si estuviera completo.
    truncated = False
    candidates = getattr(response, "candidates", None) or []
    if candidates and str(getattr(candidates[0], "finish_reason", "")).endswith("MAX_TOKENS"):
        truncated = True

    return {"ok": True, "text": text, "model": GEMINI_MODEL, "truncated": truncated}
