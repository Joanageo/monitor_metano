# -*- coding: utf-8 -*-
"""
Dashboard de Monitoramento de Metano — TROPOMI Brasil
Versão online completa — Supabase/PostGIS + filtros avançados + gráficos + ranking espacial

Como usar no Streamlit Cloud:
1) Garanta que o secrets.toml tenha DATABASE_URL.
2) Garanta que requirements.txt contenha:
   streamlit
   pandas
   geopandas
   folium
   streamlit-folium
   plotly
   sqlalchemy
   psycopg2-binary
   shapely
   pyproj
3) Rode: streamlit run dashboard_metano_tropomi_online_completo.py
"""

import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import geopandas as gpd
import streamlit as st
import folium
from folium.plugins import MarkerCluster, MiniMap, Fullscreen, HeatMap
from streamlit_folium import st_folium
import plotly.express as px
import plotly.graph_objects as go
from sqlalchemy import create_engine, text

# =========================================================
# CONFIGURAÇÃO DA PÁGINA
# =========================================================
st.set_page_config(
    page_title="Monitor CH4 | TROPOMI Brasil",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================================================
# CONEXÃO COM SUPABASE / POSTGIS
# =========================================================
try:
    DATABASE_URL = st.secrets["DATABASE_URL"]
except Exception:
    st.error("DATABASE_URL não configurada. Crie .streamlit/secrets.toml no Streamlit Cloud.")
    st.stop()

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
    connect_args={"connect_timeout": 20},
)

# =========================================================
# ESTILO
# =========================================================
st.markdown(
    """
<style>
.stApp {
    background: linear-gradient(180deg, #0b1220 0%, #0f1b2d 100%);
    color: #e6edf3;
}
* { font-family: Arial, sans-serif; }
[data-testid="stSidebar"] {
    background-color: #0c1424;
    border-right: 1px solid #1f2e4a;
}
h1, h2, h3, h4, h5, h6, p, span, div, label {
    color: #e6edf3;
}
[data-testid="metric-container"] {
    background: #121f36;
    border: 1px solid #1f3a5f;
    border-radius: 12px;
    padding: 14px;
}
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(6, minmax(135px, 1fr));
    gap: 12px;
    margin: 12px 0 20px 0;
}
.kpi-card {
    background: linear-gradient(180deg, rgba(18,31,54,0.96) 0%, rgba(13,24,42,0.96) 100%);
    border: 1px solid #1f3a5f;
    border-radius: 14px;
    padding: 14px;
    min-height: 92px;
    box-shadow: 0 10px 24px rgba(0,0,0,0.16);
}
.kpi-label {
    color: #9fb4cc;
    font-size: 0.74rem;
    font-weight: 700;
    line-height: 1.2;
    margin-bottom: 8px;
}
.kpi-value {
    color: #ffffff;
    font-size: 1.55rem;
    font-weight: 700;
    line-height: 1.05;
}
.kpi-delta {
    display: inline-block;
    margin-top: 8px;
    padding: 3px 8px;
    border-radius: 999px;
    background: rgba(35, 134, 54, 0.55);
    color: #7ee787;
    font-size: 0.70rem;
    font-weight: 700;
}
.info-card {
    background: rgba(88, 166, 255, 0.08);
    border: 1px solid rgba(88, 166, 255, 0.22);
    border-radius: 12px;
    padding: 12px;
    margin-bottom: 12px;
}
.filter-title {
    font-size: 0.85rem;
    color: #58a6ff;
    font-weight: 800;
    margin-bottom: 4px;
}
hr { border-color: #1f2e4a; }
@media (max-width: 1300px) {
    .kpi-grid { grid-template-columns: repeat(3, minmax(135px, 1fr)); }
}
@media (max-width: 800px) {
    .kpi-grid { grid-template-columns: repeat(2, minmax(135px, 1fr)); }
}
</style>
""",
    unsafe_allow_html=True,
)

# =========================================================
# UTILITÁRIOS
# =========================================================
def fmt_int(v):
    try:
        return f"{int(v):,}".replace(",", ".")
    except Exception:
        return "0"


def fmt_float(v, casas=1):
    try:
        return f"{float(v):,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "0"


def build_where(alias="a", uf="Todas", ano="Todos", mes="Todos", xmean_min=None, area_min=None):
    filtros = []
    params = {}

    if uf and uf != "Todas":
        filtros.append(f"{alias}.uf = :uf")
        params["uf"] = uf

    if ano and ano != "Todos":
        filtros.append(f"EXTRACT(YEAR FROM {alias}.date::date) = :ano")
        params["ano"] = int(ano)

    if mes and mes != "Todos":
        filtros.append(f"TO_CHAR({alias}.date::date, 'YYYY-MM') = :mes")
        params["mes"] = mes

    if xmean_min is not None:
        filtros.append(f"{alias}.xmean >= :xmean_min")
        params["xmean_min"] = float(xmean_min)

    if area_min is not None:
        filtros.append(f"COALESCE({alias}.area_km2, 0) >= :area_min")
        params["area_min"] = float(area_min)

    where = "WHERE " + " AND ".join(filtros) if filtros else ""
    return where, params


