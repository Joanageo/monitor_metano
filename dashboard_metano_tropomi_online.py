# -*- coding: utf-8 -*-

import pandas as pd
import geopandas as gpd
import streamlit as st
import folium
from folium.plugins import MarkerCluster, MiniMap, Fullscreen
from streamlit_folium import st_folium
import plotly.express as px
from sqlalchemy import create_engine


st.set_page_config(
    page_title="Monitor CH4 | TROPOMI Brasil",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================
# CONEXÃO COM SUPABASE
# =========================

try:
    DATABASE_URL = st.secrets["DATABASE_URL"]
except Exception:
    st.error("DATABASE_URL não configurada. Crie o arquivo .streamlit/secrets.toml.")
    st.stop()

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 20}
)

# =========================
# ESTILO
# =========================

st.markdown("""
<style>
.stApp {
    background: linear-gradient(180deg, #0b1220 0%, #0f1b2d 100%);
    color: #e6edf3;
}
[data-testid="stSidebar"] {
    background-color: #0c1424;
}
h1, h2, h3, h4, h5, h6, p, span, div {
    color: #e6edf3;
}
[data-testid="metric-container"] {
    background: #121f36;
    border: 1px solid #1f3a5f;
    border-radius: 12px;
    padding: 14px;
}
</style>
""", unsafe_allow_html=True)

# =========================
# FUNÇÕES DE LEITURA
# =========================

@st.cache_data(show_spinner="Carregando resumo...")
def load_resumo():
    return pd.read_sql("""
        SELECT
            (SELECT COUNT(*) FROM metano.anomalias_tropomi) AS total_anomalias,
            (SELECT COUNT(*) FROM metano.vw_fontes_metano) AS total_fontes;
    """, engine)


@st.cache_data(show_spinner="Carregando série temporal...")
def load_temporal():
    return pd.read_sql("""
        SELECT
            DATE_TRUNC('month', date::date) AS mes,
            COUNT(*) AS total_anomalias,
            ROUND(AVG(xmean)::numeric, 2) AS media_xmean,
            ROUND(MAX(xch4_max)::numeric, 2) AS maior_xch4
        FROM metano.anomalias_tropomi
        GROUP BY DATE_TRUNC('month', date::date)
        ORDER BY mes;
    """, engine)


@st.cache_data(show_spinner="Carregando UFs...")
def load_ufs():
    return pd.read_sql("""
        SELECT DISTINCT uf
        FROM metano.anomalias_tropomi
        WHERE uf IS NOT NULL
        ORDER BY uf;
    """, engine)


@st.cache_data(show_spinner="Carregando fontes...")
def load_fontes(cadeia=None):
    filtros = []

    if cadeia and cadeia != "Todas":
        filtros.append(f"cadeia = '{cadeia}'")

    where = ""
    if filtros:
        where = "WHERE " + " AND ".join(filtros)

    return gpd.read_postgis(f"""
        SELECT
            id,
            nome,
            tipo_fonte,
            cadeia,
            municipio,
            uf,
            geom
        FROM metano.vw_fontes_metano
        {where};
    """, engine, geom_col="geom")


@st.cache_data(show_spinner="Carregando anomalias TROPOMI...")
def load_anomalias(uf=None, ano=None, limite=3000):
    filtros = []

    if uf and uf != "Todas":
        filtros.append(f"uf = '{uf}'")

    if ano and ano != "Todos":
        filtros.append(f"EXTRACT(YEAR FROM date::date) = {int(ano)}")

    where = ""
    if filtros:
        where = "WHERE " + " AND ".join(filtros)

    return gpd.read_postgis(f"""
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
        FROM metano.anomalias_tropomi
        {where}
        ORDER BY date DESC
        LIMIT {int(limite)};
    """, engine, geom_col="geom")


@st.cache_data(show_spinner="Carregando ranking simplificado...")
def load_ranking_simples():
    """
    Ranking leve, sem recalcular a relação espacial pesada.
    Nesta versão inicial, o ranking pesado fica desativado para evitar timeout.
    """
    return pd.DataFrame(columns=[
        "cadeia",
        "tipo_fonte",
        "nome_fonte",
        "municipio_fonte",
        "uf_fonte",
        "frequencia_anomalias",
        "distancia_media_km",
        "maior_xmean",
        "media_xmean"
    ])


# =========================
# CABEÇALHO
# =========================

st.title("🛰️ Monitoramento de Metano — TROPOMI Brasil")
st.caption("Dashboard conectado ao Supabase/PostGIS — versão inicial online")

# =========================
# CARREGAMENTO BASE
# =========================

resumo = load_resumo()
temporal = load_temporal()
ufs_db = load_ufs()

# =========================
# SIDEBAR
# =========================

st.sidebar.header("Filtros")

cadeia_sel = st.sidebar.selectbox(
    "Cadeia produtiva",
    ["Todas", "upstream", "midstream", "downstream"]
)

anos = ["Todos"] + sorted(
    pd.to_datetime(temporal["mes"]).dt.year.dropna().astype(int).unique().tolist()
)

ano_sel = st.sidebar.selectbox("Ano", anos)

ufs = ["Todas"] + ufs_db["uf"].dropna().tolist()
uf_sel = st.sidebar.selectbox("UF", ufs)

limite = st.sidebar.slider(
    "Limite de anomalias no mapa",
    min_value=500,
    max_value=10000,
    value=3000,
    step=500
)

