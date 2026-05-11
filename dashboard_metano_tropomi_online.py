# -*- coding: utf-8 -*-
"""
Dashboard de Monitoramento de Metano — TROPOMI Brasil | Online
Versão completa otimizada para Streamlit Cloud + Supabase/PostGIS

Objetivo:
- Substituir a versão online simplificada.
- Manter conexão com Supabase/PostGIS.
- Recuperar filtros laterais, gráficos, KPIs, mapa interativo e tabelas.
- Evitar travamento com JOIN espacial pesado em tempo real.

Como rodar:
    streamlit run dashboard_metano_tropomi_online_completo.py

Requisitos principais:
    streamlit
    pandas
    geopandas
    sqlalchemy
    psycopg2-binary
    folium
    streamlit-folium
    plotly
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


# =============================================================================
# CONFIGURAÇÃO STREAMLIT
# =============================================================================

st.set_page_config(
    page_title="Monitor CH4 | TROPOMI Brasil",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# =============================================================================
# ESTILO VISUAL
# =============================================================================

st.markdown("""
<style>
.stApp {
    background: linear-gradient(180deg, #0b1220 0%, #0f1b2d 100%);
    color: #e6edf3;
}
* {
    font-family: Arial, sans-serif;
}
[data-testid="stSidebar"] {
    background-color: #0c1424;
    border-right: 1px solid #1f2e4a;
}
h1, h2, h3, h4, h5, h6, p, span, div, label {
    color: #e6edf3;
}
hr {
    border-color: #1f2e4a;
}
[data-testid="metric-container"] {
    background: linear-gradient(180deg, rgba(18,31,54,0.96) 0%, rgba(13,24,42,0.96) 100%);
    border: 1px solid #1f3a5f;
    border-radius: 14px;
    padding: 14px;
    box-shadow: 0 10px 24px rgba(0,0,0,0.16);
}
.kpi-card {
    background: linear-gradient(180deg, rgba(18,31,54,0.96) 0%, rgba(13,24,42,0.96) 100%);
    border: 1px solid #1f3a5f;
    border-radius: 14px;
    padding: 14px;
    min-height: 95px;
    box-shadow: 0 10px 24px rgba(0,0,0,0.16);
}
.kpi-label {
    color: #dce9f8;
    font-size: 0.78rem;
    font-weight: 600;
    margin-bottom: 8px;
}
.kpi-value {
    color: #ffffff;
    font-size: 1.70rem;
    font-weight: 700;
    line-height: 1.1;
}
.kpi-delta {
    display: inline-block;
    margin-top: 6px;
    padding: 3px 8px;
    border-radius: 999px;
    background: rgba(35, 134, 54, 0.55);
    color: #7ee787;
    font-size: 0.70rem;
    font-weight: 700;
}
.filter-title {
    color: #58a6ff;
    font-size: 0.86rem;
    font-weight: 700;
    margin-top: 14px;
    margin-bottom: 4px;
}
.info-card {
    background: rgba(88,166,255,0.08);
    border: 1px solid rgba(88,166,255,0.22);
    border-radius: 12px;
    padding: 12px;
    color: #c9d7e5;
}
.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
}
.stTabs [data-baseweb="tab"] {
    background-color: #111d33;
    border-radius: 8px 8px 0 0;
    padding: 8px 14px;
}
.stTabs [aria-selected="true"] {
    background-color: #1f3a5f;
}

/* Ajuste de contraste dos textos dos inputs */
.stSelectbox label,
.stSlider label,
.stRadio label,
.stCheckbox label,
.stMarkdown,
label,
p,
span {
    color: #dce9f8 !important;
}

.stSelectbox div[data-baseweb="select"] * {
    color: #0b1f3a !important;
}

.stMultiSelect div[data-baseweb="select"] * {
    color: #0b1f3a !important;
}

.stTextInput input,
.stNumberInput input,
textarea {
    color: #0b1f3a !important;
}

[data-baseweb="select"] {
    background-color: #ffffff !important;
    border-radius: 8px !important;
}

.stSlider span {
    color: #dce9f8 !important;
}