def build_fontes_where(cadeia="Todas", tipo_fonte="Todos", fonte_id="Todas", alias="f"):
    filtros = []
    params = {}

    if cadeia and cadeia != "Todas":
        filtros.append(f"{alias}.cadeia = :cadeia")
        params["cadeia"] = cadeia

    if tipo_fonte and tipo_fonte != "Todos":
        filtros.append(f"{alias}.tipo_fonte = :tipo_fonte")
        params["tipo_fonte"] = tipo_fonte

    if fonte_id and fonte_id != "Todas":
        filtros.append(f"{alias}.id = :fonte_id")
        params["fonte_id"] = int(fonte_id)

    where = "WHERE " + " AND ".join(filtros) if filtros else ""
    return where, params


def plotly_dark(fig, height=None):
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e6edf3"),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=10, r=10, t=42, b=10),
        height=height,
    )
    fig.update_xaxes(gridcolor="rgba(255,255,255,0.08)")
    fig.update_yaxes(gridcolor="rgba(255,255,255,0.08)")
    return fig

# =========================================================
# LEITURAS DE DOMÍNIO
# =========================================================
@st.cache_data(show_spinner="Carregando opções de filtro...")
def load_options():
    sql = """
    SELECT
        ARRAY(SELECT DISTINCT uf FROM metano.anomalias_tropomi WHERE uf IS NOT NULL ORDER BY uf) AS ufs,
        ARRAY(SELECT DISTINCT EXTRACT(YEAR FROM date::date)::int FROM metano.anomalias_tropomi WHERE date IS NOT NULL ORDER BY 1) AS anos,
        ARRAY(SELECT DISTINCT TO_CHAR(date::date, 'YYYY-MM') FROM metano.anomalias_tropomi WHERE date IS NOT NULL ORDER BY 1) AS meses,
        ARRAY(SELECT DISTINCT cadeia FROM metano.vw_fontes_metano WHERE cadeia IS NOT NULL ORDER BY cadeia) AS cadeias,
        ARRAY(SELECT DISTINCT tipo_fonte FROM metano.vw_fontes_metano WHERE tipo_fonte IS NOT NULL ORDER BY tipo_fonte) AS tipos;
    """
    return pd.read_sql(sql, engine).iloc[0]


@st.cache_data(show_spinner="Carregando lista de empreendimentos...")
def load_fonte_lista(cadeia="Todas", tipo_fonte="Todos"):
    where, params = build_fontes_where(cadeia=cadeia, tipo_fonte=tipo_fonte, alias="f")
    sql = f"""
        SELECT id, nome, tipo_fonte, cadeia, municipio, uf
        FROM metano.vw_fontes_metano f
        {where}
        ORDER BY nome NULLS LAST, tipo_fonte NULLS LAST
        LIMIT 5000;
    """
    return pd.read_sql(text(sql), engine, params=params)


@st.cache_data(show_spinner="Carregando resumo filtrado...")
def load_resumo_filtrado(uf="Todas", ano="Todos", mes="Todos", xmean_min=None, area_min=None, cadeia="Todas", tipo_fonte="Todos", fonte_id="Todas", raio_km=10):
    where_a, params_a = build_where("a", uf, ano, mes, xmean_min, area_min)
    where_f, params_f = build_fontes_where(cadeia, tipo_fonte, fonte_id, "f")
    params = {**params_a, **params_f, "raio_m": float(raio_km) * 1000.0}

    sql = f"""
    WITH anom AS (
        SELECT * FROM metano.anomalias_tropomi a
        {where_a}
    ), fontes AS (
        SELECT * FROM metano.vw_fontes_metano f
        {where_f}
    ), rel AS (
        SELECT DISTINCT a.id AS anomalia_id
        FROM anom a
        JOIN fontes f
          ON ST_DWithin(a.geom::geography, f.geom::geography, :raio_m)
    )
    SELECT
        (SELECT COUNT(*) FROM anom) AS total_anomalias,
        (SELECT COUNT(*) FROM fontes) AS total_fontes,
        (SELECT COUNT(*) FROM rel) AS anomalias_com_fonte,
        (SELECT ROUND(AVG(xmean)::numeric, 2) FROM anom) AS media_xmean,
        (SELECT ROUND(MAX(xch4_max)::numeric, 2) FROM anom) AS max_xch4,
        (SELECT ROUND(AVG(area_km2)::numeric, 2) FROM anom) AS area_media_km2;
    """
    return pd.read_sql(text(sql), engine, params=params)


