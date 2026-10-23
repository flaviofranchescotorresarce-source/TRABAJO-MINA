# -*- coding: utf-8 -*-
"""
Radar Minero - actualizador de ofertas
--------------------------------------
Descarga ofertas VIGENTES de minería, contratistas mineras, hidrocarburos y
energía en Perú, con su fecha de publicación y su fecha de cierre real, y
escribe 'ofertas.js' al costado de radar_minero_1.html.

Fuentes:
  1. Computrabajo   - volumen alto, fecha de cierre confirmada por el portal
  2. Bumeran        - fecha de cierre confirmada por el portal
  3. LinkedIn       - avisos de empresa, fecha de publicación
  4. HiringRoom     - portales OFICIALES de las empresas (Southern, Poderosa,
                      Antapaccay, Aenza, Luz del Sur...) con enlace directo
                      al formulario donde se sube el CV
  5. El Paisano     - blog de noticias; se filtran sus convocatorias del sector

Uso:   python actualizar_ofertas.py
       (o doble clic en "Actualizar ofertas.bat")
"""

import concurrent.futures as cf
import gzip
import html as htmlmod
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

# --- SSL: usa el almacén de certificados de Windows (necesario tras proxy corporativo)
try:
    import truststore
    CTX = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
except Exception:
    CTX = ssl.create_default_context()
    CTX.check_hostname = False
    CTX.verify_mode = ssl.CERT_NONE

CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
# Bumeran sólo entrega el listado ya renderizado a los rastreadores de buscadores
BOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"

BASE_CT = "https://pe.computrabajo.com"
BASE_BM = "https://www.bumeran.com.pe"
AQUI = os.path.dirname(os.path.abspath(__file__))

# ----------------------------------------------------------------- utilidades


def get(url, timeout=35, ua=CHROME):
    # pedir gzip es clave: el JSON de El Paisano pesa 9,5 MB sin comprimir
    # (baja en ~4 s comprimido; sin comprimir se pasaba del tiempo limite)
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-PE,es;q=0.9",
        "Accept-Encoding": "gzip",
    })
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return data.decode("utf-8", "replace")


def limpiar(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = htmlmod.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def slug(s):
    s = s.lower()
    for a, b in zip("áéíóúüñ", "aeiouun"):
        s = s.replace(a, b)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


HOY = date.today()
RE_LD = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)


def dias_hasta(iso):
    try:
        return (datetime.strptime(iso, "%Y-%m-%d").date() - HOY).days
    except Exception:
        return None


REL = [
    (r"(\d+)\s*minuto", 0), (r"(\d+)\s*hora", 0), (r"ayer", 1),
    (r"(\d+)\s*d[íi]a", 1), (r"(\d+)\s*semana", 7), (r"(\d+)\s*mes", 30),
]


def fecha_relativa(txt):
    """'Hace 3 días' -> '2026-07-27'. Devuelve None si no reconoce."""
    t = (txt or "").lower()
    if "hoy" in t or "minuto" in t or "hora" in t:
        return HOY.isoformat()
    if "ayer" in t:
        return (HOY - timedelta(days=1)).isoformat()
    for pat, mult in REL:
        m = re.search(pat, t)
        if m and m.groups():
            return (HOY - timedelta(days=int(m.group(1)) * mult)).isoformat()
    return None


def job_posting(html):
    """Extrae el bloque schema.org JobPosting de una página, si existe."""
    for blk in RE_LD.findall(html):
        try:
            d = json.loads(blk)
        except Exception:
            continue
        items = d.get("@graph", [d]) if isinstance(d, dict) else (d if isinstance(d, list) else [])
        for it in items:
            if isinstance(it, dict) and it.get("@type") == "JobPosting":
                return it
    return None


# ------------------------------------------------------- clasificación sector

# Los tokens cortos van con \b: sin él, 'epc' casa dentro de "recEPCionista",
# 'ares' dentro de "VARESina" y 'orica' dentro de "histORICA".
MINERAS = (r"southern|cerro verde|antamina|las bambas|\bmmg\b|buenaventura|poderosa|quellaveco|"
           r"anglo american|\bnexa\b|minsur|marcobre|mina justa|volcan|antapaccay|glencore|hudbay|"
           r"chinalco|yanacocha|gold fields|hochschild|shougang|consorcio minero|\bmarsa\b|alpayana|"
           r"compa[nñ]ia minera|minera |miner[íi]a |mining|\bares\b|raura|milpo|catalina huanca|"
           r"coimolache|santa luisa|el brocal|sierra metals|pan american|bateas|fidami|condestable|"
           r"veta dorada|lincuna")

