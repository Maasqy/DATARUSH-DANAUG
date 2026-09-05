# Fifty States, One Territory

Atlas interactivo de Estados Unidos: mapa nacional coloreado por vulnerabilidad
social (SDOH) a resolucion ZCTA5, con dashboards por estado/condado y un panel
de analisis con IA (Gemini) que interpreta esos mismos datos.

Construido con [Streamlit](https://streamlit.io/) -- no requiere backend
aparte, servidor de base de datos, ni build de frontend.

## Requisitos

- Python 3.10 o mas nuevo.
- Una clave de la API de Gemini (gratis) para el panel de analisis con IA --
  se consigue en <https://aistudio.google.com/apikey>. Sin esto, el resto de
  la app (mapa, dashboards, graficas) funciona igual; solo el boton
  "Generar analisis con IA" mostrara un mensaje pidiendo la clave.

## Instalacion

1. Clona el repositorio y entra a la carpeta:

   ```bash
   git clone <url-del-repo>
   cd DATARUSH-DANAUG
   ```

2. (Recomendado) crea un entorno virtual:

   ```bash
   python -m venv venv
   source venv/bin/activate      # Windows: venv\Scripts\activate
   ```

3. Instala las dependencias:

   ```bash
   pip install -r requirements.txt
   ```

4. Copia `.env.example` a `.env` y pega tu clave de Gemini:

   ```bash
   cp .env.example .env          # Windows: copy .env.example .env
   ```

   Luego edita `.env` y completa:

   ```
   GEMINI_API_KEY=tu-clave-aqui
   ```

   `.env` esta en `.gitignore` -- tu clave nunca se sube al repositorio. La
   clave se usa unicamente del lado del servidor (dentro del proceso de
   Streamlit, en `gemini_service.py`); nunca llega al navegador ni al
   frontend.

## Ejecutar la app

```bash
streamlit run MapaUS.py
```

Se abre sola en el navegador en `http://localhost:8501`. Si no se abre sola,
entra a esa direccion manualmente.

## Que trae el repo (no hace falta generar nada mas)

Los datos que usa el mapa ya vienen calculados y versionados junto al codigo:
`us_states.json`, `county_shapes.json`, `county_places.json`, `map_data.json`
y `nation_vulnerability.png`. Alcanza con instalar dependencias y correr
`streamlit run MapaUS.py` -- no hace falta descargar shapefiles del Census
Bureau ni correr ningun script de `build_*.py` para que la app funcione.

Esos scripts (`build_map_data.py`, `build_county_shapes.py`,
`build_zcta_vulnerability_map.py`, `clean_integrate_data.py`) solo son
necesarios si quieres **regenerar** esos datos desde cero (por ejemplo, si
cambias `integrated_data_by_state.csv`) -- cada uno explica en su propio
docstring que necesita y de donde descargarlo.

## Publicarla en Streamlit Community Cloud

`.env` esta en `.gitignore` a proposito -- nunca se sube al repositorio, asi
que **tampoco llega al servidor de Streamlit Community Cloud** cuando
publicas la app ahi. Ese hosting tiene su propio mecanismo, separado del
`.env` local, llamado **Secrets**:

1. Entra a tu app en <https://share.streamlit.io> -> **Settings** ->
   **Secrets**.
2. Pega lo mismo que tendrias en `.env`, pero en formato TOML:

   ```toml
   GEMINI_API_KEY = "tu-clave-aqui"
   GEMINI_MODEL = "gemini-flash-lite-latest"
   ```

3. Guarda -- la app se reinicia sola y ya deberia detectar la clave (el
   codigo revisa primero la variable de entorno/`.env` y, si no encuentra
   nada ahi, cae automaticamente a `st.secrets`, que es donde vive esto).

Si sigue sin detectarla despues de guardar los Secrets, entra a **Manage app**
y reinicia la app manualmente desde el menu (a veces no basta con guardar).

## Uso rapido

- El mapa nacional se puede recorrer con click (estado -> condado -> nivel de
  calle), con el buscador, o con los accesos directos a Alaska, Hawai y
  Puerto Rico.
- El boton **Dashboards** abre selectores para ver un estado completo, un
  estado + condado especifico, o comparar varios estados entre si -- las
  graficas y el mapa quedan sincronizados con la misma seleccion sin importar
  si se elige desde el dropdown o haciendo click en el mapa.
- La seccion **Analisis con IA (Gemini)**, siempre visible debajo del mapa,
  genera un analisis en espanol de la seleccion activa (o una comparacion, en
  modo "Comparar estados"), basado unicamente en los datos mostrados en el
  dashboard.

## Solucion de problemas

- **"No hay una GEMINI_API_KEY configurada"**:
  - En local: revisa que `.env` exista (no solo `.env.example`) y tenga la
    clave pegada, luego reinicia `streamlit run MapaUS.py` (los cambios en
    `.env` no se recargan solos).
  - En Streamlit Community Cloud: `.env` no cuenta ahi (ver la seccion de
    arriba) -- la clave se configura en **Settings > Secrets** de la app, y
    hay que reiniciarla despues de guardarla.
- **Limite de uso de la API de Gemini**: el plan gratuito tiene cuotas por
  modelo; espera unos minutos o revisa tu uso en
  <https://ai.dev/rate-limit>.
- **Puerto 8501 ocupado**: corre `streamlit run MapaUS.py --server.port 8502`
  (o el puerto que prefieras).