@st.cache_data(show_spinner="Carregando anomalias TROPOMI...")
def load_anomalias(uf="Todas", ano="Todos", mes="Todos", xmean_min=None, area_min=None, limite=3000):
    where, params = build_where("a", uf, ano, mes, xmean_min, area_min)
    params["limite"] = int(limite)
    sql = f"""
        SELECT
            id,
            date,
            uf,
            state,
            xmean,
            xch4_max,
            d_xch4,
            area_km2,
            pix_n,
            thr,
            geom
        FROM metano.anomalias_tropomi a
        {where}
        ORDER BY date DESC
        LIMIT :limite;
    """
    return gpd.read_postgis(text(sql), engine, geom_col="geom", params=params)


@st.cache_data(show_spinner="Carregando fontes...")
def load_fontes(cadeia="Todas", tipo_fonte="Todos", fonte_id="Todas", limite=8000):
    where, params = build_fontes_where(cadeia, tipo_fonte, fonte_id, "f")
    params["limite"] = int(limite)
    sql = f"""
        SELECT
            id,
            nome,
            tipo_fonte,
            cadeia,
            municipio,
            uf,
            geom
        FROM metano.vw_fontes_metano f
        {where}
        ORDER BY nome NULLS LAST
        LIMIT :limite;
    """
    return gpd.read_postgis(text(sql), engine, geom_col="geom", params=params)


@st.cache_data(show_spinner="Carregando série temporal filtrada...")
def load_temporal(uf="Todas", ano="Todos", mes="Todos", xmean_min=None, area_min=None):
    where, params = build_where("a", uf, ano, mes, xmean_min, area_min)
    sql = f"""
        SELECT
            DATE_TRUNC('month', a.date::date)::date AS mes,
            COUNT(*) AS total_anomalias,
            ROUND(AVG(a.xmean)::numeric, 2) AS media_xmean,
            ROUND(MAX(a.xch4_max)::numeric, 2) AS maior_xch4,
            ROUND(AVG(a.area_km2)::numeric, 2) AS area_media_km2
        FROM metano.anomalias_tropomi a
        {where}
        GROUP BY DATE_TRUNC('month', a.date::date)
        ORDER BY mes;
    """
    return pd.read_sql(text(sql), engine, params=params)


@st.cache_data(show_spinner="Carregando ranking por UF...")
def load_ranking_uf(uf="Todas", ano="Todos", mes="Todos", xmean_min=None, area_min=None):
    where, params = build_where("a", uf, ano, mes, xmean_min, area_min)
    sql = f"""
        SELECT
            COALESCE(a.uf, 'Sem UF') AS uf,
            COUNT(*) AS total_anomalias,
            ROUND(AVG(a.xmean)::numeric, 2) AS media_xmean,
            ROUND(MAX(a.xch4_max)::numeric, 2) AS max_xch4,
            ROUND(SUM(COALESCE(a.area_km2, 0))::numeric, 2) AS area_total_km2
        FROM metano.anomalias_tropomi a
        {where}
        GROUP BY COALESCE(a.uf, 'Sem UF')
        ORDER BY total_anomalias DESC
        LIMIT 30;
    """
    return pd.read_sql(text(sql), engine, params=params)


@st.cache_data(show_spinner="Calculando ranking espacial por empreendimento...")
def load_ranking_espacial(uf="Todas", ano="Todos", mes="Todos", xmean_min=None, area_min=None, cadeia="Todas", tipo_fonte="Todos", fonte_id="Todas", raio_km=10, limite=100):
    where_a, params_a = build_where("a", uf, ano, mes, xmean_min, area_min)
    where_f, params_f = build_fontes_where(cadeia, tipo_fonte, fonte_id, "f")
    params = {**params_a, **params_f, "raio_m": float(raio_km) * 1000.0, "limite": int(limite)}

    sql = f"""
    WITH anom AS (
        SELECT id, date, uf, xmean, xch4_max, d_xch4, area_km2, geom
        FROM metano.anomalias_tropomi a
        {where_a}
    ), fontes AS (
        SELECT id, nome, tipo_fonte, cadeia, municipio, uf, geom
        FROM metano.vw_fontes_metano f
        {where_f}
    ), pares AS (
        SELECT
            f.id AS fonte_id,
            f.nome AS nome_fonte,
            f.tipo_fonte,
            f.cadeia,
            f.municipio AS municipio_fonte,
            f.uf AS uf_fonte,
            a.id AS anomalia_id,
            a.date,
            a.xmean,
            a.xch4_max,
            a.area_km2,
            ST_Distance(a.geom::geography, f.geom::geography) / 1000.0 AS distancia_km
        FROM fontes f
        JOIN anom a
          ON ST_DWithin(a.geom::geography, f.geom::geography, :raio_m)
    )
    SELECT
        fonte_id,
        nome_fonte,
        tipo_fonte,
        cadeia,
        municipio_fonte,
        uf_fonte,
        COUNT(DISTINCT anomalia_id) AS frequencia_anomalias,
        ROUND(AVG(distancia_km)::numeric, 2) AS distancia_media_km,
        ROUND(MIN(distancia_km)::numeric, 2) AS menor_distancia_km,
        ROUND(AVG(xmean)::numeric, 2) AS media_xmean,
        ROUND(MAX(xch4_max)::numeric, 2) AS maior_xch4,
        ROUND(SUM(COALESCE(area_km2,0))::numeric, 2) AS soma_area_km2,
        MIN(date)::date AS primeira_anomalia,
        MAX(date)::date AS ultima_anomalia
    FROM pares
    GROUP BY fonte_id, nome_fonte, tipo_fonte, cadeia, municipio_fonte, uf_fonte
    ORDER BY frequencia_anomalias DESC, media_xmean DESC
    LIMIT :limite;
    """
    return pd.read_sql(text(sql), engine, params=params)