CONTRATISTAS = (r"stracon|\baesa\b|san mart[ií]n contratistas|\bjjc\b|cosapi|aenza|mota-engil|"
                r"ferrey|komatsu|\biesa\b|zicsa|sodexo|newrest|\bsgs\b|bureau veritas|\bransa\b|"
                r"unimaq|servosa|contratistas|contratista|\bepc\b|\btumi\b|robocon|opemin|opermin|"
                r"conymin|geodrill|redrilsa|explomin|master drilling|conmin|\bhlc\b|\bdsi\b|"
                r"\borica\b|famesa|\bexsa\b|enaex|confipetrol|techint|sacyr|resemin|\bhaug\b|"
                r"\bimco\b|serminas|epiroc|metso|rock drill|raise boring")

ENERGIA = (r"repsol|pluspetrol|petroper|petroperu|peru lng|\bsavia\b|\bgmp\b|c[áa]lidda|calidda|"
           r"engie|kallpa|orygen|statkraft|isa rep|luz del sur|celepsa|osinergmin|\benel\b|"
           r"petrolera|hidrocarburos|gas natural|refiner|energ[íi]a|termochilca|\bfenix\b|"
           r"lima gas|hunt oil|\bcnpc\b|frontera energy|olympic|distriluz|hidrandina|electroperu")

PRACTICAS = ("practicante|pr[áa]cticas|preprofesional|pre profesional|pre-profesional|"
             "trainee|graduate|graduados|becario|semillero|j[óo]venes profesionales|"
             "programa de talento|aprendiz|intern\\b|internship|"
             "profesional en entrenamiento")

# señales explícitas del sector (no "eléctrico" a secas: eso lo pide cualquier rubro)
SECTOR = (r"miner[íio]|\bmina\b|\bminas\b|planta concentradora|concentradora|geolog|"
          r"metalurg|perforaci[óo]n diamantina|voladura|volquete|campamento|socavon|"
          r"socav[óo]n|tajo abierto|subterr[áa]nea|relavera|chancado|petr[óo]le|"
          r"hidrocarbur|refiner[íi]a|gas natural|oil\s*&?\s*gas|planta de gas|lote petrolero|"
          r"generaci[óo]n el[ée]ctrica|hidroel[ée]ctrica|subestaci[óo]n|transmisi[óo]n el[ée]ctrica|"
          r"unidad minera|\bu\.?m\.?\b|14x14|14 x 14|20x10|10x10|7x7")
# 'ssoma' quedó fuera a propósito: lo pide cualquier rubro (avícolas, vidrio...)


def clasificar(titulo, empresa, extra=""):
    """Clasifica por título + empresa. La descripción NO decide categoría:
    mencionar 'bachiller' en el texto no convierte un aviso en práctica."""
    fuerte = f"{titulo} {empresa}".lower()
    cats = []
    if re.search(PRACTICAS, titulo.lower()):
        cats.append("practicas")
    if re.search(ENERGIA, fuerte):
        cats.append("energia")
    if re.search(MINERAS, fuerte):
        cats.append("minera")
    if re.search(CONTRATISTAS, fuerte):
        cats.append("contratista")
    if not cats:
        cats.append("sector")
    return cats


REGIONES = ["Arequipa", "Moquegua", "Tacna", "Cusco", "Apurímac", "Puno", "Lima", "Áncash",
            "Ancash", "Cajamarca", "Junín", "Junin", "La Libertad", "Ica", "Piura", "Pasco",
            "Ayacucho", "Huancavelica", "Callao", "Loreto", "Ucayali", "Madre de Dios",
            "Huánuco", "Huanuco", "Lambayeque", "Amazonas", "San Martín", "Tumbes"]


def region_de(txt):
    t = (txt or "")
    for r in REGIONES:
        if r.lower() in t.lower():
            return r.replace("Ancash", "Áncash").replace("Junin", "Junín").replace("Huanuco", "Huánuco")
    return ""


