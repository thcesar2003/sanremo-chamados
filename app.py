
import streamlit as st
import sqlite3  # mantido apenas para compatibilidade com mensagens antigas
import psycopg2
from psycopg2.extras import DictCursor
import hashlib
import hmac
import os
import html
import pandas as pd
from datetime import datetime
from pathlib import Path

# ============================================================
# CONFIGURAÇÃO
# ============================================================

st.set_page_config(
    page_title="Chamados - Jardim San Remo",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded"
)

PASTA_APP = Path(__file__).resolve().parent
DATABASE_URL = st.secrets.get("DATABASE_URL", os.environ.get("DATABASE_URL", ""))
LOGO_PATH = PASTA_APP / "logo.jpg"

STATUS = [
    "Aberto",
    "Impresso/encaminhado",
    "Em execução",
    "Aguardando material/terceiro",
    "Resolvido",
    "Cancelado"
]

PRIORIDADES = ["Baixa", "Normal", "Alta", "Urgente", "Emergência"]

LOCAIS = [
    "Torre A", "Torre B", "Torre C",
    "Garagem", "Piscina", "Academia",
    "Salão de festas", "Playground",
    "Portaria", "Área externa", "Jardim",
    "Casa de máquinas", "Elevadores",
    "Área comum", "Outro"
]

CATEGORIAS = [
    "Elétrica/iluminação",
    "Hidráulica",
    "Portões/acesso",
    "Elevadores",
    "Limpeza",
    "Jardinagem",
    "Alvenaria/pintura",
    "Equipamentos",
    "Piscina",
    "Segurança",
    "Informática/câmeras",
    "Outro"
]

# ============================================================
# VISUAL
# ============================================================

st.markdown("""
<style>
/* Corrige a cor dos rótulos de todos os campos */
[data-testid="stMain"] [data-testid="stWidgetLabel"],
[data-testid="stMain"] [data-testid="stWidgetLabel"] p,
[data-testid="stMain"] .stSelectbox label,
[data-testid="stMain"] .stNumberInput label {
    color: #263b32 !important;
}
.stTextInput input,
.stTextArea textarea,
.stNumberInput input,
.stDateInput input {
    background-color: #ffffff !important;
    color: #263b32 !important;
    border: 1px solid #cbd8ce !important;
    border-radius: 8px !important;
    caret-color: #20523c !important;
}

.stTextInput input::placeholder,
.stTextArea textarea::placeholder {
    color: #77877d !important;
    opacity: 1 !important;
}

[data-testid="stMain"] .stTextInput label,
[data-testid="stMain"] .stTextArea label {
    color: #263b32 !important;
}

.stTextInput input:focus,
.stTextArea textarea:focus {
    border-color: #39815b !important;
    box-shadow: 0 0 0 1px #39815b !important;
}

[data-testid="stSidebar"] input {
    background-color: #ffffff !important;
    color: #263b32 !important;
}
.stApp {
    background-color: #f5f7f6;
    color: #263b32;
}

[data-testid="stMain"] {
    background-color: #f5f7f6;
}

[data-testid="stMainBlockContainer"] {
    padding-top: 1.4rem;
    max-width: 1550px;
}

[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #174b35 0%, #24543e 100%);
}

[data-testid="stSidebar"] * {
    color: #ffffff;
}

[data-testid="stSidebar"] hr {
    border-color: rgba(255,255,255,0.25);
}

h1, h2, h3 {
    color: #20523c;
}

[data-testid="stMetric"] {
    background: #ffffff;
    border: 1px solid #e1e9e3;
    border-radius: 12px;
    padding: 16px;
}

[data-testid="stForm"],
[data-testid="stExpander"] {
    background-color: #ffffff;
    border: 1px solid #e1e9e3;
    border-radius: 12px;
}

.stTextInput input,
.stTextArea textarea,
.stNumberInput input,
.stDateInput input,
[data-baseweb="select"] {
    border-radius: 8px;
}

.stButton > button,
.stDownloadButton > button {
    border-radius: 8px;
    font-weight: 600;
}

[data-testid="stDataFrame"],
[data-testid="stTable"] {
    background-color: #ffffff;
    border-radius: 10px;
}

hr {
    border-color: #dce5de;
}

.sanremo-subtitle {
    color: #63756a;
    font-size: 0.98rem;
}

.sanremo-card {
    background: #ffffff;
    border: 1px solid #e1e9e3;
    border-radius: 12px;
    padding: 18px;
    margin-bottom: 12px;
}

@media print {
    [data-testid="stSidebar"],
    header,
    footer {
        display: none !important;
    }
}
</style>
""", unsafe_allow_html=True)