@st.cache_data(show_spinner="Carregando anomalias próximas do empreendimento...")
def load_anomalias_do_empreendimento(fonte_id, uf="Todas", ano="Todos", mes="Todos", xmean_min=None, area_min=None, raio_km=10, limite=1000):
    if fonte_id == "Todas":
        return pd.DataFrame()

    where_a, params_a = build_where("a", uf, ano, mes, xmean_min, area_min)
    params = {**params_a, "fonte_id": int(fonte_id), "raio_m": float(raio_km) * 1000.0, "limite": int(limite)}

    sql = f"""
    SELECT
        a.id,
        a.date,
        a.uf,
        a.xmean,
        a.xch4_max,
        a.d_xch4,
        a.area_km2,
        a.pix_n,
        ROUND((ST_Distance(a.geom::geography, f.geom::geography) / 1000.0)::numeric, 2) AS distancia_km
    FROM metano.anomalias_tropomi a
    JOIN metano.vw_fontes_metano f
      ON f.id = :fonte_id
     AND ST_DWithin(a.geom::geography, f.geom::geography, :raio_m)
    {where_a}
    ORDER BY a.date DESC, distancia_km ASC
    LIMIT :limite;
    """
    return pd.read_sql(text(sql), engine, params=params)

# =========================================================
# SIDEBAR
# =========================================================
opts = load_options()
ufs = ["Todas"] + list(opts["ufs"] or [])
anos = ["Todos"] + [int(a) for a in list(opts["anos"] or [])]
meses = ["Todos"] + list(opts["meses"] or [])
cadeias = ["Todas"] + list(opts["cadeias"] or [])
tipos = ["Todos"] + list(opts["tipos"] or [])

with st.sidebar:
    st.markdown("## 🛰️ Monitor CH4")
    st.markdown("**TROPOMI · Sentinel-5P · Supabase/PostGIS**")
    st.markdown("---")

    st.markdown('<div class="filter-title">Filtros temporais e espaciais</div>', unsafe_allow_html=True)
    ano_sel = st.selectbox("Ano", anos, index=0)
    mes_sel = st.selectbox("Mês", meses, index=0)
    uf_sel = st.selectbox("UF", ufs, index=0)

    st.markdown('<div class="filter-title">Filtros das fontes</div>', unsafe_allow_html=True)
    cadeia_sel = st.selectbox("Cadeia produtiva", cadeias, index=0)
    tipo_sel = st.selectbox("Tipo de fonte", tipos, index=0)

    fontes_lista = load_fonte_lista(cadeia_sel, tipo_sel)
    fonte_options = {"Todas": "Todas"}
    for _, row in fontes_lista.iterrows():
        nome = row.get("nome") or "Sem nome"
        tipo = row.get("tipo_fonte") or "Sem tipo"
        municipio = row.get("municipio") or ""
        uf = row.get("uf") or ""
        fonte_options[f"{nome} · {tipo} · {municipio}/{uf}"] = str(row["id"])

    fonte_label = st.selectbox("Empreendimento/fonte", list(fonte_options.keys()), index=0)
    fonte_id_sel = fonte_options[fonte_label]

    st.markdown('<div class="filter-title">Parâmetros analíticos</div>', unsafe_allow_html=True)
    raio_km = st.slider("Raio de associação fonte ↔ anomalia (km)", 1, 100, 10, 1)
    xmean_min = st.number_input("XCH₄ médio mínimo (ppb)", min_value=0.0, value=0.0, step=1.0)
    area_min = st.number_input("Área mínima da anomalia (km²)", min_value=0.0, value=0.0, step=1.0)
    limite_anomalias = st.slider("Limite de anomalias no mapa", 500, 15000, 4000, 500)
    limite_fontes = st.slider("Limite de fontes no mapa", 500, 15000, 5000, 500)

    mostrar_heatmap = st.checkbox("Mostrar mapa de calor das anomalias", value=False)
    mostrar_buffer = st.checkbox("Mostrar raio do empreendimento selecionado", value=True)
    mostrar_poligonos = st.checkbox("Mostrar polígonos TROPOMI", value=True)

    if st.button("🔄 Limpar cache e recarregar"):
        st.cache_data.clear()
        st.rerun()