# ------------------------------------------------------------- 1 COMPUTRABAJO

CONSULTAS_CT = [
    # sector
    "mineria", "minera", "mina", "unidad-minera", "contratista-minero",
    "campamento-minero", "planta-concentradora", "geologia", "metalurgia",
    "mantenimiento-mina", "operario-mina", "topografia-mina", "perforacion",
    # hidrocarburos y energía
    "hidrocarburos", "petroleo", "gas-natural", "refineria", "energia",
    "planta-de-gas", "generacion-electrica", "petrolero", "oil-and-gas",
    "lote-petrolero", "perforacion-petrolera", "gasoducto", "oleoducto",
    "grifo", "combustibles", "glp", "gnv", "central-termica", "hidroelectrica",
    "subestacion-electrica", "energias-renovables", "instrumentista",
    "operador-de-planta", "mantenimiento-electromecanico",
    # administrativo del sector
    "seguridad-y-salud-ocupacional-mineria", "medio-ambiente-mineria",
    "recursos-humanos-mineria", "administracion-mineria", "logistica-mineria",
    # programas de formación
    "practicante-mineria", "practicas-preprofesionales", "practicas-profesionales",
    "practicante-ingenieria", "practicante", "trainee", "programa-de-graduados",
]

RE_ART = re.compile(r"<article[^>]*class=\"box_offer[^\"]*\"[^>]*data-id='([^']+)'(.*?)</article>", re.S)
RE_TIT = re.compile(r"<h2[^>]*>\s*<a[^>]*href=\"([^\"#]+)[^\"]*\"[^>]*>(.*?)</a>", re.S)
RE_EMP = re.compile(r"<a class=\"fc_base t_ellipsis\"[^>]*>(.*?)</a>", re.S)
RE_UBI = re.compile(r"<p class=\"fs16 fc_base mt5\">\s*<span class=\"mr10\">(.*?)</span>", re.S)
RE_FEC = re.compile(r"<p class=\"fs13 fc_aux mt15\">(.*?)</p>", re.S)
RE_SAL = re.compile(r"<span class=\"icon i_salary[^\"]*\"></span>\s*([^<]+)", re.S)


def ct_listado(consulta, pagina=1):
    url = f"{BASE_CT}/trabajo-de-{consulta}" + (f"?p={pagina}" if pagina > 1 else "")
    try:
        c = get(url)
    except Exception:
        return []
    out = []
    for oid, cuerpo in RE_ART.findall(c):
        mt = RE_TIT.search(cuerpo)
        if not mt:
            continue
        href, titulo = mt.group(1), limpiar(mt.group(2))
        me, mu, mf = RE_EMP.search(cuerpo), RE_UBI.search(cuerpo), RE_FEC.search(cuerpo)
        ms = RE_SAL.search(cuerpo)
        out.append({
            "id": "ct" + oid,
            "puesto": titulo,
            "empresa": limpiar(me.group(1)) if me else "",
            "ubicacion": limpiar(mu.group(1)) if mu else "",
            "publicado": fecha_relativa(limpiar(mf.group(1)) if mf else ""),
            "sueldo": limpiar(ms.group(1)) if ms else "",
            "url": BASE_CT + href,
            "postular": f"https://candidato.pe.computrabajo.com/candidate/apply/?oi={oid}",
            "fuente": "Computrabajo",
        })
    return out


def ct_detalle(of):
    """Abre el aviso para leer datePosted y validThrough (fecha de cierre real)."""
    try:
        c = get(of["url"], timeout=25)
    except Exception:
        return of
    it = job_posting(c)
    if not it:
        return of
    if it.get("datePosted"):
        of["publicado"] = str(it["datePosted"])[:10]
    if it.get("validThrough"):
        of["cierra"] = str(it["validThrough"])[:10]
        of["cierra_exacta"] = True
    loc = it.get("jobLocation") or {}
    addr = (loc.get("address") or {}) if isinstance(loc, dict) else {}
    reg = " ".join(str(addr.get(k, "")) for k in ("addressRegion", "addressLocality"))
    if reg.strip():
        of["ubicacion"] = limpiar(reg)
    desc = limpiar(it.get("description", ""))[:400]
    if desc:
        of["resumen"] = desc
    return of