</style>
""", unsafe_allow_html=True)


# =============================================================================
# CONEXÃO COM SUPABASE / POSTGIS
# =============================================================================

try:
    DATABASE_URL = st.secrets["DATABASE_URL"]
except Exception:
    st.error("DATABASE_URL não configurada. Crie `.streamlit/secrets.toml` localmente ou configure o Secret no Streamlit Cloud.")
    st.stop()

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 20}
)


# =============================================================================
# FUNÇÕES AUXILIARES
# =============================================================================

MESES_LABEL = {
    1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez"
}
MESES_INV = {v: k for k, v in MESES_LABEL.items()}


def fmt_int(v):
    try:
        return f"{int(v):,}".replace(",", ".")
    except Exception:
        return "0"


def fmt_float(v, casas=2):
    try:
        return f"{float(v):,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "0"


def normaliza_opcao(v):
    if v in [None, "", "Todos", "Todas"]:
        return None
    return v


def build_anomalia_where(uf=None, ano=None, mes=None, xmean_min=0, area_min=0):
    filtros = []
    params = {}

    if normaliza_opcao(uf):
        filtros.append("a.uf = :uf")
        params["uf"] = uf

    if normaliza_opcao(ano):
        filtros.append("EXTRACT(YEAR FROM a.date::date) = :ano")
        params["ano"] = int(ano)

    if normaliza_opcao(mes):
        filtros.append("EXTRACT(MONTH FROM a.date::date) = :mes")
        params["mes"] = int(mes)

    filtros.append("COALESCE(a.xmean, 0) >= :xmean_min")
    params["xmean_min"] = float(xmean_min)

    filtros.append("COALESCE(a.area_km2, 0) >= :area_min")
    params["area_min"] = float(area_min)

    where = "WHERE " + " AND ".join(filtros) if filtros else ""
    return where, params


def build_fonte_where(cadeia=None, tipo_fonte=None, fonte_id=None, uf=None):
    filtros = []
    params = {}

    if normaliza_opcao(cadeia):
        filtros.append("f.cadeia = :cadeia")
        params["cadeia"] = cadeia

    if normaliza_opcao(tipo_fonte):
        filtros.append("f.tipo_fonte = :tipo_fonte")
        params["tipo_fonte"] = tipo_fonte

    if normaliza_opcao(fonte_id):
        filtros.append("f.id = :fonte_id")
        params["fonte_id"] = int(fonte_id)

    if normaliza_opcao(uf):
        filtros.append("f.uf = :uf_fonte")
        params["uf_fonte"] = uf

    where = "WHERE " + " AND ".join(filtros) if filtros else ""
    return where, params


def plotly_layout(fig, altura=380):
    fig.update_layout(
        height=altura,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e6edf3"),
        margin=dict(l=20, r=20, t=50, b=30),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(color="#e6edf3")
        )
    )
    fig.update_xaxes(gridcolor="rgba(255,255,255,0.08)", zerolinecolor="rgba(255,255,255,0.08)")
    fig.update_yaxes(gridcolor="rgba(255,255,255,0.08)", zerolinecolor="rgba(255,255,255,0.08)")
    return fig


# =============================================================================
# FUNÇÕES DE CONSULTA
# =============================================================================

def gdf_to_folium_geojson(gdf):
    """
    Converte GeoDataFrame para GeoJSON serializável pelo Folium.
    Corrige erro: Object of type Polygon is not JSON serializable.
    """
    gdf2 = gdf.copy()

    # Remove colunas geométricas extras, mantendo apenas a geometria ativa
    active_geom = gdf2.geometry.name
    for col in list(gdf2.columns):
        if col != active_geom:
            try:
                if hasattr(gdf2[col], "geom_type"):
                    gdf2 = gdf2.drop(columns=[col])
            except Exception:
                pass

    # Converte datas/timestamps para texto
    for col in gdf2.columns:
        if col == active_geom:
            continue
        if pd.api.types.is_datetime64_any_dtype(gdf2[col]):
            gdf2[col] = gdf2[col].astype(str)
        else:
            gdf2[col] = gdf2[col].apply(
                lambda x: x.isoformat() if hasattr(x, "isoformat") else x
            )

    # Garante CRS web
    if gdf2.crs is None:
        gdf2 = gdf2.set_crs(epsg=4326, allow_override=True)
    else:
        gdf2 = gdf2.to_crs(epsg=4326)

    return gdf2.to_json()


# =============================================================================
# FUNÇÕES DE CONSULTA
# =============================================================================

@st.cache_data(show_spinner="Carregando opções de filtros...")
def load_opcoes():
    anos = pd.read_sql(text("""
        SELECT DISTINCT EXTRACT(YEAR FROM date::date)::int AS ano
        FROM metano.anomalias_tropomi
        WHERE date IS NOT NULL
        ORDER BY ano;
    """), engine)

    meses = pd.read_sql(text("""
        SELECT DISTINCT EXTRACT(MONTH FROM date::date)::int AS mes
        FROM metano.anomalias_tropomi
        WHERE date IS NOT NULL
        ORDER BY mes;
    """), engine)

    ufs = pd.read_sql(text("""
        SELECT DISTINCT uf
        FROM metano.anomalias_tropomi
        WHERE uf IS NOT NULL
        ORDER BY uf;
    """), engine)

    cadeias = pd.read_sql(text("""
        SELECT DISTINCT cadeia
        FROM metano.vw_fontes_metano
        WHERE cadeia IS NOT NULL
        ORDER BY cadeia;
    """), engine)

    tipos = pd.read_sql(text("""
        SELECT DISTINCT tipo_fonte
        FROM metano.vw_fontes_metano
        WHERE tipo_fonte IS NOT NULL
        ORDER BY tipo_fonte;
    """), engine)

    fontes = pd.read_sql(text("""
        SELECT id, nome, tipo_fonte, cadeia, municipio, uf
        FROM metano.vw_fontes_metano
        WHERE nome IS NOT NULL
        ORDER BY nome
        LIMIT 20000;
    """), engine)

    return anos, meses, ufs, cadeias, tipos, fontes


@st.cache_data(show_spinner="Carregando resumo filtrado...")
def load_resumo_filtrado(uf=None, ano=None, mes=None, xmean_min=0, area_min=0,
                         cadeia=None, tipo_fonte=None, fonte_id=None):
    where_a, params_a = build_anomalia_where(uf, ano, mes, xmean_min, area_min)
    where_f, params_f = build_fonte_where(cadeia, tipo_fonte, fonte_id, uf=None)

    sql_a = f"""
        SELECT
            COUNT(*) AS total_anomalias,
            ROUND(AVG(a.xmean)::numeric, 2) AS media_xmean,
            ROUND(MAX(a.xch4_max)::numeric, 2) AS max_xch4,
            ROUND(SUM(a.area_km2)::numeric, 2) AS area_total_km2,
            ROUND(AVG(a.area_km2)::numeric, 2) AS area_media_km2,
            ROUND(AVG(a.pix_n)::numeric, 2) AS pix_medio,
            MIN(a.date::date) AS data_ini,
            MAX(a.date::date) AS data_fim
        FROM metano.anomalias_tropomi a
        {where_a};
    """

    sql_f = f"""
        SELECT COUNT(*) AS total_fontes
        FROM metano.vw_fontes_metano f
        {where_f};
    """

    a = pd.read_sql(text(sql_a), engine, params=params_a)
    f = pd.read_sql(text(sql_f), engine, params=params_f)

    out = pd.concat([a, f], axis=1)
    return out


@st.cache_data(show_spinner="Carregando série temporal filtrada...")
def load_temporal_filtrado(uf=None, ano=None, mes=None, xmean_min=0, area_min=0):
    where, params = build_anomalia_where(uf, ano, mes, xmean_min, area_min)

    sql = f"""
        SELECT
            DATE_TRUNC('month', a.date::date)::date AS mes,
            COUNT(*) AS total_anomalias,
            ROUND(AVG(a.xmean)::numeric, 2) AS media_xmean,
            ROUND(MAX(a.xch4_max)::numeric, 2) AS maior_xch4,
            ROUND(SUM(a.area_km2)::numeric, 2) AS area_total_km2,
            ROUND(AVG(a.area_km2)::numeric, 2) AS area_media_km2
        FROM metano.anomalias_tropomi a
        {where}
        GROUP BY DATE_TRUNC('month', a.date::date)
        ORDER BY mes;
    """

    return pd.read_sql(text(sql), engine, params=params)


@st.cache_data(show_spinner="Carregando ranking por UF...")
def load_ranking_uf(uf=None, ano=None, mes=None, xmean_min=0, area_min=0):
    where, params = build_anomalia_where(uf, ano, mes, xmean_min, area_min)

    sql = f"""
        SELECT
            COALESCE(a.uf, 'Sem UF') AS uf,
            COUNT(*) AS total_anomalias,
            ROUND(AVG(a.xmean)::numeric, 2) AS media_xmean,
            ROUND(MAX(a.xch4_max)::numeric, 2) AS maior_xch4,
            ROUND(SUM(a.area_km2)::numeric, 2) AS area_total_km2
        FROM metano.anomalias_tropomi a
        {where}
        GROUP BY COALESCE(a.uf, 'Sem UF')
        ORDER BY total_anomalias DESC
        LIMIT 27;
    """

    return pd.read_sql(text(sql), engine, params=params)


@st.cache_data(show_spinner="Carregando distribuição por intensidade...")
def load_distribuicao_intensidade(uf=None, ano=None, mes=None, xmean_min=0, area_min=0):
    where, params = build_anomalia_where(uf, ano, mes, xmean_min, area_min)

    sql = f"""
        SELECT
            CASE
                WHEN COALESCE(a.xmean,0) < 1800 THEN 'Baixo (< 1800 ppb)'
                WHEN COALESCE(a.xmean,0) < 1900 THEN 'Moderado (1800–1900 ppb)'
                WHEN COALESCE(a.xmean,0) < 2000 THEN 'Alto (1900–2000 ppb)'
                ELSE 'Muito alto (≥ 2000 ppb)'
            END AS classe_xch4,
            COUNT(*) AS total
        FROM metano.anomalias_tropomi a
        {where}
        GROUP BY classe_xch4
        ORDER BY total DESC;
    """

    return pd.read_sql(text(sql), engine, params=params)


@st.cache_data(show_spinner="Carregando fontes filtradas...")
def load_fontes_filtradas(cadeia=None, tipo_fonte=None, fonte_id=None, uf=None, limite=5000):
    where, params = build_fonte_where(cadeia, tipo_fonte, fonte_id, uf)
    params["limite"] = int(limite)

    sql = f"""
        SELECT
            f.id,
            f.nome,
            f.tipo_fonte,
            f.cadeia,
            f.municipio,
            f.uf,
            f.geom
        FROM metano.vw_fontes_metano f
        {where}
        LIMIT :limite;
    """

    return gpd.read_postgis(text(sql), engine, geom_col="geom", params=params)


@st.cache_data(show_spinner="Carregando anomalias para mapa...")
def load_anomalias_mapa(uf=None, ano=None, mes=None, xmean_min=0, area_min=0, limite=2000):
    where, params = build_anomalia_where(uf, ano, mes, xmean_min, area_min)
    params["limite"] = int(limite)

    sql = f"""
        SELECT
            a.id,
            a.date,
            a.uf,
            a.state,
            a.xmean,
            a.xch4_max,
            a.d_xch4,
            a.area_km2,
            a.pix_n,
            a.thr,
            a.geom
        FROM metano.anomalias_tropomi a
        {where}
        ORDER BY a.date DESC
        LIMIT :limite;
    """

    return gpd.read_postgis(text(sql), engine, geom_col="geom", params=params)


@st.cache_data(show_spinner="Carregando amostra para dispersão...")
def load_amostra_dispersao(uf=None, ano=None, mes=None, xmean_min=0, area_min=0, limite=6000):
    where, params = build_anomalia_where(uf, ano, mes, xmean_min, area_min)
    params["limite"] = int(limite)

    sql = f"""
        SELECT
            a.date,
            a.uf,
            a.xmean,
            a.xch4_max,
            a.d_xch4,
            a.area_km2,
            a.pix_n,
            a.thr
        FROM metano.anomalias_tropomi a
        {where}
        ORDER BY a.date DESC
        LIMIT :limite;
    """

    return pd.read_sql(text(sql), engine, params=params)


@st.cache_data(show_spinner="Carregando análise das fontes...")
def load_fontes_stats(cadeia=None, tipo_fonte=None, fonte_id=None):
    where, params = build_fonte_where(cadeia, tipo_fonte, fonte_id, uf=None)

    sql_cadeia = f"""
        SELECT
            COALESCE(f.cadeia, 'Sem cadeia') AS cadeia,
            COUNT(*) AS total
        FROM metano.vw_fontes_metano f
        {where}
        GROUP BY COALESCE(f.cadeia, 'Sem cadeia')
        ORDER BY total DESC;
    """

    sql_tipo = f"""
        SELECT
            COALESCE(f.tipo_fonte, 'Sem tipo') AS tipo_fonte,
            COUNT(*) AS total
        FROM metano.vw_fontes_metano f
        {where}
        GROUP BY COALESCE(f.tipo_fonte, 'Sem tipo')
        ORDER BY total DESC
        LIMIT 15;
    """

    return (
        pd.read_sql(text(sql_cadeia), engine, params=params),
        pd.read_sql(text(sql_tipo), engine, params=params)
    )


# =============================================================================
# CARREGAMENTO DAS OPÇÕES
# =============================================================================

try:
    anos_db, meses_db, ufs_db, cadeias_db, tipos_db, fontes_db = load_opcoes()
except Exception as e:
    st.error(f"Erro ao carregar opções iniciais do banco: {e}")
    st.stop()


# =============================================================================
# SIDEBAR
# =============================================================================

with st.sidebar:
    st.markdown("## 🛰️ Monitor CH4")
    st.markdown("**TROPOMI · Sentinel-5P · Supabase/PostGIS**")
    st.markdown("---")

    st.markdown('<div class="filter-title">Filtros temporais e espaciais</div>', unsafe_allow_html=True)

    anos_opcoes = ["Todos"] + [str(a) for a in anos_db["ano"].dropna().astype(int).tolist()]
    ano_sel = st.selectbox("Ano", anos_opcoes, index=0)

    meses_disponiveis = meses_db["mes"].dropna().astype(int).tolist()
    meses_opcoes = ["Todos"] + [MESES_LABEL[m] for m in meses_disponiveis if m in MESES_LABEL]
    mes_label_sel = st.selectbox("Mês", meses_opcoes, index=0)
    mes_sel = None if mes_label_sel == "Todos" else MESES_INV.get(mes_label_sel)

    ufs_opcoes = ["Todas"] + ufs_db["uf"].dropna().astype(str).tolist()
    uf_sel = st.selectbox("UF", ufs_opcoes, index=0)

    st.markdown('<div class="filter-title">Filtros das fontes</div>', unsafe_allow_html=True)

    cadeias_opcoes = ["Todas"] + cadeias_db["cadeia"].dropna().astype(str).tolist()
    cadeia_sel = st.selectbox("Cadeia produtiva", cadeias_opcoes, index=0)

    tipos_opcoes = ["Todos"] + tipos_db["tipo_fonte"].dropna().astype(str).tolist()
    tipo_sel = st.selectbox("Tipo de fonte", tipos_opcoes, index=0)

    fontes_filtradas_sidebar = fontes_db.copy()
    if cadeia_sel != "Todas":
        fontes_filtradas_sidebar = fontes_filtradas_sidebar[fontes_filtradas_sidebar["cadeia"] == cadeia_sel]
    if tipo_sel != "Todos":
        fontes_filtradas_sidebar = fontes_filtradas_sidebar[fontes_filtradas_sidebar["tipo_fonte"] == tipo_sel]

    fonte_labels = ["Todas"]
    fonte_label_to_id = {"Todas": None}

    for _, row in fontes_filtradas_sidebar.head(3000).iterrows():
        label = f"{row['nome']} | {row.get('tipo_fonte','')} | {row.get('uf','')}"
        fonte_labels.append(label)
        fonte_label_to_id[label] = int(row["id"])

    fonte_label_sel = st.selectbox("Empreendimento/fonte", fonte_labels, index=0)
    fonte_id_sel = fonte_label_to_id.get(fonte_label_sel)

    st.markdown('<div class="filter-title">Parâmetros analíticos</div>', unsafe_allow_html=True)

    raio_km = st.slider(
        "Raio de associação fonte ↔ anomalia (km)",
        min_value=1,
        max_value=100,
        value=10,
        step=1,
        help="Nesta versão online, o raio é exibido como parâmetro visual/analítico. O cruzamento espacial pesado deve ser pré-calculado em tabela materializada."
    )

    xmean_min = st.slider(
        "XCH₄ médio mínimo (ppb)",
        min_value=0,
        max_value=2500,
        value=0,
        step=10
    )

    area_min = st.slider(
        "Área mínima da anomalia (km²)",
        min_value=0,
        max_value=1000,
        value=0,
        step=10
    )

    limite_mapa = st.slider(
        "Limite de anomalias no mapa",
        min_value=300,
        max_value=8000,
        value=2000,
        step=100
    )

    limite_fontes = st.slider(
        "Limite de fontes no mapa",
        min_value=500,
        max_value=10000,
        value=5000,
        step=500
    )

    st.markdown('<div class="filter-title">Camada do mapa</div>', unsafe_allow_html=True)
    camada_mapa = st.radio(
        "Tipo de visualização",
        ["Polígonos TROPOMI", "Heatmap por centroide", "Clusters de anomalias"],
        index=0
    )

    mostrar_fontes = st.checkbox("Mostrar fontes no mapa", value=True)
    mostrar_tabela = st.checkbox("Mostrar tabelas no final", value=True)

    st.markdown("---")
    st.caption("Fonte: Sentinel-5P/TROPOMI · Supabase/PostGIS · bases de infraestrutura cadastradas no Monitor.")


# =============================================================================
# CONSULTAS COM FILTROS
# =============================================================================

try:
    resumo = load_resumo_filtrado(
        uf=uf_sel,
        ano=ano_sel,
        mes=mes_sel,
        xmean_min=xmean_min,
        area_min=area_min,
        cadeia=cadeia_sel,
        tipo_fonte=tipo_sel,
        fonte_id=fonte_id_sel
    )

    temporal = load_temporal_filtrado(
        uf=uf_sel,
        ano=ano_sel,
        mes=mes_sel,
        xmean_min=xmean_min,
        area_min=area_min
    )

    ranking_uf = load_ranking_uf(
        uf=uf_sel,
        ano=ano_sel,
        mes=mes_sel,
        xmean_min=xmean_min,
        area_min=area_min
    )

    dist_int = load_distribuicao_intensidade(
        uf=uf_sel,
        ano=ano_sel,
        mes=mes_sel,
        xmean_min=xmean_min,
        area_min=area_min
    )

    fontes = load_fontes_filtradas(
        cadeia=cadeia_sel,
        tipo_fonte=tipo_sel,
        fonte_id=fonte_id_sel,
        uf=None if uf_sel == "Todas" else uf_sel,
        limite=limite_fontes
    )

    anomalias = load_anomalias_mapa(
        uf=uf_sel,
        ano=ano_sel,
        mes=mes_sel,
        xmean_min=xmean_min,
        area_min=area_min,
        limite=limite_mapa
    )

    dispersao = load_amostra_dispersao(
        uf=uf_sel,
        ano=ano_sel,
        mes=mes_sel,
        xmean_min=xmean_min,
        area_min=area_min,
        limite=6000
    )

    fontes_cadeia, fontes_tipo = load_fontes_stats(
        cadeia=cadeia_sel,
        tipo_fonte=tipo_sel,
        fonte_id=fonte_id_sel
    )

except Exception as e:
    st.error(f"Erro ao consultar o banco com os filtros atuais: {e}")
    st.stop()


# =============================================================================
# CABEÇALHO + KPIs
# =============================================================================

st.markdown("""
# 🛰️ Monitoramento de Metano — TROPOMI Brasil
**Dashboard online conectado ao Supabase/PostGIS**
""")

r = resumo.iloc[0] if len(resumo) else {}

total_anomalias = r.get("total_anomalias", 0) if hasattr(r, "get") else 0
media_xmean = r.get("media_xmean", 0) if hasattr(r, "get") else 0
max_xch4 = r.get("max_xch4", 0) if hasattr(r, "get") else 0
area_total = r.get("area_total_km2", 0) if hasattr(r, "get") else 0
area_media = r.get("area_media_km2", 0) if hasattr(r, "get") else 0
pix_medio = r.get("pix_medio", 0) if hasattr(r, "get") else 0
total_fontes = r.get("total_fontes", 0) if hasattr(r, "get") else 0
data_ini = r.get("data_ini", None) if hasattr(r, "get") else None
data_fim = r.get("data_fim", None) if hasattr(r, "get") else None

k1, k2, k3, k4 = st.columns(4)
with k1:
    st.metric("Anomalias filtradas", fmt_int(total_anomalias))
with k2:
    st.metric("XCH₄ médio", f"{fmt_float(media_xmean, 2)} ppb")
with k3:
    st.metric("XCH₄ máximo", f"{fmt_float(max_xch4, 2)} ppb")
with k4:
    st.metric("Fontes filtradas", fmt_int(total_fontes))

k5, k6, k7, k8 = st.columns(4)
with k5:
    st.metric("Área total das anomalias", f"{fmt_float(area_total, 2)} km²")
with k6:
    st.metric("Área média", f"{fmt_float(area_media, 2)} km²")
with k7:
    st.metric("Pixels médios", fmt_float(pix_medio, 2))
with k8:
    periodo_txt = "-"
    if pd.notna(data_ini) and pd.notna(data_fim):
        periodo_txt = f"{pd.to_datetime(data_ini).strftime('%d/%m/%Y')} → {pd.to_datetime(data_fim).strftime('%d/%m/%Y')}"
    st.metric("Período filtrado", periodo_txt)

st.markdown(f"""
<div class="info-card">
O parâmetro de raio atualmente selecionado é <b>{raio_km} km</b>. 
Para ranking espacial fonte ↔ anomalia em produção, recomenda-se pré-calcular as associações no PostGIS em uma tabela materializada, 
evitando ST_DWithin em tempo real no Streamlit Cloud.
</div>
""", unsafe_allow_html=True)

st.markdown("---")


# =============================================================================
# ABAS
# =============================================================================

tab_visao, tab_mapa, tab_fontes, tab_dados = st.tabs([
    "📊 Análises TROPOMI",
    "🗺️ Mapa interativo",
    "🏭 Fontes de emissão",
    "⬇️ Dados e download"
])


# =============================================================================
# ABA 1 — ANÁLISES TROPOMI
# =============================================================================

with tab_visao:
    c1, c2 = st.columns([1.35, 1.0], gap="medium")

    with c1:
        st.subheader("Evolução mensal das anomalias")

        if len(temporal) > 0:
            fig = px.line(
                temporal,
                x="mes",
                y="total_anomalias",
                markers=True,
                labels={"mes": "Mês", "total_anomalias": "Total de anomalias"},
                title="Total mensal de anomalias TROPOMI"
            )
            st.plotly_chart(plotly_layout(fig, 390), use_container_width=True)
        else:
            st.info("Nenhum dado temporal encontrado para os filtros selecionados.")

    with c2:
        st.subheader("Classes de intensidade")

        if len(dist_int) > 0:
            fig = px.pie(
                dist_int,
                names="classe_xch4",
                values="total",
                hole=0.45,
                title="Distribuição por XCH₄ médio"
            )
            st.plotly_chart(plotly_layout(fig, 390), use_container_width=True)
        else:
            st.info("Nenhuma classe encontrada.")

    c3, c4 = st.columns(2, gap="medium")

    with c3:
        st.subheader("Ranking por UF")

        if len(ranking_uf) > 0:
            fig = px.bar(
                ranking_uf.sort_values("total_anomalias", ascending=True),
                x="total_anomalias",
                y="uf",
                orientation="h",
                labels={"total_anomalias": "Total de anomalias", "uf": "UF"},
                title="Anomalias por UF"
            )
            st.plotly_chart(plotly_layout(fig, 460), use_container_width=True)
        else:
            st.info("Sem ranking por UF.")

    with c4:
        st.subheader("XCH₄ médio e área")

        if len(dispersao) > 0:
            fig = px.scatter(
                dispersao,
                x="area_km2",
                y="xmean",
                color="uf" if "uf" in dispersao.columns else None,
                hover_data=[c for c in ["date", "uf", "xch4_max", "pix_n", "thr"] if c in dispersao.columns],
                labels={"area_km2": "Área da anomalia (km²)", "xmean": "XCH₄ médio (ppb)"},
                title="Relação entre área da anomalia e XCH₄ médio"
            )
            st.plotly_chart(plotly_layout(fig, 460), use_container_width=True)
        else:
            st.info("Sem dados para dispersão.")

    c5, c6 = st.columns(2, gap="medium")

    with c5:
        st.subheader("XCH₄ médio mensal")

        if len(temporal) > 0:
            fig = px.line(
                temporal,
                x="mes",
                y="media_xmean",
                markers=True,
                labels={"mes": "Mês", "media_xmean": "XCH₄ médio (ppb)"},
                title="Média mensal de XCH₄"
            )
            st.plotly_chart(plotly_layout(fig, 360), use_container_width=True)

    with c6:
        st.subheader("Área total mensal")

        if len(temporal) > 0:
            fig = px.bar(
                temporal,
                x="mes",
                y="area_total_km2",
                labels={"mes": "Mês", "area_total_km2": "Área total (km²)"},
                title="Área mensal acumulada das anomalias"
            )
            st.plotly_chart(plotly_layout(fig, 360), use_container_width=True)


# =============================================================================
# ABA 2 — MAPA
# =============================================================================

with tab_mapa:
    st.subheader("Mapa TROPOMI + fontes de emissão")

    if len(anomalias) > 0:
        try:
            anomalias_plot = anomalias.to_crs(epsg=4326)
        except Exception:
            anomalias_plot = anomalias.set_crs(epsg=4326, allow_override=True)

        try:
            centro = anomalias_plot.geometry.centroid
            lat_c = centro.y.mean()
            lon_c = centro.x.mean()
            if pd.isna(lat_c) or pd.isna(lon_c):
                lat_c, lon_c = -14.2, -51.9
        except Exception:
            lat_c, lon_c = -14.2, -51.9

        zoom = 5 if uf_sel != "Todas" else 4
    else:
        anomalias_plot = gpd.GeoDataFrame()
        lat_c, lon_c, zoom = -14.2, -51.9, 4

    m = folium.Map(
        location=[lat_c, lon_c],
        zoom_start=zoom,
        tiles=None,
        prefer_canvas=True
    )

    folium.TileLayer("CartoDB dark_matter", name="Base escura", show=True).add_to(m)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap", show=False).add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Satélite",
        show=False
    ).add_to(m)

    Fullscreen(position="topright").add_to(m)
    MiniMap(toggle_display=True).add_to(m)

    if len(anomalias_plot) > 0:
        if camada_mapa == "Polígonos TROPOMI":
            # simplificação leve para reduzir peso no navegador
            anomalias_geo = anomalias_plot.copy()
            try:
                anomalias_geo["geometry"] = anomalias_geo.geometry.simplify(0.005, preserve_topology=True)
            except Exception:
                pass

            tooltip_fields = [c for c in ["date", "uf", "xmean", "xch4_max", "d_xch4", "area_km2", "pix_n", "thr"] if c in anomalias_geo.columns]
            aliases = {
                "date": "Data",
                "uf": "UF",
                "xmean": "XCH₄ médio",
                "xch4_max": "XCH₄ máximo",
                "d_xch4": "ΔXCH₄",
                "area_km2": "Área km²",
                "pix_n": "Pixels",
                "thr": "Limiar"
            }

            folium.GeoJson(
                data=gdf_to_folium_geojson(anomalias_geo),
                name="Anomalias TROPOMI",
                style_function=lambda feature: {
                    "fillColor": "#ff4d4d",
                    "color": "#ff9999",
                    "weight": 1,
                    "fillOpacity": 0.35,
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=tooltip_fields,
                    aliases=[aliases.get(c, c) for c in tooltip_fields],
                    localize=True,
                    sticky=True
                )
            ).add_to(m)

        elif camada_mapa == "Heatmap por centroide":
            heat_points = []
            for _, row in anomalias_plot.iterrows():
                try:
                    pt = row.geometry.representative_point()
                    peso = float(row.get("xmean", 1) or 1)
                    heat_points.append([pt.y, pt.x, peso])
                except Exception:
                    continue
            if heat_points:
                HeatMap(
                    heat_points,
                    name="Heatmap XCH₄",
                    radius=18,
                    blur=20,
                    max_zoom=8
                ).add_to(m)

        else:
            cluster_anom = MarkerCluster(name="Clusters de anomalias").add_to(m)
            for _, row in anomalias_plot.iterrows():
                try:
                    pt = row.geometry.representative_point()
                    popup = f"""
                    <div style="font-family:Arial; font-size:13px;">
                        <b>Anomalia TROPOMI</b><br>
                        <b>Data:</b> {row.get('date', '')}<br>
                        <b>UF:</b> {row.get('uf', '')}<br>
                        <b>XCH₄ médio:</b> {row.get('xmean', '')}<br>
                        <b>XCH₄ máximo:</b> {row.get('xch4_max', '')}<br>
                        <b>Área:</b> {row.get('area_km2', '')} km²
                    </div>
                    """
                    folium.CircleMarker(
                        location=[pt.y, pt.x],
                        radius=5,
                        color="#ff9999",
                        fill=True,
                        fill_color="#ff4d4d",
                        fill_opacity=0.8,
                        popup=folium.Popup(popup, max_width=320),
                    ).add_to(cluster_anom)
                except Exception:
                    continue

    if mostrar_fontes and fontes is not None and len(fontes) > 0:
        try:
            fontes_plot = fontes.to_crs(epsg=4326)
        except Exception:
            fontes_plot = fontes.set_crs(epsg=4326, allow_override=True)

        cluster = MarkerCluster(name="Fontes de emissão").add_to(m)

        for _, row in fontes_plot.iterrows():
            try:
                geom = row.geometry
                if geom is None or geom.is_empty:
                    continue

                pt = geom.centroid if geom.geom_type in ["Point", "MultiPoint"] else geom.representative_point()

                cadeia = row.get("cadeia", "")
                cor = "#4ea1ff"
                if str(cadeia).lower() == "upstream":
                    cor = "#f39c12"
                elif str(cadeia).lower() == "midstream":
                    cor = "#58a6ff"
                elif str(cadeia).lower() == "downstream":
                    cor = "#7ee787"

                popup = f"""
                <div style="font-family: Arial; font-size: 13px;">
                    <b>{row.get('nome', 'Sem nome')}</b><br>
                    <b>Cadeia:</b> {row.get('cadeia', '')}<br>
                    <b>Tipo:</b> {row.get('tipo_fonte', '')}<br>
                    <b>Município:</b> {row.get('municipio', '')}<br>
                    <b>UF:</b> {row.get('uf', '')}<br>
                    <b>Raio analítico selecionado:</b> {raio_km} km
                </div>
                """

                folium.CircleMarker(
                    location=[pt.y, pt.x],
                    radius=4,
                    color=cor,
                    fill=True,
                    fill_color=cor,
                    fill_opacity=0.9,
                    popup=folium.Popup(popup, max_width=320),
                    tooltip=row.get("nome", "Fonte")
                ).add_to(cluster)

                if fonte_id_sel is not None:
                    folium.Circle(
                        location=[pt.y, pt.x],
                        radius=raio_km * 1000,
                        color="#58a6ff",
                        weight=2,
                        fill=True,
                        fill_color="#58a6ff",
                        fill_opacity=0.06,
                        tooltip=f"Raio de {raio_km} km da fonte selecionada"
                    ).add_to(m)

            except Exception:
                continue

    folium.LayerControl(collapsed=False).add_to(m)

    st_folium(m, width=None, height=680)

    st.caption(
        "Observação: o mapa carrega uma amostra limitada para manter desempenho no Streamlit Cloud. "
        "A análise espacial pesada deve ser materializada no banco para ranking completo fonte ↔ anomalia."
    )


# =============================================================================
# ABA 3 — FONTES
# =============================================================================

with tab_fontes:
    c1, c2 = st.columns(2, gap="medium")

    with c1:
        st.subheader("Fontes por cadeia produtiva")
        if len(fontes_cadeia) > 0:
            fig = px.bar(
                fontes_cadeia.sort_values("total", ascending=True),
                x="total",
                y="cadeia",
                orientation="h",
                labels={"total": "Total", "cadeia": "Cadeia"},
                title="Distribuição das fontes por cadeia"
            )
            st.plotly_chart(plotly_layout(fig, 420), use_container_width=True)
        else:
            st.info("Nenhuma fonte encontrada.")

    with c2:
        st.subheader("Fontes por tipo")
        if len(fontes_tipo) > 0:
            fig = px.bar(
                fontes_tipo.sort_values("total", ascending=True),
                x="total",
                y="tipo_fonte",
                orientation="h",
                labels={"total": "Total", "tipo_fonte": "Tipo de fonte"},
                title="Tipos de fonte cadastrados"
            )
            st.plotly_chart(plotly_layout(fig, 420), use_container_width=True)
        else:
            st.info("Nenhum tipo de fonte encontrado.")

    st.subheader("Fontes filtradas")
    if fontes is not None and len(fontes) > 0:
        fontes_tabela = pd.DataFrame(fontes.drop(columns="geom", errors="ignore"))
        st.dataframe(fontes_tabela.head(1000), use_container_width=True, height=420)

        st.download_button(
            "⬇️ Baixar fontes filtradas CSV",
            fontes_tabela.to_csv(index=False).encode("utf-8"),
            "fontes_metano_filtradas.csv",
            "text/csv"
        )
    else:
        st.info("Nenhuma fonte encontrada para os filtros selecionados.")


# =============================================================================
# ABA 4 — DADOS
# =============================================================================

with tab_dados:
    st.subheader("Dados carregados no painel")

    c1, c2 = st.columns(2)

    with c1:
        st.markdown("### Série temporal filtrada")
        st.dataframe(temporal, use_container_width=True, height=300)
        st.download_button(
            "⬇️ Baixar série temporal CSV",
            temporal.to_csv(index=False).encode("utf-8"),
            "serie_temporal_tropomi_filtrada.csv",
            "text/csv"
        )

    with c2:
        st.markdown("### Ranking por UF")
        st.dataframe(ranking_uf, use_container_width=True, height=300)
        st.download_button(
            "⬇️ Baixar ranking UF CSV",
            ranking_uf.to_csv(index=False).encode("utf-8"),
            "ranking_uf_tropomi.csv",
            "text/csv"
        )

    if mostrar_tabela:
        st.markdown("### Amostra das anomalias carregadas no mapa")
        if anomalias is not None and len(anomalias) > 0:
            anomalias_tabela = pd.DataFrame(anomalias.drop(columns="geom", errors="ignore"))
            st.dataframe(anomalias_tabela.head(1000), use_container_width=True, height=420)

            st.download_button(
                "⬇️ Baixar anomalias do mapa CSV",
                anomalias_tabela.to_csv(index=False).encode("utf-8"),
                "anomalias_tropomi_mapa.csv",
                "text/csv"
            )
        else:
            st.info("Nenhuma anomalia encontrada para os filtros selecionados.")

    st.markdown("---")
    st.markdown("""
    **Nota técnica:** esta versão evita executar cruzamentos espaciais pesados no carregamento do dashboard. 
    Para retomar o ranking completo fonte ↔ anomalia com distância média e frequência, crie uma tabela materializada no Supabase/PostGIS 
    com as associações pré-calculadas e consulte essa tabela diretamente no Streamlit.
    """)