# Normaliza filtros numéricos: zero significa sem filtro restritivo.
xmean_min_query = None if float(xmean_min) <= 0 else float(xmean_min)
area_min_query = None if float(area_min) <= 0 else float(area_min)

# =========================================================
# CARREGAMENTO PRINCIPAL
# =========================================================
resumo = load_resumo_filtrado(
    uf_sel, ano_sel, mes_sel, xmean_min_query, area_min_query,
    cadeia_sel, tipo_sel, fonte_id_sel, raio_km
)
anomalias = load_anomalias(uf_sel, ano_sel, mes_sel, xmean_min_query, area_min_query, limite_anomalias)
fontes = load_fontes(cadeia_sel, tipo_sel, fonte_id_sel, limite_fontes)
temporal = load_temporal(uf_sel, ano_sel, mes_sel, xmean_min_query, area_min_query)
ranking_uf = load_ranking_uf(uf_sel, ano_sel, mes_sel, xmean_min_query, area_min_query)
ranking = load_ranking_espacial(
    uf_sel, ano_sel, mes_sel, xmean_min_query, area_min_query,
    cadeia_sel, tipo_sel, fonte_id_sel, raio_km, limite=150
)
anomalias_fonte = load_anomalias_do_empreendimento(
    fonte_id_sel, uf_sel, ano_sel, mes_sel, xmean_min_query, area_min_query, raio_km
)

# =========================================================
# CABEÇALHO E KPIs
# =========================================================
st.markdown("# 🛰️ Monitoramento de Metano no Brasil")
st.caption("TROPOMI/Sentinel-5P conectado ao Supabase/PostGIS — versão online com filtros, gráficos e ranking espacial")

r = resumo.iloc[0] if len(resumo) else {}
total_anom = int(r.get("total_anomalias", 0) or 0)
total_fontes = int(r.get("total_fontes", 0) or 0)
anom_com_fonte = int(r.get("anomalias_com_fonte", 0) or 0)
pct_assoc = (anom_com_fonte / total_anom * 100) if total_anom > 0 else 0

st.markdown(
    f"""
<div class="kpi-grid">
  <div class="kpi-card"><div class="kpi-label">Anomalias filtradas</div><div class="kpi-value">{fmt_int(total_anom)}</div></div>
  <div class="kpi-card"><div class="kpi-label">Fontes filtradas</div><div class="kpi-value">{fmt_int(total_fontes)}</div></div>
  <div class="kpi-card"><div class="kpi-label">Anomalias no mapa</div><div class="kpi-value">{fmt_int(len(anomalias))}</div><div class="kpi-delta">limite aplicado</div></div>
  <div class="kpi-card"><div class="kpi-label">Com fonte até {raio_km} km</div><div class="kpi-value">{fmt_float(pct_assoc, 0)}%</div><div class="kpi-delta">{fmt_int(anom_com_fonte)} anomalias</div></div>
  <div class="kpi-card"><div class="kpi-label">XCH₄ médio</div><div class="kpi-value">{fmt_float(r.get('media_xmean', 0), 1)}</div><div class="kpi-delta">ppb</div></div>
  <div class="kpi-card"><div class="kpi-label">Maior XCH₄</div><div class="kpi-value">{fmt_float(r.get('max_xch4', 0), 1)}</div><div class="kpi-delta">ppb</div></div>
</div>
<hr>
""",
    unsafe_allow_html=True,
)

# =========================================================
# ABAS PRINCIPAIS
# =========================================================
tab_mapa, tab_graficos, tab_ranking, tab_tabelas = st.tabs([
    "🗺️ Mapa e análise lateral",
    "📈 Gráficos",
    "🏭 Ranking espacial",
    "📋 Tabelas e downloads",
])