def cosechar_computrabajo(max_detalles=700):
    """Recorre SIEMPRE todas las consultas antes de cortar.

    Antes el tope se aplicaba mientras se recorrían las consultas y, como las
    mineras van primero, las de hidrocarburos y energía nunca se ejecutaban.
    Los listados son baratos: se cosechan todos y el tope se aplica sólo al
    paso caro, que es abrir cada aviso para leer su fecha de cierre.
    """
    vistos, crudo = set(), []
    for q in CONSULTAS_CT:
        for pag in (1, 2):
            for of in ct_listado(q, pag):
                if of["id"] in vistos:
                    continue
                vistos.add(of["id"])
                crudo.append(of)
            time.sleep(0.12)
    crudo = crudo[:max_detalles]
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        crudo = list(ex.map(ct_detalle, crudo))
    return crudo


# ----------------------------------------------------------------- 2 BUMERAN

AREAS_BM = [
    "empleos-area-mineria-petroleo-y-gas.html",
    "empleos-area-produccion-y-manufactura.html",
    "empleos-area-ingenieria.html",
    "empleos-busqueda-mineria.html",
    "empleos-busqueda-practicante-mineria.html",
    "empleos-busqueda-hidrocarburos.html",
    "empleos-busqueda-energia.html",
    "empleos-busqueda-petroleo.html",
    "empleos-busqueda-gas-natural.html",
    "empleos-busqueda-refineria.html",
    "empleos-busqueda-planta-de-gas.html",
    "empleos-busqueda-electrica.html",
]


def bm_listado():
    """El listado trae un ItemList schema.org con título + URL de cada aviso."""
    vistos, out = set(), []
    for area in AREAS_BM:
        for pag in (1, 2, 3):
            u = f"{BASE_BM}/{area}" + (f"?page={pag}" if pag > 1 else "")
            try:
                c = get(u, ua=BOT, timeout=30)
            except Exception:
                break
            hallados = 0
            for blk in RE_LD.findall(c):
                try:
                    d = json.loads(blk)
                except Exception:
                    continue
                if not (isinstance(d, dict) and d.get("@type") == "ItemList"):
                    continue
                for it in d.get("itemListElement", []):
                    url = it.get("url", "")
                    m = re.search(r"-(\d+)\.html", url)
                    if not m or m.group(1) in vistos:
                        continue
                    vistos.add(m.group(1))
                    out.append({"id": "bm" + m.group(1), "puesto": limpiar(it.get("name", "")),
                                "url": url, "postular": url, "fuente": "Bumeran"})
                    hallados += 1
            if not hallados:
                break
            time.sleep(0.2)
    return out


def bm_detalle(of):
    try:
        c = get(of["url"], ua=BOT, timeout=25)
    except Exception:
        return of
    it = job_posting(c)
    if not it:
        return of
    if it.get("title"):
        of["puesto"] = limpiar(it["title"])
    if it.get("datePosted"):
        of["publicado"] = str(it["datePosted"])[:10]
    if it.get("validThrough"):
        of["cierra"] = str(it["validThrough"])[:10]
        of["cierra_exacta"] = True
    org = it.get("hiringOrganization") or {}
    if isinstance(org, dict) and org.get("name"):
        of["empresa"] = limpiar(org["name"])
    loc = it.get("jobLocation") or {}
    addr = (loc.get("address") or {}) if isinstance(loc, dict) else {}
    reg = " ".join(str(addr.get(k, "")) for k in ("addressRegion", "addressLocality")
                   if addr.get(k) and str(addr.get(k)) != "PE")
    if reg.strip():
        of["ubicacion"] = limpiar(reg)
    desc = limpiar(it.get("description", ""))[:400]
    if desc:
        of["resumen"] = desc
    return of


def cosechar_bumeran(max_ofertas=140):
    crudo = bm_listado()[:max_ofertas]
    if not crudo:
        return []
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        crudo = list(ex.map(bm_detalle, crudo))
    return [o for o in crudo if o.get("empresa") or o.get("publicado")]


# ---------------------------------------------------------------- 3 LINKEDIN

CONSULTAS_LI = [
    # minería
    "minería", "practicante minería", "trainee minería", "contratista minero",
    "planta concentradora", "prácticas preprofesionales", "programa de graduados",
    # hidrocarburos y energía
    "hidrocarburos", "petróleo y gas", "oil and gas", "refinería", "gas natural",
    "energía", "generación eléctrica", "energías renovables", "instrumentista",
    "planta de gas", "practicante energía",
]