# ============================================================
# BANCO DE DADOS
# ============================================================

class ConexaoPostgres:
    """Adaptador pequeno para manter as consultas do app compatíveis com PostgreSQL."""
    def __init__(self):
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL não configurada. Configure em .streamlit/secrets.toml ou nas Secrets do Streamlit Cloud.")
        self.raw = psycopg2.connect(DATABASE_URL, cursor_factory=DictCursor, connect_timeout=15)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.raw.commit()
            else:
                self.raw.rollback()
        finally:
            self.raw.close()
        return False

    def execute(self, sql, params=None):
        cur = self.raw.cursor()
        # As consultas existentes usam ? como placeholder SQLite; PostgreSQL usa %s.
        cur.execute(sql.replace("?", "%s"), params or ())
        return cur

    def executemany(self, sql, seq_of_params):
        cur = self.raw.cursor()
        cur.executemany(sql.replace("?", "%s"), seq_of_params)
        return cur

    def commit(self):
        self.raw.commit()


def conectar():
    return ConexaoPostgres()


def hash_senha(senha, salt=None):
    if salt is None:
        salt = os.urandom(16)

    chave = hashlib.pbkdf2_hmac(
        "sha256",
        senha.encode("utf-8"),
        salt,
        200000
    )

    return salt.hex() + "$" + chave.hex()


def verificar_senha(senha, senha_salva):
    try:
        if not isinstance(senha, str) or not isinstance(senha_salva, str):
            return False
        salt_hex, chave_hex = senha_salva.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        chave = hashlib.pbkdf2_hmac(
            "sha256",
            senha.encode("utf-8"),
            salt,
            200000
        )
        return hmac.compare_digest(chave.hex(), chave_hex)
    except (ValueError, AttributeError):
        return False