# =========================================================
# MAPA
# =========================================================
with tab_mapa:
    col_mapa, col_painel = st.columns([1.45, 1.0], gap="medium")

    with col_mapa:
        if anomalias is not None and len(anomalias) > 0:
            anomalias_plot = anomalias.to_crs(epsg=4326)
            centro = [anomalias_plot.geometry.centroid.y.mean(), anomalias_plot.geometry.centroid.x.mean()]
            zoom = 5 if uf_sel == "Todas" else 6
        else:
            anomalias_plot = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
            centro = [-14.2, -51.9]
            zoom = 4

        m = folium.Map(location=centro, zoom_start=zoom, tiles=None, prefer_canvas=True)
        folium.TileLayer("CartoDB dark_matter", name="Base escura", show=True).add_to(m)
        folium.TileLayer("OpenStreetMap", name="OpenStreetMap", show=False).add_to(m)
        folium.TileLayer(
            "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri", name="Satélite", show=False
        ).add_to(m)
        Fullscreen(position="topright").add_to(m)
        MiniMap(toggle_display=True).add_to(m)

        if mostrar_heatmap and len(anomalias_plot) > 0:
            heat_points = []
            for _, row in anomalias_plot.iterrows():
                try:
                    pt = row.geometry.representative_point()
                    peso = float(row.get("xmean") or 1)
                    heat_points.append([pt.y, pt.x, peso])
                except Exception:
                    pass
            if heat_points:
                HeatMap(heat_points, name="Heatmap XCH₄", radius=18, blur=22, min_opacity=0.25).add_to(m)

        if mostrar_poligonos and len(anomalias_plot) > 0:
            folium.GeoJson(
                anomalias_plot,
                name="Anomalias TROPOMI",
                style_function=lambda feature: {
                    "fillColor": "#ff4d4d",
                    "color": "#ff9999",
                    "weight": 1,
                    "fillOpacity": 0.35,
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=[c for c in ["date", "uf", "xmean", "xch4_max", "d_xch4", "area_km2", "pix_n", "thr"] if c in anomalias_plot.columns],
                    aliases=["Data", "UF", "XCH₄ médio", "XCH₄ máximo", "ΔXCH₄", "Área km²", "Pixels", "Limiar"],
                    localize=True,
                    sticky=True,
                ),
            ).add_to(m)

        if fontes is not None and len(fontes) > 0:
            fontes_plot = fontes.to_crs(epsg=4326)
            cluster = MarkerCluster(name="Fontes de emissão").add_to(m)

            for _, row in fontes_plot.iterrows():
                try:
                    geom = row.geometry
                    if geom is None or geom.is_empty:
                        continue
                    pt = geom if geom.geom_type == "Point" else geom.representative_point()
                    popup = f"""
                    <div style="font-family: Arial; font-size: 13px; color:#111;">
                        <b>{row.get('nome', 'Sem nome')}</b><br>
                        <b>Cadeia:</b> {row.get('cadeia', '')}<br>
                        <b>Tipo:</b> {row.get('tipo_fonte', '')}<br>
                        <b>Município:</b> {row.get('municipio', '')}<br>
                        <b>UF:</b> {row.get('uf', '')}<br>
                        <b>ID:</b> {row.get('id', '')}
                    </div>
                    """
                    cor = "#4ea1ff"
                    if row.get("cadeia") == "upstream":
                        cor = "#ffb347"
                    elif row.get("cadeia") == "midstream":
                        cor = "#4ea1ff"
                    elif row.get("cadeia") == "downstream":
                        cor = "#7ee787"

                    folium.CircleMarker(
                        location=[pt.y, pt.x],
                        radius=5 if str(row.get("id")) == str(fonte_id_sel) else 4,
                        color="#ffffff" if str(row.get("id")) == str(fonte_id_sel) else cor,
                        weight=2 if str(row.get("id")) == str(fonte_id_sel) else 1,
                        fill=True,
                        fill_color=cor,
                        fill_opacity=0.92,
                        popup=folium.Popup(popup, max_width=320),
                        tooltip=row.get("nome", "Fonte"),
                    ).add_to(cluster)

                    if mostrar_buffer and fonte_id_sel != "Todas" and str(row.get("id")) == str(fonte_id_sel):
                        folium.Circle(
                            location=[pt.y, pt.x],
                            radius=float(raio_km) * 1000.0,
                            color="#58a6ff",
                            weight=2,
                            fill=True,
                            fill_color="#58a6ff",
                            fill_opacity=0.08,
                            tooltip=f"Raio de análise: {raio_km} km",
                        ).add_to(m)
                except Exception:
                    continue

        folium.LayerControl(collapsed=False).add_to(m)
        st_folium(m, width=None, height=680, key="mapa_tropomi_online")

    with col_painel:
        st.markdown("### Leitura rápida")
        st.markdown(
            f"""
<div class="info-card">
<b>Filtro ativo</b><br>
UF: <b>{uf_sel}</b><br>
Ano: <b>{ano_sel}</b><br>
Mês: <b>{mes_sel}</b><br>
Cadeia: <b>{cadeia_sel}</b><br>
Tipo: <b>{tipo_sel}</b><br>
Raio: <b>{raio_km} km</b>
</div>
""",
            unsafe_allow_html=True,
        )

        if fonte_id_sel != "Todas":
            st.markdown("#### Empreendimento selecionado")
            st.write(fonte_label)
            st.metric("Anomalias próximas", fmt_int(len(anomalias_fonte)))
            if len(anomalias_fonte) > 0:
                st.metric("Distância média", f"{fmt_float(anomalias_fonte['distancia_km'].mean(), 2)} km")
                st.metric("Maior XCH₄ próximo", f"{fmt_float(anomalias_fonte['xch4_max'].max(), 1)} ppb")
                st.dataframe(anomalias_fonte.head(15), use_container_width=True, height=260)
            else:
                st.info("Nenhuma anomalia foi encontrada dentro do raio definido para esse empreendimento.")
        else:
            st.markdown("#### Top fontes associadas")
            if len(ranking) > 0:
                st.dataframe(
                    ranking[["nome_fonte", "tipo_fonte", "cadeia", "uf_fonte", "frequencia_anomalias", "distancia_media_km", "media_xmean"]].head(12),
                    use_container_width=True,
                    height=360,
                )
            else:
                st.info("Nenhuma relação espacial encontrada com o raio e filtros atuais.")