RE_LI = re.compile(r"<div class=\"base-card[^\"]*\"[^>]*data-entity-urn=\"urn:li:jobPosting:(\d+)\"(.*?)(?=<div class=\"base-card|\Z)", re.S)
RE_LI_URL = re.compile(r"class=\"base-card__full-link\"[^>]*href=\"([^\"?]+)", re.S)
RE_LI_TIT = re.compile(r"class=\"[^\"]*base-search-card__title\"[^>]*>(.*?)</h3>", re.S)
RE_LI_EMP = re.compile(r"class=\"[^\"]*base-search-card__subtitle\"[^>]*>(.*?)</h4>", re.S)
RE_LI_UBI = re.compile(r"class=\"job-search-card__location\"[^>]*>(.*?)</span>", re.S)
RE_LI_FEC = re.compile(r"datetime=\"(\d{4}-\d{2}-\d{2})\"", re.S)
GEOID_PERU = "102927786"


def _li_es_peru(ubic):
    if re.search(r"\bper[uú]\b", (ubic or "").lower()):
        return True
    return region_de(ubic) != ""


def cosechar_linkedin():
    out, vistos = [], set()
    for q in CONSULTAS_LI:
        for start in (0, 25):
            u = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                 f"?keywords={urllib.parse.quote(q)}&location={urllib.parse.quote('Perú')}"
                 f"&geoId={GEOID_PERU}&f_TPR=r2592000&start={start}")
            try:
                c = get(u, timeout=25)
            except Exception:
                break
            hallados = RE_LI.findall(c)
            if not hallados:
                break
            for jid, cuerpo in hallados:
                if jid in vistos:
                    continue
                vistos.add(jid)
                mt, me = RE_LI_TIT.search(cuerpo), RE_LI_EMP.search(cuerpo)
                mu, mf = RE_LI_UBI.search(cuerpo), RE_LI_FEC.search(cuerpo)
                mur = RE_LI_URL.search(cuerpo)
                if not mt:
                    continue
                ubic = limpiar(mu.group(1)) if mu else ""
                if not _li_es_peru(ubic):
                    continue
                enlace = mur.group(1) if mur else f"https://www.linkedin.com/jobs/view/{jid}"
                out.append({
                    "id": "li" + jid,
                    "puesto": limpiar(mt.group(1)),
                    "empresa": limpiar(me.group(1)) if me else "",
                    "ubicacion": ubic,
                    "publicado": mf.group(1) if mf else None,
                    "url": enlace, "postular": enlace,
                    "fuente": "LinkedIn",
                })
            time.sleep(0.25)
    return out


# -------------------------------------------------------------- 4 HIRINGROOM
# Portales oficiales de postulación. El enlace 'postular' abre directamente el
# formulario de la empresa donde se adjunta el CV.

PORTALES_HR = {
    "southernperu":      "Southern Peru Copper",
    "cerroverde":        "Sociedad Minera Cerro Verde",
    "minerapoderosa":    "Compañía Minera Poderosa",
    "antapaccay":        "Glencore Antapaccay",
    "aenza":             "AENZA",
    "jjc":               "JJC Contratistas Generales",
    "tumi":              "Tumi Contratistas",
    "confipetrol":       "Confipetrol Andina",
    "resemin":           "RESEMIN",
    "ransa":             "Ransa",
    "repsol":            "Repsol Perú",
    "luzdelsur":         "Luz del Sur",
    "orygen":            "Orygen",
    "celepsa":           "Celepsa",
    "rep":               "ISA REP",
    "cementospacasmayo": "Cementos Pacasmayo",
    "unacem":            "UNACEM",
}

RE_HR = re.compile(
    r'href="(/jobs/get_vacancy/([0-9a-f]+))"[^>]*>.*?name__vacancy"?>\s*(.*?)\s*</h4>'
    r'.*?hr-Location-pin[^>]*></i>\s*(.*?)\s*</span>', re.S)