def inicializar_banco():
    with conectar() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id BIGSERIAL PRIMARY KEY,
                usuario TEXT UNIQUE NOT NULL,
                senha TEXT NOT NULL,
                perfil TEXT NOT NULL DEFAULT 'Usuario',
                ativo INTEGER NOT NULL DEFAULT 1
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS chamados (
                id BIGSERIAL PRIMARY KEY,
                data_abertura TEXT NOT NULL,
                solicitante TEXT,
                local TEXT NOT NULL,
                categoria TEXT NOT NULL,
                prioridade TEXT NOT NULL,
                titulo TEXT NOT NULL,
                descricao TEXT NOT NULL,
                observacoes TEXT,
                responsavel TEXT,
                material_necessario TEXT,
                compra_necessaria TEXT,
                custo_estimado REAL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'Aberto',
                data_atualizacao TEXT,
                usuario_abertura TEXT
            )
        """)

        quantidade = conn.execute(
            "SELECT COUNT(*) FROM usuarios"
        ).fetchone()[0]

        if quantidade == 0:
            usuarios_iniciais = [
                ("sindico", hash_senha("Troque123!"), "Administrador", 1),
                ("portaria", hash_senha("Troque123!"), "Usuario", 1),
                ("zelador", hash_senha("Troque123!"), "Usuario", 1)
            ]

            conn.executemany("""
                INSERT INTO usuarios (usuario, senha, perfil, ativo)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (usuario) DO NOTHING
            """, usuarios_iniciais)

        conn.commit()


inicializar_banco()


# ============================================================
# CONSULTAS AO BANCO
# ============================================================

def listar_usuarios(apenas_ativos=False):
    with conectar() as conn:
        sql = "SELECT id, usuario, perfil, ativo FROM usuarios"
        if apenas_ativos:
            sql += " WHERE ativo = 1"
        sql += " ORDER BY usuario"
        return pd.read_sql_query(sql, conn.raw)


def buscar_usuario(usuario):
    with conectar() as conn:
        return conn.execute(
            "SELECT * FROM usuarios WHERE usuario = ?",
            (usuario,)
        ).fetchone()


def alterar_senha_usuario(usuario, nova_senha):
    with conectar() as conn:
        conn.execute(
            "UPDATE usuarios SET senha = ? WHERE usuario = ?",
            (hash_senha(nova_senha), usuario)
        )
        conn.commit()


def criar_usuario(usuario, senha, perfil):
    with conectar() as conn:
        conn.execute("""
            INSERT INTO usuarios (usuario, senha, perfil, ativo)
            VALUES (?, ?, ?, 1)
        """, (usuario, hash_senha(senha), perfil))
        conn.commit()


def atualizar_usuario(id_usuario, perfil, ativo):
    with conectar() as conn:
        conn.execute("""
            UPDATE usuarios
            SET perfil = ?, ativo = ?
            WHERE id = ?
        """, (perfil, int(ativo), int(id_usuario)))
        conn.commit()


def carregar_chamados():
    with conectar() as conn:
        return pd.read_sql_query(
            "SELECT * FROM chamados ORDER BY id DESC",
            conn.raw
        )


def buscar_chamado(id_chamado):
    with conectar() as conn:
        return conn.execute(
            "SELECT * FROM chamados WHERE id = ?",
            (int(id_chamado),)
        ).fetchone()


def salvar_chamado(dados):
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")

    with conectar() as conn:
        cursor = conn.execute("""
            INSERT INTO chamados (
                data_abertura, solicitante, local, categoria,
                prioridade, titulo, descricao, observacoes,
                responsavel, material_necessario,
                compra_necessaria, custo_estimado, status,
                data_atualizacao, usuario_abertura
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
        """, (
            agora,
            dados["solicitante"],
            dados["local"],
            dados["categoria"],
            dados["prioridade"],
            dados["titulo"],
            dados["descricao"],
            dados["observacoes"],
            dados["responsavel"],
            dados["material_necessario"],
            dados["compra_necessaria"],
            dados["custo_estimado"],
            "Aberto",
            agora,
            st.session_state["usuario"]
        ))

        novo_id = cursor.fetchone()[0]
        conn.commit()
        return novo_id


def atualizar_chamado(id_chamado, dados):
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")

    with conectar() as conn:
        conn.execute("""
            UPDATE chamados SET
                solicitante = ?,
                local = ?,
                categoria = ?,
                prioridade = ?,
                titulo = ?,
                descricao = ?,
                observacoes = ?,
                responsavel = ?,
                material_necessario = ?,
                compra_necessaria = ?,
                custo_estimado = ?,
                status = ?,
                data_atualizacao = ?
            WHERE id = ?
        """, (
            dados["solicitante"],
            dados["local"],
            dados["categoria"],
            dados["prioridade"],
            dados["titulo"],
            dados["descricao"],
            dados["observacoes"],
            dados["responsavel"],
            dados["material_necessario"],
            dados["compra_necessaria"],
            dados["custo_estimado"],
            dados["status"],
            agora,
            int(id_chamado)
        ))
        conn.commit()


# ============================================================
# LOGIN
# ============================================================

# Inicializa todas as chaves da sessão antes de usá-las.
if "autenticado" not in st.session_state:
    st.session_state["autenticado"] = False
if "usuario" not in st.session_state:
    st.session_state["usuario"] = None
if "perfil" not in st.session_state:
    st.session_state["perfil"] = None

# O formulário e o processamento do login ficam dentro do mesmo bloco.
# Usuários não autenticados param aqui e não chegam ao restante do sistema.
if not st.session_state["autenticado"]:
    st.markdown("<br>", unsafe_allow_html=True)
    espaco1, centro, espaco2 = st.columns([1, 1.3, 1])

    with centro:
        if LOGO_PATH.exists():
            st.image(str(LOGO_PATH), width=260)

        st.markdown(
            "<h2 style='text-align:center'>Sistema de Chamados</h2>",
            unsafe_allow_html=True
        )
        st.markdown(
            "<p class='sanremo-subtitle' style='text-align:center'>"
            "Condomínio Jardim San Remo</p>",
            unsafe_allow_html=True
        )

        with st.form("form_login"):
            usuario_login = st.text_input("Usuário").strip().lower()
            senha_login = st.text_input("Senha", type="password")
            entrar = st.form_submit_button(
                "Entrar",
                use_container_width=True
            )

        st.caption("Acesso restrito à equipe do condomínio.")

        if entrar:
            try:
                usuario_encontrado = buscar_usuario(usuario_login)
            except Exception as erro:
                st.error(f"Não foi possível consultar os usuários no banco: {erro}")
                usuario_encontrado = None

            if usuario_encontrado is None:
                st.error(
                    "Usuário não encontrado no banco de dados. "
                    "Confira o nome digitado e os usuários cadastrados."
                )
            elif not verificar_senha(senha_login, usuario_encontrado["senha"]):
                st.error("Senha incorreta.")
            elif not usuario_encontrado["ativo"]:
                st.error("Este usuário está inativo. Procure o síndico.")
            else:
                st.session_state["autenticado"] = True
                st.session_state["usuario"] = usuario_encontrado["usuario"]
                st.session_state["perfil"] = usuario_encontrado["perfil"]
                st.rerun()

    st.stop()

# Segunda proteção: evita KeyError se a sessão estiver incompleta ou antiga.
usuario_atual = st.session_state.get("usuario")
perfil_atual = st.session_state.get("perfil")
if not usuario_atual or not perfil_atual:
    st.session_state["autenticado"] = False
    st.session_state["usuario"] = None
    st.session_state["perfil"] = None
    st.rerun()

eh_admin = perfil_atual == "Administrador"


# ============================================================
# CABEÇALHO
# ============================================================

col_logo, col_titulo, col_usuario = st.columns(
    [1.1, 3.7, 1.6],
    vertical_alignment="center"
)

with col_logo:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=190)
    else:
        st.markdown("## 🏢 Jardim San Remo")

with col_titulo:
    st.markdown(
        "<h2 style='margin-bottom:0'>Sistema de Chamados de Manutenção</h2>"
        "<p class='sanremo-subtitle'>Mais organização para o seu condomínio</p>",
        unsafe_allow_html=True
    )

with col_usuario:
    st.markdown(f"**Usuário:** {html.escape(usuario_atual)}")
    st.caption(f"Perfil: {perfil_atual}")

st.divider()


# ============================================================
# MENU LATERAL
# ============================================================

with st.sidebar:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=210)

    st.markdown("## Jardim San Remo")
    st.caption("Manutenção e serviços")
    st.divider()

    paginas = [
        "Painel",
        "Abrir chamado",
        "Gerenciar chamados",
        "Imprimir ordens",
        "Relatórios",
        "Minha senha"
    ]

    if eh_admin:
        paginas.append("Usuários")

    pagina = st.radio(
        "Navegação",
        paginas,
        label_visibility="collapsed"
    )

    st.divider()
    st.caption(f"Conectado como {usuario_atual}")

    if st.button("Sair", use_container_width=True):
        st.session_state["autenticado"] = False
        st.session_state.pop("usuario", None)
        st.session_state.pop("perfil", None)
        st.rerun()


# ============================================================
# CARREGAR DADOS
# ============================================================

df = carregar_chamados()

if not df.empty:
    df["custo_estimado"] = pd.to_numeric(
        df["custo_estimado"], errors="coerce"
    ).fillna(0)


# ============================================================
# PAINEL
# ============================================================

if pagina == "Painel":
    st.title("Painel de Manutenção")
    st.caption("Visão geral dos chamados do condomínio")

    total = len(df)
    abertos = int((df["status"] == "Aberto").sum()) if total else 0
    andamento = int(
        df["status"].isin([
            "Impresso/encaminhado",
            "Em execução",
            "Aguardando material/terceiro"
        ]).sum()
    ) if total else 0
    resolvidos = int((df["status"] == "Resolvido").sum()) if total else 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total de chamados", total)
    m2.metric("Abertos", abertos)
    m3.metric("Em andamento", andamento)
    m4.metric("Resolvidos", resolvidos)

    st.markdown("### Últimos chamados")

    if df.empty:
        st.info("Ainda não há chamados cadastrados.")
    else:
        colunas = [
            "id", "data_abertura", "local",
            "categoria", "prioridade", "status", "titulo"
        ]
        painel = df[colunas].head(10).copy()
        painel.columns = [
            "Nº", "Data/hora", "Local",
            "Categoria", "Prioridade", "Status", "Descrição curta"
        ]
        st.dataframe(painel, use_container_width=True, hide_index=True)

        col_esq, col_dir = st.columns(2)

        with col_esq:
            st.markdown("### Chamados por status")
            contagem_status = df["status"].value_counts()
            st.bar_chart(contagem_status)

        with col_dir:
            st.markdown("### Chamados por categoria")
            contagem_categoria = df["categoria"].value_counts()
            st.bar_chart(contagem_categoria)

    st.markdown("""
    <div class="sanremo-card">
        <strong style="color:#20523c">Condomínio Jardim San Remo</strong>
        <p style="margin-bottom:0">
        Juntos por um condomínio mais seguro, organizado e bem cuidado.
        </p>
    </div>
    """, unsafe_allow_html=True)


# ============================================================
# ABRIR CHAMADO
# ============================================================

elif pagina == "Abrir chamado":
    st.title("Abrir novo chamado")
    st.caption("Registre o problema para acompanhamento da equipe.")

    with st.form("form_novo_chamado"):
        c1, c2 = st.columns(2)

        with c1:
            solicitante = st.text_input("Solicitante")
            local = st.selectbox("Local", LOCAIS)
            categoria = st.selectbox("Categoria", CATEGORIAS)
            prioridade = st.selectbox("Prioridade", PRIORIDADES, index=1)

        with c2:
            titulo = st.text_input("Título do chamado *")
            responsavel = st.text_input("Responsável sugerido")
            compra_necessaria = st.selectbox(
                "Necessita compra?",
                ["Não", "Sim"]
            )
            custo_estimado = st.number_input(
                "Custo estimado (R$)",
                min_value=0.0,
                value=0.0,
                step=10.0
            )

        descricao = st.text_area(
            "Descrição do problema *",
            height=130
        )

        observacoes = st.text_area(
            "Observações adicionais",
            height=80
        )

        material_necessario = st.text_area(
            "Materiais necessários",
            height=80
        )

        enviar = st.form_submit_button(
            "Registrar chamado",
            use_container_width=True
        )

        if enviar:
            if not titulo.strip() or not descricao.strip():
                st.error("Preencha o título e a descrição do problema.")
            else:
                dados = {
                    "solicitante": solicitante.strip(),
                    "local": local,
                    "categoria": categoria,
                    "prioridade": prioridade,
                    "titulo": titulo.strip(),
                    "descricao": descricao.strip(),
                    "observacoes": observacoes.strip(),
                    "responsavel": responsavel.strip(),
                    "material_necessario": material_necessario.strip(),
                    "compra_necessaria": compra_necessaria,
                    "custo_estimado": custo_estimado
                }

                novo_id = salvar_chamado(dados)
                st.success(f"Chamado nº {novo_id:03d} registrado com sucesso!")
                st.info("O chamado foi criado com status Aberto.")


# ============================================================
# GERENCIAR CHAMADOS
# ============================================================

elif pagina == "Gerenciar chamados":
    st.title("Gerenciar chamados")

    df = carregar_chamados()

    if df.empty:
        st.info("Não existem chamados cadastrados.")
    else:
        f1, f2, f3 = st.columns(3)

        with f1:
            filtro_status = st.selectbox(
                "Filtrar por status",
                ["Todos"] + STATUS
            )

        with f2:
            filtro_local = st.selectbox(
                "Filtrar por local",
                ["Todos"] + LOCAIS
            )

        with f3:
            busca = st.text_input("Buscar por nº, título ou descrição")

        filtrado = df.copy()

        if filtro_status != "Todos":
            filtrado = filtrado[filtrado["status"] == filtro_status]

        if filtro_local != "Todos":
            filtrado = filtrado[filtrado["local"] == filtro_local]

        if busca.strip():
            termo = busca.strip().lower()
            mascara = (
                filtrado["titulo"].fillna("").str.lower().str.contains(
                    termo, regex=False
                )
                | filtrado["descricao"].fillna("").str.lower().str.contains(
                    termo, regex=False
                )
                | filtrado["id"].astype(str).str.contains(termo, regex=False)
            )
            filtrado = filtrado[mascara]

        colunas = [
            "id", "data_abertura", "local", "categoria",
            "prioridade", "titulo", "responsavel", "status"
        ]
        tabela = filtrado[colunas].copy()
        tabela.columns = [
            "Nº", "Data/hora", "Local", "Categoria",
            "Prioridade", "Título", "Responsável", "Status"
        ]
        st.dataframe(tabela, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("### Editar chamado")

        ids = filtrado["id"].astype(int).tolist()

        if ids:
            id_escolhido = st.selectbox(
                "Selecione o número do chamado",
                ids,
                format_func=lambda x: f"Chamado nº {x:03d}"
            )

            chamado = buscar_chamado(id_escolhido)

            if chamado:
                with st.form("form_editar_chamado"):
                    c1, c2 = st.columns(2)

                    with c1:
                        titulo_ed = st.text_input(
                            "Título",
                            value=chamado["titulo"] or ""
                        )
                        solicitante_ed = st.text_input(
                            "Solicitante",
                            value=chamado["solicitante"] or ""
                        )
                        local_ed = st.selectbox(
                            "Local",
                            LOCAIS,
                            index=LOCAIS.index(chamado["local"])
                            if chamado["local"] in LOCAIS else 0
                        )
                        categoria_ed = st.selectbox(
                            "Categoria",
                            CATEGORIAS,
                            index=CATEGORIAS.index(chamado["categoria"])
                            if chamado["categoria"] in CATEGORIAS else 0
                        )
                        prioridade_ed = st.selectbox(
                            "Prioridade",
                            PRIORIDADES,
                            index=PRIORIDADES.index(chamado["prioridade"])
                            if chamado["prioridade"] in PRIORIDADES else 1
                        )

                    with c2:
                        responsavel_ed = st.text_input(
                            "Responsável",
                            value=chamado["responsavel"] or ""
                        )
                        status_ed = st.selectbox(
                            "Status",
                            STATUS,
                            index=STATUS.index(chamado["status"])
                            if chamado["status"] in STATUS else 0
                        )
                        compra_ed = st.selectbox(
                            "Necessita compra?",
                            ["Não", "Sim"],
                            index=1 if chamado["compra_necessaria"] == "Sim" else 0
                        )
                        custo_ed = st.number_input(
                            "Custo estimado (R$)",
                            min_value=0.0,
                            value=float(chamado["custo_estimado"] or 0),
                            step=10.0
                        )

                    descricao_ed = st.text_area(
                        "Descrição",
                        value=chamado["descricao"] or "",
                        height=120
                    )
                    observacoes_ed = st.text_area(
                        "Observações",
                        value=chamado["observacoes"] or "",
                        height=80
                    )
                    material_ed = st.text_area(
                        "Materiais necessários",
                        value=chamado["material_necessario"] or "",
                        height=80
                    )

                    salvar_edicao = st.form_submit_button(
                        "Salvar alterações",
                        use_container_width=True
                    )

                    if salvar_edicao:
                        if not titulo_ed.strip() or not descricao_ed.strip():
                            st.error("Título e descrição são obrigatórios.")
                        else:
                            atualizar_chamado(id_escolhido, {
                                "titulo": titulo_ed.strip(),
                                "solicitante": solicitante_ed.strip(),
                                "local": local_ed,
                                "categoria": categoria_ed,
                                "prioridade": prioridade_ed,
                                "responsavel": responsavel_ed.strip(),
                                "status": status_ed,
                                "compra_necessaria": compra_ed,
                                "custo_estimado": custo_ed,
                                "descricao": descricao_ed.strip(),
                                "observacoes": observacoes_ed.strip(),
                                "material_necessario": material_ed.strip()
                            })
                            st.success("Chamado atualizado.")
                            st.rerun()


# ============================================================
# IMPRESSÃO DE ORDENS DE SERVIÇO
# ============================================================

elif pagina == "Imprimir ordens":
    st.title("Imprimir ordens de serviço")

    df = carregar_chamados()

    if df.empty:
        st.info("Não há chamados para imprimir.")
    else:
        ids = df["id"].astype(int).tolist()
        id_escolhido = st.selectbox(
            "Selecione o chamado",
            ids,
            format_func=lambda x: f"Ordem de serviço nº {x:03d}"
        )

        chamado = buscar_chamado(id_escolhido)

        if chamado:
            def seguro(valor):
                return html.escape(str(valor if valor is not None else ""))

            html_ordem = f"""
            <!DOCTYPE html>
            <html lang="pt-BR">
            <head>
                <meta charset="UTF-8">
                <title>Ordem de Serviço {id_escolhido:03d}</title>
                <style>
                    * {{ box-sizing: border-box; }}
                    body {{
                        font-family: Arial, sans-serif;
                        font-size: 10pt;
                        line-height: 1.2;
                        color: #263b32;
                        margin: 18px;
                    }}
                    .cabecalho {{
                        text-align: center;
                        border-bottom: 2px solid #20523c;
                        padding-bottom: 6px;
                        margin-bottom: 10px;
                    }}
                    h1 {{ color: #20523c; font-size: 17pt; margin: 0 0 3px; }}
                    h2 {{ font-size: 12pt; margin: 3px 0; }}
                    .numero {{
                        font-size: 15pt;
                        font-weight: bold;
                        color: #20523c;
                        margin-top: 3px;
                    }}
                    p {{ margin: 5px 0; }}
                    .campo {{
                        border: 1px solid #d5dfd8;
                        padding: 5px 7px;
                        margin-bottom: 5px;
                        border-radius: 4px;
                        white-space: pre-wrap;
                        overflow-wrap: anywhere;
                    }}
                    .rotulo {{
                        font-weight: bold;
                        display: block;
                        margin-bottom: 2px;
                    }}
                    .assinaturas {{
                        display: flex;
                        gap: 28px;
                        margin-top: 28px;
                        page-break-inside: avoid;
                    }}
                    .assinatura {{
                        flex: 1;
                        text-align: center;
                        border-top: 1px solid #555;
                        padding-top: 5px;
                        font-size: 9pt;
                    }}
                    .botao {{
                        padding: 8px 16px;
                        background: #20523c;
                        color: white;
                        border: 0;
                        border-radius: 5px;
                        cursor: pointer;
                    }}
                    @page {{ size: A4 portrait; margin: 8mm; }}
                    @media print {{
                        html, body {{
                            width: auto !important;
                            height: auto !important;
                            margin: 0 !important;
                            padding: 0 !important;
                            font-size: 9pt;
                            line-height: 1.12;
                        }}
                        .nao-imprimir {{ display: none !important; }}
                        .cabecalho {{ padding-bottom: 4px; margin-bottom: 6px; }}
                        h1 {{ font-size: 15pt; }}
                        h2 {{ font-size: 10pt; }}
                        .numero {{ font-size: 13pt; }}
                        p {{ margin: 3px 0; }}
                        .campo {{ padding: 4px 6px; margin-bottom: 4px; break-inside: avoid; }}
                        .rotulo {{ margin-bottom: 1px; }}
                        .assinaturas {{ margin-top: 20px; }}
                        * {{ print-color-adjust: exact; -webkit-print-color-adjust: exact; }}
                    }}
                </style>
            </head>
            <body>
                <div class="cabecalho">
                    <h1>CONDOMÍNIO JARDIM SAN REMO</h1>
                    <h2>ORDEM DE SERVIÇO - MANUTENÇÃO</h2>
                    <div class="numero">Nº {id_escolhido:03d}</div>
                </div>

                <p><strong>Data de abertura:</strong>
                {seguro(chamado["data_abertura"])}</p>

                <p><strong>Solicitante:</strong>
                {seguro(chamado["solicitante"])}</p>

                <p><strong>Local:</strong> {seguro(chamado["local"])}
                &nbsp;&nbsp; <strong>Categoria:</strong>
                {seguro(chamado["categoria"])}</p>

                <p><strong>Prioridade:</strong>
                {seguro(chamado["prioridade"])}
                &nbsp;&nbsp; <strong>Status:</strong>
                {seguro(chamado["status"])}</p>

                <div class="campo">
                    <span class="rotulo">Título</span>
                    {seguro(chamado["titulo"])}
                </div>

                <div class="campo">
                    <span class="rotulo">Descrição do problema/serviço</span>
                    {seguro(chamado["descricao"])}
                </div>

                <div class="campo">
                    <span class="rotulo">Materiais necessários</span>
                    {seguro(chamado["material_necessario"])}
                </div>

                <div class="campo">
                    <span class="rotulo">Compra necessária</span>
                    {seguro(chamado["compra_necessaria"])}
                </div>

                <div class="campo">
                    <span class="rotulo">Custo estimado</span>
                    R$ {float(chamado["custo_estimado"] or 0):,.2f}
                </div>

                <div class="campo">
                    <span class="rotulo">Responsável</span>
                    {seguro(chamado["responsavel"])}
                </div>

                <div class="campo">
                    <span class="rotulo">Observações</span>
                    {seguro(chamado["observacoes"])}
                </div>

                <div class="assinaturas">
                    <div class="assinatura">Responsável pela execução</div>
                    <div class="assinatura">Conferência / Síndico</div>
                </div>

                <p class="nao-imprimir" style="margin-top:30px">
                    <button class="botao" onclick="window.print()">
                    Imprimir ordem de serviço
                    </button>
                </p>
            </body>
            </html>
            """

            st.components.v1.html(
                html_ordem,
                height=850,
                scrolling=True
            )

            st.caption(
                "Use o botão de impressão exibido na ordem. "
                "Na janela de impressão do navegador, escolha a impressora "
                "ou a opção de salvar em PDF."
            )


# ============================================================
# RELATÓRIOS
# ============================================================

elif pagina == "Relatórios":
    st.title("Relatórios de manutenção")

    df = carregar_chamados()

    if df.empty:
        st.info("Ainda não há dados para gerar relatórios.")
    else:
        df["custo_estimado"] = pd.to_numeric(
            df["custo_estimado"], errors="coerce"
        ).fillna(0)

        c1, c2, c3 = st.columns(3)

        c1.metric("Total de chamados", len(df))
        c2.metric(
            "Custo estimado total",
            f"R$ {df['custo_estimado'].sum():,.2f}"
        )
        c3.metric(
            "Chamados urgentes/emergenciais",
            int(df["prioridade"].isin(["Urgente", "Emergência"]).sum())
        )

        st.markdown("### Resumo por status")
        resumo_status = (
            df.groupby("status")
            .size()
            .reset_index(name="Quantidade")
            .sort_values("Quantidade", ascending=False)
        )
        st.dataframe(resumo_status, use_container_width=True, hide_index=True)

        st.markdown("### Resumo por categoria")
        resumo_categoria = (
            df.groupby("categoria")
            .size()
            .reset_index(name="Quantidade")
            .sort_values("Quantidade", ascending=False)
        )
        st.dataframe(
            resumo_categoria,
            use_container_width=True,
            hide_index=True
        )

        st.markdown("### Relação completa")
        st.dataframe(df, use_container_width=True, hide_index=True)

        csv = df.to_csv(index=False).encode("utf-8-sig")

        st.download_button(
            "Exportar relatório em CSV",
            data=csv,
            file_name="relatorio_chamados_san_remo.csv",
            mime="text/csv",
            use_container_width=True
        )


# ============================================================
# MINHA SENHA
# ============================================================

elif pagina == "Minha senha":
    st.title("Alterar minha senha")

    with st.form("form_trocar_senha"):
        senha_atual = st.text_input("Senha atual", type="password")
        senha_nova = st.text_input("Nova senha", type="password")
        confirmar_senha = st.text_input(
            "Confirme a nova senha",
            type="password"
        )

        trocar = st.form_submit_button(
            "Alterar senha",
            use_container_width=True
        )

        if trocar:
            registro = buscar_usuario(usuario_atual)

            if not registro or not verificar_senha(
                senha_atual, registro["senha"]
            ):
                st.error("A senha atual está incorreta.")
            elif len(senha_nova) < 8:
                st.error("A nova senha deve ter pelo menos 8 caracteres.")
            elif senha_nova != confirmar_senha:
                st.error("A confirmação não corresponde à nova senha.")
            elif senha_nova == senha_atual:
                st.error("Escolha uma senha diferente da atual.")
            else:
                alterar_senha_usuario(usuario_atual, senha_nova)
                st.success("Senha alterada com sucesso.")


# ============================================================
# USUÁRIOS - SOMENTE ADMINISTRADOR
# ============================================================

elif pagina == "Usuários":
    st.title("Gerenciamento de usuários")

    if not eh_admin:
        st.error("Você não tem permissão para acessar esta área.")
        st.stop()

    st.markdown("### Cadastrar usuário")

    with st.form("form_criar_usuario"):
        novo_usuario = st.text_input(
            "Nome de usuário",
            help="Use letras minúsculas, sem espaços."
        ).strip().lower()

        nova_senha_usuario = st.text_input(
            "Senha inicial",
            type="password"
        )

        perfil_novo = st.selectbox(
            "Perfil",
            ["Usuario", "Administrador"]
        )

        criar = st.form_submit_button(
            "Cadastrar usuário",
            use_container_width=True
        )

        if criar:
            if not novo_usuario:
                st.error("Informe um nome de usuário.")
            elif " " in novo_usuario:
                st.error("O nome de usuário não pode conter espaços.")
            elif len(nova_senha_usuario) < 8:
                st.error("A senha precisa ter pelo menos 8 caracteres.")
            elif buscar_usuario(novo_usuario):
                st.error("Esse usuário já existe.")
            else:
                try:
                    criar_usuario(
                        novo_usuario,
                        nova_senha_usuario,
                        perfil_novo
                    )
                    st.success(
                        f"Usuário '{novo_usuario}' cadastrado."
                    )
                    st.rerun()
                except psycopg2.IntegrityError:
                    st.error("Não foi possível cadastrar esse usuário.")

    st.divider()
    st.markdown("### Usuários cadastrados")

    usuarios_df = listar_usuarios()

    if usuarios_df.empty:
        st.info("Nenhum usuário cadastrado.")
    else:
        exibir_usuarios = usuarios_df.copy()
        exibir_usuarios["ativo"] = exibir_usuarios["ativo"].map(
            {1: "Sim", 0: "Não"}
        )
        exibir_usuarios.columns = [
            "ID", "Usuário", "Perfil", "Ativo"
        ]

        st.dataframe(
            exibir_usuarios,
            use_container_width=True,
            hide_index=True
        )

        st.markdown("### Alterar perfil ou acesso")

        opcoes_usuarios = usuarios_df["usuario"].tolist()
        usuario_editar = st.selectbox(
            "Selecione o usuário",
            opcoes_usuarios
        )

        registro_editar = usuarios_df[
            usuarios_df["usuario"] == usuario_editar
        ].iloc[0]

        with st.form("form_editar_usuario"):
            perfil_editar = st.selectbox(
                "Perfil do usuário",
                ["Usuario", "Administrador"],
                index=0 if registro_editar["perfil"] == "Usuario" else 1
            )

            ativo_editar = st.checkbox(
                "Usuário ativo",
                value=bool(registro_editar["ativo"])
            )

            salvar_usuario = st.form_submit_button(
                "Salvar usuário",
                use_container_width=True
            )

            if salvar_usuario:
                if (
                    usuario_editar == usuario_atual
                    and not ativo_editar
                ):
                    st.error(
                        "Não é permitido desativar o usuário conectado."
                    )
                else:
                    atualizar_usuario(
                        int(registro_editar["id"]),
                        perfil_editar,
                        ativo_editar
                    )
                    st.success("Dados do usuário atualizados.")
                    st.rerun()


# ============================================================
# RODAPÉ
# ============================================================

st.markdown("---")
st.caption(
    "Condomínio Jardim San Remo • Sistema de Chamados de Manutenção"
)