st.sidebar.info(
    "Nesta versão inicial, o mapa carrega um limite de anomalias para evitar lentidão. "
    "Depois criaremos tabelas materializadas para ranking completo."
)

# =========================
# CONSULTAS COM FILTRO
# =========================

anomalias = load_anomalias(uf=uf_sel, ano=ano_sel, limite=limite)
fontes = load_fontes(cadeia=cadeia_sel)
ranking = load_ranking_simples()

# =========================
# CARDS
# =========================

if len(resumo) > 0:
    r = resumo.iloc[0]

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Anomalias TROPOMI",
        f"{int(r['total_anomalias']):,}".replace(",", ".")
    )

    col2.metric(
        "Fontes cadastradas",
        f"{int(r['total_fontes']):,}".replace(",", ".")
    )

    col3.metric(
        "Anomalias no mapa",
        f"{len(anomalias):,}".replace(",", ".")
    )

    col4.metric(
        "Fontes no mapa",
        f"{len(fontes):,}".replace(",", ".")
    )

# =========================
# GRÁFICO TEMPORAL
# =========================

st.subheader("Evolução mensal das anomalias TROPOMI")

if len(temporal) > 0:
    fig = px.line(
        temporal,
        x="mes",
        y="total_anomalias",
        markers=True,
        labels={
            "mes": "Mês",
            "total_anomalias": "Total de anomalias"
        }
    )

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e6edf3")
    )

    st.plotly_chart(fig, use_container_width=True)
else:
    st.warning("Nenhum dado temporal encontrado.")

# =========================
# RANKING
# =========================

st.subheader("Ranking de instalações associadas às anomalias")

st.warning(
    "O ranking completo foi temporariamente desativado porque a view espacial está pesada no Supabase. "
    "Na próxima etapa vamos transformar a relação pluma → fonte em tabela materializada para carregar rápido."
)

st.dataframe(ranking, use_container_width=True)

# =========================
# MAPA
# =========================

st.subheader("Mapa TROPOMI + fontes de emissão")

m = folium.Map(
    location=[-14.2, -51.9],
    zoom_start=4,
    tiles=None,
    prefer_canvas=True
)

folium.TileLayer(
    "CartoDB dark_matter",
    name="Base escura"
).add_to(m)

folium.TileLayer(
    "OpenStreetMap",
    name="OpenStreetMap",
    show=False
).add_to(m)

Fullscreen(position="topright").add_to(m)
MiniMap(toggle_display=True).add_to(m)

# Anomalias TROPOMI
if anomalias is not None and len(anomalias) > 0:
    anomalias_plot = anomalias.to_crs(epsg=4326)

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
            fields=["date", "uf", "xmean", "xch4_max", "area_km2"],
            aliases=["Data", "UF", "XCH4 médio", "XCH4 máximo", "Área km²"],
            localize=True
        )
    ).add_to(m)

# Fontes
if fontes is not None and len(fontes) > 0:
    fontes_plot = fontes.to_crs(epsg=4326)

    cluster = MarkerCluster(name="Fontes de emissão").add_to(m)

    for _, row in fontes_plot.iterrows():
        try:
            geom = row.geometry

            if geom is None or geom.is_empty:
                continue

            if geom.geom_type in ["Point", "MultiPoint"]:
                pt = geom.centroid
            else:
                pt = geom.representative_point()

            popup = f"""
            <div style="font-family: Arial; font-size: 13px;">
                <b>{row.get('nome', 'Sem nome')}</b><br>
                <b>Cadeia:</b> {row.get('cadeia', '')}<br>
                <b>Tipo:</b> {row.get('tipo_fonte', '')}<br>
                <b>Município:</b> {row.get('municipio', '')}<br>
                <b>UF:</b> {row.get('uf', '')}
            </div>
            """

            folium.CircleMarker(
                location=[pt.y, pt.x],
                radius=4,
                color="#4ea1ff",
                fill=True,
                fill_color="#4ea1ff",
                fill_opacity=0.9,
                popup=folium.Popup(popup, max_width=280),
            ).add_to(cluster)

        except Exception:
            continue

folium.LayerControl(collapsed=False).add_to(m)

st_folium(m, width=None, height=650)

# =========================
# TABELAS E DOWNLOAD
# =========================

st.subheader("Amostra das anomalias carregadas")

if anomalias is not None and len(anomalias) > 0:
    anomalias_tabela = pd.DataFrame(anomalias.drop(columns="geom"))
    st.dataframe(anomalias_tabela.head(500), use_container_width=True)

    st.download_button(
        "Baixar amostra de anomalias CSV",
        anomalias_tabela.to_csv(index=False).encode("utf-8"),
        "anomalias_tropomi_amostra.csv",
        "text/csv"
    )
else:
    st.info("Nenhuma anomalia encontrada para os filtros selecionados.")

st.subheader("Amostra das fontes carregadas")

if fontes is not None and len(fontes) > 0:
    fontes_tabela = pd.DataFrame(fontes.drop(columns="geom"))
    st.dataframe(fontes_tabela.head(500), use_container_width=True)

    st.download_button(
        "Baixar fontes CSV",
        fontes_tabela.to_csv(index=False).encode("utf-8"),
        "fontes_metano.csv",
        "text/csv"
    )
else:
    st.info("Nenhuma fonte encontrada para os filtros selecionados.")