def hr_portal(par):
    sub, empresa = par
    try:
        c = get(f"https://{sub}.hiringroom.com/jobs", timeout=22)
    except Exception:
        return []
    out = []
    for href, vid, titulo, ubic in RE_HR.findall(c):
        ubic = limpiar(ubic).replace(", Peru", "").replace(", Perú", "")
        # "Tacna, Tacna" -> "Tacna"
        partes = [p.strip() for p in ubic.split(",")]
        if len(partes) > 1 and partes[0] == partes[1]:
            ubic = partes[0]
        out.append({
            "id": "hr" + vid,
            "puesto": limpiar(titulo),
            "empresa": empresa,
            "ubicacion": ubic,
            "publicado": None,
            "url": f"https://{sub}.hiringroom.com{href}",
            "postular": f"https://hiringroom.com/jobs/get_vacancy/{vid}/candidates/new",
            "fuente": "Portal oficial",
            "oficial": True,
        })
    return out


RE_ENGIE = re.compile(r'href="(https://jobs\.engie\.com/job/([^/"]+)/(\d+)-[^"]*)"')


def hr_engie():
    """ENGIE Perú no usa HiringRoom: publica sus vacantes en /talento con
    enlace directo a jobs.engie.com, que es donde se sube el CV."""
    try:
        c = get("https://engie-energia.pe/talento", timeout=25)
    except Exception:
        return []
    out, vistos = [], set()
    for url, slug, jid in RE_ENGIE.findall(c):
        if jid in vistos:
            continue
        vistos.add(jid)
        titulo = limpiar(urllib.parse.unquote(slug).replace("-", " "))
        out.append({
            "id": "eng" + jid,
            "puesto": titulo,
            "empresa": "ENGIE Energía Perú",
            "ubicacion": "Lima",
            "publicado": None,
            "url": url,
            "postular": url,
            "fuente": "Portal oficial",
            "oficial": True,
        })
    return out


def cosechar_hiringroom():
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        listas = list(ex.map(hr_portal, PORTALES_HR.items()))
    todo = [o for sub in listas for o in sub]
    todo += hr_engie()
    return todo


# -------------------------------------------------------------- 5 EL PAISANO
# Agregador de convocatorias. Su buscador de empleo se alimenta de un único
# JSON (plugin json-job-openings) con miles de avisos, cada uno con su
# "Fecha Máxima" -> es la fecha de cierre real de la convocatoria.

URL_EP = "https://elpaisano.pe/wp-content/uploads/json-jobs/jobs.json"