# =========================================================
# GRÁFICOS
# =========================================================
with tab_graficos:
    c1, c2 = st.columns(2, gap="medium")

    with c1:
        st.subheader("Evolução mensal das anomalias")
        if len(temporal) > 0:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=temporal["mes"], y=temporal["total_anomalias"], mode="lines+markers", name="Anomalias"))
            fig.add_trace(go.Scatter(x=temporal["mes"], y=temporal["media_xmean"], mode="lines+markers", name="XCH₄ médio", yaxis="y2"))
            fig.update_layout(
                yaxis=dict(title="Total de anomalias"),
                yaxis2=dict(title="XCH₄ médio", overlaying="y", side="right"),
                title="Total mensal e XCH₄ médio",
            )
            st.plotly_chart(plotly_dark(fig, height=430), use_container_width=True)
        else:
            st.warning("Nenhum dado temporal encontrado.")

    with c2:
        st.subheader("Ranking por UF")
        if len(ranking_uf) > 0:
            fig = px.bar(
                ranking_uf.head(15),
                x="total_anomalias",
                y="uf",
                orientation="h",
                hover_data=["media_xmean", "max_xch4", "area_total_km2"],
                labels={"total_anomalias": "Anomalias", "uf": "UF"},
                title="UFs com mais anomalias",
            )
            fig.update_layout(yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(plotly_dark(fig, height=430), use_container_width=True)
        else:
            st.warning("Nenhum dado por UF encontrado.")

    c3, c4 = st.columns(2, gap="medium")

    with c3:
        st.subheader("Distribuição de XCH₄ médio")
        if len(anomalias) > 0 and "xmean" in anomalias.columns:
            fig = px.histogram(
                pd.DataFrame(anomalias.drop(columns="geom")),
                x="xmean",
                nbins=35,
                labels={"xmean": "XCH₄ médio"},
                title="Histograma das anomalias carregadas no mapa",
            )
            st.plotly_chart(plotly_dark(fig, height=390), use_container_width=True)
        else:
            st.info("Sem anomalias carregadas para o histograma.")

    with c4:
        st.subheader("Área da anomalia × XCH₄")
        if len(anomalias) > 0 and {"area_km2", "xmean"}.issubset(set(anomalias.columns)):
            df_scatter = pd.DataFrame(anomalias.drop(columns="geom"))
            fig = px.scatter(
                df_scatter,
                x="area_km2",
                y="xmean",
                color="uf" if "uf" in df_scatter.columns else None,
                hover_data=[c for c in ["date", "xch4_max", "pix_n", "thr"] if c in df_scatter.columns],
                labels={"area_km2": "Área (km²)", "xmean": "XCH₄ médio"},
                title="Relação entre extensão espacial e concentração média",
            )
            st.plotly_chart(plotly_dark(fig, height=390), use_container_width=True)
        else:
            st.info("Sem dados suficientes para o gráfico de dispersão.")

    c5, c6 = st.columns(2, gap="medium")

    with c5:
        st.subheader("Fontes por cadeia produtiva")
        if fontes is not None and len(fontes) > 0 and "cadeia" in fontes.columns:
            df_cadeia = pd.DataFrame(fontes.drop(columns="geom")).groupby("cadeia", dropna=False).size().reset_index(name="total")
            fig = px.pie(df_cadeia, names="cadeia", values="total", hole=0.45, title="Composição das fontes filtradas")
            st.plotly_chart(plotly_dark(fig, height=390), use_container_width=True)
        else:
            st.info("Sem fontes para composição por cadeia.")

    with c6:
        st.subheader("Tipos de fonte")
        if fontes is not None and len(fontes) > 0 and "tipo_fonte" in fontes.columns:
            df_tipo = pd.DataFrame(fontes.drop(columns="geom")).groupby("tipo_fonte", dropna=False).size().reset_index(name="total").sort_values("total", ascending=False).head(15)
            fig = px.bar(df_tipo, x="total", y="tipo_fonte", orientation="h", title="Principais tipos de fonte")
            fig.update_layout(yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(plotly_dark(fig, height=390), use_container_width=True)
        else:
            st.info("Sem fontes para ranking por tipo.")

# =========================================================
# RANKING ESPACIAL
# =========================================================
with tab_ranking:
    st.subheader("Ranking de instalações associadas às anomalias")
    st.caption(
        "A associação é calculada com ST_DWithin sobre geometria geography, usando o raio definido na barra lateral. "
        "Isso não confirma causalidade, mas prioriza empreendimentos para investigação."
    )

    if len(ranking) > 0:
        st.dataframe(ranking, use_container_width=True, height=520)

        c1, c2 = st.columns(2, gap="medium")
        with c1:
            fig = px.bar(
                ranking.head(20),
                x="frequencia_anomalias",
                y="nome_fonte",
                color="cadeia",
                orientation="h",
                hover_data=["tipo_fonte", "municipio_fonte", "uf_fonte", "distancia_media_km", "media_xmean"],
                labels={"frequencia_anomalias": "Nº de anomalias", "nome_fonte": "Fonte"},
                title="Empreendimentos com mais anomalias no raio definido",
            )
            fig.update_layout(yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(plotly_dark(fig, height=560), use_container_width=True)

        with c2:
            fig = px.scatter(
                ranking,
                x="distancia_media_km",
                y="media_xmean",
                size="frequencia_anomalias",
                color="cadeia",
                hover_name="nome_fonte",
                hover_data=["tipo_fonte", "uf_fonte", "maior_xch4"],
                labels={"distancia_media_km": "Distância média (km)", "media_xmean": "XCH₄ médio"},
                title="Prioridade investigativa: distância × intensidade",
            )
            st.plotly_chart(plotly_dark(fig, height=560), use_container_width=True)

        st.download_button(
            "⬇️ Baixar ranking espacial CSV",
            ranking.to_csv(index=False).encode("utf-8"),
            "ranking_espacial_tropomi_fontes.csv",
            "text/csv",
        )
    else:
        st.warning("Nenhuma associação espacial encontrada. Aumente o raio, reduza filtros ou selecione outro empreendimento.")

# =========================================================
# TABELAS E DOWNLOADS
# =========================================================
with tab_tabelas:
    st.subheader("Anomalias carregadas")
    if anomalias is not None and len(anomalias) > 0:
        anomalias_tabela = pd.DataFrame(anomalias.drop(columns="geom"))
        st.dataframe(anomalias_tabela.head(1000), use_container_width=True, height=360)
        st.download_button(
            "⬇️ Baixar anomalias CSV",
            anomalias_tabela.to_csv(index=False).encode("utf-8"),
            "anomalias_tropomi_filtradas.csv",
            "text/csv",
        )
    else:
        st.info("Nenhuma anomalia encontrada para os filtros selecionados.")

    st.subheader("Fontes carregadas")
    if fontes is not None and len(fontes) > 0:
        fontes_tabela = pd.DataFrame(fontes.drop(columns="geom"))
        st.dataframe(fontes_tabela.head(1000), use_container_width=True, height=360)
        st.download_button(
            "⬇️ Baixar fontes CSV",
            fontes_tabela.to_csv(index=False).encode("utf-8"),
            "fontes_metano_filtradas.csv",
            "text/csv",
        )
    else:
        st.info("Nenhuma fonte encontrada para os filtros selecionados.")

    if fonte_id_sel != "Todas":
        st.subheader("Anomalias próximas ao empreendimento selecionado")
        if len(anomalias_fonte) > 0:
            st.dataframe(anomalias_fonte, use_container_width=True, height=320)
            st.download_button(
                "⬇️ Baixar anomalias do empreendimento CSV",
                anomalias_fonte.to_csv(index=False).encode("utf-8"),
                "anomalias_empreendimento_selecionado.csv",
                "text/csv",
            )
        else:
            st.info("Nenhuma anomalia próxima ao empreendimento selecionado.")

st.markdown("---")
st.caption(
    "Nota metodológica: a proximidade espacial fonte–anomalia deve ser interpretada como triagem investigativa. "
    "A confirmação de emissão exige análise temporal, meteorologia, inventários operacionais e, quando possível, sensores complementares."
)