def cosechar_elpaisano():
    try:
        data = json.loads(get(URL_EP, timeout=60))
    except Exception:
        return []
    if not isinstance(data, list):
        return []

    out = []
    for i, it in enumerate(data):
        if not isinstance(it, dict):
            continue
        puesto = limpiar(it.get("Puesto", ""))
        if not puesto or len(puesto) < 3:
            continue

        # primer enlace util: es la pagina donde realmente se postula
        enlace = ""
        for k in ("Enlace 1", "Enlace 2", "Enlace 3", "Enlace 4", "Enlace 5", "Enlace 6"):
            v = (it.get(k) or "").strip()
            if v.startswith("http"):
                enlace = v
                break
        if not enlace:
            enlace = "https://elpaisano.pe/el-paisano-trabajos/"

        cierre = (it.get("Fecha Máxima") or "").strip()[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", cierre):
            cierre = ""

        sueldo = re.sub(r"\s+", " ", str(it.get("Salario") or "")).strip()
        if re.fullmatch(r"\d[\d.,]*", sueldo):
            sueldo = "S/ " + sueldo

        resumen = limpiar(it.get("Requisitos") or it.get("¿Quiénes pueden Postular?") or "")[:400]
        ubic = limpiar(it.get("Localidad") or it.get("Región") or "")

        of = {
            "id": "ep%d" % i,
            "puesto": puesto,
            "empresa": limpiar(it.get("Institución", "")),
            "ubicacion": ubic,
            "publicado": None,
            "sueldo": sueldo,
            "resumen": resumen,
            "url": enlace,
            "postular": enlace,
            "fuente": "El Paisano",
        }
        if cierre:
            of["cierra"] = cierre
            of["cierra_exacta"] = True
        out.append(of)
    return out


# ---------------------------------------------------------------- normalizar

RUIDO = ("call center|teleoperador|vendedor de tienda|delivery|motorizado|"
         "ventas de seguros|asesor comercial de creditos|cajero de banco|"
         "antivirus|celular|recuperar fotos|leptospirosis|remates vehiculares")

# entidades cuyas convocatorias no son del sector aunque el texto mencione
# "energía" o "ambiente" (plazas docentes, CAS administrativos, salud)
INSTITUCIONAL = (r"universidad|instituto de educaci|municipalidad|poder judicial|"
                 r"ministerio p[úu]blico|fiscal[íi]a|red de salud|diresa|essalud|"
                 r"hospital|agrobanco|sunarp|reniec|caja de pensiones|"
                 r"gobierno regional|ugel|colegio |c[áa]tedra|plaza docente")

# Entidades del Estado. Sus convocatorias no son del sector minero-energético,
# pero se guardan aparte en su propia categoría ("estado"), sin mezclarse.
ESTADO = (r"ministerio|municipalidad|gobierno regional|universidad|poder judicial|"
          r"fiscal[íi]a|sunat|sunarp|sunedu|reniec|\bonpe\b|\bjne\b|\binei\b|indecopi|"
          r"\bosce\b|servir|essalud|diresa|red de salud|hospital|\bugel\b|"
          r"programa nacional|instituto nacional|superintendencia|contralor[íi]a|"
          r"defensor[íi]a|congreso|pronied|qali warma|pensi[óo]n 65|foncodes|devida|"
          r"sencico|cofopri|agrobanco|banco de la naci[óo]n|caja de pensiones|"
          r"ej[ée]rcito|marina de guerra|polic[íi]a|autoridad nacional|sedapal|"
          r"beneficencia|instituto de educaci|direcci[óo]n regional|unidad ejecutora|"
          r"proyecto especial|mancomunidad|centro de salud|micro red|servicio nacional|"
          r"colegio nacional|senasa|senamhi|ingemmet|osinergmin|minem|midagri|minedu|"
          r"minsa|produce|mincetur|midis|essalud|\bsis\b|\bpnp\b")


def es_estado(of):
    """Convocatoria pública que vale la pena guardar aunque no sea del sector."""
    txt = f"{of.get('puesto','')} {of.get('empresa','')}".lower()
    if re.search(RUIDO, txt):
        return False
    return bool(re.search(ESTADO, (of.get("empresa", "") or "").lower()))

# líneas de negocio ajenas al sector dentro de grupos diversificados
# (AENZA tiene inmobiliaria "Viva", UNACEM y Pacasmayo tienen retail, etc.)
FUERA_SECTOR = (r"inmobiliari|viva negocio|restitucion|retail|tienda|cobranza|"
                r"agencia bancaria|progresol|casa & ideas")


def relevante(of):
    if of.get("oficial"):
        # viene del portal de una empresa del sector: se acepta salvo que sea
        # de una línea de negocio ajena (inmobiliaria, retail, cobranzas)
        return not re.search(FUERA_SECTOR, f"{of.get('puesto','')} {of.get('empresa','')}".lower())
    fuerte = f"{of.get('puesto','')} {of.get('empresa','')}".lower()
    debil = (of.get("resumen", "") or "").lower()
    if re.search(RUIDO, fuerte) or re.search(RUIDO, debil[:120]):
        return False
    if re.search(INSTITUCIONAL, of.get("empresa", "").lower()):
        return False
    if re.search(SECTOR, fuerte) or re.search(MINERAS, fuerte) \
            or re.search(CONTRATISTAS, fuerte) or re.search(ENERGIA, fuerte):
        return True
    if re.search(PRACTICAS, of.get("puesto", "").lower()) and re.search(SECTOR, debil):
        return True
    return False


def normalizar(lista):
    fin, vistos = [], set()
    for of in lista:
        if not of.get("puesto"):
            continue
        publico = False
        if not relevante(of):
            # no es del sector: sólo se guarda si es convocatoria del Estado,
            # y va etiquetada aparte para no mezclarse con lo minero-energético
            if of.get("fuente") == "El Paisano" and es_estado(of):
                publico = True
            else:
                continue
        clave = (slug(of["puesto"])[:60], slug(of.get("empresa", ""))[:40])
        if clave in vistos:
            continue
        vistos.add(clave)

        pub = of.get("publicado")
        cierre = of.get("cierra")
        exacta = bool(of.get("cierra_exacta"))
        if not cierre and pub and not of.get("oficial"):
            # sin dato del portal: los avisos suelen mantenerse ~30 días
            try:
                cierre = (datetime.strptime(pub, "%Y-%m-%d").date() + timedelta(days=30)).isoformat()
            except Exception:
                cierre = None
        d = dias_hasta(cierre) if cierre else None
        if d is not None and d < 0:
            continue  # ya venció

        of["publicado"] = pub
        of["cierra"] = cierre
        of["cierra_exacta"] = exacta
        of["dias"] = d
        if publico:
            of["cats"] = ["estado"]
            of["estatal"] = True
        else:
            of["cats"] = clasificar(of["puesto"], of.get("empresa", ""), of.get("resumen", ""))
            if of.get("oficial"):
                of["cats"].append("oficial")
        of["region"] = region_de(of.get("ubicacion", "")) or "Otras"
        fin.append(of)

    fin.sort(key=lambda o: (o["dias"] if o["dias"] is not None else 999, o["puesto"]))
    return fin


# --------------------------------------------------------------------- salida

FUENTES = [
    ("Computrabajo",  cosechar_computrabajo),
    ("Bumeran",       cosechar_bumeran),
    ("LinkedIn",      cosechar_linkedin),
    ("Portal oficial", cosechar_hiringroom),
    ("El Paisano",    cosechar_elpaisano),
]


def registrar(linea):
    """Deja constancia en bitacora.txt: la tarea programada corre sin ventana."""
    try:
        with open(os.path.join(AQUI, "bitacora.txt"), "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M}  {linea}\n")
    except Exception:
        pass


def main():
    print("Radar Minero - actualizando ofertas...\n")
    todo, resumen = [], []
    for nombre, fn in FUENTES:
        try:
            r = fn()
            todo += r
            resumen.append((nombre, len(r)))
            print(f"  {nombre:16} {len(r):4} avisos")
        except Exception as e:
            resumen.append((nombre, 0))
            print(f"  {nombre:16}    0 avisos  (fallo: {str(e)[:60]})")

    ofertas = normalizar(todo)

    # puntaje por perfil: reglas deterministas, sin IA y sin coste
    nota_agente = None
    if ofertas:
        try:
            import agente
            ofertas, nota_agente = agente.aplicar(ofertas)
            if nota_agente:
                print(f"\n  Perfil: {nota_agente}")
        except Exception as e:
            print(f"\n  ! El puntaje fallo ({str(e)[:70]}); las ofertas se guardan igual")

    if not ofertas:
        print("\nNo se obtuvo ninguna oferta. Revisa tu conexion o el proxy de la empresa.")
        print("El archivo ofertas.js anterior se conserva.")
        registrar("FALLO - ninguna oferta descargada; se conserva ofertas.js anterior")
        return 1

    payload = {
        "actualizado": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total": len(ofertas),
        "fuentes": [{"nombre": n, "n": sum(1 for o in ofertas if o["fuente"] == n)}
                    for n, _ in FUENTES],
        "agente": nota_agente,
        "ofertas": ofertas,
    }
    destino = os.path.join(AQUI, "ofertas.js")
    with open(destino, "w", encoding="utf-8") as f:
        f.write("window.OFERTAS = ")
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")

    con_cierre = sum(1 for o in ofertas if o.get("cierra_exacta"))
    oficiales = sum(1 for o in ofertas if o.get("oficial"))
    estatales = sum(1 for o in ofertas if o.get("estatal"))
    sector = len(ofertas) - estatales
    print(f"\n  Tras filtrar y quitar repetidos: {sector} ofertas del sector")
    print(f"  + {estatales} convocatorias del Estado (categoria aparte)")
    print(f"  {con_cierre} con fecha de cierre confirmada por el portal")
    print(f"  {oficiales} en portales oficiales de las empresas")
    print(f"\nGuardado en {destino}")
    print("Abre radar_minero_1.html y pulsa F5.")
    registrar(f"OK - {sector} del sector + {estatales} del Estado "
              f"({con_cierre} con cierre confirmado, {oficiales} de portales oficiales) | "
              + ", ".join(f"{n}:{c}" for n, c in resumen))
    return 0


if __name__ == "__main__":
    sys.exit(main())
