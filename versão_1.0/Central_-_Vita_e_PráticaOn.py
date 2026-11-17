import os
import sys
import re
import unicodedata
import traceback
import tkinter as tk
from tkinter import messagebox, filedialog
import shutil
import json
import uuid
import base64
import importlib
import webbrowser
import math
from datetime import datetime, timedelta

# ================= SISTEMA ANTI-FECHAMENTO =================
def capturar_erro_fatal(exc_type, exc_value, exc_traceback):
    erro = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("Erro Crítico de Inicialização", f"O sistema falhou ao iniciar. O erro foi:\n\n{erro}")
    sys.exit(1)

sys.excepthook = capturar_erro_fatal

try:
    import customtkinter as ctk
except ImportError:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("Erro", "A biblioteca 'customtkinter' não está instalada.\nInstale via CMD: pip install customtkinter")
    sys.exit(1)

# ---------- Bibliotecas pesadas: só são carregadas quando a função que as usa é acionada ----------
# (pandas, PyMuPDF, lxml, Pillow, pypdf e openpyxl levavam vários segundos para importar na abertura.)
class _ImportTardio:
    def __init__(self, modulo, pacote_pip):
        self._modulo = modulo
        self._pip = pacote_pip
        self._obj = None

    def __getattr__(self, nome):
        if self._obj is None:
            try:
                self._obj = importlib.import_module(self._modulo)
            except ImportError:
                messagebox.showerror("Erro", f"A biblioteca '{self._pip}' não está instalada.\nInstale via CMD: pip install {self._pip}")
                raise
        return getattr(self._obj, nome)

pd = _ImportTardio("pandas", "pandas")                 # conversor de XML/CSV para Excel e Leitor de NF-e
fitz = _ImportTardio("pymupdf", "PyMuPDF")             # PDF -> imagem (módulo "pymupdf" = antigo "fitz")
etree = _ImportTardio("lxml.etree", "lxml")            # Leitor de NF-e
Image = _ImportTardio("PIL.Image", "Pillow")           # conversões JPG/PNG <-> PDF e PNG <-> JPG
_pypdf = _ImportTardio("pypdf", "pypdf")               # unir/separar PDFs
_openpyxl_styles = _ImportTardio("openpyxl.styles", "openpyxl")
_ImageOps = _ImportTardio("PIL.ImageOps", "Pillow")        # corrige a rotação das fotos (EXIF)
_qrcode = _ImportTardio("qrcode", "qrcode[pil]")           # Gerador de QR Code (única biblioteca nova)  # negrito no cabeçalho do Excel

def PdfReader(*args, **kwargs):
    return _pypdf.PdfReader(*args, **kwargs)

def PdfWriter(*args, **kwargs):
    return _pypdf.PdfWriter(*args, **kwargs)

def Font(*args, **kwargs):
    return _openpyxl_styles.Font(*args, **kwargs)

# Namespace padrão de todo XML de NF-e emitido pela Sefaz/Receita.
NFE_NAMESPACE = {"nfe": "http://www.portalfiscal.inf.br/nfe"}


# ================= CONFIGURAÇÕES E DADOS =================
def obter_caminho_recurso(nome_arquivo):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, nome_arquivo)

# ---------- Paleta (claro, escuro) e fontes "vivas" ----------
# Cada cor é um par (claro, escuro): o CustomTkinter troca sozinho entre os dois quando o tema muda.
# O valor entre aspas em _C("#...") é a cor original do tema escuro.
_PALETA = {
    "#0F0F0F": ("#F2F4F7", "#0F0F0F"),  # fundo do app
    "#0A0A0A": ("#E4E7EC", "#0A0A0A"),
    "#121212": ("#EBEEF2", "#121212"),  # menu lateral
    "#1A1A1A": ("#FFFFFF", "#1A1A1A"),  # cartões
    "#262626": ("#E1E5EB", "#262626"),  # painéis e botões
    "#2D2D2D": ("#D3D9E1", "#2D2D2D"),  # hover e bordas
    "#333333": ("#D3D9E1", "#333333"),
    "#444444": ("#6B7280", "#444444"),
    "#555555": ("#4B5563", "#555555"),
    "#808080": ("#6B7280", "#808080"),  # textos secundários
    "#D1D1D1": ("#2B2F36", "#D1D1D1"),
    "#E5E5E5": ("#333333", "#E5E5E5"),
    "#FFFFFF": ("#111111", "#FFFFFF"),  # texto principal
    "#000000": ("#FFFFFF", "#000000"),  # texto sobre botões claros/verdes
    "#FF4444": ("#D32F2F", "#FF4444"),
    "#AA0000": ("#B71C1C", "#AA0000"),
    "#2E8BFF": ("#1A6FE0", "#2E8BFF"),
    "#1A66CC": ("#0F55B8", "#1A66CC"),
    "#00FF66": ("#00A844", "#00FF66"),
    "#00CC52": ("#008A38", "#00CC52"),
    "#FFB300": ("#B26A00", "#FFB300"),
}

def _C(cor_escura):
    return _PALETA.get(cor_escura.upper(), cor_escura)

ESCALA_FONTE = 1.0
_FONTES_CACHE = {}

def _f(familia, tamanho, *estilos):
    # Devolve uma CTkFont compartilhada. Ao mudar o tamanho da fonte nas Configurações,
    # todas elas são reconfiguradas e o app inteiro se atualiza sem reiniciar.
    chave = (familia, tamanho, estilos)
    item = _FONTES_CACHE.get(chave)
    if item is None:
        fonte = ctk.CTkFont(family=familia, size=max(7, round(tamanho * ESCALA_FONTE)),
                            weight="bold" if "bold" in estilos else "normal",
                            slant="italic" if "italic" in estilos else "roman",
                            underline="underline" in estilos)
        item = _FONTES_CACHE[chave] = (fonte, tamanho)
    return item[0]

def _aplicar_escala_fontes(escala):
    global ESCALA_FONTE
    ESCALA_FONTE = escala
    for fonte, base in _FONTES_CACHE.values():
        fonte.configure(size=max(7, round(base * escala)))

COLOR_BG = _C("#0F0F0F")
COLOR_CARD = _C("#1A1A1A")
COLOR_ACCENT = _C("#FFFFFF")
COLOR_HOVER_WHITE = _C("#E5E5E5") 
COLOR_HOVER = _C("#2D2D2D")
COLOR_SUBTITLE = _C("#808080")
COLOR_DANGER = _C("#FF4444")
COLOR_VITA_BLUE = _C("#2E8BFF")
COLOR_OVERLAY_GRAY = _C("#0A0A0A")
COLOR_SUCCESS_HOVER = _C("#00CC52")

# Fonte de ícones usada no checkbox da lista de afazeres das Anotações.
# Precisa estar instalada na máquina (o instalador do app cuida disso).
FONTE_ICONES = "Font Awesome 6 Free Solid"
CHECKBOX_VAZIO = "\uf0c8"    # ícone "square" (preenchido, sem check) da Font Awesome 6 Free Solid
CHECKBOX_MARCADO = "\uf14a"  # ícone "square-check" da Font Awesome 6 Free Solid
SEPARADOR_CHECKBOX = "  | "  # fica entre a caixinha e o texto da tarefa

# ---------- Filtros da Renomeação de PDFs (ignoram maiúsculas/minúsculas e acentos) ----------
def _normalizar_nome_arquivo(texto):
    decomposto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in decomposto if unicodedata.category(c) != "Mn").lower().strip()

def _montar_padrao_nome(nome_regex):
    # aceita: [000-]NomeDoDocumento[-092026]  (prefixo numérico e sufixo mês/ano são opcionais)
    return re.compile(rf"^(?:(\d+)\s*-\s*)?(?:{nome_regex})(?:\s*[-_]\s*\d{{6}})?$")

PADRAO_RECIBO_PAGAMENTO = _montar_padrao_nome(r"recibo[\s_]*de[\s_]*pagamento")
PADRAO_EXTRATO_MENSAL = _montar_padrao_nome(r"extrato[\s_]*mensal")
PADRAO_RELATORIO_LIQUIDOS = _montar_padrao_nome(r"(?:relatorio|relacao)[\s_]*de[\s_]*liquidos")
PADRAO_DCTFWEB = re.compile(r"^(?:(\d+)\s*-\s*)?recibo_\d+_(\d{2})(\d{4})_\d+_\d+$")  # grupos: empresa (opcional), mês, ano

PASTA_APPDATA = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'CentralVitaApp')
os.makedirs(PASTA_APPDATA, exist_ok=True)
ARQUIVO_NOTAS = os.path.join(PASTA_APPDATA, 'anotacoes.json')
ARQUIVO_SENHAS = os.path.join(PASTA_APPDATA, 'senhas.json')
ARQUIVO_PRAZOS = os.path.join(PASTA_APPDATA, 'prazos.json')
ARQUIVO_CONFIG = os.path.join(PASTA_APPDATA, 'config.json')

# ---------- Ícone do app embutido no código (não depende de nenhuma pasta nem do instalador) ----------
ICONE_APP_B64 = """
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
zRebbbPItYYMovqf6mnQoEEJ7zFlyhSKRqKOD6EbpMViRES0efNmCoVCKTmEnLdHH32UiMhq93Xb7BMRffTRR+2a7vnz5wtpDVfa
11577bItVJLS6SagDMCZ7iCAWABLlixxCstwO3UffvghKYpCoVDIdpZE07lmzZo4P8JMaxgG3X///Z0uaCZMeXk5nTp1yjbbokPa
fLGZRo4cSQBc+eLvgwcPpoaGBietbtjvdvz4cerXr193mP9gEIAL+/Sp02QYZi3RDd3x7jWNKisr7cKOJ8+vhv6KLly4QLqhuwqb
iOjAtwfommuu6VRh83WvV7/uEEvX7bwREVUtrvLkhwkAgFatWuUitGmZzDz9/vePdJqUWUsAsSAe//fH3YUmFPju3bupqKjIY845
7UsvveS2AoKz9Z8LF3qUlUj4mtGjR1NLS4vj+HH3zyCqra2lsrIyD6ninUZN0+y0/B7bt2+nq6++Oq1xisATgAuyZ2Eh7fpml0mC
qNNucm1+6smnPDWHC7K0tJRqa2tdbS4Tqb6+nm666aYOrQCfz8vLo5qaGqH2u/MxZ84cTz447VUFV9GXX37pSsskikQiXRKpDDwB
xAKprKykaDRq9ukFx8kwDKqrq6P+5eUeRfL3Of86xySA0P+OaWbNe/vttz1Kixc+N2vWLItIOumsfKsGb9myhXr06JHQEj388MNO
HtiKRc2077//fod5yFkCcMEoikLr169PaM5fr672FCIToqCggL744gt37dPM3kE4HKY777zTRTa/Z5eUlNDhvx32OKS6plNrayuN
GzfOcw9OW1ZWRrW1ta5oIfcezp0715Xx/uwhAAAaNmwYNV1ocrqFghltaWmh0aNHe5TA3ysqKigcDrvaXybPZ5995lt7xWc///zz
CU3/m2++6atA/r148WIPcTkw9dxzz2VC+cEigFhAf/zjaz6FaZrSTZv8+/ec9t13303YpfRrv/n7kCFD6HzjeVc8gj/r6n6gAQMG
JGx+RowYYccy7HiERZxDhw5R7969u6vbF3wC+JpTw+kS6rpOM2bM8FUkD9zU/1Rvd710w0xHhkHHjh2j0tJSlzI43dq1a03SRWO2
D+E4oE96ngfAJuCGDRtcaUXr9cADD/imlQRohwQAaO7cuS6vXjTn+/fvp169eiXsiv3hD//l7VJaztgrr7xiP4evnzJlCsViMd+u
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
"""

def _gravar_icone_embutido():
    # Grava o ícone embutido na pasta de dados do app e devolve o caminho (o Tk precisa de um arquivo .ico).
    import base64
    caminho = os.path.join(PASTA_APPDATA, "icone_app.ico")
    try:
        dados = base64.b64decode("".join(ICONE_APP_B64.split()))
        if not os.path.exists(caminho) or os.path.getsize(caminho) != len(dados):
            with open(caminho, "wb") as f:
                f.write(dados)
        return caminho
    except Exception:
        return None

# ---------- Versão do app e atualizações ----------
# A cada lançamento: aumente VERSAO_APP aqui, gere o instalador novo e atualize o versao.json no GitHub.
VERSAO_APP = "1.0"
URL_VERSAO = "https://raw.githubusercontent.com/Fabitoz/Central-Vita-PraticaOn/main/versao.json"
URL_REPOSITORIO = "https://github.com/Fabitoz/Central-Vita-PraticaOn"

# ---------- Configurações do usuário (tema, tamanho da fonte, verificação de atualizações) ----------
ESCALAS_FONTE = {"Pequena": 0.9, "Normal": 1.0, "Grande": 1.15, "Muito grande": 1.3}
CONFIG_PADRAO = {"tema": "dark", "fonte": "Normal", "verificar_atualizacoes": True}

def _carregar_config():
    cfg = dict(CONFIG_PADRAO)
    try:
        with open(ARQUIVO_CONFIG, "r", encoding="utf-8") as f:
            salvo = json.load(f)
        if isinstance(salvo, dict):
            cfg.update({k: v for k, v in salvo.items() if k in CONFIG_PADRAO})
    except Exception:
        pass
    if cfg["tema"] not in ("dark", "light"):
        cfg["tema"] = "dark"
    if cfg["fonte"] not in ESCALAS_FONTE:
        cfg["fonte"] = "Normal"
    cfg["verificar_atualizacoes"] = bool(cfg["verificar_atualizacoes"])
    return cfg

def _salvar_config():
    try:
        with open(ARQUIVO_CONFIG, "w", encoding="utf-8") as f:
            json.dump(CONFIG, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

CONFIG = _carregar_config()
ESCALA_FONTE = ESCALAS_FONTE[CONFIG["fonte"]]

# ---------- Proteção das senhas (Windows DPAPI: só o mesmo usuário do Windows consegue ler) ----------
def _dpapi(dados, proteger):
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(dados, len(dados))
    entrada = BLOB(len(dados), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    saida = BLOB()
    funcao = ctypes.windll.crypt32.CryptProtectData if proteger else ctypes.windll.crypt32.CryptUnprotectData
    if not funcao(ctypes.byref(entrada), None, None, None, None, 0, ctypes.byref(saida)):
        raise OSError("Falha na criptografia do Windows")
    try:
        return ctypes.string_at(saida.pbData, saida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(ctypes.cast(saida.pbData, ctypes.c_void_p))

def _proteger_senha(texto):
    if not texto:
        return ""
    bruto = texto.encode("utf-8")
    try:
        return "dpapi:" + base64.b64encode(_dpapi(bruto, True)).decode("ascii")
    except Exception:
        return "b64:" + base64.b64encode(bruto).decode("ascii")  # plano B (sem criptografia real)

def _revelar_senha(valor):
    if not valor:
        return ""
    try:
        if valor.startswith("dpapi:"):
            return _dpapi(base64.b64decode(valor[6:]), False).decode("utf-8")
        if valor.startswith("b64:"):
            return base64.b64decode(valor[4:]).decode("utf-8")
    except Exception:
        return ""
    return valor

# ---------- Helpers de números, tamanhos e nomes de arquivo (usados nas novas abas) ----------
def _parse_num_br(texto):
    # aceita "1.234,56", "1234,56", "1234.56", "15%" e "R$ 10"
    t = texto.strip().replace("R$", "").replace("%", "").replace(" ", "")
    if not t:
        raise ValueError("vazio")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif t.count(".") > 1:
        t = t.replace(".", "")
    valor = float(t)
    if not math.isfinite(valor):
        raise ValueError("número inválido")
    return valor

def _fmt_br(valor, casas_max=4):
    s = f"{valor:,.{casas_max}f}"
    inteiro, dec = s.split(".")
    dec = dec.rstrip("0").ljust(2, "0")
    return inteiro.replace(",", ".") + "," + dec

def _fmt_tamanho(n):
    n = float(n)
    for unidade in ("B", "KB", "MB"):
        if n < 1024:
            return f"{int(n)} {unidade}" if unidade == "B" else f"{_fmt_br(n, 2)} {unidade}"
        n /= 1024
    return f"{_fmt_br(n, 2)} GB"

def _nome_arquivo_seguro(nome, padrao):
    limpo = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", nome).strip().strip(".")
    return limpo or padrao

# ---------- Helpers fiscais, de datas e de XML (abas de CNPJ, chave, NFS-e/CT-e, prazos e páginas de PDF) ----------
def _limpar_cnpj(texto):
    return re.sub(r"[^0-9A-Za-z]", "", texto).upper()

def _dv_cnpj(base):
    # Vale para CNPJ numérico e para o novo CNPJ alfanumérico (valor do caractere = código ASCII - 48).
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6] + pesos1
    def calc(seq, pesos):
        resto = sum((ord(c) - 48) * p for c, p in zip(seq, pesos)) % 11
        return "0" if resto < 2 else str(11 - resto)
    d1 = calc(base, pesos1)
    d2 = calc(base + d1, pesos2)
    return d1 + d2

def _cnpj_valido(cnpj):
    return bool(re.fullmatch(r"[0-9A-Z]{12}\d{2}", cnpj)) and len(set(cnpj)) > 1 and _dv_cnpj(cnpj[:12]) == cnpj[12:]

def _fmt_cnpj(c):
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"

# ---------- Nomes das abas novas ----------
ABA_CEP = "📮 Consulta de CEP (BETA)"
ABA_CNPJ_LOTE = "📋 Conferência de CNPJ em Lote"
ABA_EXTENSO = "🔢 Número para Extenso"
ABA_IMG_OTIM = "📐 Redimensionar Imagens (BETA)"
ABA_CONFIG = "🔧 Configurações"

# ---------- Internet: CEP (ViaCEP, com BrasilAPI de reserva) e CNPJ (BrasilAPI + endereço completado pelo CEP) ----------
class _CepNaoEncontrado(Exception):
    pass

def _http_json(url, timeout=15):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "CentralVita/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))

def _sem_acento_maiusculo(texto):
    decomposto = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in decomposto if unicodedata.category(c) != "Mn").upper().strip()

def _consultar_cep(cep):
    # Roda fora da thread da interface. Tenta o ViaCEP; se ele estiver fora do ar ou não achar o CEP, tenta a BrasilAPI.
    import urllib.error
    nao_achou = False
    try:
        d = _http_json(f"https://viacep.com.br/ws/{cep}/json/")
        if isinstance(d, dict) and not d.get("erro"):
            return {"cep": d.get("cep") or cep, "logradouro": d.get("logradouro") or "", "complemento": d.get("complemento") or "",
                    "bairro": d.get("bairro") or "", "cidade": d.get("localidade") or "", "uf": d.get("uf") or "",
                    "estado": d.get("estado") or "", "ibge": d.get("ibge") or "", "ddd": d.get("ddd") or "", "fonte": "ViaCEP"}
        nao_achou = True
    except Exception:
        pass
    try:
        d = _http_json(f"https://brasilapi.com.br/api/cep/v2/{cep}")
        return {"cep": d.get("cep") or cep, "logradouro": d.get("street") or "", "complemento": "",
                "bairro": d.get("neighborhood") or "", "cidade": d.get("city") or "", "uf": d.get("state") or "",
                "estado": "", "ibge": "", "ddd": "", "fonte": "BrasilAPI"}
    except urllib.error.HTTPError as e:
        if e.code in (400, 404):
            raise _CepNaoEncontrado()
        raise
    except Exception:
        if nao_achou:
            raise _CepNaoEncontrado()
        raise

def _completar_endereco_cep(d):
    # Se a BrasilAPI (CNPJ) veio sem logradouro, bairro, município ou UF, completa pelo CEP (ViaCEP).
    # O número NÃO existe no CEP: se faltar no CNPJ, o endereço continua sendo tratado como incompleto.
    cep = re.sub(r"\D", "", str(d.get("cep") or ""))
    campos = [("logradouro", "logradouro", "Logradouro"), ("bairro", "bairro", "Bairro"), ("municipio", "cidade", "Município"), ("uf", "uf", "UF")]
    if len(cep) != 8 or all(str(d.get(k) or "").strip() for k, _, _ in campos):
        return
    try:
        r = _consultar_cep(cep)
    except Exception:
        return
    completados = []
    for chave_cnpj, chave_cep, rotulo in campos:
        if not str(d.get(chave_cnpj) or "").strip() and r.get(chave_cep):
            valor = _sem_acento_maiusculo(r[chave_cep])
            if chave_cnpj == "logradouro":
                # o logradouro do CEP já traz o tipo ("Rua X"), então o tipo da BrasilAPI deixa de ser usado
                partes = valor.split(" ", 1)
                valor = partes[0].capitalize() + (" " + partes[1] if len(partes) > 1 else "")
                d["_logradouro_com_tipo"] = True
            d[chave_cnpj] = valor
            completados.append(rotulo)
    if completados:
        d["_completado_cep"] = (completados, r.get("fonte") or "ViaCEP")

def _consultar_cnpj_api(cnpj):
    d = _http_json(f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}")
    _completar_endereco_cep(d)
    return d

# ---------- Número por extenso ----------
_UNID_EXT = ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez", "onze", "doze", "treze",
             "quatorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove"]
_DEZ_EXT = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"]
_CENT_EXT = ["", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos", "oitocentos", "novecentos"]
_ESCALAS_EXTENSO = {2: ("milhão", "milhões"), 3: ("bilhão", "bilhões"), 4: ("trilhão", "trilhões")}

def _extenso_ate_999(n):
    if n == 100:
        return "cem"
    partes = []
    c, resto = divmod(n, 100)
    if c:
        partes.append(_CENT_EXT[c])
    if resto:
        if resto < 20:
            partes.append(_UNID_EXT[resto])
        else:
            d, u = divmod(resto, 10)
            partes.append(_DEZ_EXT[d] + (" e " + _UNID_EXT[u] if u else ""))
    return " e ".join(partes)

def _extenso_inteiro(n):
    if n == 0:
        return "zero"
    grupos = []
    while n:
        n, g = divmod(n, 1000)
        grupos.append(g)
    partes = []
    for i in range(len(grupos) - 1, -1, -1):
        g = grupos[i]
        if g == 0:
            continue
        if i == 0:
            txt = _extenso_ate_999(g)
        elif i == 1:
            txt = "mil" if g == 1 else f"{_extenso_ate_999(g)} mil"
        else:
            sing, plur = _ESCALAS_EXTENSO[i]
            txt = f"{_extenso_ate_999(g)} {sing if g == 1 else plur}"
        partes.append((g, txt))
    resultado = partes[0][1]
    for k in range(1, len(partes)):
        g, txt = partes[k]
        ultimo = k == len(partes) - 1
        resultado += (" e " if ultimo and (g < 100 or g % 100 == 0) else " ") + txt
    return resultado

def _ler_numero_br(texto):
    from decimal import Decimal
    t = texto.upper().replace("R$", "").replace(" ", "").strip()
    negativo = t.startswith("-")
    t = t.lstrip("-+")
    if not t:
        raise ValueError("Digite um número.")
    if "," in t and "." in t and t.rfind(".") > t.rfind(","):
        raise ValueError("Formato ambíguo. Use ponto no milhar e vírgula nos centavos (ex.: 1.234,56).")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif "." in t and re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    if not re.fullmatch(r"\d+(\.\d+)?", t):
        raise ValueError("Número inválido. Use só dígitos, ponto e vírgula (ex.: 1.234,56).")
    if len(t.split(".")[0].lstrip("0") or "0") > 15:
        raise ValueError("Número grande demais (máximo: 999 trilhões).")
    return negativo, Decimal(t)

def _numero_por_extenso(texto, moeda=True):
    # Devolve (texto por extenso, valor formatado).
    from decimal import Decimal, ROUND_HALF_UP
    negativo, d = _ler_numero_br(texto)
    if moeda:
        valor = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        reais = int(valor)
        centavos = int((valor - reais) * 100)
        partes = []
        if reais > 0 or centavos == 0:
            unidade = "real" if reais == 1 else ("de reais" if reais > 0 and reais % 10**6 == 0 else "reais")
            partes.append(f"{_extenso_inteiro(reais)} {unidade}")
        if centavos > 0:
            partes.append(f"{_extenso_inteiro(centavos)} {'centavo' if centavos == 1 else 'centavos'}")
        extenso = " e ".join(partes)
        valor_fmt = "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        if negativo and valor > 0:
            extenso, valor_fmt = "menos " + extenso, "-" + valor_fmt
        return extenso, valor_fmt
    texto_num = format(d, "f")
    parte_int, _, frac = texto_num.partition(".")
    frac = frac.rstrip("0")[:15]
    extenso = _extenso_inteiro(int(parte_int))
    valor_fmt = f"{int(parte_int):,}".replace(",", ".")
    if frac:
        extenso += " vírgula " + "zero " * (len(frac) - len(frac.lstrip("0"))) + _extenso_inteiro(int(frac))
        valor_fmt += "," + frac
    if negativo and d > 0:
        extenso, valor_fmt = "menos " + extenso, "-" + valor_fmt
    return extenso, valor_fmt

# ---------- Redimensionar/comprimir imagens ----------
def _fmt_tamanho(b):
    if b < 1024 * 1024:
        return f"{b / 1024:.0f} KB"
    return f"{b / (1024 * 1024):.2f} MB".replace(".", ",")

def _codificar_imagem(img, formato, qualidade):
    import io
    buf = io.BytesIO()
    if formato == "JPEG":
        img.save(buf, "JPEG", quality=qualidade, optimize=True)
    else:
        img.save(buf, "PNG", optimize=True)
    return buf.getvalue()

def _otimizar_imagem(img, formato, qualidade, alvo_kb):
    # Com tamanho-alvo: baixa a qualidade (só JPG, até 45) e depois reduz as dimensões em 10% por vez.
    dados = _codificar_imagem(img, formato, qualidade)
    if not alvo_kb:
        return dados
    alvo = alvo_kb * 1024
    q, atual = qualidade, img
    for _ in range(40):
        if len(dados) <= alvo:
            break
        if formato == "JPEG" and q > 45:
            q = max(45, q - 10)
        else:
            larg, alt = atual.size
            if min(larg, alt) <= 100:
                break
            atual = atual.resize((max(1, int(larg * 0.9)), max(1, int(alt * 0.9))), getattr(Image, "Resampling", Image).LANCZOS)
        dados = _codificar_imagem(atual, formato, q)
    return dados

def _processar_imagem_otimizada(caminho, pasta_saida, max_larg, max_alt, qualidade, alvo_kb, modo):
    tam_antes = os.path.getsize(caminho)
    img = _ImageOps.exif_transpose(Image.open(caminho))  # respeita a rotação das fotos de celular
    if modo == "jpg":
        formato = "JPEG"
    elif modo == "png":
        formato = "PNG"
    else:
        formato = "PNG" if os.path.splitext(caminho)[1].lower() == ".png" else "JPEG"
    if max_larg or max_alt:
        img.thumbnail((max_larg or 10**6, max_alt or 10**6), getattr(Image, "Resampling", Image).LANCZOS)  # só reduz, mantém a proporção
    if formato == "JPEG" and img.mode != "RGB":
        if img.mode in ("RGBA", "LA", "P"):
            rgba = img.convert("RGBA")
            fundo = Image.new("RGB", rgba.size, (255, 255, 255))
            fundo.paste(rgba, mask=rgba.split()[-1])
            img = fundo
        else:
            img = img.convert("RGB")
    elif formato == "PNG" and img.mode not in ("RGB", "RGBA", "L", "LA", "P"):
        img = img.convert("RGBA")
    dados = _otimizar_imagem(img, formato, qualidade, alvo_kb)
    nome = os.path.splitext(os.path.basename(caminho))[0]
    ext = ".jpg" if formato == "JPEG" else ".png"
    saida = os.path.join(pasta_saida, f"{nome}_reduzida{ext}")
    n = 2
    while os.path.exists(saida):
        saida = os.path.join(pasta_saida, f"{nome}_reduzida_{n}{ext}")
        n += 1
    with open(saida, "wb") as f:
        f.write(dados)
    return saida, tam_antes, len(dados)

# ---------- Verificador de atualizações ----------
def _versao_tupla(texto):
    partes = [int(p) for p in re.findall(r"\d+", str(texto))][:4]
    return tuple(partes + [0] * (4 - len(partes)))

def _buscar_versao_remota():
    d = _http_json(URL_VERSAO, timeout=10)
    if not isinstance(d, dict) or not str(d.get("versao") or "").strip():
        raise ValueError("arquivo de versão inválido")
    return {"versao": str(d["versao"]).strip(),
            "link": str(d.get("link") or (URL_REPOSITORIO + "/releases/latest")).strip(),
            "novidades": str(d.get("novidades") or "").strip()}

def _dv_chave(chave43):
    soma, peso = 0, 2
    for c in reversed(chave43):
        soma += (ord(c) - 48) * peso
        peso = 2 if peso == 9 else peso + 1
    resto = soma % 11
    return "0" if resto < 2 else str(11 - resto)

def _fmt_tel(tel):
    d = re.sub(r"\D", "", tel or "")
    if len(d) == 10: return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    if len(d) == 11: return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    return tel or ""

def _fmt_cnae(c):
    # 6201500 -> 6201-5/00 ; códigos curtos (ex.: 0 de "Dispensada") ganham zeros à esquerda -> 0000-0/00
    d = re.sub(r"\D", "", str(c if c is not None else ""))
    if not d:
        return ""
    d = d.zfill(7)
    return f"{d[:4]}-{d[4]}/{d[5:]}" if len(d) == 7 else d

def _pascoa(ano):
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return datetime(ano, mes, dia + 1).date()

def _feriados_br(ano, facultativos=True):
    # Feriados nacionais (+ Carnaval e Corpus Christi, dias sem expediente bancário). Estaduais/municipais não entram.
    fixos = {(1, 1): "Confraternização Universal", (4, 21): "Tiradentes", (5, 1): "Dia do Trabalho",
             (9, 7): "Independência do Brasil", (10, 12): "Nossa Senhora Aparecida", (11, 2): "Finados",
             (11, 15): "Proclamação da República", (11, 20): "Consciência Negra", (12, 25): "Natal"}
    dias = {datetime(ano, m, d).date(): nome for (m, d), nome in fixos.items()}
    pascoa = _pascoa(ano)
    dias[pascoa - timedelta(days=2)] = "Sexta-feira Santa"
    if facultativos:
        dias[pascoa - timedelta(days=48)] = "Carnaval (segunda-feira)"
        dias[pascoa - timedelta(days=47)] = "Carnaval (terça-feira)"
        dias[pascoa + timedelta(days=60)] = "Corpus Christi"
    return dias

def _parse_paginas(texto, total):
    # "1-3, 5, 8-" -> índices (base 0), na ordem digitada e sem repetir
    indices = []
    for parte in re.split(r"[;,]", texto):
        parte = parte.strip()
        if not parte:
            continue
        m = re.fullmatch(r"(\d+)\s*(?:-\s*(\d*))?", parte)
        if not m:
            raise ValueError(f"Trecho inválido: '{parte}'. Use o formato 1-3, 5, 8-10.")
        ini = int(m.group(1))
        if m.group(2) is None:
            fim = ini
        else:
            fim = int(m.group(2)) if m.group(2) else total
        if ini < 1 or fim < ini or fim > total:
            raise ValueError(f"'{parte}' está fora do intervalo do PDF (1 a {total}).")
        for p in range(ini - 1, fim):
            if p not in indices:
                indices.append(p)
    if not indices:
        raise ValueError("Informe as páginas (ex.: 1-3, 5, 8-10).")
    return indices

def _nome_local(e):
    return e.tag.rsplit("}", 1)[-1] if isinstance(e.tag, str) else ""

def _achar(contexto, *nomes):
    # Primeiro elemento descendente com um dos nomes (ignora namespace), respeitando a ordem dos nomes.
    if contexto is None:
        return None
    for nome in nomes:
        for e in contexto.iter():
            if _nome_local(e) == nome:
                return e
    return None

def _filho(contexto, *nomes):
    if contexto is None:
        return None
    for nome in nomes:
        for e in contexto:
            if _nome_local(e) == nome:
                return e
    return None

def _txt(e):
    return (e.text or "").strip() if e is not None else ""

def _texto_xml(contexto, *nomes):
    return _txt(_achar(contexto, *nomes))

def _texto_filho(contexto, *nomes):
    return _txt(_filho(contexto, *nomes))

def _moeda_xml(valor):
    if not valor:
        return ""
    try:
        return "R$ " + _fmt_br(float(valor), 2)
    except ValueError:
        return valor

def _data_xml_br(valor):
    if not valor:
        return ""
    try:
        dt = datetime.fromisoformat(valor)
    except ValueError:
        return valor
    return dt.strftime("%d/%m/%Y") if len(valor) <= 10 else dt.strftime("%d/%m/%Y %H:%M")

def _identificar_xml(raiz):
    nomes = {_nome_local(e) for e in raiz.iter()}
    if "infCte" in nomes: return "cte"
    if "infNFe" in nomes: return "nfe"
    if nomes & {"infNFSe", "InfNfse", "InfNFSe", "CompNfse"}: return "nfse"
    return None

def _resumo_cte(raiz):
    inf = _achar(raiz, "infCte")
    r = []
    def sec(titulo): r.append((f"== {titulo} ==", ""))
    def add(campo, valor): r.append((campo, valor or ""))

    ide, emit, rem, exped, receb, dest = (_filho(inf, n) for n in ("ide", "emit", "rem", "exped", "receb", "dest"))
    vprest, imp = _filho(inf, "vPrest"), _filho(inf, "imp")

    sec("CT-e")
    add("Chave de Acesso", (inf.get("Id") or "").replace("CTe", "", 1))
    add("Número", _texto_filho(ide, "nCT"))
    add("Série", _texto_filho(ide, "serie"))
    add("Data de Emissão", _data_xml_br(_texto_filho(ide, "dhEmi")))
    add("Tipo do CT-e", {"0": "Normal", "1": "Complemento de valores", "2": "Anulação", "3": "Substituto"}.get(_texto_filho(ide, "tpCTe"), _texto_filho(ide, "tpCTe")))
    add("Modal", {"01": "Rodoviário", "02": "Aéreo", "03": "Aquaviário", "04": "Ferroviário", "05": "Dutoviário", "06": "Multimodal"}.get(_texto_filho(ide, "modal"), _texto_filho(ide, "modal")))
    add("CFOP", _texto_filho(ide, "CFOP"))
    add("Natureza da Prestação", _texto_filho(ide, "natOp"))
    add("Início da Prestação", "/".join(x for x in (_texto_filho(ide, "xMunIni"), _texto_filho(ide, "UFIni")) if x))
    add("Fim da Prestação", "/".join(x for x in (_texto_filho(ide, "xMunFim"), _texto_filho(ide, "UFFim")) if x))
    prot = _achar(raiz, "infProt")
    if prot is not None:
        add("Protocolo de Autorização", _texto_filho(prot, "nProt"))
        add("Situação", " - ".join(x for x in (_texto_filho(prot, "cStat"), _texto_filho(prot, "xMotivo")) if x))

    sec("EMITENTE (TRANSPORTADOR)")
    add("Nome", _texto_filho(emit, "xNome")); add("CNPJ", _texto_filho(emit, "CNPJ")); add("Inscrição Estadual", _texto_filho(emit, "IE"))

    for titulo, parte in (("REMETENTE", rem), ("EXPEDIDOR", exped), ("RECEBEDOR", receb), ("DESTINATÁRIO", dest)):
        if parte is not None:
            sec(titulo)
            add("Nome", _texto_filho(parte, "xNome")); add("CNPJ/CPF", _texto_filho(parte, "CNPJ", "CPF"))

    toma3, toma4 = _filho(ide, "toma3"), _filho(ide, "toma4")
    papeis = {"0": "Remetente", "1": "Expedidor", "2": "Recebedor", "3": "Destinatário", "4": "Outros"}
    if toma3 is not None:
        cod = _texto_filho(toma3, "toma")
        parte = {"0": rem, "1": exped, "2": receb, "3": dest}.get(cod)
        sec("TOMADOR DO SERVIÇO")
        add("Papel", papeis.get(cod, cod)); add("Nome", _texto_filho(parte, "xNome")); add("CNPJ/CPF", _texto_filho(parte, "CNPJ", "CPF"))
    elif toma4 is not None:
        sec("TOMADOR DO SERVIÇO")
        add("Papel", "Outros"); add("Nome", _texto_filho(toma4, "xNome")); add("CNPJ/CPF", _texto_filho(toma4, "CNPJ", "CPF"))

    sec("VALORES")
    add("Valor Total da Prestação", _moeda_xml(_texto_filho(vprest, "vTPrest")))
    add("Valor a Receber", _moeda_xml(_texto_filho(vprest, "vRec")))
    comps = [f"{_texto_filho(c, 'xNome')}: {_moeda_xml(_texto_filho(c, 'vComp'))}" for c in (vprest if vprest is not None else []) if _nome_local(c) == "Comp"]
    if comps:
        add("Componentes", "\n".join(comps))
    add("Base de Cálculo do ICMS", _moeda_xml(_texto_xml(imp, "vBC")))
    add("Alíquota do ICMS (%)", _texto_xml(imp, "pICMS"))
    add("Valor do ICMS", _moeda_xml(_texto_xml(imp, "vICMS")))

    carga = _achar(inf, "infCarga")
    if carga is not None:
        sec("CARGA")
        add("Valor da Carga", _moeda_xml(_texto_filho(carga, "vCarga")))
        add("Produto Predominante", _texto_filho(carga, "proPred"))
        unidades = {"00": "m³", "01": "kg", "02": "ton", "03": "un", "04": "litros", "05": "MMBTU"}
        qtds = [f"{_texto_filho(q, 'tpMed') or 'Qtd.'}: {_texto_filho(q, 'qCarga')} {unidades.get(_texto_filho(q, 'cUnid'), '')}".strip() for q in carga if _nome_local(q) == "infQ"]
        if qtds:
            add("Quantidades", "\n".join(qtds))

    docs = _achar(inf, "infDoc")
    chaves = [_txt(c) for c in (docs.iter() if docs is not None else []) if _nome_local(c) == "chave" and _txt(c)]
    if chaves:
        sec(f"DOCUMENTOS TRANSPORTADOS ({len(chaves)})")
        for c in chaves[:30]:
            add("Chave", c)
        if len(chaves) > 30:
            add("...", f"(+{len(chaves) - 30} chaves; veja 'Ver Todos os Campos')")
    return r

def _resumo_nfse(raiz):
    inf = _achar(raiz, "infNFSe", "InfNfse", "InfNFSe")
    if inf is None:
        inf = raiz
    nacional = _nome_local(inf) == "infNFSe"
    r = []
    def sec(titulo): r.append((f"== {titulo} ==", ""))
    def add(campo, valor): r.append((campo, valor or ""))

    sec("NFS-e (PADRÃO NACIONAL)" if nacional else "NFS-e (PADRÃO ABRASF / MUNICIPAL)")
    add("Número", _texto_filho(inf, "nNFSe", "Numero", "NumeroNfse"))
    if nacional:
        add("Chave de Acesso", (inf.get("Id") or "").removeprefix("NFS"))
    add("Código de Verificação", _texto_filho(inf, "CodigoVerificacao"))
    add("Data de Emissão", _data_xml_br(_texto_xml(raiz, "DataEmissao", "dhEmi", "dhProc")))
    add("Competência", _data_xml_br(_texto_xml(raiz, "Competencia", "dCompet")))
    add("Natureza da Operação", _texto_xml(raiz, "NaturezaOperacao"))

    prest = _achar(raiz, "PrestadorServico", "Prestador", "emit")
    sec("PRESTADOR")
    add("Nome", _texto_xml(prest, "RazaoSocial", "xNome")); add("Nome Fantasia", _texto_xml(prest, "NomeFantasia", "xFant"))
    add("CNPJ", _texto_xml(prest, "Cnpj", "CNPJ")); add("Inscrição Municipal", _texto_xml(prest, "InscricaoMunicipal", "IM"))

    toma = _achar(raiz, "TomadorServico", "Tomador", "toma")
    sec("TOMADOR")
    add("Nome", _texto_xml(toma, "RazaoSocial", "xNome")); add("CNPJ/CPF", _texto_xml(toma, "Cnpj", "CNPJ", "Cpf", "CPF"))

    sec("SERVIÇO")
    add("Item da Lista / Cód. Tributação", _texto_xml(raiz, "ItemListaServico", "cTribNac"))
    add("CNAE", _texto_xml(raiz, "CodigoCnae", "CNAE"))
    add("Discriminação", _texto_xml(raiz, "Discriminacao", "xDescServ"))

    sec("VALORES")
    add("Valor dos Serviços", _moeda_xml(_texto_xml(raiz, "ValorServicos", "vServ")))
    add("Deduções", _moeda_xml(_texto_xml(raiz, "ValorDeducoes")))
    add("Base de Cálculo", _moeda_xml(_texto_xml(raiz, "BaseCalculo", "vBC")))
    add("Alíquota do ISS", _texto_xml(raiz, "Aliquota", "pAliqAplic", "pAliq"))
    add("Valor do ISS", _moeda_xml(_texto_xml(raiz, "ValorIss", "vISSQN")))
    retido = _texto_xml(raiz, "IssRetido")
    add("ISS Retido", {"1": "Sim", "2": "Não"}.get(retido, retido))
    add("Valor Líquido", _moeda_xml(_texto_xml(raiz, "ValorLiquidoNfse", "vLiq")))
    return r

def _todos_os_campos(raiz):
    campos = []
    def visitar(e, caminho):
        nome = _nome_local(e)
        if not nome or nome == "Signature" or len(campos) >= 3000:
            return
        atual = f"{caminho}/{nome}" if caminho else nome
        filhos = [f for f in e if isinstance(f.tag, str)]
        texto = (e.text or "").strip()
        if not filhos and texto:
            campos.append((atual, texto))
        for atributo, valor in e.attrib.items():
            campos.append((f"{atual}@{atributo.rsplit('}', 1)[-1]}", valor))
        for f in filhos:
            visitar(f, atual)
    visitar(raiz, "")
    return campos

# Tema escolhido nas Configurações (padrão: escuro). Não seguimos o tema do Windows para o app ficar sempre previsível.
ctk.set_appearance_mode(CONFIG["tema"])

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self._refrescar_tags = []  # funções que refazem as fontes das tags de texto quando o tamanho da fonte muda

        try:
            import ctypes
            myappid = 'vita.praticaon.central.1.0'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

        self.title("Central Vita & PráticaOn")
        self.geometry("660x660")
        self.configure(fg_color=COLOR_BG)

        # Ícone da janela: tenta o ícone embutido no executável e, se não achar,
        # usa o ícone gravado pelo instalador. Aplicado após 300 ms para o
        # CustomTkinter não sobrescrever com o ícone padrão (pena azul).
        def _aplicar_icone():
            # Procura o ícone ao lado do .py, ao lado do .exe, na pasta Icons do instalador e na pasta atual.
            pastas = []
            try:
                pastas.append(os.path.dirname(os.path.abspath(__file__)))
            except NameError:
                pass
            pastas.append(os.path.dirname(os.path.abspath(sys.argv[0])))
            pastas.append(os.path.dirname(os.path.abspath(sys.executable)))
            nomes_icone = ("Central Vita e PráticaOn.ico", "computador.ico")
            candidatos = [obter_caminho_recurso(n) for n in nomes_icone]
            for pasta in pastas:
                for sub in ("", "Icons"):
                    base_ico = os.path.join(pasta, sub) if sub else pasta
                    candidatos.extend(os.path.join(base_ico, n) for n in nomes_icone)
                    try:  # se o nome for outro, usa o primeiro .ico da pasta
                        candidatos.extend(os.path.join(base_ico, n) for n in sorted(os.listdir(base_ico)) if n.lower().endswith(".ico"))
                    except OSError:
                        pass
            candidatos.append(r"C:\Program Files\Vita Contabilidade & PráticaOn Contábil\Central Vita e PráticaOn\Icons\Central Vita e PráticaOn.ico")
            # Pasta de instalação atual (Program Files (x86)): usa computador.ico ou, se o nome for outro, o primeiro .ico que achar.
            for base in (os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), os.environ.get("ProgramFiles", r"C:\Program Files")):
                pasta_inst = os.path.join(base, "Fábio - Vita e PráticaOn", "Central Vita & PráticaOn")
                candidatos.append(os.path.join(pasta_inst, "computador.ico"))
                try:
                    candidatos.extend(os.path.join(pasta_inst, n) for n in sorted(os.listdir(pasta_inst)) if n.lower().endswith(".ico"))
                except OSError:
                    pass
            icone_embutido = _gravar_icone_embutido()
            if icone_embutido:
                candidatos.insert(0, icone_embutido)  # o ícone embutido tem prioridade
            # Registro de diagnóstico: mostra quais caminhos foram testados e qual funcionou (pasta de dados do app, icone_log.txt).
            registro = [f"executavel: {sys.executable}", f"argv0: {sys.argv[0]}", f"empacotado (PyInstaller): {getattr(sys, 'frozen', False)}"]
            try:
                for caminho in candidatos:
                    if not os.path.exists(caminho):
                        continue
                    try:
                        self.iconbitmap(caminho)
                        registro.append(f"OK: {caminho}")
                        return
                    except Exception as e:
                        registro.append(f"FALHOU: {caminho} -> {e}")
                registro.append("Nenhum ícone encontrado. Caminhos testados:")
                registro.extend("  " + c for c in candidatos)
            finally:
                try:
                    with open(os.path.join(PASTA_APPDATA, "icone_log.txt"), "w", encoding="utf-8") as f:
                        f.write("\n".join(registro))
                except Exception:
                    pass

        self.after(300, _aplicar_icone)

        # --- CONTAINER PRINCIPAL ---
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(expand=True, fill="both")

        # --- BOTÃO MENU HAMBÚRGUER ---
        self.btn_menu = ctk.CTkButton(
            self.main_container, text="☰", width=40, height=40,
            font=_f("Montserrat", 22), fg_color="transparent", text_color=COLOR_ACCENT,
            hover_color=COLOR_HOVER, command=self.toggle_sidebar
        )
        self.btn_menu.place(x=15, y=15)

        self.header_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.header_frame.pack(pady=(20, 15), fill="x", padx=60) 

        self.text_header_frame = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        self.text_header_frame.pack(anchor="center")
        
        # Wi-Fi / Boas-vindas
        self.lbl_welcome = ctk.CTkLabel(self.text_header_frame, text="Bem-vindo(a) à Central ", font=_f("Fraunces 9pt Black Italic", 26), text_color=COLOR_ACCENT)
        self.lbl_welcome.pack(side="left")

        # Link Vita
        self.lbl_vita_link = ctk.CTkLabel(self.text_header_frame, text="Vita", font=_f("Fraunces 9pt Black Italic", 24), text_color=COLOR_VITA_BLUE, cursor="hand2")
        self.lbl_vita_link.pack(side="left")
        self.lbl_vita_link.bind("<Button-1>", lambda e: webbrowser.open("http://www.vitacontabil.com.br/"))

        # Conectivo E e PráticaOn
        self.lbl_and = ctk.CTkLabel(self.text_header_frame, text=" & ", font=_f("Fraunces 9pt Black Italic", 24), text_color=COLOR_ACCENT)
        self.lbl_and.pack(side="left")
        self.lbl_pratica = ctk.CTkLabel(self.text_header_frame, text="PráticaOn", font=_f("Fraunces 9pt Black Italic", 24), text_color=COLOR_VITA_BLUE)
        self.lbl_pratica.pack(side="left")
        self.lbl_punct = ctk.CTkLabel(self.text_header_frame, text="!", font=_f("Fraunces 9pt Black Italic", 24), text_color=COLOR_ACCENT)
        self.lbl_punct.pack(side="left")

        # --- NAVEGAÇÃO CUSTOMIZADA E ABAS ---
        self.abas_disponiveis = [
            "👋 Bem-Vindo",
            "📝 Anotações", 
            "🔐 Gerenciador de Senhas",
            "🎨 Símbolos para Copiar", 
            "📄 Renomeação de PDFs", 
            "🧮 Calculadora Científica",
            "⏱️ Calculadora de Horas",
            "📅 Calculadora de Datas",
            "✂️ Unir e Separar PDFs",
            "🖼️ PDF ↔ JPG/PNG",
            "🔁 PNG ↔ JPG",
            "📊 XML/CSV para Excel (BETA)",
            "🧾 Leitor de NF-e (BETA)",
            "📉 Comprimir PDF (BETA)",
            "📑 Juntar Imagens em PDF (BETA)",
            "🔤 Contador de Caracteres",
            "💯 Calculadora de Percentuais",
            "📱 Gerador de QR Code",
            "📆 Prazos de Vencimento",
            "🏢 Consulta de CNPJ (BETA)",
            ABA_CEP,
            ABA_CNPJ_LOTE,
            ABA_EXTENSO,
            ABA_IMG_OTIM,
            ABA_CONFIG,
            "🔄 Editar Páginas de PDF (BETA)",
            "📜 Leitor de NFS-e/CT-e (BETA)",
            "🔑 Conferência de Chave (BETA)",
            "🔌 Desligamento Completo"
        ]
        self.aba_atual = "👋 Bem-Vindo"

        # Container para os conteúdos das abas
        self.content_container = ctk.CTkFrame(self.main_container, fg_color=COLOR_CARD, corner_radius=15)
        self.content_container.pack(expand=True, fill="both", padx=20, pady=(0, 10))

        # Dicionário de frames de conteúdo
        self.frames_conteudo = {}
        for nome_aba in self.abas_disponiveis:
            frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
            self.frames_conteudo[nome_aba] = frame

        # Inicialização das Abas
        self.setup_aba_bem_vindo()
        self.setup_aba_notas()
        self.setup_aba_senhas()
        self.setup_aba_contador()
        self.setup_aba_percentuais()
        self.setup_aba_comprimir_pdf()
        self.setup_aba_juntar_imagens()
        self.setup_aba_qrcode()
        self.setup_aba_renomeacao()
        self.setup_aba_simbolos()
        self.setup_aba_calculadora()
        self.setup_aba_horas()
        self.setup_aba_datas()
        self.setup_aba_pdf_tools()
        self.setup_aba_pdf_imagem()
        self.setup_aba_png_jpg()
        self.setup_aba_xml_csv_excel()
        self.setup_aba_nfe()
        self.setup_aba_nfse_cte()
        self.setup_aba_chave_nfe()
        self.setup_aba_prazos()
        self.setup_aba_cnpj()
        self.setup_aba_cep()
        self.setup_aba_cnpj_lote()
        self.setup_aba_extenso()
        self.setup_aba_imagens_otimizar()
        self.setup_aba_config()
        if CONFIG["verificar_atualizacoes"]:
            self.after(3000, lambda: self.verificar_atualizacao(silencioso=True))
        self.setup_aba_paginas_pdf()
        self.setup_aba_desligamento()

        self.selecionar_aba(self.aba_atual)

        # --- FOOTER ---
        self.footer_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.footer_frame.pack(side="bottom", fill="x", pady=(5, 18), padx=20)
        self.footer = ctk.CTkLabel(self.footer_frame, text="© Fábio, Gemini e Claude | Vita Contabilidade & PráticaOn Contábil", font=_f("Montserrat", 12, "bold"), text_color=_C("#333333"))
        self.footer.pack(anchor="center")

        # --- BOTÃO "?" ---
        self.btn_sobre = ctk.CTkLabel(self, text="?", font=_f("Montserrat", 18, "bold"), text_color=_C("#FFFFFF"), cursor="hand2")
        self.btn_sobre.place(relx=1.0, rely=0.0, x=-30, y=25, anchor="ne")
        self.btn_sobre.bind("<Enter>", lambda e: self.btn_sobre.configure(text_color=_C("#808080")))
        self.btn_sobre.bind("<Leave>", lambda e: self.btn_sobre.configure(text_color=_C("#FFFFFF")))
        self.btn_sobre.bind("<Button-1>", lambda e: self.mostrar_overlay_sobre())

        self.overlay_frame = None

        # --- SIDEBAR (MENU) ---
        # O frame externo continua fixo (não rola) e é só quem tem a borda e o botão de
        # fechar, sempre visível no topo. Todo o conteúdo (título + grupos de botões) fica
        # dentro de um CTkScrollableFrame interno, que ganha uma barra de rolagem sozinho
        # quando os itens não cabem na altura da tela -- foi isso que resolvia não dar
        # pra descer e ver as últimas funções do menu.
        self.sidebar_frame = ctk.CTkFrame(self, width=340, corner_radius=0, fg_color=_C("#121212"), border_width=1, border_color=_C("#2D2D2D"))
        self.sidebar_visible = False

        # Botão Fechar colocado exatamente sobre o botão hambúrguer
        self.btn_close_sidebar = ctk.CTkButton(
            self.sidebar_frame, text="✖", width=40, height=40, 
            font=_f("Montserrat", 16), fg_color="transparent", text_color=COLOR_ACCENT, 
            hover_color=COLOR_DANGER, command=self.toggle_sidebar
        )
        self.btn_close_sidebar.place(x=15, y=15)

        # LARGURA_ITEM_MENU: usada tanto no CTkScrollableFrame quanto em cada botão/item.
        # O CustomTkinter não redimensiona sozinho a largura "de desenho" desses widgets
        # (ela fica presa no padrão da biblioteca -- 200px no scrollable frame, 140px no
        # botão -- mesmo que o "pack(fill='x')" estique fisicamente o widget). Por isso
        # alargar só o sidebar_frame não bastava: era preciso dizer explicitamente a
        # largura de cada um deles.
        LARGURA_ITEM_MENU = 300

        self.sidebar_scroll = ctk.CTkScrollableFrame(self.sidebar_frame, width=LARGURA_ITEM_MENU, fg_color="transparent", corner_radius=0)
        self.sidebar_scroll.pack(fill="both", expand=True, padx=0, pady=(60, 10))

        ctk.CTkLabel(self.sidebar_scroll, text="Menu de Funções", font=_f("Fraunces 9pt Black Italic", 24), text_color=COLOR_HOVER_WHITE).pack(pady=(5, 20))

        # Ícones "problemáticos" que o Tk insiste em desenhar com uma fonte de texto
        # simples em vez do emoji colorido, criando aquele espaço enorme entre o ícone
        # e o nome (mesmo caso da tesourinha "✂️"). Para esses, separamos o ícone do
        # texto em dois labels, cada um na sua fonte, e juntamos como se fosse um botão só.
        ICONES_EMOJI_SEPARADO = ("✂️ Unir e Separar PDFs", "🖼️ PDF ↔ JPG/PNG")

        def _adicionar_item_sidebar(nome_aba):
            if nome_aba in ICONES_EMOJI_SEPARADO:
                icone, texto = nome_aba.split(" ", 1)

                item_aba = ctk.CTkFrame(self.sidebar_scroll, fg_color="transparent", width=LARGURA_ITEM_MENU, height=40)
                item_aba.pack(fill="x", padx=15, pady=2)
                item_aba.pack_propagate(False)

                lbl_icone = ctk.CTkLabel(item_aba, text=icone, font=_f("Segoe UI Emoji", 14), text_color=COLOR_ACCENT)
                lbl_icone.pack(side="left", padx=(10, 6))
                lbl_texto = ctk.CTkLabel(item_aba, text=texto, font=_f("Montserrat", 14, "bold"), text_color=COLOR_ACCENT, anchor="w")
                lbl_texto.pack(side="left", fill="x", expand=True)

                def _abrir_item(event=None, n=nome_aba):
                    self.selecionar_aba_sidebar(n)

                for widget in (item_aba, lbl_icone, lbl_texto):
                    widget.configure(cursor="hand2")
                    widget.bind("<Button-1>", _abrir_item)
                    widget.bind("<Enter>", lambda e, f=item_aba: f.configure(fg_color=COLOR_HOVER))
                    widget.bind("<Leave>", lambda e, f=item_aba: f.configure(fg_color="transparent"))
            else:
                btn = ctk.CTkButton(self.sidebar_scroll, text=nome_aba, anchor="w", width=LARGURA_ITEM_MENU, height=40, fg_color="transparent", hover_color=COLOR_HOVER, text_color=COLOR_ACCENT, font=_f("Montserrat", 14, "bold"), command=lambda n=nome_aba: self.selecionar_aba_sidebar(n))
                btn.pack(fill="x", padx=15, pady=2)

        # Item avulso (fora de qualquer grupo) -- continua acessível como antes.
        _adicionar_item_sidebar("👋 Bem-Vindo")

        # Agrupamento das demais abas por categoria, conforme solicitado.
        self.grupos_menu = [
            ("Utilitários", ["📝 Anotações", "🔐 Gerenciador de Senhas", "🔤 Contador de Caracteres", "📆 Prazos de Vencimento", "🎨 Símbolos para Copiar"]),
            ("Automatizadores", ["📄 Renomeação de PDFs", "📱 Gerador de QR Code", "🏢 Consulta de CNPJ (BETA)", ABA_CEP, ABA_CNPJ_LOTE, ABA_EXTENSO]),
            ("Calculadoras", ["🧮 Calculadora Científica", "💯 Calculadora de Percentuais", "⏱️ Calculadora de Horas", "📅 Calculadora de Datas"]),
            ("Arquivos", ["✂️ Unir e Separar PDFs", "📉 Comprimir PDF (BETA)", "📑 Juntar Imagens em PDF (BETA)", "🔄 Editar Páginas de PDF (BETA)", "🖼️ PDF ↔ JPG/PNG", "🔁 PNG ↔ JPG", "📊 XML/CSV para Excel (BETA)", ABA_IMG_OTIM]),
            ("Fiscal", ["🧾 Leitor de NF-e (BETA)", "📜 Leitor de NFS-e/CT-e (BETA)", "🔑 Conferência de Chave (BETA)"]),
            ("Sistema", [ABA_CONFIG, "🔌 Desligamento Completo"]),
        ]

        for nome_grupo, itens_grupo in self.grupos_menu:
            ctk.CTkLabel(self.sidebar_scroll, text=nome_grupo.upper(), font=_f("Montserrat", 10, "bold"), text_color=COLOR_SUBTITLE).pack(anchor="w", padx=25, pady=(14, 4))
            for nome_aba in itens_grupo:
                _adicionar_item_sidebar(nome_aba)

    def toggle_sidebar(self):
        if self.sidebar_visible:
            self.sidebar_frame.place_forget()
            self.sidebar_visible = False
        else:
            self.sidebar_frame.place(x=0, y=0, relheight=1.0)
            self.sidebar_frame.tkraise()
            self.sidebar_visible = True

    def selecionar_aba_sidebar(self, nome_aba):
        self.selecionar_aba(nome_aba)
        self.toggle_sidebar()

    def selecionar_aba(self, nome_aba):
        self.aba_atual = nome_aba
        # Oculta todos os frames
        for frame in self.frames_conteudo.values():
            frame.pack_forget()
        # Mostra o frame selecionado
        self.frames_conteudo[nome_aba].pack(expand=True, fill="both", padx=10, pady=10)

    # ================= MÓDULO 0: BEM-VINDO =================
    def setup_aba_bem_vindo(self):
        aba = self.frames_conteudo["👋 Bem-Vindo"]

        cartao = ctk.CTkFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        cartao.pack(expand=True, fill="both")

        FONTE_BEMVINDO = ("Montserrat", 14)
        texto_bv = ctk.CTkTextbox(cartao, fg_color="transparent", text_color=_C("#FFFFFF"), font=_f(*FONTE_BEMVINDO), border_width=0, wrap="word")
        texto_bv.pack(expand=True, fill="both", padx=30, pady=25)

        # CTkTextbox.tag_config() bloqueia a opção "font" (ver nota na aba de Anotações),
        # então aplicamos a tag de negrito direto no tkinter.Text interno, já escalada.
        def _tags_bem_vindo():
            _fonte_negrito = texto_bv._apply_font_scaling((FONTE_BEMVINDO[0], max(7, round(FONTE_BEMVINDO[1] * ESCALA_FONTE)), "bold"))
            texto_bv._textbox.tag_config("negrito_bv", font=_fonte_negrito)
        _tags_bem_vindo()
        self._refrescar_tags.append(_tags_bem_vindo)

        def inserir(trecho, negrito=False):
            texto_bv.insert("end", trecho, "negrito_bv" if negrito else None)

        inserir("Bem-vindo(a) à ")
        inserir("Central de Automação da Vita & PráticaOn Contábil", negrito=True)
        inserir(".\n\n")
        inserir(
            "Este app foi criado no intuito de facilitar a rotina pesada de nossos "
            "colaboradores. No momento, ele conta com algumas funcionalidades como:\n\n"
        )
        for item in [
            "Anotações;",
            "Contador de caracteres e palavras;",
            "Prazos de vencimento;",
            "Gerenciador de Senhas;",
            "Símbolos diversos para copiá-los e colá-los;",
            "Renomeação de PDFs (para o Setor de RH);",
            "Calculadora Científica;",
            "Calculadora de Percentuais;",
            "Calculadora de Horas;",
            "Calculadora de Datas;",
            "Ferramenta que une e/ou separa PDFs;",
            "Ferramenta que comprime PDFs (BETA);",
            "Ferramenta que junta imagens em um PDF (BETA);",
            "Gerador de QR Code;",
            "Consulta de CNPJ (BETA);",
            "Consulta de CEP (BETA);",
            "Conferência de CNPJ em lote;",
            "Conversor de número para extenso;",
            "Ferramenta que redimensiona e comprime imagens (BETA);",
            "Configurações com tema claro/escuro e tamanho da fonte;",
            "Verificador de atualizações do app;",
            "Ferramenta que gira, extrai e exclui páginas de PDF (BETA);",
            "Conferência de chave de acesso de NF-e (BETA);",
            "Leitor de XML de NFS-e e CT-e (BETA);",
            "Ferramenta que faz o desligamento completo do PC.",
        ]:
            inserir(f"• {item}\n", negrito=True)
        inserir("\n")
        inserir("Caso você, usuário, tenha alguma dúvida, reclamação ou sugestão: Clique no botão ")
        inserir("'?'", negrito=True)
        inserir(
            " que pode ser encontrado no canto superior direito do app, clique no meu "
            "e-mail para copiá-lo e me envie uma mensagem que farei o que for possível "
            "para tornar essa experiência ainda melhor.\n\n"
        )
        inserir("Atenciosamente,\nFábio.", negrito=True)

        texto_bv.configure(state="disabled")

    # ================= MÓDULO 1: ANOTAÇÕES =================
    def carregar_dados_notas(self):
        if os.path.exists(ARQUIVO_NOTAS):
            try:
                with open(ARQUIVO_NOTAS, "r", encoding="utf-8") as f:
                    self.notas_data = json.load(f)
            except Exception:
                self.notas_data = {}
        else:
            self.notas_data = {}

    def salvar_dados_notas(self):
        try:
            with open(ARQUIVO_NOTAS, "w", encoding="utf-8") as f:
                json.dump(self.notas_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao salvar arquivo de dados: {e}")

    def setup_aba_notas(self):
        aba = self.frames_conteudo["📝 Anotações"]
        self.notas_data = {}
        self.nota_atual_id = None
        self._after_salvo_nota = None
        self.botoes_notas = {}
        
        self.carregar_dados_notas()

        self.notas_paned = ctk.CTkFrame(aba, fg_color="transparent")
        self.notas_paned.pack(expand=True, fill="both", padx=0, pady=0)

        self.notas_sidebar = ctk.CTkFrame(self.notas_paned, width=180, fg_color=_C("#121212"), corner_radius=12)
        self.notas_sidebar.pack(side="left", fill="y", padx=(0, 10))
        self.notas_sidebar.pack_propagate(False)

        self.btn_nova_nota = ctk.CTkButton(self.notas_sidebar, text="+ Nova Anotação", command=self.criar_nova_nota, fg_color=COLOR_VITA_BLUE, font=_f("Montserrat", 12, "bold"))
        self.btn_nova_nota.pack(pady=15, padx=10, fill="x")

        self.btn_local_salvamento = ctk.CTkLabel(self.notas_sidebar, text="Onde é salvo?", font=_f("Montserrat", 11, "bold", "italic"), text_color=COLOR_SUBTITLE, cursor="hand2")
        self.btn_local_salvamento.pack(side="bottom", pady=15)
        self.btn_local_salvamento.bind("<Enter>", lambda e: self.btn_local_salvamento.configure(text_color=COLOR_ACCENT))
        self.btn_local_salvamento.bind("<Leave>", lambda e: self.btn_local_salvamento.configure(text_color=COLOR_SUBTITLE))
        self.btn_local_salvamento.bind("<Button-1>", lambda e: self.mostrar_overlay_local_salvamento())

        self.scroll_lista_notas = ctk.CTkScrollableFrame(self.notas_sidebar, fg_color="transparent")
        self.scroll_lista_notas.pack(expand=True, fill="both", padx=5, pady=(0, 0))

        self.notas_editor = ctk.CTkFrame(self.notas_paned, fg_color=_C("#262626"), corner_radius=12)
        self.notas_editor.pack(side="left", expand=True, fill="both")

        self.editor_header = ctk.CTkFrame(self.notas_editor, fg_color="transparent")
        self.editor_header.pack(fill="x", padx=15, pady=(15, 10))

        self.entry_titulo_nota = ctk.CTkEntry(self.editor_header, font=_f("Montserrat", 16, "bold"), fg_color=_C("#1A1A1A"), border_width=0, placeholder_text="Título da Anotação")
        self.entry_titulo_nota.pack(side="left", expand=True, fill="x", padx=(0, 10))

        self.btn_excluir_nota = ctk.CTkButton(self.editor_header, text="Excluir", width=60, fg_color=COLOR_DANGER, hover_color=_C("#AA0000"), text_color=_C("#FFFFFF"), font=_f("Montserrat", 12, "bold"), command=self.excluir_nota_atual)
        self.btn_excluir_nota.pack(side="right")

        FONTE_NOTA = ("Montserrat", 13)
        self.textbox_conteudo_nota = ctk.CTkTextbox(self.notas_editor, fg_color=_C("#1A1A1A"), text_color=_C("#FFFFFF"), font=_f(*FONTE_NOTA), border_width=0, wrap="word")
        self.textbox_conteudo_nota.pack(expand=True, fill="both", padx=15, pady=(0, 10))

        # --- Tags de formatação de texto (negrito, itálico, sublinhado e caixinha de afazeres) ---
        # OBS: CTkTextbox.tag_config() bloqueia a opção "font" de propósito (por causa do
        # escalonamento por DPI do CustomTkinter). Por isso aplicamos as tags direto no
        # tkinter.Text interno (self.textbox_conteudo_nota._textbox), já escalando a fonte
        # manualmente com o mesmo método que o próprio CTkTextbox usa internamente.
        def _fonte_escalada(*estilos):
            return self.textbox_conteudo_nota._apply_font_scaling((FONTE_NOTA[0], max(7, round(FONTE_NOTA[1] * ESCALA_FONTE))) + estilos)

        _text_interno = self.textbox_conteudo_nota._textbox

        def _tags_notas():
            _text_interno.tag_config("negrito", font=_fonte_escalada("bold"))
            _text_interno.tag_config("italico", font=_fonte_escalada("italic"))
            _text_interno.tag_config("negrito_italico", font=_fonte_escalada("bold", "italic"))
            _text_interno.tag_config("checkbox", font=_fonte_escalada("bold"))
            _text_interno.tag_config("checkbox_icone", font=self.textbox_conteudo_nota._apply_font_scaling((FONTE_ICONES, max(7, round((FONTE_NOTA[1] + 2) * ESCALA_FONTE)))))
        _tags_notas()
        self._refrescar_tags.append(_tags_notas)
        self.textbox_conteudo_nota.tag_config("sublinhado", underline=True)
        self.textbox_conteudo_nota.bind("<Button-1>", self._clique_checkbox)

        # --- Barra de formatação (rodapé da área de escrita) ---
        self.editor_toolbar = ctk.CTkFrame(self.notas_editor, fg_color="transparent")
        self.editor_toolbar.pack(fill="x", padx=15, pady=(0, 10))

        def _criar_botao_formatacao(texto, comando, fonte, largura=36):
            botao = ctk.CTkButton(self.editor_toolbar, text=texto, width=largura, height=32, fg_color=_C("#1A1A1A"), hover_color=COLOR_HOVER, text_color=COLOR_ACCENT, font=fonte, corner_radius=8, command=comando)
            botao.pack(side="left", padx=(0, 6))
            return botao

        self.botoes_formatacao_toolbar = [
            _criar_botao_formatacao("B", self.alternar_negrito, _f("Montserrat", 14, "bold")),
            _criar_botao_formatacao("I", self.alternar_italico, _f("Montserrat", 14, "bold", "italic")),
            _criar_botao_formatacao("S", self.alternar_sublinhado, _f("Montserrat", 14, "bold", "underline")),
            _criar_botao_formatacao("•", self.alternar_lista_marcadores, _f("Montserrat", 16, "bold")),
            _criar_botao_formatacao("1.", self.alternar_lista_numerada, _f("Montserrat", 12, "bold")),
            _criar_botao_formatacao(CHECKBOX_MARCADO, self.alternar_lista_afazeres, _f(FONTE_ICONES, 15), largura=40),
        ]

        self.btn_salvar_nota = ctk.CTkButton(self.notas_editor, text="Salvar Anotação", command=self.salvar_nota_atual, fg_color=COLOR_VITA_BLUE, font=_f("Montserrat", 12, "bold"), height=40)
        self.btn_salvar_nota.pack(fill="x", padx=15, pady=(0, 15))

        self.atualizar_lista_notas()
        self.limpar_editor() 

    def criar_nova_nota(self):
        if self.nota_atual_id: self.salvar_nota_atual(silencioso=True)
        novo_id = str(uuid.uuid4())
        self.notas_data[novo_id] = {"titulo": "Nova Anotação", "conteudo": ""}
        self.salvar_dados_notas()
        self.atualizar_lista_notas()
        self.abrir_nota(novo_id)

    def atualizar_lista_notas(self):
        for btn in self.botoes_notas.values(): btn.destroy()
        self.botoes_notas = {}
        for nota_id, dados in self.notas_data.items():
            cor_fundo = COLOR_HOVER if nota_id == self.nota_atual_id else "transparent"
            btn = ctk.CTkButton(self.scroll_lista_notas, text=dados["titulo"], anchor="w", fg_color=cor_fundo, text_color=COLOR_ACCENT, hover_color=COLOR_HOVER, command=lambda id=nota_id: self.abrir_nota(id))
            btn.pack(fill="x", pady=2)
            self.botoes_notas[nota_id] = btn

    def abrir_nota(self, nota_id):
        if self.nota_atual_id and self.nota_atual_id != nota_id: self.salvar_nota_atual(silencioso=True)
        self.nota_atual_id = nota_id
        dados = self.notas_data[nota_id]
        
        self.entry_titulo_nota.configure(state="normal")
        self.entry_titulo_nota.delete(0, tk.END)
        self.entry_titulo_nota.insert(0, dados["titulo"])
        
        self.textbox_conteudo_nota.configure(state="normal")
        self.textbox_conteudo_nota.delete("1.0", tk.END)
        self._aplicar_texto_com_marcacao(dados["conteudo"])
        
        self.btn_excluir_nota.configure(state="normal")
        self.btn_salvar_nota.configure(state="normal")
        for botao in self.botoes_formatacao_toolbar:
            botao.configure(state="normal")
        self.atualizar_lista_notas()

    def salvar_nota_atual(self, silencioso=False):
        if not self.nota_atual_id: return
        novo_titulo = self.entry_titulo_nota.get().strip() or "Sem Título"
        novo_conteudo = self._texto_com_marcacao()
        self.notas_data[self.nota_atual_id]["titulo"] = novo_titulo
        self.notas_data[self.nota_atual_id]["conteudo"] = novo_conteudo
        self.salvar_dados_notas()
        self.atualizar_lista_notas()
        if not silencioso:
            # O texto original é fixo: antes ele era lido do botão, e um 2º clique dentro dos 2 s
            # "memorizava" o texto "Salvo!" como se fosse o original (e o botão ficava assim para sempre).
            self.btn_salvar_nota.configure(text="Salvo!", fg_color=_C("#00FF66"))
            if self._after_salvo_nota:
                self.after_cancel(self._after_salvo_nota)
            self._after_salvo_nota = self.after(2000, lambda: self.btn_salvar_nota.configure(text="Salvar Anotação", fg_color=COLOR_VITA_BLUE))

    def excluir_nota_atual(self):
        if not self.nota_atual_id: return
        if messagebox.askyesno("Confirmar", "Tem certeza que deseja excluir esta anotação permanentemente?"):
            del self.notas_data[self.nota_atual_id]
            self.salvar_dados_notas()
            self.limpar_editor()
            self.atualizar_lista_notas()

    def limpar_editor(self):
        self.nota_atual_id = None
        self.entry_titulo_nota.delete(0, tk.END)
        self.entry_titulo_nota.configure(state="disabled")
        self.textbox_conteudo_nota.delete("1.0", tk.END)
        self.textbox_conteudo_nota.configure(state="disabled")
        self.btn_excluir_nota.configure(state="disabled")
        self.btn_salvar_nota.configure(state="disabled")
        for botao in self.botoes_formatacao_toolbar:
            botao.configure(state="disabled")

    # ---------- Formatação de texto (negrito, itálico, sublinhado) ----------
    def _selecao_atual(self):
        tb = self.textbox_conteudo_nota
        try:
            return tb.index("sel.first"), tb.index("sel.last")
        except tk.TclError:
            return None, None

    def _estado_ativo_em(self, idx):
        tags = self.textbox_conteudo_nota.tag_names(idx)
        negrito = "negrito" in tags or "negrito_italico" in tags
        italico = "italico" in tags or "negrito_italico" in tags
        sublinhado = "sublinhado" in tags
        return negrito, italico, sublinhado

    def _selecao_totalmente_ativa(self, inicio, fim, checar):
        tb = self.textbox_conteudo_nota
        idx = inicio
        while tb.compare(idx, "<", fim):
            if not checar(idx):
                return False
            idx = tb.index(f"{idx}+1c")
        return True

    def _alternar_estilo_fonte(self, alvo):
        tb = self.textbox_conteudo_nota
        inicio, fim = self._selecao_atual()
        if inicio is None:
            messagebox.showinfo("Formatação", "Selecione o texto que deseja formatar.")
            return

        def checar(idx):
            negrito, italico, _ = self._estado_ativo_em(idx)
            return negrito if alvo == "negrito" else italico

        ligar = not self._selecao_totalmente_ativa(inicio, fim, checar)
        idx = inicio
        while tb.compare(idx, "<", fim):
            negrito, italico, _ = self._estado_ativo_em(idx)
            if alvo == "negrito":
                negrito = ligar
            else:
                italico = ligar
            prox = tb.index(f"{idx}+1c")
            for t in ("negrito", "italico", "negrito_italico"):
                tb.tag_remove(t, idx, prox)
            if negrito and italico:
                tb.tag_add("negrito_italico", idx, prox)
            elif negrito:
                tb.tag_add("negrito", idx, prox)
            elif italico:
                tb.tag_add("italico", idx, prox)
            idx = prox
        tb.focus_set()

    def alternar_negrito(self):
        self._alternar_estilo_fonte("negrito")

    def alternar_italico(self):
        self._alternar_estilo_fonte("italico")

    def alternar_sublinhado(self):
        tb = self.textbox_conteudo_nota
        inicio, fim = self._selecao_atual()
        if inicio is None:
            messagebox.showinfo("Formatação", "Selecione o texto que deseja formatar.")
            return
        ligar = not self._selecao_totalmente_ativa(inicio, fim, lambda idx: self._estado_ativo_em(idx)[2])
        if ligar:
            tb.tag_add("sublinhado", inicio, fim)
        else:
            tb.tag_remove("sublinhado", inicio, fim)
        tb.focus_set()

    # ---------- Listas (marcadores, numerada e de afazeres) ----------
    def _linhas_selecionadas(self):
        tb = self.textbox_conteudo_nota
        try:
            inicio = tb.index("sel.first linestart")
            fim = tb.index("sel.last linestart")
        except tk.TclError:
            inicio = tb.index("insert linestart")
            fim = inicio
        linhas = []
        linha_atual = inicio
        while True:
            linhas.append(linha_atual)
            if tb.compare(linha_atual, ">=", fim):
                break
            proxima = tb.index(f"{linha_atual} +1 line linestart")
            if tb.compare(proxima, "==", linha_atual):
                break
            linha_atual = proxima
        return linhas

    def alternar_lista_marcadores(self):
        tb = self.textbox_conteudo_nota
        linhas = self._linhas_selecionadas()
        if not linhas:
            return
        todas_tem = all(tb.get(l, f"{l} lineend").startswith("• ") for l in linhas)
        for l in linhas:
            texto = tb.get(l, f"{l} lineend")
            if todas_tem and texto.startswith("• "):
                tb.delete(l, f"{l}+2c")
            elif not todas_tem and not texto.startswith("• "):
                tb.insert(l, "• ")
        tb.focus_set()

    def alternar_lista_numerada(self):
        tb = self.textbox_conteudo_nota
        linhas = self._linhas_selecionadas()
        if not linhas:
            return
        padrao_num = re.compile(r"^\d+\.\s")
        todas_tem = all(padrao_num.match(tb.get(l, f"{l} lineend")) for l in linhas)
        if todas_tem:
            for l in linhas:
                m = padrao_num.match(tb.get(l, f"{l} lineend"))
                if m:
                    tb.delete(l, f"{l}+{m.end()}c")
        else:
            n = 1
            for l in linhas:
                if not padrao_num.match(tb.get(l, f"{l} lineend")):
                    tb.insert(l, f"{n}. ")
                n += 1
        tb.focus_set()

    def alternar_lista_afazeres(self):
        tb = self.textbox_conteudo_nota
        linhas = self._linhas_selecionadas()
        if not linhas:
            return

        def tem_checkbox(l):
            return tb.get(l, f"{l}+1c") in (CHECKBOX_VAZIO, CHECKBOX_MARCADO)

        todas_tem = all(tem_checkbox(l) for l in linhas)
        tamanho_prefixo = 1 + len(SEPARADOR_CHECKBOX)
        for l in linhas:
            if todas_tem and tem_checkbox(l):
                tb.delete(l, f"{l}+{tamanho_prefixo}c")
            elif not todas_tem and not tem_checkbox(l):
                tb.insert(l, SEPARADOR_CHECKBOX)
                tb.insert(l, CHECKBOX_VAZIO, ("checkbox", "checkbox_icone"))
        tb.focus_set()

    def _clique_checkbox(self, event):
        tb = self.textbox_conteudo_nota
        try:
            idx = tb.index(f"@{event.x},{event.y}")
        except tk.TclError:
            return
        if "checkbox" not in tb.tag_names(idx):
            return
        char_atual = tb.get(idx, f"{idx}+1c")
        tb.delete(idx, f"{idx}+1c")
        novo_char = CHECKBOX_MARCADO if char_atual == CHECKBOX_VAZIO else CHECKBOX_VAZIO
        tb.insert(idx, novo_char, ("checkbox", "checkbox_icone"))

    # ---------- Persistência da formatação (a nota é salva como texto simples com marcação) ----------
    def _delimitadores_transicao(self, antigo, novo):
        delimitadores = ("**", "*", "__")
        ponto = 0
        while ponto < 3 and antigo[ponto] == novo[ponto]:
            ponto += 1
        if ponto == 3:
            return ""
        saida = ""
        for i in range(2, ponto - 1, -1):
            if antigo[i]:
                saida += delimitadores[i]
        for i in range(ponto, 3):
            if novo[i]:
                saida += delimitadores[i]
        return saida

    def _texto_com_marcacao(self):
        tb = self.textbox_conteudo_nota
        fim_idx = tb.index("end-1c")
        resultado = []
        estado_atual = (False, False, False)
        idx = "1.0"
        while tb.compare(idx, "<", fim_idx):
            prox = tb.index(f"{idx}+1c")
            novo_estado = self._estado_ativo_em(idx)
            if novo_estado != estado_atual:
                resultado.append(self._delimitadores_transicao(estado_atual, novo_estado))
                estado_atual = novo_estado
            resultado.append(tb.get(idx, prox))
            idx = prox
        resultado.append(self._delimitadores_transicao(estado_atual, (False, False, False)))
        return "".join(resultado)

    def _aplicar_texto_com_marcacao(self, texto):
        tb = self.textbox_conteudo_nota
        padrao = re.compile(r'(\*\*\*|\*\*|\*|__)')
        negrito = italico = sublinhado = False
        for parte in padrao.split(texto):
            if not parte:
                continue
            if parte == "***":
                negrito, italico = not negrito, not italico
            elif parte == "**":
                negrito = not negrito
            elif parte == "*":
                italico = not italico
            elif parte == "__":
                sublinhado = not sublinhado
            else:
                tags = []
                if negrito and italico:
                    tags.append("negrito_italico")
                elif negrito:
                    tags.append("negrito")
                elif italico:
                    tags.append("italico")
                if sublinhado:
                    tags.append("sublinhado")
                tb.insert("end", parte, tuple(tags) if tags else None)
        # Garante que qualquer caixinha de afazeres já existente no texto continue
        # clicável (e que os dois estados continuem usando o ícone da Font Awesome)
        conteudo = tb.get("1.0", "end-1c")
        for i, ch in enumerate(conteudo):
            if ch in (CHECKBOX_VAZIO, CHECKBOX_MARCADO):
                tb.tag_add("checkbox", f"1.0+{i}c", f"1.0+{i+1}c")
                tb.tag_add("checkbox_icone", f"1.0+{i}c", f"1.0+{i+1}c")

    # ================= MÓDULO 2: RENOMEAÇÃO =================
    def setup_aba_renomeacao(self):
        aba = self.frames_conteudo["📄 Renomeação de PDFs"]
        self.dir_card = ctk.CTkFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        self.dir_card.pack(pady=(0, 15), padx=0, fill="x")
        
        self.entry_caminho = ctk.CTkEntry(self.dir_card, placeholder_text="Onde estão os arquivos?", height=35, border_width=0, fg_color=_C("#1A1A1A"))
        self.entry_caminho.pack(side="left", padx=(15, 10), pady=10, expand=True, fill="x")

        self.btn_procurar = ctk.CTkButton(self.dir_card, text="Explorar", width=80, height=35, command=self.selecionar_pasta, fg_color=COLOR_ACCENT, hover_color=COLOR_HOVER_WHITE, text_color=COLOR_BG, font=_f("Montserrat", 11, "bold"))
        self.btn_procurar.pack(side="right", padx=(0, 15), pady=10)

        self.scroll_ren = ctk.CTkScrollableFrame(aba, fg_color="transparent")
        self.scroll_ren.pack(expand=True, fill="both")

        self.criar_secao_ren(self.scroll_ren, "Remuneração e Folha", [
            ("Recibo de Pagamento", "bot_pagamento_mensal"),
            ("Recibo de Pró-Labore", "bot_pro_labore"),
            ("Relatório de Líquidos", "bot_relacao_liquidos"),
            ("Extrato Mensal", "bot_extrato_mensal"),
        ])
        self.criar_secao_ren(self.scroll_ren, "Férias e Adiantamentos", [
            ("Programação de Férias", "bot_programacao_ferias"),
            ("Recibo de Adiantamento", "bot_adiantamento"),
        ])
        self.criar_secao_ren(self.scroll_ren, "Encargos e Impostos", [
            ("Guia de INSS", "bot_inss"),
            ("Guia de FGTS", "bot_fgts"),
            ("Guia de DCTFWeb", "bot_dctfweb"),
        ])
        self.criar_secao_ren(self.scroll_ren, "Rescisões e Desligamentos", [
            ("Termo de Rescisão", "bot_termo_rescisao"),
            ("Termo de Quitação", "bot_termo_quitacao"),
        ])

    def criar_secao_ren(self, master, titulo, botoes):
        label = ctk.CTkLabel(master, text=titulo.upper(), font=_f("Montserrat", 10, "bold"), text_color=COLOR_SUBTITLE)
        label.pack(anchor="w", padx=5, pady=(10, 5))
        for texto, func in botoes:
            btn = ctk.CTkButton(master, text=f"  {texto}", command=getattr(self, func), height=40, fg_color=_C("#262626"), text_color=_C("#D1D1D1"), hover_color=COLOR_HOVER, anchor="w", font=_f("Montserrat", 11), corner_radius=8)
            btn.pack(fill="x", pady=2, padx=0)

    def selecionar_pasta(self):
        caminho = filedialog.askdirectory()
        if caminho:
            self.entry_caminho.delete(0, tk.END)
            self.entry_caminho.insert(0, caminho)

    def aplicar_renomeacao(self, tipo_documento, sufixo=None, padrao_nome=None):
        pasta = self.entry_caminho.get().strip()
        if not pasta or not os.path.exists(pasta):
            messagebox.showwarning("Aviso", "Por favor, selecione uma pasta válida primeiro.")
            return
        
        arquivos = [f for f in os.listdir(pasta) if f.lower().endswith('.pdf')]
        if not arquivos:
            messagebox.showinfo("Informação", "Nenhum arquivo PDF encontrado na pasta selecionada.")
            return

        arquivos_renomeados = 0
        for arquivo in arquivos:
            caminho_antigo = os.path.join(pasta, arquivo)
            nome_sem_ext = os.path.splitext(arquivo)[0]
            if padrao_nome and not padrao_nome.match(_normalizar_nome_arquivo(nome_sem_ext)):
                continue  # não pertence a este botão: não mexe

            if sufixo:
                novo_nome = f"{nome_sem_ext} - {sufixo}.pdf"
            elif tipo_documento == "PROGRAMAÇÃO DE FÉRIAS":
                match_ferias = re.search(r'^(.*?)\s*-\s*Programa[cç][aã]o\s*(?:de)?\s*F[eé]rias', nome_sem_ext, re.IGNORECASE)
                if match_ferias:
                    prefixo = match_ferias.group(1).strip()
                    if prefixo.endswith("-"):
                        prefixo = prefixo[:-1].strip()
                    novo_nome = f"{prefixo} - {tipo_documento}.pdf" if prefixo else f"{tipo_documento}.pdf"
                else:
                    match = re.match(r'^(\d+)\s*-\s*', arquivo)
                    prefixo = f"{match.group(1)} - " if match else ""
                    novo_nome = f"{prefixo}{tipo_documento}.pdf"
            else:
                match = re.match(r'^(\d+)\s*-\s*', arquivo)
                prefixo = f"{match.group(1)} - " if match else ""
                novo_nome = f"{prefixo}{tipo_documento}.pdf"

            caminho_novo = os.path.join(pasta, novo_nome)
            try:
                os.replace(caminho_antigo, caminho_novo)
                arquivos_renomeados += 1
            except Exception as e:
                print(f"Erro ao renomear {arquivo}: {e}")

        nome_sucesso = sufixo if sufixo else tipo_documento
        messagebox.showinfo("Sucesso", f"Renomeação de {arquivos_renomeados} arquivo(s) de '{nome_sucesso}' concluída com sucesso!")

    def bot_pagamento_mensal(self): self.aplicar_renomeacao("RECIBO DE PAGAMENTO", padrao_nome=PADRAO_RECIBO_PAGAMENTO)
    def bot_pro_labore(self): self.aplicar_renomeacao("RECIBO DE PRÓ-LABORE", padrao_nome=PADRAO_RECIBO_PAGAMENTO)
    def bot_relacao_liquidos(self): self.aplicar_renomeacao("RELATÓRIO DE LÍQUIDOS", padrao_nome=PADRAO_RELATORIO_LIQUIDOS)
    def bot_extrato_mensal(self): self.aplicar_renomeacao("EXTRATO MENSAL", padrao_nome=PADRAO_EXTRATO_MENSAL)
    def bot_programacao_ferias(self): self.aplicar_renomeacao("PROGRAMAÇÃO DE FÉRIAS")
    def bot_adiantamento(self): self.aplicar_renomeacao("RECIBO DE ADIANTAMENTO", padrao_nome=PADRAO_RECIBO_PAGAMENTO)
    def bot_inss(self): self.aplicar_renomeacao(None, sufixo="INSS")
    def bot_fgts(self): self.aplicar_renomeacao(None, sufixo="FGTS")
    def bot_termo_rescisao(self): self.aplicar_renomeacao("TERMO DE RESCISÃO")
    def bot_termo_quitacao(self): self.aplicar_renomeacao("TERMO DE QUITAÇÃO")
    def bot_dctfweb(self): self.aplicar_dctfweb()

    def aplicar_dctfweb(self):
        pasta = self.entry_caminho.get().strip()
        if not pasta or not os.path.exists(pasta):
            messagebox.showwarning("Aviso", "Por favor, selecione uma pasta válida primeiro.")
            return

        arquivos = [f for f in os.listdir(pasta) if f.lower().endswith('.pdf') and os.path.isfile(os.path.join(pasta, f))]
        movidos = 0
        ignorados = 0
        for arquivo in arquivos:
            nome_sem_ext = os.path.splitext(arquivo)[0]
            match = PADRAO_DCTFWEB.match(nome_sem_ext.strip().lower())
            if not match:
                continue  # não é um recibo de DCTFWeb: não mexe
            empresa, mes, ano = match.group(1), match.group(2), match.group(3)
            if not (1 <= int(mes) <= 12):
                ignorados += 1
                continue

            pasta_empresa = f"EMPRESA {empresa}" if empresa else "SEM EMPRESA INFORMADA"
            pasta_destino = os.path.join(pasta, pasta_empresa, f"{mes}.{ano}")
            caminho_novo = os.path.join(pasta_destino, "RECIBO DE DCTFWeb.pdf")
            try:
                os.makedirs(pasta_destino, exist_ok=True)
                if os.path.exists(caminho_novo):
                    ignorados += 1  # já existe um arquivo com esse nome na pasta do mês: não sobrescreve
                    continue
                shutil.move(os.path.join(pasta, arquivo), caminho_novo)
                movidos += 1
            except Exception as e:
                ignorados += 1
                print(f"Erro ao mover {arquivo}: {e}")

        if movidos == 0 and ignorados == 0:
            messagebox.showinfo("Informação", "Nenhum recibo de DCTFWeb encontrado na pasta selecionada.")
            return
        msg = f"{movidos} arquivo(s) de 'DCTFWeb' organizado(s) com sucesso!"
        if ignorados:
            msg += f"\n\n{ignorados} arquivo(s) não foram movidos (mês inválido ou já existe um arquivo com o mesmo nome na pasta)."
        messagebox.showinfo("Sucesso", msg)

    # ================= MÓDULO 3: SÍMBOLS PARA COPIAR =================
    def setup_aba_simbolos(self):
        aba = self.frames_conteudo["🎨 Símbolos para Copiar"]
        self.scroll_simbolos = ctk.CTkScrollableFrame(aba, fg_color="transparent")
        self.scroll_simbolos.pack(expand=True, fill="both")

        secoes_dados = [
            ("Símbolos de Estrelas", "★ ☆ ✡ ✦ ✧ ✩ ✪ ✫ ✬ ✭ ✮ ✯ ✰ ⁂ ⁎ ⁑ ✢ ✣ ✤ ✥ ✱ ✲ ✳ ✴ ✵ ✶ ✷ ✸ ✹ ✺ ✻ ✼ ✽ ✾ ✿ ❀ ❂ ❃ ❇ ❈ ❉ ❊ ❋ ❄ ❆ ❅ ⋆ ≛"),
            ("Marca Registrada, Escritório", "© ® ™ ℠ ℡ ℗ ‱ № ℀ ℁ ℅ ℆ ⅍ ☊ ☎ ☏ ⌨ ✁ ✂ ✃ ✄ ✆ ✇ ✈ ✉ ✎ ✏ ✐ ✑ ✒ ‰ § ¶ ☞ ☛ ☟ ☜ ☚"),
            ("Símbolos de Moedas", "¢ $ € £ ¥ ₮ ৲ ৳ ௹ ฿ ៛ ₠ ₡ ₢ ₣ ₤ ₥ ₦ ₧ ₨ ₩ ₪ ₫ ₭ ₯ ₰ ₱ ₲ ₳ ₴ ₵ ￥ ﷼ ¤ ƒ"),
            ("Símbolos de Agrupamento", "〈 〉 《 》 「 」 『 』 【 】 〔 〕 ︵ ︶ ︷ ︸ ︹ ︺ ︻ ︼ ︽ ︾ ︿ ﹀ ﹁ ﹂ ﹃ ﹄ ﹙ ﹚ ﹛ ﹜ ﹝ ﹞ ﹤ ﹥ （ ） ＜ ＞ ｛ ｝ 〖 〗 〘 〙 〚 〛 « » ‹ › 〱"),
            ("Símbolos de Xadrez e Cartas", "♔ ♕ ♖ ♗ ♘ ♙ ♚ ♛ ♜ ♝ ♞ ♟ ♤ ♠ ♧ ♣ ♡ ♥ ♢ ♦ ⚀ ⚁ ⚂ ⚃ ⚄ ⚅"),
            ("Símbolos de Notas Musicais", "♩ ♪ ♫ ♬ ♭ ♮ ♯ ° ø ؂ ≠ ≭"),
            ("Símbolos de Tempo e Unidade de Medida", "° ℃ ℉ ϟ ☀ ☁ ☂ ☃ ☉ ☼ ☽ ☾ ♁ ♨ ❄ ❅ ❆ ☇ ☈ ☄ ㎎ ㎏ ㎜ ㎝ ㎞ ㎡ ㏄ ㏎ ㏑ ㏒ ㏕"),
            ("Símbolos de Crenças", "✝ ✞ ✟ † ☦ ✠ ✙ ✚ ✛ ✜ ☧ ☨ ☩"),
            ("Símbolos de Coração", "♥ ♡ ❤ ❥ ❣ ❦ ❧ დ ღ ۵  ও"),
            ("Símbolos de Marca de Verificação", "✓ ✔ ✗ ✘ ☓ ∨ √ ✇ ☐ ☑ ☒ 㤄 㤥"),
            ("Símbolos de Masculino, Feminino e Pessoas", "♀ ♂ ☹ ☺ ☻ ☿ 〠 ヅ ツ ㋡ 웃 유 ü Ü ت シ ッ ㋛ ꑇ ꐦ ꐠ ꐡ ꐕ ꌇ ꌈ ꉕ ꈋ ꈌ ꆛ ꆜ ꃼ ☠ ☃ 〲 〴 ϡ ﭢ ⍢ ⍣ ⍤ ⍥ ⍨ ⍩ ὃ ὕ ὣ Ѷ Ӫ ӫ ⚣ ⚤ ⚥ ⚦ ⚧ ⚨ ⚢"),
            ("Símbolos de Matemática", "π ∞ Σ √ ∛ ∜ ∫ ∬ ∭ ∮ ∯ ∰ ∱ ∲ ∳ ∀ ∁ ∂ ∃ ∄ ∅ ∆ ∇ ∈ ∉ ∊ ∋ ∌ ∍ ∎ ∏ ∐ ∑ − ∓ ∔ ∕ ∖ ∗ ∘ ∙ ∝ ∟ ∠ ∡ ∢ ∣ ∤∥ ∦ ∧ ∨ ∩ ∪ ∴ ∵ ∶ ∷ ∸ ∹ ∺ ∻ ∼ ∽ ∾ ∿ ≀ ≁ ≂ ≃ ≄ ≅ ≆ ≇ ≈ ≉ ≊ ≋ ≌ ≍ ≎ ≏ ≐ ≑ ≒ ≓ ≔ ≕ ≖ ≗ ≘ ≙ ≚ ≛ ≜ ≝ ≞ ≟ ≠ ≡ ≢ ≣ ≤ ≥ ≦ ≧ ≨ ≩ ≪ ≫ ≬ ≭ ≮ ≯ ≰ ≱ ≲ ≳ ≴ ≵ ≶ ≷ ≸ ≹ ≺ ≻ ≼ ≽ ≦ ≧ ⊂ ⊃ ⊄ ⊅ ⊆ ⊇ ⊈ ⊉ ⊊ ⊋ ⊌ ⊍ ⊎ ⊏ ⊐ ⊑ ⊒ ⊓ ⊔ ⊕ ⊖ ⊗ ⊘ ⊙ ⊚ ⊛ ⊜ ⊝ ⊞ ⊟ ⊠ ⊡ ⊢ ⊣ ⊤ ⊥ ⊦ ⊧ ⊨ ⊩ ⊪ ⊫ ⊬ ⊭ ⊮ ⊯ ⊰ ⊱ ⊲ ⊳ ⊴ ⊵ ⊶ ⊷ ⊸ ⊹ ⊺ ⊻ ⊼ ⊽ ⊾ ⊿ ⋀ ⋁ ⋂ ⋃ ⋄ ⋅ ⋆ ⋇ ⋈ ⋉ ⋊ ⋋ ⋌ ⋍ ⋎ ⋏ ⋐ ⋑ ⋒ ⋓ ⋔ ⋕ ⋖ ⋗ ⋘ ⋙ ⋚ ⋛ ⋜ ⋝ ⋞ ⋟ ⋠ ⋡ ⋢ ⋣ ⋤ ⋥ ⋦ ⋧ ⋨ ⋩ ⋪ ⋫ ⋬ ⋭ ⋮ ⋯ ⋰ ⋱ ⁺ ⁻ ⁼ ⁽ ⁾ ⁿ ₊ ₋ ₌ ₍ ₎ ✖ ﹢ ﹣ ＋ － ／ ＝ ÷ ± × 𝕏"),
            ("Números Sobrescritos", "¹ ² ³ ⁴ ⁵ ⁶ ⁷ ⁸ ⁹ ⁰")
        ]
        
        self.simbolos_botoes = {} 
        for titulo, str_simbolos in secoes_dados:
            self.criar_secao_acordeao(titulo, str_simbolos)

    def criar_secao_acordeao(self, titulo, simbolos_str):
        btn_header = ctk.CTkButton(
            self.scroll_simbolos, text=f"▶ {titulo.upper()}", anchor="w", 
            fg_color=_C("#121212"), hover_color=COLOR_HOVER, text_color=COLOR_ACCENT,
            font=_f("Montserrat", 11, "bold"), corner_radius=8
        )
        btn_header.pack(fill="x", pady=(10, 2), padx=5)

        frame_grid = ctk.CTkFrame(self.scroll_simbolos, fg_color="transparent")
        btn_header.configure(command=lambda f=frame_grid, b=btn_header: self.toggle_acordeao(f, b))

        # Os botões só são criados na 1ª vez que a seção é aberta (criar centenas de botões
        # do CustomTkinter na inicialização era uma das causas da demora para abrir o app).
        def construir():
            col_atual = 0
            row_atual = 0
            max_cols = 4
            font_simbolo = _f("Segoe UI Symbol", 20)

            for simbolo in simbolos_str.split():
                btn = ctk.CTkButton(
                    frame_grid, text=simbolo, width=125, height=60,
                    fg_color=_C("#262626"), text_color=_C("#D1D1D1"), hover_color=COLOR_HOVER,
                    font=font_simbolo, corner_radius=8
                )
                btn.grid(row=row_atual, column=col_atual, padx=4, pady=4)
                btn.configure(command=lambda b=btn, s=simbolo: self.copiar_e_animar_simbolo(b, s))

                col_atual += 1
                if col_atual >= max_cols:
                    col_atual = 0
                    row_atual += 1

        frame_grid._construir_simbolos = construir

    def toggle_acordeao(self, frame_grid, btn_header):
        if frame_grid.winfo_ismapped():
            frame_grid.pack_forget()
            btn_header.configure(text=btn_header.cget("text").replace("▼", "▶"))
        else:
            construir = getattr(frame_grid, "_construir_simbolos", None)
            if construir:
                frame_grid._construir_simbolos = None
                construir()
            frame_grid.pack(fill="x", padx=5, pady=2, after=btn_header)
            btn_header.configure(text=btn_header.cget("text").replace("▶", "▼"))

    def copiar_e_animar_simbolo(self, btn, simbolo):
        try:
            self.clipboard_clear()
            self.clipboard_append(simbolo)
            self.update()
        except:
            pass
        
        btn.configure(fg_color=_C("#00FF66"), text_color=_C("#000000"), text="✓", hover_color=COLOR_SUCCESS_HOVER)
        self.after(3000, lambda: btn.configure(fg_color=_C("#262626"), text_color=_C("#D1D1D1"), text=simbolo, hover_color=COLOR_HOVER))


    # ================= MÓDULO 3B: GERENCIADOR DE SENHAS =================
    def carregar_dados_senhas(self):
        self.senhas_data = {}
        if os.path.exists(ARQUIVO_SENHAS):
            try:
                with open(ARQUIVO_SENHAS, "r", encoding="utf-8") as f:
                    self.senhas_data = json.load(f)
            except Exception:
                self.senhas_data = {}

    def salvar_dados_senhas(self):
        try:
            with open(ARQUIVO_SENHAS, "w", encoding="utf-8") as f:
                json.dump(self.senhas_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao salvar arquivo de senhas: {e}")

    def setup_aba_senhas(self):
        aba = self.frames_conteudo["🔐 Gerenciador de Senhas"]
        self.senha_atual_id = None
        self.botoes_senhas = {}
        self._after_salvo_senha = None
        self.senha_visivel = False
        self.carregar_dados_senhas()

        paned = ctk.CTkFrame(aba, fg_color="transparent")
        paned.pack(expand=True, fill="both")

        sidebar = ctk.CTkFrame(paned, width=180, fg_color=_C("#121212"), corner_radius=12)
        sidebar.pack(side="left", fill="y", padx=(0, 10))
        sidebar.pack_propagate(False)

        ctk.CTkButton(sidebar, text="+ Nova Senha", command=self.criar_nova_senha, fg_color=COLOR_VITA_BLUE, font=_f("Montserrat", 12, "bold")).pack(pady=15, padx=10, fill="x")

        self.scroll_lista_senhas = ctk.CTkScrollableFrame(sidebar, fg_color="transparent")
        self.scroll_lista_senhas.pack(expand=True, fill="both", padx=5, pady=(0, 0))

        editor = ctk.CTkFrame(paned, fg_color=_C("#262626"), corner_radius=12)
        editor.pack(side="left", expand=True, fill="both")

        header = ctk.CTkFrame(editor, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=(15, 10))

        self.entry_titulo_senha = ctk.CTkEntry(header, font=_f("Montserrat", 16, "bold"), fg_color=_C("#1A1A1A"), border_width=0, placeholder_text="Título (ex.: Gmail, Prefeitura...)")
        self.entry_titulo_senha.pack(side="left", expand=True, fill="x", padx=(0, 10))

        self.btn_excluir_senha = ctk.CTkButton(header, text="Excluir", width=60, fg_color=COLOR_DANGER, hover_color=_C("#AA0000"), text_color=_C("#FFFFFF"), font=_f("Montserrat", 12, "bold"), command=self.excluir_senha_atual)
        self.btn_excluir_senha.pack(side="right")

        campos = ctk.CTkFrame(editor, fg_color="transparent")
        campos.pack(fill="x", padx=15, pady=(5, 0))

        ctk.CTkLabel(campos, text="Login (e-mail ou outro tipo de login)", font=_f("Montserrat", 11, "bold"), text_color=COLOR_SUBTITLE, anchor="w").pack(fill="x", pady=(0, 4))
        linha_login = ctk.CTkFrame(campos, fg_color="transparent")
        linha_login.pack(fill="x", pady=(0, 14))
        self.entry_login_senha = ctk.CTkEntry(linha_login, font=_f("Montserrat", 13), fg_color=_C("#1A1A1A"), border_width=0, height=38)
        self.entry_login_senha.pack(side="left", expand=True, fill="x", padx=(0, 8))
        self.btn_copiar_login = ctk.CTkButton(linha_login, text="Copiar", width=80, height=38, fg_color=_C("#1A1A1A"), hover_color=COLOR_HOVER, text_color=COLOR_ACCENT, font=_f("Montserrat", 11, "bold"), command=lambda: self.copiar_campo_senha(self.entry_login_senha, self.btn_copiar_login))
        self.btn_copiar_login.pack(side="left")

        ctk.CTkLabel(campos, text="Senha", font=_f("Montserrat", 11, "bold"), text_color=COLOR_SUBTITLE, anchor="w").pack(fill="x", pady=(0, 4))
        linha_senha = ctk.CTkFrame(campos, fg_color="transparent")
        linha_senha.pack(fill="x")
        self.entry_senha = ctk.CTkEntry(linha_senha, font=_f("Montserrat", 13), fg_color=_C("#1A1A1A"), border_width=0, height=38, show="•")
        self.entry_senha.pack(side="left", expand=True, fill="x", padx=(0, 8))
        self.btn_mostrar_senha = ctk.CTkButton(linha_senha, text="Mostrar", width=80, height=38, fg_color=_C("#1A1A1A"), hover_color=COLOR_HOVER, text_color=COLOR_ACCENT, font=_f("Montserrat", 11, "bold"), command=self.alternar_visibilidade_senha)
        self.btn_mostrar_senha.pack(side="left", padx=(0, 8))
        self.btn_copiar_senha = ctk.CTkButton(linha_senha, text="Copiar", width=80, height=38, fg_color=_C("#1A1A1A"), hover_color=COLOR_HOVER, text_color=COLOR_ACCENT, font=_f("Montserrat", 11, "bold"), command=lambda: self.copiar_campo_senha(self.entry_senha, self.btn_copiar_senha))
        self.btn_copiar_senha.pack(side="left")

        self.btn_salvar_senha = ctk.CTkButton(editor, text="Salvar Senha", command=self.salvar_senha_atual, fg_color=COLOR_VITA_BLUE, font=_f("Montserrat", 12, "bold"), height=40)
        self.btn_salvar_senha.pack(side="bottom", fill="x", padx=15, pady=(0, 15))

        self.atualizar_lista_senhas()
        self.limpar_editor_senhas()

    def _widgets_editor_senhas(self):
        return (self.entry_titulo_senha, self.entry_login_senha, self.entry_senha)

    def criar_nova_senha(self):
        if self.senha_atual_id: self.salvar_senha_atual(silencioso=True)
        novo_id = str(uuid.uuid4())
        self.senhas_data[novo_id] = {"titulo": "Nova Senha", "login": "", "senha": ""}
        self.salvar_dados_senhas()
        self.atualizar_lista_senhas()
        self.abrir_senha(novo_id)

    def atualizar_lista_senhas(self):
        for btn in self.botoes_senhas.values(): btn.destroy()
        self.botoes_senhas = {}
        for senha_id, dados in self.senhas_data.items():
            cor_fundo = COLOR_HOVER if senha_id == self.senha_atual_id else "transparent"
            btn = ctk.CTkButton(self.scroll_lista_senhas, text=dados.get("titulo", "Sem Título"), anchor="w", fg_color=cor_fundo, text_color=COLOR_ACCENT, hover_color=COLOR_HOVER, command=lambda id=senha_id: self.abrir_senha(id))
            btn.pack(fill="x", pady=2)
            self.botoes_senhas[senha_id] = btn

    def abrir_senha(self, senha_id):
        if self.senha_atual_id and self.senha_atual_id != senha_id: self.salvar_senha_atual(silencioso=True)
        self.senha_atual_id = senha_id
        dados = self.senhas_data[senha_id]

        for w in self._widgets_editor_senhas():
            w.configure(state="normal")
            w.delete(0, tk.END)
        self.entry_titulo_senha.insert(0, dados.get("titulo", ""))
        self.entry_login_senha.insert(0, dados.get("login", ""))
        self.entry_senha.insert(0, _revelar_senha(dados.get("senha", "")))

        self.senha_visivel = True
        self.alternar_visibilidade_senha()  # sempre abre com a senha oculta

        for b in (self.btn_excluir_senha, self.btn_salvar_senha, self.btn_mostrar_senha, self.btn_copiar_login, self.btn_copiar_senha):
            b.configure(state="normal")
        self.atualizar_lista_senhas()

    def salvar_senha_atual(self, silencioso=False):
        if not self.senha_atual_id: return
        self.senhas_data[self.senha_atual_id] = {
            "titulo": self.entry_titulo_senha.get().strip() or "Sem Título",
            "login": self.entry_login_senha.get().strip(),
            "senha": _proteger_senha(self.entry_senha.get()),
        }
        self.salvar_dados_senhas()
        self.atualizar_lista_senhas()
        if not silencioso:
            self.btn_salvar_senha.configure(text="Salvo!", fg_color=_C("#00FF66"))
            if self._after_salvo_senha:
                self.after_cancel(self._after_salvo_senha)
            self._after_salvo_senha = self.after(2000, lambda: self.btn_salvar_senha.configure(text="Salvar Senha", fg_color=COLOR_VITA_BLUE))

    def excluir_senha_atual(self):
        if not self.senha_atual_id: return
        if messagebox.askyesno("Confirmar", "Tem certeza que deseja excluir esta senha permanentemente?"):
            del self.senhas_data[self.senha_atual_id]
            self.salvar_dados_senhas()
            self.limpar_editor_senhas()
            self.atualizar_lista_senhas()

    def limpar_editor_senhas(self):
        self.senha_atual_id = None
        for w in self._widgets_editor_senhas():
            w.delete(0, tk.END)
            w.configure(state="disabled")
        for b in (self.btn_excluir_senha, self.btn_salvar_senha, self.btn_mostrar_senha, self.btn_copiar_login, self.btn_copiar_senha):
            b.configure(state="disabled")

    def alternar_visibilidade_senha(self):
        self.senha_visivel = not self.senha_visivel
        self.entry_senha.configure(show="" if self.senha_visivel else "•")
        self.btn_mostrar_senha.configure(text="Ocultar" if self.senha_visivel else "Mostrar")

    def copiar_campo_senha(self, entry, botao):
        try:
            self.clipboard_clear()
            self.clipboard_append(entry.get())
            self.update()
        except Exception:
            pass
        botao.configure(text="Copiado!", fg_color=_C("#00FF66"), text_color=_C("#000000"))
        self.after(1500, lambda: botao.configure(text="Copiar", fg_color=_C("#1A1A1A"), text_color=COLOR_ACCENT))

    # ================= MÓDULO 3C: CONTADOR DE CARACTERES E PALAVRAS =================
    def setup_aba_contador(self):
        aba = self.frames_conteudo["🔤 Contador de Caracteres"]
        ctk.CTkLabel(aba, text="CONTADOR DE CARACTERES E PALAVRAS", font=_f("Montserrat", 16, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(15, 4))
        ctk.CTkLabel(aba, text="Digite ou cole o texto abaixo; a contagem é atualizada na hora.", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE).pack(pady=(0, 10))

        frame_stats = ctk.CTkFrame(aba, fg_color="transparent")
        frame_stats.pack(fill="x", padx=15)
        self.lbls_contador = {}
        itens = [("caracteres", "Caracteres"), ("sem_espacos", "Sem espaços"), ("palavras", "Palavras"), ("linhas", "Linhas"), ("paragrafos", "Parágrafos")]
        for col, (chave, rotulo) in enumerate(itens):
            frame_stats.grid_columnconfigure(col, weight=1, uniform="stats_contador")
            card = ctk.CTkFrame(frame_stats, fg_color=_C("#262626"), corner_radius=10)
            card.grid(row=0, column=col, padx=4, sticky="ew")
            lbl_num = ctk.CTkLabel(card, text="0", font=_f("Montserrat", 22, "bold"), text_color=COLOR_ACCENT)
            lbl_num.pack(pady=(10, 0))
            ctk.CTkLabel(card, text=rotulo, font=_f("Montserrat", 10, "bold"), text_color=COLOR_SUBTITLE).pack(pady=(0, 10))
            self.lbls_contador[chave] = lbl_num

        self.txt_contador = ctk.CTkTextbox(aba, fg_color=_C("#262626"), text_color=_C("#FFFFFF"), font=_f("Montserrat", 13), border_width=0, wrap="word")
        self.txt_contador.pack(expand=True, fill="both", padx=15, pady=(12, 8))
        # <<Modified>> dispara em qualquer alteração (digitar, colar, recortar, apagar)
        self.txt_contador._textbox.bind("<<Modified>>", self._atualizar_contador, add="+")

        barra = ctk.CTkFrame(aba, fg_color="transparent")
        barra.pack(fill="x", padx=15, pady=(0, 12))
        for texto, comando in (("Colar", self._contador_colar), ("Copiar Texto", self._contador_copiar), ("Limpar", self._contador_limpar)):
            ctk.CTkButton(barra, text=texto, width=110, height=34, fg_color=_C("#262626"), hover_color=COLOR_HOVER, text_color=COLOR_ACCENT, font=_f("Montserrat", 12, "bold"), command=comando).pack(side="left", padx=(0, 8))

    def _atualizar_contador(self, event=None):
        tb = self.txt_contador._textbox
        if not tb.edit_modified():
            return
        tb.edit_modified(False)
        texto = tb.get("1.0", "end-1c")
        dados = {
            "caracteres": len(texto),
            "sem_espacos": len("".join(texto.split())),
            "palavras": len(texto.split()),
            "linhas": len(texto.splitlines()),
            "paragrafos": len([p for p in re.split(r"\n\s*\n", texto) if p.strip()]),
        }
        for chave, valor in dados.items():
            self.lbls_contador[chave].configure(text=f"{valor:,}".replace(",", "."))

    def _contador_colar(self):
        try:
            self.txt_contador.insert("insert", self.clipboard_get())
        except tk.TclError:
            pass

    def _contador_copiar(self):
        texto = self.txt_contador.get("1.0", "end-1c")
        if texto:
            self.clipboard_clear()
            self.clipboard_append(texto)
            self.update()

    def _contador_limpar(self):
        self.txt_contador.delete("1.0", "end")

    # ================= MÓDULO 4B: CALCULADORA DE PERCENTUAIS =================
    def setup_aba_percentuais(self):
        aba = self.frames_conteudo["💯 Calculadora de Percentuais"]
        ctk.CTkLabel(aba, text="CALCULADORA DE PERCENTUAIS", font=_f("Montserrat", 16, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(15, 4))
        ctk.CTkLabel(aba, text="Preencha os dois campos do cartão e clique em Calcular (ou aperte Enter).\nAceita 1.234,56 ou 1234.56.", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE, justify="center").pack(pady=(0, 8))

        scroll = ctk.CTkScrollableFrame(aba, fg_color="transparent")
        scroll.pack(expand=True, fill="both")

        def pct_de(p, v): return f"Resultado: {_fmt_br(p / 100 * v)}"
        def representa(a, b): return f"Resultado: {_fmt_br(a / b * 100)}%"
        def variacao(a, b):
            if a == 0:
                raise ZeroDivisionError
            v = (b - a) / a * 100
            if v > 0: return f"Aumento de {_fmt_br(v)}%"
            if v < 0: return f"Redução de {_fmt_br(abs(v))}%"
            return "Sem variação (0%)"
        def acresc_desc(p, v): return f"Com acréscimo: {_fmt_br(v * (1 + p / 100))}\nCom desconto: {_fmt_br(v * (1 - p / 100))}"
        def valor_total(a, p): return f"Resultado: {_fmt_br(a / (p / 100))}"

        # (título, frase [texto ou 0 = campo numérico], função)
        cartoes = [
            ("PORCENTAGEM DE UM VALOR", ["Quanto é", 0, "% de", 0, "?"], pct_de),
            ("QUANTO REPRESENTA", [0, "é quantos % de", 0, "?"], representa),
            ("VARIAÇÃO PERCENTUAL", ["De", 0, "para", 0], variacao),
            ("ACRÉSCIMO E DESCONTO", ["Aplicar", 0, "% sobre", 0], acresc_desc),
            ("VALOR TOTAL (INVERSO)", [0, "é", 0, "% de quanto?"], valor_total),
        ]

        for titulo, frase, funcao in cartoes:
            card = ctk.CTkFrame(scroll, fg_color=_C("#262626"), corner_radius=12)
            card.pack(fill="x", padx=10, pady=6)
            ctk.CTkLabel(card, text=titulo, font=_f("Montserrat", 12, "bold"), text_color=COLOR_VITA_BLUE).pack(anchor="w", padx=15, pady=(12, 6))
            linha = ctk.CTkFrame(card, fg_color="transparent")
            linha.pack(fill="x", padx=15)

            entradas = []
            for parte in frase:
                if parte == 0:
                    e = ctk.CTkEntry(linha, width=100, height=34, justify="center", fg_color=_C("#1A1A1A"), border_width=0, font=_f("Montserrat", 13))
                    e.pack(side="left", padx=4)
                    entradas.append(e)
                else:
                    ctk.CTkLabel(linha, text=parte, font=_f("Montserrat", 13), text_color=COLOR_ACCENT).pack(side="left", padx=2)

            lbl_res = ctk.CTkLabel(card, text="", font=_f("Montserrat", 14, "bold"), text_color=_C("#00FF66"), justify="left", anchor="w")
            lbl_res.pack(fill="x", padx=15, pady=(8, 12))

            def calcular(f=funcao, es=entradas, lbl=lbl_res):
                try:
                    a, b = (_parse_num_br(e.get()) for e in es)
                except ValueError:
                    lbl.configure(text="Preencha os dois campos com números válidos.", text_color=COLOR_DANGER)
                    return
                try:
                    lbl.configure(text=f(a, b), text_color=_C("#00FF66"))
                except ZeroDivisionError:
                    lbl.configure(text="Não é possível dividir por zero.", text_color=COLOR_DANGER)

            ctk.CTkButton(linha, text="Calcular", width=90, height=34, font=_f("Montserrat", 12, "bold"), command=calcular, fg_color=COLOR_ACCENT, text_color=COLOR_BG, hover_color=COLOR_HOVER_WHITE).pack(side="right")
            for e in entradas:
                e.bind("<Return>", lambda ev, c=calcular: c())

    # ================= MÓDULO 7B: COMPRIMIR PDF =================
    def setup_aba_comprimir_pdf(self):
        aba = self.frames_conteudo["📉 Comprimir PDF (BETA)"]
        frame = ctk.CTkFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        frame.pack(fill="x", padx=20, pady=(30, 15))

        ctk.CTkLabel(frame, text="COMPRIMIR PDF (BETA)", font=_f("Montserrat", 16, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(20, 10))
        ctk.CTkLabel(frame, text="Reduz o tamanho de um PDF. Escolha o nível e depois o arquivo.", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE).pack(pady=(0, 15))

        self.descricoes_compressao = {
            "Leve": "Sem perda de qualidade: só remove dados redundantes. Reduz pouco.",
            "Média": "Recomendado: reduz a resolução das imagens para ~110 DPI, mantendo boa leitura.",
            "Forte": "Menor tamanho possível: imagens a ~72 DPI e mais compactadas. Pode perder nitidez.",
        }
        self.seg_compressao = ctk.CTkSegmentedButton(frame, values=["Leve", "Média", "Forte"], command=self._atualizar_desc_compressao, selected_color=COLOR_VITA_BLUE, font=_f("Montserrat", 12, "bold"))
        self.seg_compressao.pack(pady=(0, 10))
        self.lbl_desc_compressao = ctk.CTkLabel(frame, text="", font=_f("Montserrat", 11, "italic"), text_color=COLOR_SUBTITLE, wraplength=480)
        self.lbl_desc_compressao.pack(pady=(0, 15))
        self.seg_compressao.set("Média")
        self._atualizar_desc_compressao("Média")

        ctk.CTkButton(frame, text="Selecionar PDF e Comprimir", width=230, height=40, font=_f("Montserrat", 12, "bold"), command=self.comprimir_pdf, fg_color=COLOR_ACCENT, text_color=COLOR_BG, hover_color=COLOR_HOVER_WHITE).pack(pady=(5, 25))

    def _atualizar_desc_compressao(self, nivel):
        self.lbl_desc_compressao.configure(text=self.descricoes_compressao.get(nivel, ""))

    def comprimir_pdf(self):
        arquivo = filedialog.askopenfilename(title="Selecione o PDF para comprimir", filetypes=[("Arquivos PDF", "*.pdf")])
        if not arquivo:
            return
        nivel = self.seg_compressao.get()
        parametros = {
            "Média": dict(dpi_threshold=150, dpi_target=110, quality=75),
            "Forte": dict(dpi_threshold=110, dpi_target=72, quality=50),
        }
        aviso = ""
        documento = None
        try:
            self.configure(cursor="watch")
            self.update_idletasks()
            documento = fitz.open(arquivo)
            if documento.needs_pass:
                messagebox.showerror("Erro", "Este PDF está protegido por senha e não pode ser comprimido.")
                return
            if nivel in parametros:
                try:
                    documento.rewrite_images(**parametros[nivel])
                except AttributeError:
                    aviso = "\n\nObs.: sua versão do PyMuPDF não comprime imagens, então só a otimização sem perda foi aplicada. Para habilitar: pip install -U PyMuPDF"
            dados = documento.tobytes(garbage=4, clean=True, deflate=True, deflate_images=True, deflate_fonts=True)
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao comprimir o PDF:\n{e}")
            return
        finally:
            if documento is not None:
                documento.close()
            self.configure(cursor="")

        tamanho_original = os.path.getsize(arquivo)
        if len(dados) >= tamanho_original:
            messagebox.showinfo("Sem ganho", f"Este PDF já está otimizado ({_fmt_tamanho(tamanho_original)}); não foi possível reduzi-lo mais com o nível {nivel}." + aviso)
            return

        base = os.path.splitext(os.path.basename(arquivo))[0]
        saida = filedialog.asksaveasfilename(title="Salvar PDF comprimido como...", initialdir=os.path.dirname(arquivo), initialfile=f"{base}_comprimido.pdf", defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
        if not saida:
            return
        try:
            with open(saida, "wb") as f:
                f.write(dados)
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível salvar o arquivo:\n{e}")
            return
        reducao = (1 - len(dados) / tamanho_original) * 100
        messagebox.showinfo("Sucesso", f"PDF comprimido com sucesso!\n\nDe {_fmt_tamanho(tamanho_original)} para {_fmt_tamanho(len(dados))} ({_fmt_br(reducao, 1)}% menor).{aviso}")

    # ================= MÓDULO 8B: JUNTAR IMAGENS EM PDF =================
    def setup_aba_juntar_imagens(self):
        aba = self.frames_conteudo["📑 Juntar Imagens em PDF (BETA)"]
        self.imagens_pdf = []

        ctk.CTkLabel(aba, text="JUNTAR IMAGENS EM UM PDF (BETA)", font=_f("Montserrat", 16, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(15, 4))
        ctk.CTkLabel(aba, text="Adicione as imagens, ajuste a ordem (cada imagem vira uma página) e gere o PDF.", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE).pack(pady=(0, 10))

        barra = ctk.CTkFrame(aba, fg_color="transparent")
        barra.pack(fill="x", padx=15)
        ctk.CTkButton(barra, text="+ Adicionar Imagens", width=170, height=36, fg_color=COLOR_VITA_BLUE, font=_f("Montserrat", 12, "bold"), command=self.adicionar_imagens_pdf).pack(side="left", padx=(0, 8))
        ctk.CTkButton(barra, text="Limpar Lista", width=110, height=36, fg_color=_C("#444444"), hover_color=_C("#555555"), text_color="white", font=_f("Montserrat", 12, "bold"), command=self.limpar_imagens_pdf).pack(side="left")

        self.scroll_imagens_pdf = ctk.CTkScrollableFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        self.scroll_imagens_pdf.pack(expand=True, fill="both", padx=15, pady=10)

        self.var_a4_pdf = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(aba, text="Ajustar todas as páginas ao tamanho A4", variable=self.var_a4_pdf, font=_f("Montserrat", 12), text_color=COLOR_ACCENT, fg_color=COLOR_VITA_BLUE).pack(anchor="w", padx=20, pady=(0, 10))

        ctk.CTkButton(aba, text="Gerar PDF", height=40, font=_f("Montserrat", 12, "bold"), command=self.gerar_pdf_das_imagens, fg_color=COLOR_ACCENT, text_color=COLOR_BG, hover_color=COLOR_HOVER_WHITE).pack(fill="x", padx=15, pady=(0, 15))
        self._renderizar_imagens_pdf()

    def adicionar_imagens_pdf(self):
        arquivos = filedialog.askopenfilenames(title="Selecione as imagens", filetypes=[("Imagens", "*.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff")])
        if arquivos:
            self.imagens_pdf.extend(arquivos)
            self._renderizar_imagens_pdf()

    def limpar_imagens_pdf(self):
        self.imagens_pdf = []
        self._renderizar_imagens_pdf()

    def _mover_imagem_pdf(self, i, delta):
        j = i + delta
        if 0 <= j < len(self.imagens_pdf):
            self.imagens_pdf[i], self.imagens_pdf[j] = self.imagens_pdf[j], self.imagens_pdf[i]
            self._renderizar_imagens_pdf()

    def _remover_imagem_pdf(self, i):
        if 0 <= i < len(self.imagens_pdf):
            del self.imagens_pdf[i]
            self._renderizar_imagens_pdf()

    def _renderizar_imagens_pdf(self):
        for w in self.scroll_imagens_pdf.winfo_children():
            w.destroy()
        if not self.imagens_pdf:
            ctk.CTkLabel(self.scroll_imagens_pdf, text="Nenhuma imagem adicionada ainda.", font=_f("Montserrat", 12, "italic"), text_color=COLOR_SUBTITLE).pack(pady=30)
            return
        for i, caminho in enumerate(self.imagens_pdf):
            linha = ctk.CTkFrame(self.scroll_imagens_pdf, fg_color=_C("#1A1A1A"), corner_radius=8)
            linha.pack(fill="x", pady=3, padx=3)
            nome = os.path.basename(caminho)
            if len(nome) > 42:
                nome = nome[:39] + "..."
            ctk.CTkLabel(linha, text=f"{i + 1}. {nome}", font=_f("Montserrat", 12), text_color=COLOR_ACCENT, anchor="w").pack(side="left", fill="x", expand=True, padx=(10, 5), pady=6)
            ctk.CTkButton(linha, text="✖", width=30, height=28, fg_color="transparent", hover_color=COLOR_DANGER, text_color=COLOR_ACCENT, command=lambda i=i: self._remover_imagem_pdf(i)).pack(side="right", padx=(0, 6))
            ctk.CTkButton(linha, text="▼", width=30, height=28, fg_color="transparent", hover_color=COLOR_HOVER, text_color=COLOR_ACCENT, command=lambda i=i: self._mover_imagem_pdf(i, 1)).pack(side="right")
            ctk.CTkButton(linha, text="▲", width=30, height=28, fg_color="transparent", hover_color=COLOR_HOVER, text_color=COLOR_ACCENT, command=lambda i=i: self._mover_imagem_pdf(i, -1)).pack(side="right")

    def _imagem_para_rgb(self, imagem):
        imagem = _ImageOps.exif_transpose(imagem)  # respeita a rotação das fotos de celular
        if imagem.mode in ("RGBA", "LA") or (imagem.mode == "P" and "transparency" in imagem.info):
            imagem = imagem.convert("RGBA")
            fundo = Image.new("RGB", imagem.size, "white")  # transparência vira fundo branco (não preto)
            fundo.paste(imagem, mask=imagem.split()[3])
            return fundo
        return imagem.convert("RGB")

    def _ajustar_a4(self, imagem):
        larg, alt = 1240, 1754  # A4 a 150 DPI
        if imagem.width > imagem.height:
            larg, alt = alt, larg  # imagem deitada -> página A4 deitada
        escala = min(larg / imagem.width, alt / imagem.height)
        novo = (max(1, int(imagem.width * escala)), max(1, int(imagem.height * escala)))
        redimensionada = imagem.resize(novo, getattr(Image, "Resampling", Image).LANCZOS)
        pagina = Image.new("RGB", (larg, alt), "white")
        pagina.paste(redimensionada, ((larg - novo[0]) // 2, (alt - novo[1]) // 2))
        return pagina

    def gerar_pdf_das_imagens(self):
        if not self.imagens_pdf:
            messagebox.showwarning("Atenção", "Adicione pelo menos uma imagem.")
            return
        saida = filedialog.asksaveasfilename(title="Salvar PDF como...", initialfile="imagens.pdf", defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
        if not saida:
            return
        try:
            self.configure(cursor="watch")
            self.update_idletasks()
            paginas = []
            for caminho in self.imagens_pdf:
                with Image.open(caminho) as imagem:
                    pagina = self._imagem_para_rgb(imagem)
                if self.var_a4_pdf.get():
                    pagina = self._ajustar_a4(pagina)
                paginas.append(pagina)
            paginas[0].save(saida, "PDF", save_all=True, append_images=paginas[1:], resolution=150.0)
            messagebox.showinfo("Sucesso", f"PDF com {len(paginas)} página(s) gerado com sucesso!")
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao gerar o PDF:\n{e}")
        finally:
            self.configure(cursor="")

    # ================= MÓDULO 2B: GERADOR DE QR CODE =================
    def setup_aba_qrcode(self):
        aba = self.frames_conteudo["📱 Gerador de QR Code"]
        ctk.CTkLabel(aba, text="GERADOR DE QR CODE", font=_f("Montserrat", 16, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(15, 4))
        ctk.CTkLabel(aba, text="Informe o conteúdo e o nome do arquivo, gere a prévia e salve a imagem.", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE).pack(pady=(0, 10))

        corpo = ctk.CTkFrame(aba, fg_color="transparent")
        corpo.pack(expand=True, fill="both", padx=15, pady=(0, 10))

        esquerda = ctk.CTkFrame(corpo, fg_color=_C("#262626"), corner_radius=12)
        esquerda.pack(side="left", expand=True, fill="both", padx=(0, 10))

        ctk.CTkLabel(esquerda, text="Conteúdo (link, texto, Wi-Fi...)", font=_f("Montserrat", 11, "bold"), text_color=COLOR_SUBTITLE, anchor="w").pack(fill="x", padx=15, pady=(15, 4))
        self.txt_qr = ctk.CTkTextbox(esquerda, height=110, fg_color=_C("#1A1A1A"), text_color=_C("#FFFFFF"), font=_f("Montserrat", 13), border_width=0, wrap="word")
        self.txt_qr.pack(fill="x", padx=15)

        ctk.CTkLabel(esquerda, text="Nome do arquivo (sem extensão)", font=_f("Montserrat", 11, "bold"), text_color=COLOR_SUBTITLE, anchor="w").pack(fill="x", padx=15, pady=(14, 4))
        self.entry_qr_nome = ctk.CTkEntry(esquerda, height=36, fg_color=_C("#1A1A1A"), border_width=0, font=_f("Montserrat", 13), placeholder_text="ex.: qrcode_site")
        self.entry_qr_nome.pack(fill="x", padx=15)

        ctk.CTkButton(esquerda, text="Gerar QR Code", height=40, font=_f("Montserrat", 12, "bold"), command=self.gerar_qrcode, fg_color=COLOR_VITA_BLUE).pack(fill="x", padx=15, pady=(18, 8))
        ctk.CTkButton(esquerda, text="Salvar Imagem", height=40, font=_f("Montserrat", 12, "bold"), command=self.salvar_qrcode, fg_color=COLOR_ACCENT, text_color=COLOR_BG, hover_color=COLOR_HOVER_WHITE).pack(fill="x", padx=15, pady=(0, 15))

        direita = ctk.CTkFrame(corpo, fg_color=_C("#262626"), corner_radius=12, width=260)
        direita.pack(side="left", fill="y")
        direita.pack_propagate(False)
        self.lbl_qr_preview = ctk.CTkLabel(direita, text="A prévia aparece aqui", font=_f("Montserrat", 12, "italic"), text_color=COLOR_SUBTITLE)
        self.lbl_qr_preview.place(relx=0.5, rely=0.5, anchor="center")

    def _montar_qrcode(self):
        texto = self.txt_qr.get("1.0", "end").strip()
        if not texto:
            messagebox.showwarning("Atenção", "Digite o conteúdo do QR Code.")
            return None
        qr = _qrcode.QRCode(box_size=10, border=4)
        qr.add_data(texto)
        qr.make(fit=True)
        return qr.make_image(fill_color="black", back_color="white").get_image().convert("RGB")

    def gerar_qrcode(self):
        try:
            imagem = self._montar_qrcode()
            if imagem is None:
                return
            prev = imagem.resize((230, 230), getattr(Image, "Resampling", Image).NEAREST)
            self._qr_preview_ctk = ctk.CTkImage(light_image=prev, dark_image=prev, size=(230, 230))
            self.lbl_qr_preview.configure(image=self._qr_preview_ctk, text="")
        except ImportError:
            return  # a mensagem de instalação já foi exibida
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao gerar o QR Code:\n{e}")

    def salvar_qrcode(self):
        try:
            imagem = self._montar_qrcode()
            if imagem is None:
                return
            nome = _nome_arquivo_seguro(self.entry_qr_nome.get(), "qrcode")
            saida = filedialog.asksaveasfilename(title="Salvar QR Code", initialfile=nome, defaultextension=".png", filetypes=[("PNG", "*.png"), ("JPG", "*.jpg")])
            if not saida:
                return
            imagem.save(saida)
            messagebox.showinfo("Sucesso", "QR Code salvo com sucesso!")
        except ImportError:
            return
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao salvar o QR Code:\n{e}")

    # ================= MÓDULO 4: CALCULADORA CIENTÍFICA =================
    def setup_aba_calculadora(self):
        aba = self.frames_conteudo["🧮 Calculadora Científica"]
        
        self.display_calc = ctk.CTkEntry(aba, font=_f("Segoe UI", 28, "bold"), justify="right", height=60, fg_color=_C("#121212"), border_width=0)
        self.display_calc.pack(fill="x", padx=20, pady=(20, 10))

        teclado_frame = ctk.CTkFrame(aba, fg_color="transparent")
        teclado_frame.pack(expand=True, fill="both", padx=20, pady=10)

        botoes_calc = [
            ('sin', 0, 0), ('cos', 0, 1), ('tan', 0, 2), ('pi', 0, 3), ('C', 0, 4, COLOR_DANGER),
            ('log', 1, 0), ('ln', 1, 1), ('(', 1, 2), (')', 1, 3), ('/', 1, 4, COLOR_VITA_BLUE),
            ('sqrt', 2, 0), ('7', 2, 1), ('8', 2, 2), ('9', 2, 3), ('*', 2, 4, COLOR_VITA_BLUE),
            ('^', 3, 0), ('4', 3, 1), ('5', 3, 2), ('6', 3, 3), ('-', 3, 4, COLOR_VITA_BLUE),
            ('e', 4, 0), ('1', 4, 1), ('2', 4, 2), ('3', 4, 3), ('+', 4, 4, COLOR_VITA_BLUE),
            ('!', 5, 0), ('0', 5, 1), ('.', 5, 2), ('DEL', 5, 3), ('=', 5, 4, _C("#00FF66"))
        ]

        for i in range(6):
            teclado_frame.rowconfigure(i, weight=1)
        for j in range(5):
            teclado_frame.columnconfigure(j, weight=1)

        for config in botoes_calc:
            txt = config[0]
            r = config[1]
            c = config[2]
            cor = config[3] if len(config) > 3 else _C("#262626")
            txt_color = _C("#000000") if txt == "=" else COLOR_ACCENT
            
            btn = ctk.CTkButton(
                teclado_frame, text=txt, font=_f("Segoe UI", 16, "bold"), 
                fg_color=cor, text_color=txt_color, hover_color=COLOR_HOVER if len(config) <= 3 else None,
                command=lambda t=txt: self.click_calculadora(t)
            )
            btn.grid(row=r, column=c, sticky="nsew", padx=3, pady=3)

    def click_calculadora(self, valor):
        atual = self.display_calc.get()
        
        if valor == 'C':
            self.display_calc.delete(0, tk.END)
        elif valor == 'DEL':
            self.display_calc.delete(len(atual)-1, tk.END)
        elif valor == '=':
            try:
                expressao = atual.replace('^', '**').replace('pi', str(math.pi)).replace('e', str(math.e))
                expressao = expressao.replace('sin', 'math.sin').replace('cos', 'math.cos').replace('tan', 'math.tan')
                expressao = expressao.replace('log', 'math.log10').replace('ln', 'math.log').replace('sqrt', 'math.sqrt')
                
                while '!' in expressao:
                    idx = expressao.find('!')
                    num = ""
                    i = idx - 1
                    while i >= 0 and (expressao[i].isdigit() or expressao[i] == '.'):
                        num = expressao[i] + num
                        i -= 1
                    expressao = expressao[:i+1] + f"math.factorial({int(num)})" + expressao[idx+1:]

                resultado = eval(expressao)
                self.display_calc.delete(0, tk.END)
                self.display_calc.insert(tk.END, str(resultado))
            except Exception:
                self.display_calc.delete(0, tk.END)
                self.display_calc.insert(tk.END, "Erro")
        else:
            if atual == "Erro":
                self.display_calc.delete(0, tk.END)
            self.display_calc.insert(tk.END, valor)


    # ================= MÓDULO 5: CALCULADORA DE HORAS =================
    def setup_aba_horas(self):
        aba = self.frames_conteudo["⏱️ Calculadora de Horas"]

        # --- 1ª OPÇÃO: DIFERENÇA ENTRE HORAS ---
        frame_diff = ctk.CTkFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        frame_diff.pack(fill="x", padx=20, pady=(15, 10))
        ctk.CTkLabel(frame_diff, text="Diferença entre Horas", font=_f("Montserrat", 14, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(15, 5))

        row3 = ctk.CTkFrame(frame_diff, fg_color="transparent")
        row3.pack(pady=10)
        self.entry_hora_ini = ctk.CTkEntry(row3, placeholder_text="Hora Inicial (HH:MM)", width=130, justify="center")
        self.entry_hora_ini.pack(side="left", padx=10)
        self.entry_hora_fim = ctk.CTkEntry(row3, placeholder_text="Hora Final (HH:MM)", width=130, justify="center")
        self.entry_hora_fim.pack(side="left", padx=10)

        ctk.CTkButton(frame_diff, text="Calcular Diferença", command=self.diff_horas, fg_color=COLOR_VITA_BLUE, font=_f("Montserrat", 12, "bold")).pack(pady=10)

        self.lbl_res_horas_diff = ctk.CTkLabel(frame_diff, text="Resultado: --:--", font=_f("Montserrat", 16, "bold"))
        self.lbl_res_horas_diff.pack(pady=(5, 15))

        # --- 2ª OPÇÃO: SOMAR MÚLTIPLAS HORAS (IDÊNTICO À IMAGEM ANEXADA) ---
        frame_add = ctk.CTkFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        frame_add.pack(fill="both", expand=True, padx=20, pady=10)
        ctk.CTkLabel(frame_add, text="Somar Múltiplas Horas", font=_f("Montserrat", 14, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(15, 5))

        container_multislot = ctk.CTkFrame(frame_add, fg_color="transparent")
        container_multislot.pack(fill="both", expand=True, padx=15, pady=5)

        # Lado Esquerdo: Lista Rolável de Slots
        self.frame_slots_scroll = ctk.CTkScrollableFrame(container_multislot, fg_color="transparent", width=260)
        self.frame_slots_scroll.pack(side="left", fill="both", expand=True, padx=(0, 10))

        # Grid interno para alinhar as colunas com perfeição
        self.slots_container = ctk.CTkFrame(self.frame_slots_scroll, fg_color="transparent")
        self.slots_container.pack(anchor="center")

        # Cabeçalhos das colunas
        ctk.CTkLabel(self.slots_container, text="Horas", font=_f("Montserrat", 12, "bold"), text_color=COLOR_SUBTITLE).grid(row=0, column=0, padx=5, pady=(0, 5))
        ctk.CTkLabel(self.slots_container, text="", width=10).grid(row=0, column=1)
        ctk.CTkLabel(self.slots_container, text="Minutos", font=_f("Montserrat", 12, "bold"), text_color=COLOR_SUBTITLE).grid(row=0, column=2, padx=5, pady=(0, 5))

        # Lado Direito: Caixa de Resultado Grande e Botões de Controle
        frame_controle = ctk.CTkFrame(container_multislot, fg_color="transparent")
        frame_controle.pack(side="right", fill="y", padx=(10, 0), pady=10)

        ctk.CTkLabel(frame_controle, text="Resultado", font=_f("Montserrat", 12, "bold"), text_color=COLOR_ACCENT).pack(pady=(0, 5))
        
        # Caixa estilizada do resultado
        self.frame_res_box = ctk.CTkFrame(frame_controle, fg_color=_C("#1A1A1A"), border_width=1, border_color=_C("#444444"), width=140, height=70)
        self.frame_res_box.pack(pady=(0, 15))
        self.frame_res_box.pack_propagate(False)
        
        self.lbl_soma_total = ctk.CTkLabel(self.frame_res_box, text="00:00", font=_f("Segoe UI", 26, "bold"), text_color=COLOR_ACCENT)
        self.lbl_soma_total.place(relx=0.5, rely=0.5, anchor="center")

        # Botão Limpar
        self.btn_limpar_slots = ctk.CTkButton(frame_controle, text="Limpar", fg_color=COLOR_VITA_BLUE, hover_color=_C("#1A66CC"), font=_f("Montserrat", 12, "bold"), command=self.limpar_slots, width=120, height=35)
        self.btn_limpar_slots.pack(pady=5)

        # Botão para expandir slots extras
        self.btn_add_slot = ctk.CTkButton(frame_controle, text="+ Adicionar Slot", fg_color=_C("#262626"), border_width=1, border_color=COLOR_SUBTITLE, hover_color=COLOR_HOVER, font=_f("Montserrat", 11, "bold"), command=self.adicionar_slot, width=120, height=30)
        self.btn_add_slot.pack(pady=5)

        # Inicializa com 5 slots padrão
        self.slots_horas = []
        for _ in range(5):
            self.adicionar_slot()

    def adicionar_slot(self):
        idx = len(self.slots_horas) + 1
        
        entry_h = ctk.CTkEntry(self.slots_container, width=65, justify="center", placeholder_text="00")
        entry_h.grid(row=idx, column=0, padx=5, pady=4)
        entry_h.bind("<KeyRelease>", self.atualizar_soma_total)

        lbl_colon = ctk.CTkLabel(self.slots_container, text=":", font=_f("Segoe UI", 14, "bold"), text_color=COLOR_SUBTITLE)
        lbl_colon.grid(row=idx, column=1, pady=4)

        entry_m = ctk.CTkEntry(self.slots_container, width=65, justify="center", placeholder_text="00")
        entry_m.grid(row=idx, column=2, padx=5, pady=4)
        entry_m.bind("<KeyRelease>", self.atualizar_soma_total)

        self.slots_horas.append({"h": entry_h, "m": entry_m, "colon": lbl_colon})

    def atualizar_soma_total(self, *args):
        total_minutos = 0
        for slot in self.slots_horas:
            h_str = slot["h"].get().strip()
            m_str = slot["m"].get().strip()

            try:
                h = int(h_str) if h_str else 0
            except ValueError:
                h = 0
            
            try:
                m = int(m_str) if m_str else 0
            except ValueError:
                m = 0

            if h < 0:
                total_minutos += h * 60 - abs(m)
            else:
                total_minutos += h * 60 + m

        sign = "-" if total_minutos < 0 else ""
        total_minutos = abs(total_minutos)
        horas_f = total_minutos // 60
        minutos_f = total_minutos % 60

        self.lbl_soma_total.configure(text=f"{sign}{horas_f:02d}:{minutos_f:02d}")

    def limpar_slots(self):
        for slot in self.slots_horas:
            slot["h"].destroy()
            slot["m"].destroy()
            slot["colon"].destroy()
        self.slots_horas = []
        for _ in range(5):
            self.adicionar_slot()
        self.lbl_soma_total.configure(text="00:00")

    def parse_hora(self, hora_str):
        sinal = -1 if "-" in hora_str else 1
        hora_str = re.sub(r'[^\d]', '', hora_str)
        if len(hora_str) == 4:
            h, m = int(hora_str[:2]), int(hora_str[2:])
        elif len(hora_str) <= 2 and len(hora_str) > 0:
            h, m = int(hora_str), 0
        elif len(hora_str) == 3:
            h, m = int(hora_str[:1]), int(hora_str[1:])
        else:
            raise ValueError
        return timedelta(hours=h, minutes=m) * sinal

    def format_timedelta(self, td):
        total_seconds = int(td.total_seconds())
        sign = "-" if total_seconds < 0 else ""
        total_seconds = abs(total_seconds)
        return f"{sign}{total_seconds // 3600:02d}:{(total_seconds % 3600) // 60:02d}"

    def diff_horas(self):
        try:
            h1, h2 = self.parse_hora(self.entry_hora_ini.get()), self.parse_hora(self.entry_hora_fim.get())
            diff = h2 - h1
            if diff.total_seconds() < 0: diff += timedelta(hours=24)
            self.lbl_res_horas_diff.configure(text=f"Resultado: {self.format_timedelta(diff)}")
        except: messagebox.showerror("Erro", "Formato de hora inválido.")


    # ================= MÓDULO 6: CALCULADORA DE DATAS =================
    def setup_aba_datas(self):
        aba = self.frames_conteudo["📅 Calculadora de Datas"]

        frame_add = ctk.CTkFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        frame_add.pack(fill="x", padx=20, pady=(15, 10))
        ctk.CTkLabel(frame_add, text="Somar ou Subtrair Dias", font=_f("Montserrat", 14, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(15, 5))

        row1 = ctk.CTkFrame(frame_add, fg_color="transparent")
        row1.pack(pady=10)
        self.entry_data1 = ctk.CTkEntry(row1, placeholder_text="DD/MM/AAAA", width=140, justify="center")
        self.entry_data1.pack(side="left", padx=10)
        self.entry_dias = ctk.CTkEntry(row1, placeholder_text="Dias (ex: 5, -3)", width=140, justify="center")
        self.entry_dias.pack(side="left", padx=10)

        ctk.CTkButton(frame_add, text="Calcular", command=self.calc_dias, fg_color=COLOR_VITA_BLUE, font=_f("Montserrat", 12, "bold")).pack(pady=10)
        self.lbl_res_data_add = ctk.CTkLabel(frame_add, text="Resultado: --/--/----", font=_f("Montserrat", 16, "bold"))
        self.lbl_res_data_add.pack(pady=(5, 15))


        frame_diff = ctk.CTkFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        frame_diff.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(frame_diff, text="Diferença entre Datas", font=_f("Montserrat", 14, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(15, 5))

        row2 = ctk.CTkFrame(frame_diff, fg_color="transparent")
        row2.pack(pady=10)
        self.entry_data_ini = ctk.CTkEntry(row2, placeholder_text="Data Inicial", width=140, justify="center")
        self.entry_data_ini.pack(side="left", padx=10)
        self.entry_data_fim = ctk.CTkEntry(row2, placeholder_text="Data Final", width=140, justify="center")
        self.entry_data_fim.pack(side="left", padx=10)

        ctk.CTkButton(frame_diff, text="Calcular Diferença", command=self.diff_datas, fg_color=COLOR_VITA_BLUE, font=_f("Montserrat", 12, "bold")).pack(pady=10)
        self.lbl_res_data_diff = ctk.CTkLabel(frame_diff, text="Resultado: -- dias", font=_f("Montserrat", 16, "bold"))
        self.lbl_res_data_diff.pack(pady=(5, 15))

    def parse_data(self, data_str):
        data_str = re.sub(r'[^\d]', '', data_str)
        if len(data_str) == 8:
            return datetime.strptime(data_str, "%d%m%Y")
        elif len(data_str) == 6:
            return datetime.strptime(data_str, "%d%m%y")
        else:
            raise ValueError

    def calc_dias(self):
        try:
            d = self.parse_data(self.entry_data1.get())
            dias = int(self.entry_dias.get())
            res = d + timedelta(days=dias)
            self.lbl_res_data_add.configure(text=f"Resultado: {res.strftime('%d/%m/%Y')}")
            
            self.entry_data1.delete(0, 'end')
            self.entry_data1.insert(0, d.strftime('%d/%m/%Y'))
        except: messagebox.showerror("Erro", "Verifique as datas e valores informados. Padrão: DD/MM/AAAA ou DDMMAAAA")

    def diff_datas(self):
        try:
            d1, d2 = self.parse_data(self.entry_data_ini.get()), self.parse_data(self.entry_data_fim.get())
            res = (d2 - d1).days
            self.lbl_res_data_diff.configure(text=f"Resultado: {abs(res)} dias")
            
            self.entry_data_ini.delete(0, 'end')
            self.entry_data_ini.insert(0, d1.strftime('%d/%m/%Y'))
            self.entry_data_fim.delete(0, 'end')
            self.entry_data_fim.insert(0, d2.strftime('%d/%m/%Y'))
        except: messagebox.showerror("Erro", "Verifique as datas informadas. Padrão: DD/MM/AAAA ou DDMMAAAA")


    # ================= MÓDULO 7: UNIR E SEPARAR PDFs =================
    def setup_aba_pdf_tools(self):
        aba = self.frames_conteudo["✂️ Unir e Separar PDFs"]

        frame_unir = ctk.CTkFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        frame_unir.pack(fill="x", padx=20, pady=(30, 15))

        ctk.CTkLabel(frame_unir, text="UNIR PDFs", font=_f("Montserrat", 16, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(20, 10))
        ctk.CTkLabel(frame_unir, text="Selecione múltiplos arquivos PDF para juntá-los em um só.", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE).pack(pady=(0, 15))
        ctk.CTkButton(frame_unir, text="Selecionar e Unir PDFs", width=200, height=40, font=_f("Montserrat", 12, "bold"), command=self.unir_pdfs, fg_color=COLOR_ACCENT, text_color=COLOR_BG, hover_color=COLOR_HOVER_WHITE).pack(pady=(5, 25))

        frame_separar = ctk.CTkFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        frame_separar.pack(fill="x", padx=20, pady=15)

        ctk.CTkLabel(frame_separar, text="SEPARAR PDF", font=_f("Montserrat", 16, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(20, 10))
        ctk.CTkLabel(frame_separar, text="Selecione um arquivo PDF para separá-lo página por página.", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE).pack(pady=(0, 15))
        ctk.CTkButton(frame_separar, text="Selecionar e Separar PDF", width=200, height=40, font=_f("Montserrat", 12, "bold"), command=self.separar_pdfs, fg_color=COLOR_ACCENT, text_color=COLOR_BG, hover_color=COLOR_HOVER_WHITE).pack(pady=(5, 25))

    def unir_pdfs(self):
        arquivos = filedialog.askopenfilenames(title="Selecione os PDFs para unir", filetypes=[("Arquivos PDF", "*.pdf")])
        if arquivos:
            writer = PdfWriter()
            for arquivo in arquivos:
                try:
                    reader = PdfReader(arquivo)
                    for page in reader.pages:
                        writer.add_page(page)
                except Exception as e:
                    messagebox.showerror("Erro", f"Erro ao ler o arquivo {arquivo}:\n{e}")
                    return
            
            saida = filedialog.asksaveasfilename(title="Salvar PDF Unido como...", defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
            if saida:
                with open(saida, "wb") as f:
                    writer.write(f)
                messagebox.showinfo("Sucesso", "PDFs unidos com sucesso!")

    def separar_pdfs(self):
        arquivo = filedialog.askopenfilename(title="Selecione o PDF para separar", filetypes=[("Arquivos PDF", "*.pdf")])
        if arquivo:
            pasta_saida = filedialog.askdirectory(title="Selecione a pasta para salvar as páginas separadas")
            if pasta_saida:
                try:
                    reader = PdfReader(arquivo)
                    base_name = os.path.splitext(os.path.basename(arquivo))[0]
                    for i, page in enumerate(reader.pages):
                        writer = PdfWriter()
                        writer.add_page(page)
                        saida = os.path.join(pasta_saida, f"{base_name}_pag_{i+1}.pdf")
                        with open(saida, "wb") as f:
                            writer.write(f)
                    messagebox.showinfo("Sucesso", f"PDF separado em {len(reader.pages)} arquivos com sucesso!")
                except Exception as e:
                    messagebox.showerror("Erro", f"Erro ao separar o PDF:\n{e}")

    # ================= MÓDULO 8: PDF <-> JPG/PNG =================
    def setup_aba_pdf_imagem(self):
        aba = self.frames_conteudo["🖼️ PDF ↔ JPG/PNG"]

        frame_pdf_para_img = ctk.CTkFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        frame_pdf_para_img.pack(fill="x", padx=20, pady=(30, 15))

        ctk.CTkLabel(frame_pdf_para_img, text="PDF PARA IMAGEM", font=_f("Montserrat", 16, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(20, 10))
        ctk.CTkLabel(frame_pdf_para_img, text="Selecione um PDF para converter cada página em uma imagem.", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE).pack(pady=(0, 15))

        frame_botoes_pdf_img = ctk.CTkFrame(frame_pdf_para_img, fg_color="transparent")
        frame_botoes_pdf_img.pack(pady=(5, 25))
        ctk.CTkButton(frame_botoes_pdf_img, text="Converter para JPG", width=170, height=40, font=_f("Montserrat", 12, "bold"), command=lambda: self.pdf_para_imagem("JPEG"), fg_color=COLOR_ACCENT, text_color=COLOR_BG, hover_color=COLOR_HOVER_WHITE).pack(side="left", padx=(0, 10))
        ctk.CTkButton(frame_botoes_pdf_img, text="Converter para PNG", width=170, height=40, font=_f("Montserrat", 12, "bold"), command=lambda: self.pdf_para_imagem("PNG"), fg_color=COLOR_ACCENT, text_color=COLOR_BG, hover_color=COLOR_HOVER_WHITE).pack(side="left")

        frame_img_para_pdf = ctk.CTkFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        frame_img_para_pdf.pack(fill="x", padx=20, pady=15)

        ctk.CTkLabel(frame_img_para_pdf, text="IMAGEM PARA PDF", font=_f("Montserrat", 16, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(20, 10))
        ctk.CTkLabel(frame_img_para_pdf, text="Selecione uma ou mais imagens (JPG/PNG) para juntá-las em um único PDF.", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE).pack(pady=(0, 15))
        ctk.CTkButton(frame_img_para_pdf, text="Selecionar Imagens e Gerar PDF", width=230, height=40, font=_f("Montserrat", 12, "bold"), command=self.imagem_para_pdf, fg_color=COLOR_ACCENT, text_color=COLOR_BG, hover_color=COLOR_HOVER_WHITE).pack(pady=(5, 25))

    def pdf_para_imagem(self, formato):
        arquivo = filedialog.askopenfilename(title="Selecione o PDF", filetypes=[("Arquivos PDF", "*.pdf")])
        if not arquivo:
            return
        pasta_saida = filedialog.askdirectory(title="Selecione a pasta para salvar as imagens")
        if not pasta_saida:
            return
        try:
            extensao = "jpg" if formato == "JPEG" else "png"
            documento = fitz.open(arquivo)
            base_name = os.path.splitext(os.path.basename(arquivo))[0]
            matriz = fitz.Matrix(2.0, 2.0)  # zoom 2x (~144 DPI), boa qualidade sem arquivos gigantes
            total_paginas = documento.page_count
            for i in range(total_paginas):
                pagina = documento.load_page(i)
                pixmap = pagina.get_pixmap(matrix=matriz)
                caminho_saida = os.path.join(pasta_saida, f"{base_name}_pag_{i + 1}.{extensao}")
                if formato == "JPEG":
                    # PyMuPDF não salva .jpg diretamente com boa compressão; convertemos via Pillow.
                    imagem = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                    imagem.save(caminho_saida, "JPEG", quality=95)
                else:
                    pixmap.save(caminho_saida)
            documento.close()
            messagebox.showinfo("Sucesso", f"PDF convertido em {total_paginas} imagem(ns) .{extensao.upper()} com sucesso!")
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao converter o PDF em imagem:\n{e}")

    def imagem_para_pdf(self):
        arquivos = filedialog.askopenfilenames(title="Selecione as imagens (JPG/PNG)", filetypes=[("Imagens", "*.jpg *.jpeg *.png"), ("JPG", "*.jpg *.jpeg"), ("PNG", "*.png")])
        if not arquivos:
            return
        saida = filedialog.asksaveasfilename(title="Salvar PDF como...", defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
        if not saida:
            return
        try:
            imagens = []
            for caminho in arquivos:
                imagem = Image.open(caminho)
                if imagem.mode != "RGB":
                    imagem = imagem.convert("RGB")
                imagens.append(imagem)

            primeira_imagem, *demais_imagens = imagens
            primeira_imagem.save(saida, save_all=True, append_images=demais_imagens)
            messagebox.showinfo("Sucesso", f"{len(imagens)} imagem(ns) convertida(s) em PDF com sucesso!")
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao converter as imagens em PDF:\n{e}")

    # ================= MÓDULO 9: PNG <-> JPG =================
    def setup_aba_png_jpg(self):
        aba = self.frames_conteudo["🔁 PNG ↔ JPG"]

        frame_png_para_jpg = ctk.CTkFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        frame_png_para_jpg.pack(fill="x", padx=20, pady=(30, 15))

        ctk.CTkLabel(frame_png_para_jpg, text="PNG PARA JPG", font=_f("Montserrat", 16, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(20, 10))
        ctk.CTkLabel(frame_png_para_jpg, text="Selecione uma ou mais imagens PNG para converter em JPG.", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE).pack(pady=(0, 15))
        ctk.CTkButton(frame_png_para_jpg, text="Selecionar e Converter para JPG", width=230, height=40, font=_f("Montserrat", 12, "bold"), command=lambda: self.converter_png_jpg("JPEG"), fg_color=COLOR_ACCENT, text_color=COLOR_BG, hover_color=COLOR_HOVER_WHITE).pack(pady=(5, 25))

        frame_jpg_para_png = ctk.CTkFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        frame_jpg_para_png.pack(fill="x", padx=20, pady=15)

        ctk.CTkLabel(frame_jpg_para_png, text="JPG PARA PNG", font=_f("Montserrat", 16, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(20, 10))
        ctk.CTkLabel(frame_jpg_para_png, text="Selecione uma ou mais imagens JPG para converter em PNG.", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE).pack(pady=(0, 15))
        ctk.CTkButton(frame_jpg_para_png, text="Selecionar e Converter para PNG", width=230, height=40, font=_f("Montserrat", 12, "bold"), command=lambda: self.converter_png_jpg("PNG"), fg_color=COLOR_ACCENT, text_color=COLOR_BG, hover_color=COLOR_HOVER_WHITE).pack(pady=(5, 25))

    def converter_png_jpg(self, formato_destino):
        if formato_destino == "JPEG":
            arquivos = filedialog.askopenfilenames(title="Selecione as imagens PNG", filetypes=[("Imagens PNG", "*.png")])
        else:
            arquivos = filedialog.askopenfilenames(title="Selecione as imagens JPG", filetypes=[("Imagens JPG", "*.jpg *.jpeg")])
        if not arquivos:
            return

        pasta_saida = filedialog.askdirectory(title="Selecione a pasta para salvar as imagens convertidas")
        if not pasta_saida:
            return

        convertidas = 0
        for caminho in arquivos:
            try:
                imagem = Image.open(caminho)
                nome_sem_ext = os.path.splitext(os.path.basename(caminho))[0]
                if formato_destino == "JPEG":
                    if imagem.mode in ("RGBA", "P"):
                        imagem = imagem.convert("RGB")
                    caminho_saida = os.path.join(pasta_saida, f"{nome_sem_ext}.jpg")
                    imagem.save(caminho_saida, "JPEG", quality=95)
                else:
                    caminho_saida = os.path.join(pasta_saida, f"{nome_sem_ext}.png")
                    imagem.save(caminho_saida, "PNG")
                convertidas += 1
            except Exception as e:
                print(f"Erro ao converter {caminho}: {e}")

        extensao = "JPG" if formato_destino == "JPEG" else "PNG"
        messagebox.showinfo("Sucesso", f"{convertidas} imagem(ns) convertida(s) para .{extensao} com sucesso!")

    # ================= MÓDULO 10: XML/CSV PARA EXCEL =================
    def setup_aba_xml_csv_excel(self):
        aba = self.frames_conteudo["📊 XML/CSV para Excel (BETA)"]

        frame_conversor = ctk.CTkFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        frame_conversor.pack(fill="x", padx=20, pady=(30, 15))

        ctk.CTkLabel(frame_conversor, text="XML/CSV PARA EXCEL (BETA)", font=_f("Montserrat", 16, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(20, 10))
        ctk.CTkLabel(
            frame_conversor,
            text="Selecione um arquivo .xml ou .csv para convertê-lo em uma\nplanilha Excel (.xlsx) já formatada.",
            font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE, justify="center"
        ).pack(pady=(0, 15))
        ctk.CTkButton(frame_conversor, text="Selecionar Arquivo e Gerar Excel", width=230, height=40, font=_f("Montserrat", 12, "bold"), command=self.converter_xml_csv_para_excel, fg_color=COLOR_ACCENT, text_color=COLOR_BG, hover_color=COLOR_HOVER_WHITE).pack(pady=(5, 25))

    def converter_xml_csv_para_excel(self):
        arquivo = filedialog.askopenfilename(
            title="Selecione o arquivo XML ou CSV",
            filetypes=[("XML ou CSV", "*.xml *.csv"), ("Arquivo XML", "*.xml"), ("Arquivo CSV", "*.csv")]
        )
        if not arquivo:
            return

        try:
            extensao = os.path.splitext(arquivo)[1].lower()

            # ---- Etapa 1: leitura com pandas ----
            if extensao == ".csv":
                try:
                    dados = pd.read_csv(arquivo, sep=None, engine="python", encoding="utf-8-sig")
                except Exception:
                    dados = pd.read_csv(arquivo, sep=";", encoding="latin-1")
            elif extensao == ".xml":
                dados = pd.read_xml(arquivo)
            else:
                messagebox.showwarning("Aviso", "Selecione um arquivo .xml ou .csv.")
                return

            if dados.empty:
                messagebox.showinfo("Informação", "Nenhum dado foi encontrado no arquivo selecionado.")
                return

            # ---- Etapa 2: limpeza e transformação simples dos dados ----
            dados = dados.dropna(how="all")
            for coluna in dados.select_dtypes(include="object").columns:
                dados[coluna] = dados[coluna].str.strip()

            saida = filedialog.asksaveasfilename(title="Salvar planilha Excel como...", defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
            if not saida:
                return

            # ---- Etapa 3: escrita formatada com openpyxl (via pandas.ExcelWriter) ----
            with pd.ExcelWriter(saida, engine="openpyxl") as escritor:
                dados.to_excel(escritor, index=False, sheet_name="Dados")
                planilha = escritor.sheets["Dados"]

                for celula in planilha[1]:
                    celula.font = Font(bold=True)

                for coluna_celulas in planilha.columns:
                    letra_coluna = coluna_celulas[0].column_letter
                    maior_largura = max((len(str(c.value)) for c in coluna_celulas if c.value is not None), default=10)
                    planilha.column_dimensions[letra_coluna].width = min(maior_largura + 2, 50)

            messagebox.showinfo("Sucesso", f"Arquivo convertido para Excel com sucesso!\n{len(dados)} linha(s) exportada(s).")
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao converter o arquivo para Excel:\n{e}")

    # ================= MÓDULO 11: LEITOR DE NF-E (BETA) =================
    def setup_aba_nfe(self):
        aba = self.frames_conteudo["🧾 Leitor de NF-e (BETA)"]
        self.nfe_dados_extraidos = None  # guarda o último XML lido, para o botão de exportar

        frame_topo = ctk.CTkFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        frame_topo.pack(fill="x", padx=20, pady=(30, 15))

        ctk.CTkLabel(frame_topo, text="LEITOR DE NF-E (BETA)", font=_f("Montserrat", 16, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(20, 10))
        ctk.CTkLabel(
            frame_topo,
            text="Selecione o XML de uma Nota Fiscal Eletrônica para extrair chave de acesso,\nemitente, destinatário, valores e itens.",
            font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE, justify="center"
        ).pack(pady=(0, 15))

        frame_botoes_nfe = ctk.CTkFrame(frame_topo, fg_color="transparent")
        frame_botoes_nfe.pack(pady=(5, 25))
        ctk.CTkButton(frame_botoes_nfe, text="Selecionar XML e Extrair Dados", width=220, height=40, font=_f("Montserrat", 12, "bold"), command=self.ler_xml_nfe, fg_color=COLOR_ACCENT, text_color=COLOR_BG, hover_color=COLOR_HOVER_WHITE).pack(side="left", padx=(0, 10))
        self.btn_exportar_nfe = ctk.CTkButton(frame_botoes_nfe, text="Exportar para Excel", width=170, height=40, font=_f("Montserrat", 12, "bold"), command=self.exportar_nfe_excel, fg_color="transparent", border_width=1, border_color=COLOR_SUBTITLE, text_color=COLOR_ACCENT, hover_color=COLOR_HOVER, state="disabled")
        self.btn_exportar_nfe.pack(side="left")

        self.textbox_nfe = ctk.CTkTextbox(aba, fg_color=_C("#1A1A1A"), text_color=_C("#FFFFFF"), font=_f("Consolas", 12), border_width=0, wrap="word")
        self.textbox_nfe.pack(expand=True, fill="both", padx=20, pady=(0, 20))
        self.textbox_nfe.insert("1.0", "Nenhuma NF-e carregada ainda.")
        self.textbox_nfe.configure(state="disabled")

    def _texto_xml_nfe(self, elemento, caminho):
        """Busca um campo dentro de um elemento do XML da NF-e, já tratando namespace e texto vazio."""
        if elemento is None:
            return ""
        alvo = elemento.find(caminho, NFE_NAMESPACE)
        return alvo.text.strip() if alvo is not None and alvo.text else ""

    def extrair_dados_nfe(self, caminho_arquivo):
        arvore = etree.parse(caminho_arquivo)
        raiz = arvore.getroot()

        # Funciona tanto para o XML "cru" da NF-e quanto para o protocolo completo
        # (nfeProc), já que procuramos a tag <infNFe> em qualquer profundidade.
        inf_nfe = raiz.find(".//nfe:infNFe", NFE_NAMESPACE)
        if inf_nfe is None:
            raise ValueError("Não foi encontrada a tag <infNFe> -- o arquivo selecionado não parece ser um XML de NF-e válido.")

        chave_acesso = (inf_nfe.get("Id") or "").replace("NFe", "", 1).strip()

        ide = inf_nfe.find("nfe:ide", NFE_NAMESPACE)
        emit = inf_nfe.find("nfe:emit", NFE_NAMESPACE)
        dest = inf_nfe.find("nfe:dest", NFE_NAMESPACE)
        total = inf_nfe.find("nfe:total/nfe:ICMSTot", NFE_NAMESPACE)

        cabecalho = {
            "Chave de Acesso": chave_acesso,
            "Número da NF-e": self._texto_xml_nfe(ide, "nfe:nNF"),
            "Série": self._texto_xml_nfe(ide, "nfe:serie"),
            "Data de Emissão": self._texto_xml_nfe(ide, "nfe:dhEmi") or self._texto_xml_nfe(ide, "nfe:dEmi"),
            "Natureza da Operação": self._texto_xml_nfe(ide, "nfe:natOp"),
            "Emitente": self._texto_xml_nfe(emit, "nfe:xNome"),
            "CNPJ/CPF Emitente": self._texto_xml_nfe(emit, "nfe:CNPJ") or self._texto_xml_nfe(emit, "nfe:CPF"),
            "Destinatário": self._texto_xml_nfe(dest, "nfe:xNome"),
            "CNPJ/CPF Destinatário": self._texto_xml_nfe(dest, "nfe:CNPJ") or self._texto_xml_nfe(dest, "nfe:CPF"),
            "Valor Total da NF-e": self._texto_xml_nfe(total, "nfe:vNF"),
            "Valor dos Produtos": self._texto_xml_nfe(total, "nfe:vProd"),
            "Valor do ICMS": self._texto_xml_nfe(total, "nfe:vICMS"),
            "Valor do IPI": self._texto_xml_nfe(total, "nfe:vIPI"),
        }

        itens = []
        for det in inf_nfe.findall("nfe:det", NFE_NAMESPACE):
            prod = det.find("nfe:prod", NFE_NAMESPACE)
            if prod is None:
                continue
            itens.append({
                "Item": det.get("nItem", ""),
                "Código": self._texto_xml_nfe(prod, "nfe:cProd"),
                "Descrição": self._texto_xml_nfe(prod, "nfe:xProd"),
                "NCM": self._texto_xml_nfe(prod, "nfe:NCM"),
                "CFOP": self._texto_xml_nfe(prod, "nfe:CFOP"),
                "Qtd.": self._texto_xml_nfe(prod, "nfe:qCom"),
                "Unid.": self._texto_xml_nfe(prod, "nfe:uCom"),
                "Valor Unit.": self._texto_xml_nfe(prod, "nfe:vUnCom"),
                "Valor Total": self._texto_xml_nfe(prod, "nfe:vProd"),
            })

        return cabecalho, itens

    def ler_xml_nfe(self):
        arquivo = filedialog.askopenfilename(title="Selecione o XML da NF-e", filetypes=[("Arquivo XML", "*.xml")])
        if not arquivo:
            return
        try:
            cabecalho, itens = self.extrair_dados_nfe(arquivo)
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao ler o XML da NF-e:\n{e}")
            return

        self.nfe_dados_extraidos = {"cabecalho": cabecalho, "itens": itens}

        linhas = ["===== DADOS DA NOTA =====\n\n"]
        for chave, valor in cabecalho.items():
            linhas.append(f"{chave}: {valor or '-'}\n")

        linhas.append(f"\n===== ITENS ({len(itens)}) =====\n\n")
        if itens:
            for item in itens:
                linhas.append(
                    f"[{item['Item']}] {item['Descrição']}\n"
                    f"    NCM {item['NCM']} | CFOP {item['CFOP']} | Qtd {item['Qtd.']} {item['Unid.']} | "
                    f"Unit. {item['Valor Unit.']} | Total {item['Valor Total']}\n"
                )
        else:
            linhas.append("Nenhum item encontrado.\n")

        self.textbox_nfe.configure(state="normal")
        self.textbox_nfe.delete("1.0", "end")
        self.textbox_nfe.insert("1.0", "".join(linhas))
        self.textbox_nfe.configure(state="disabled")

        self.btn_exportar_nfe.configure(state="normal")

    def exportar_nfe_excel(self):
        if not self.nfe_dados_extraidos:
            messagebox.showwarning("Aviso", "Leia uma NF-e primeiro.")
            return

        saida = filedialog.asksaveasfilename(title="Salvar planilha da NF-e como...", defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
        if not saida:
            return

        try:
            cabecalho = self.nfe_dados_extraidos["cabecalho"]
            itens = self.nfe_dados_extraidos["itens"]

            colunas_itens = ["Item", "Código", "Descrição", "NCM", "CFOP", "Qtd.", "Unid.", "Valor Unit.", "Valor Total"]
            dados_cabecalho = pd.DataFrame(list(cabecalho.items()), columns=["Campo", "Valor"])
            dados_itens = pd.DataFrame(itens, columns=colunas_itens) if itens else pd.DataFrame(columns=colunas_itens)

            with pd.ExcelWriter(saida, engine="openpyxl") as escritor:
                dados_cabecalho.to_excel(escritor, index=False, sheet_name="Resumo")
                dados_itens.to_excel(escritor, index=False, sheet_name="Itens")

                for nome_planilha in ("Resumo", "Itens"):
                    planilha = escritor.sheets[nome_planilha]
                    for celula in planilha[1]:
                        celula.font = Font(bold=True)
                    for coluna_celulas in planilha.columns:
                        letra_coluna = coluna_celulas[0].column_letter
                        maior_largura = max((len(str(c.value)) for c in coluna_celulas if c.value is not None), default=10)
                        planilha.column_dimensions[letra_coluna].width = min(maior_largura + 2, 50)

            messagebox.showinfo("Sucesso", "Dados da NF-e exportados para Excel com sucesso!")
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao exportar a NF-e para Excel:\n{e}")

    def _definir_texto(self, textbox, texto):
        textbox.configure(state="normal")
        textbox.delete("1.0", "end")
        textbox.insert("1.0", texto)
        textbox.configure(state="disabled")

    def _copiar_para_area(self, texto):
        try:
            self.clipboard_clear()
            self.clipboard_append(texto)
            self.update()
        except Exception:
            pass

    # ================= MÓDULO 3D: PRAZOS DE VENCIMENTO =================
    DIAS_SEMANA = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]

    def carregar_dados_prazos(self):
        self.prazos_data = {"avisar": True, "itens": []}
        if os.path.exists(ARQUIVO_PRAZOS):
            try:
                with open(ARQUIVO_PRAZOS, "r", encoding="utf-8") as f:
                    dados = json.load(f)
                if isinstance(dados, dict) and isinstance(dados.get("itens"), list):
                    self.prazos_data = {"avisar": bool(dados.get("avisar", True)), "itens": dados["itens"]}
            except Exception:
                pass

    def salvar_dados_prazos(self):
        try:
            with open(ARQUIVO_PRAZOS, "w", encoding="utf-8") as f:
                json.dump(self.prazos_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao salvar os prazos: {e}")

    def setup_aba_prazos(self):
        aba = self.frames_conteudo["📆 Prazos de Vencimento"]
        self.carregar_dados_prazos()

        # --- Cartão 1: dia útil do vencimento ---
        card1 = ctk.CTkFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        card1.pack(fill="x", padx=15, pady=(10, 8))
        ctk.CTkLabel(card1, text="O VENCIMENTO CAI EM DIA ÚTIL?", font=_f("Montserrat", 13, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(12, 6))
        linha = ctk.CTkFrame(card1, fg_color="transparent")
        linha.pack()
        self.entry_dia_util = ctk.CTkEntry(linha, placeholder_text="DD/MM/AAAA", width=150, height=34, justify="center", fg_color=_C("#1A1A1A"), border_width=0)
        self.entry_dia_util.pack(side="left", padx=(0, 8))
        self.entry_dia_util.bind("<Return>", lambda e: self.verificar_dia_util())
        ctk.CTkButton(linha, text="Verificar", width=90, height=34, fg_color=COLOR_VITA_BLUE, font=_f("Montserrat", 12, "bold"), command=self.verificar_dia_util).pack(side="left")
        self.var_fac_prazos = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(card1, text="Tratar Carnaval e Corpus Christi como sem expediente bancário", variable=self.var_fac_prazos, font=_f("Montserrat", 11), text_color=COLOR_SUBTITLE, fg_color=COLOR_VITA_BLUE).pack(pady=(8, 4))
        self.lbl_dia_util = ctk.CTkLabel(card1, text="Considera feriados nacionais (estaduais e municipais não entram).", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE, justify="left", wraplength=560)
        self.lbl_dia_util.pack(padx=15, pady=(2, 12))

        # --- Cartão 2: lista de prazos ---
        card2 = ctk.CTkFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        card2.pack(expand=True, fill="both", padx=15, pady=(0, 10))
        cab = ctk.CTkFrame(card2, fg_color="transparent")
        cab.pack(fill="x", padx=15, pady=(12, 6))
        ctk.CTkLabel(cab, text="MEUS PRAZOS", font=_f("Montserrat", 13, "bold"), text_color=COLOR_VITA_BLUE).pack(side="left")
        self.var_avisar_prazos = ctk.BooleanVar(value=self.prazos_data.get("avisar", True))
        ctk.CTkSwitch(cab, text="Avisar ao abrir o app", variable=self.var_avisar_prazos, command=self._alternar_aviso_prazos, font=_f("Montserrat", 11), text_color=COLOR_SUBTITLE).pack(side="right")

        add = ctk.CTkFrame(card2, fg_color="transparent")
        add.pack(fill="x", padx=15)
        self.entry_prazo_desc = ctk.CTkEntry(add, placeholder_text="Descrição (ex.: DAS - Cliente X)", height=34, fg_color=_C("#1A1A1A"), border_width=0)
        self.entry_prazo_desc.pack(side="left", expand=True, fill="x", padx=(0, 8))
        self.entry_prazo_data = ctk.CTkEntry(add, placeholder_text="DD/MM/AAAA", width=110, height=34, justify="center", fg_color=_C("#1A1A1A"), border_width=0)
        self.entry_prazo_data.pack(side="left", padx=(0, 8))
        self.entry_prazo_data.bind("<Return>", lambda e: self.adicionar_prazo())
        ctk.CTkButton(add, text="Adicionar", width=90, height=34, fg_color=COLOR_VITA_BLUE, font=_f("Montserrat", 12, "bold"), command=self.adicionar_prazo).pack(side="left")

        self.scroll_prazos = ctk.CTkScrollableFrame(card2, fg_color=_C("#1A1A1A"), corner_radius=8)
        self.scroll_prazos.pack(expand=True, fill="both", padx=15, pady=12)
        self._renderizar_prazos()
        self.after(1500, self._avisar_prazos_ao_abrir)

    def _eh_util(self, d, facultativos):
        return d.weekday() < 5 and d not in _feriados_br(d.year, facultativos)

    def _motivo_nao_util(self, d, facultativos):
        if d.weekday() == 5: return "sábado"
        if d.weekday() == 6: return "domingo"
        nome = _feriados_br(d.year, facultativos).get(d)
        return f"feriado: {nome}" if nome else None

    def _dia_util_vizinho(self, d, passo, facultativos):
        while True:
            d += timedelta(days=passo)
            if self._eh_util(d, facultativos):
                return d

    def verificar_dia_util(self):
        try:
            d = self.parse_data(self.entry_dia_util.get()).date()
        except ValueError:
            messagebox.showerror("Erro", "Data inválida. Use DD/MM/AAAA ou DDMMAAAA.")
            return
        self.entry_dia_util.delete(0, "end")
        self.entry_dia_util.insert(0, d.strftime("%d/%m/%Y"))
        fac = self.var_fac_prazos.get()
        motivo = self._motivo_nao_util(d, fac)
        fmt = lambda x: f"{x.strftime('%d/%m/%Y')} ({self.DIAS_SEMANA[x.weekday()]})"
        if motivo is None:
            self.lbl_dia_util.configure(text=f"✔ {fmt(d)} é dia útil: vence normalmente.", text_color=_C("#00FF66"))
        else:
            ant = self._dia_util_vizinho(d, -1, fac)
            prox = self._dia_util_vizinho(d, 1, fac)
            self.lbl_dia_util.configure(
                text=f"✖ {fmt(d)} não é dia útil ({motivo}).\nDia útil anterior (se antecipar): {fmt(ant)}\nPróximo dia útil (se prorrogar): {fmt(prox)}\nConfira na legislação se o tributo antecipa ou prorroga.",
                text_color=_C("#FFB300"))

    def _status_prazo(self, item):
        d = datetime.strptime(item["data"], "%Y-%m-%d").date()
        if item.get("concluido"):
            return "Concluído", COLOR_SUBTITLE
        delta = (d - datetime.now().date()).days
        if delta < 0: texto, cor = f"Vencido há {-delta} dia(s)", COLOR_DANGER
        elif delta == 0: texto, cor = "Vence hoje", _C("#FFB300")
        elif delta == 1: texto, cor = "Vence amanhã", _C("#FFB300")
        elif delta <= 3: texto, cor = f"Faltam {delta} dias", _C("#FFB300")
        else: texto, cor = f"Faltam {delta} dias", _C("#00FF66")
        if not self._eh_util(d, True):
            texto += "  •  cai em dia não útil"
        return texto, cor

    def adicionar_prazo(self):
        descricao = self.entry_prazo_desc.get().strip()
        if not descricao:
            messagebox.showwarning("Atenção", "Digite a descrição do prazo.")
            return
        try:
            d = self.parse_data(self.entry_prazo_data.get())
        except ValueError:
            messagebox.showerror("Erro", "Data inválida. Use DD/MM/AAAA ou DDMMAAAA.")
            return
        self.prazos_data["itens"].append({"id": str(uuid.uuid4()), "descricao": descricao, "data": d.strftime("%Y-%m-%d"), "concluido": False})
        self.salvar_dados_prazos()
        self.entry_prazo_desc.delete(0, "end")
        self.entry_prazo_data.delete(0, "end")
        self._renderizar_prazos()

    def _concluir_prazo(self, prazo_id):
        for item in self.prazos_data["itens"]:
            if item.get("id") == prazo_id:
                item["concluido"] = not item.get("concluido", False)
        self.salvar_dados_prazos()
        self._renderizar_prazos()

    def _excluir_prazo(self, prazo_id):
        if messagebox.askyesno("Confirmar", "Excluir este prazo?"):
            self.prazos_data["itens"] = [i for i in self.prazos_data["itens"] if i.get("id") != prazo_id]
            self.salvar_dados_prazos()
            self._renderizar_prazos()

    def _alternar_aviso_prazos(self):
        self.prazos_data["avisar"] = bool(self.var_avisar_prazos.get())
        self.salvar_dados_prazos()

    def _renderizar_prazos(self):
        for w in self.scroll_prazos.winfo_children():
            w.destroy()
        validos = []
        for item in self.prazos_data["itens"]:
            try:
                validos.append((item.get("concluido", False), datetime.strptime(item["data"], "%Y-%m-%d").date(), item))
            except Exception:
                continue
        if not validos:
            ctk.CTkLabel(self.scroll_prazos, text="Nenhum prazo cadastrado.", font=_f("Montserrat", 12, "italic"), text_color=COLOR_SUBTITLE).pack(pady=25)
            return
        for concluido, d, item in sorted(validos, key=lambda x: (x[0], x[1])):
            linha = ctk.CTkFrame(self.scroll_prazos, fg_color=_C("#262626"), corner_radius=8)
            linha.pack(fill="x", pady=3, padx=3)
            ctk.CTkButton(linha, text="✖", width=30, height=28, fg_color="transparent", hover_color=COLOR_DANGER, text_color=COLOR_ACCENT, command=lambda i=item["id"]: self._excluir_prazo(i)).pack(side="right", padx=(0, 6))
            ctk.CTkButton(linha, text="↺" if concluido else "✔", width=30, height=28, fg_color="transparent", hover_color=COLOR_HOVER, text_color=COLOR_ACCENT, command=lambda i=item["id"]: self._concluir_prazo(i)).pack(side="right")
            texto_frame = ctk.CTkFrame(linha, fg_color="transparent")
            texto_frame.pack(side="left", fill="x", expand=True, padx=10, pady=6)
            ctk.CTkLabel(texto_frame, text=f"{d.strftime('%d/%m/%Y')}  •  {item.get('descricao', '')}", font=_f("Montserrat", 12, "bold"), text_color=COLOR_SUBTITLE if concluido else COLOR_ACCENT, anchor="w", justify="left", wraplength=360).pack(fill="x")
            status, cor = self._status_prazo(item)
            ctk.CTkLabel(texto_frame, text=status, font=_f("Montserrat", 11), text_color=cor, anchor="w").pack(fill="x")

    def _avisar_prazos_ao_abrir(self):
        if not self.prazos_data.get("avisar", True):
            return
        hoje = datetime.now().date()
        urgentes = []
        for item in self.prazos_data["itens"]:
            try:
                d = datetime.strptime(item["data"], "%Y-%m-%d").date()
            except Exception:
                continue
            if not item.get("concluido") and (d - hoje).days <= 3:
                urgentes.append((d, item))
        if not urgentes:
            return
        urgentes.sort(key=lambda x: x[0])
        linhas = []
        for d, item in urgentes[:10]:
            status, _ = self._status_prazo(item)
            linhas.append(f"• {d.strftime('%d/%m/%Y')} - {item.get('descricao', '')} ({status.split('  •')[0]})")
        if len(urgentes) > 10:
            linhas.append(f"... e mais {len(urgentes) - 10}.")
        messagebox.showwarning("Prazos de vencimento", "Atenção aos prazos:\n\n" + "\n".join(linhas))

    # ================= MÓDULO 2C: CONSULTA DE CNPJ =================
    def setup_aba_cnpj(self):
        aba = self.frames_conteudo["🏢 Consulta de CNPJ (BETA)"]
        self.cnpj_dados = []

        ctk.CTkLabel(aba, text="CONSULTA DE CNPJ (BETA)", font=_f("Montserrat", 16, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(15, 4))
        ctk.CTkLabel(aba, text="Consulta dados públicos do CNPJ pela BrasilAPI (precisa de internet).", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE).pack(pady=(0, 10))

        linha = ctk.CTkFrame(aba, fg_color="transparent")
        linha.pack()
        self.entry_cnpj = ctk.CTkEntry(linha, width=260, height=38, justify="center", font=_f("Montserrat", 14), fg_color=_C("#262626"), border_width=0, placeholder_text="00.000.000/0000-00")
        self.entry_cnpj.pack(side="left", padx=(0, 8))
        self.entry_cnpj.bind("<Return>", lambda e: self.consultar_cnpj())
        ctk.CTkButton(linha, text="Colar", width=70, height=38, fg_color=_C("#262626"), hover_color=COLOR_HOVER, text_color=COLOR_ACCENT, font=_f("Montserrat", 12, "bold"), command=self._colar_cnpj).pack(side="left", padx=(0, 8))
        self.btn_cnpj = ctk.CTkButton(linha, text="Consultar", width=110, height=38, fg_color=COLOR_VITA_BLUE, font=_f("Montserrat", 12, "bold"), command=self.consultar_cnpj)
        self.btn_cnpj.pack(side="left")

        self.lbl_status_cnpj = ctk.CTkLabel(aba, text="", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE)
        self.lbl_status_cnpj.pack(pady=(8, 4))

        self.scroll_cnpj = ctk.CTkScrollableFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        self.scroll_cnpj.pack(expand=True, fill="both", padx=15, pady=(0, 8))
        ctk.CTkButton(aba, text="Copiar Tudo", height=36, fg_color=_C("#262626"), hover_color=COLOR_HOVER, text_color=COLOR_ACCENT, font=_f("Montserrat", 12, "bold"), command=self._copiar_tudo_cnpj).pack(fill="x", padx=15, pady=(0, 12))

    def _colar_cnpj(self):
        try:
            texto = self.clipboard_get()
        except tk.TclError:
            return
        self.entry_cnpj.delete(0, "end")
        self.entry_cnpj.insert(0, texto.strip())

    def consultar_cnpj(self):
        cnpj = _limpar_cnpj(self.entry_cnpj.get())
        if len(cnpj) != 14:
            self.lbl_status_cnpj.configure(text="O CNPJ deve ter 14 caracteres.", text_color=COLOR_DANGER)
            return
        if not _cnpj_valido(cnpj):
            self.lbl_status_cnpj.configure(text="CNPJ inválido: os dígitos verificadores não conferem.", text_color=COLOR_DANGER)
            return
        self.entry_cnpj.delete(0, "end")
        self.entry_cnpj.insert(0, _fmt_cnpj(cnpj))
        self.btn_cnpj.configure(state="disabled", text="Consultando...")
        self.lbl_status_cnpj.configure(text="Buscando dados na BrasilAPI...", text_color=COLOR_SUBTITLE)
        import queue, threading
        fila = queue.Queue()
        threading.Thread(target=self._buscar_cnpj_thread, args=(cnpj, fila), daemon=True).start()
        self.after(150, lambda: self._checar_fila_cnpj(fila))

    def _buscar_cnpj_thread(self, cnpj, fila):
        # Roda fora da thread da interface para o app não travar enquanto a internet responde.
        import urllib.error
        try:
            fila.put(("ok", _consultar_cnpj_api(cnpj)))  # BrasilAPI + endereço completado pelo CEP (ViaCEP), se faltar
        except urllib.error.HTTPError as e:
            fila.put(("http", e.code))
        except (urllib.error.URLError, TimeoutError):
            fila.put(("rede", None))
        except Exception as e:
            fila.put(("erro", str(e)))

    def _checar_fila_cnpj(self, fila):
        import queue
        try:
            tipo, valor = fila.get_nowait()
        except queue.Empty:
            self.after(150, lambda: self._checar_fila_cnpj(fila))
            return
        self.btn_cnpj.configure(state="normal", text="Consultar")
        if tipo == "ok":
            self.cnpj_dados = self._montar_dados_cnpj(valor)
            self._renderizar_cnpj()
            self.lbl_status_cnpj.configure(text="✔ Consulta concluída.", text_color=_C("#00FF66"))
            return
        mensagens = {404: "CNPJ não encontrado na base.", 400: "A BrasilAPI não aceitou este CNPJ.", 429: "Muitas consultas seguidas. Aguarde um instante e tente de novo."}
        if tipo == "http":
            texto = mensagens.get(valor, f"A BrasilAPI respondeu com erro {valor}. Tente novamente mais tarde.")
        elif tipo == "rede":
            texto = "Não foi possível conectar. Verifique sua internet."
        else:
            texto = f"Erro na consulta: {valor}"
        self.lbl_status_cnpj.configure(text=texto, text_color=COLOR_DANGER)

    def _montar_dados_cnpj(self, d):
        def sim_nao(v): return "Não informado" if v is None else ("Sim" if v else "Não")
        dados = []
        def add(campo, valor):
            if valor not in (None, "", []):
                dados.append((campo, str(valor)))

        cnpj = _limpar_cnpj(str(d.get("cnpj") or ""))
        add("CNPJ", _fmt_cnpj(cnpj) if len(cnpj) == 14 else cnpj)
        add("Razão Social", d.get("razao_social"))
        add("Nome Fantasia", d.get("nome_fantasia"))
        add("Matriz/Filial", d.get("descricao_identificador_matriz_filial"))
        add("Situação Cadastral", d.get("descricao_situacao_cadastral"))
        add("Data da Situação", _data_xml_br(d.get("data_situacao_cadastral") or ""))
        motivo = d.get("descricao_motivo_situacao_cadastral")
        if motivo and motivo.upper() != "SEM MOTIVO":
            add("Motivo da Situação", motivo)
        add("Início das Atividades", _data_xml_br(d.get("data_inicio_atividade") or ""))
        add("Natureza Jurídica", d.get("natureza_juridica"))
        add("Porte", d.get("descricao_porte") or d.get("porte"))
        capital = d.get("capital_social")
        if isinstance(capital, (int, float)):
            add("Capital Social", "R$ " + _fmt_br(capital, 2))
        if d.get("cnae_fiscal") is not None:
            add("Atividade Principal", f"{_fmt_cnae(d.get('cnae_fiscal'))} | {d.get('cnae_fiscal_descricao') or ''}".strip(" |"))
        # Inclui todas as secundárias, inclusive as "(Dispensada *)" (código 0000-0/00 ou 9999-9/99).
        secundarias = [f"{_fmt_cnae(c.get('codigo'))} | {c.get('descricao') or ''}".strip(" |")
                       for c in (d.get("cnaes_secundarios") or []) if isinstance(c, dict) and (c.get("codigo") is not None or c.get("descricao"))]
        add("Atividades Secundárias", "\n".join(secundarias))
        # Formato: Rua NOME, N° 0 (COMPL.: ...) | BAIRRO, MUNICIPIO - UF | 00000-000
        # Se o logradouro veio do ViaCEP, ele já traz o tipo ("Rua X"): o tipo da BrasilAPI não é usado.
        tipo_log = "" if d.get("_logradouro_com_tipo") else (d.get("descricao_tipo_de_logradouro") or "").strip().capitalize()
        rua = " ".join(x for x in (tipo_log, (d.get("logradouro") or "").strip()) if x)
        if (d.get("numero") or "").strip():
            rua += f", N° {d['numero'].strip()}"
        if (d.get("complemento") or "").strip():
            rua += f" (COMPL.: {d['complemento'].strip()})"
        cidade_uf = " - ".join(x for x in ((d.get("municipio") or "").strip(), (d.get("uf") or "").strip()) if x)
        local = ", ".join(x for x in ((d.get("bairro") or "").strip(), cidade_uf) if x)
        cep = re.sub(r"\D", "", str(d.get("cep") or ""))
        cep = f"{cep[:5]}-{cep[5:]}" if len(cep) == 8 else cep
        # Se a API não trouxe qualquer parte do endereço (exceto o complemento), não mostra endereço parcial: avisa para consultar a fonte oficial.
        campos_obrigatorios = ["logradouro", "numero", "bairro", "municipio", "uf"]
        if not d.get("_logradouro_com_tipo"):
            campos_obrigatorios.insert(0, "descricao_tipo_de_logradouro")
        if any(not str(d.get(c) or "").strip() for c in campos_obrigatorios) or len(cep) != 9:
            add("Endereço", "Endereço incompleto na base da API. Por favor, faça a consulta real.")
        else:
            add("Endereço", " | ".join(x for x in (rua, local, cep) if x))
            completado = d.get("_completado_cep")
            if completado:
                add("Obs. do Endereço", f"{', '.join(completado[0])} completado(s) pelo {completado[1]} a partir do CEP.")
        tels = [_fmt_tel(t) for t in (d.get("ddd_telefone_1"), d.get("ddd_telefone_2")) if t]
        add("Telefone", " / ".join(tels))
        add("E-mail", (d.get("email") or "").lower())
        add("Optante pelo Simples", sim_nao(d.get("opcao_pelo_simples")))
        add("Optante pelo MEI", sim_nao(d.get("opcao_pelo_mei")))
        regimes = [r for r in (d.get("regime_tributario") or []) if isinstance(r, dict)]
        if regimes:
            ultimo = max(regimes, key=lambda r: r.get("ano") or 0)
            add("Regime Tributário", f"{ultimo.get('forma_de_tributacao', '')} ({ultimo.get('ano', '')})")
        socios = [f"{s.get('nome_socio', '')} - {s.get('qualificacao_socio', '')}".strip(" -") for s in (d.get("qsa") or []) if isinstance(s, dict)]
        add("Sócios/Administradores", "\n".join(socios))
        return dados

    def _renderizar_cnpj(self):
        for w in self.scroll_cnpj.winfo_children():
            w.destroy()
        for campo, valor in self.cnpj_dados:
            linha = ctk.CTkFrame(self.scroll_cnpj, fg_color=_C("#1A1A1A"), corner_radius=8)
            linha.pack(fill="x", pady=3, padx=3)
            ctk.CTkLabel(linha, text=campo, width=130, anchor="nw", justify="left", wraplength=125, font=_f("Montserrat", 11, "bold"), text_color=COLOR_SUBTITLE).pack(side="left", anchor="n", padx=(10, 4), pady=8)
            ctk.CTkButton(linha, text="Copiar", width=60, height=26, fg_color="transparent", border_width=1, border_color=COLOR_SUBTITLE, hover_color=COLOR_HOVER, text_color=COLOR_ACCENT, font=_f("Montserrat", 10, "bold"), command=lambda v=valor: self._copiar_para_area(v)).pack(side="right", anchor="n", padx=8, pady=8)
            ctk.CTkLabel(linha, text=valor, anchor="w", justify="left", wraplength=290, font=_f("Montserrat", 12), text_color=COLOR_ACCENT).pack(side="left", fill="x", expand=True, padx=4, pady=8)

    def _copiar_tudo_cnpj(self):
        if not self.cnpj_dados:
            messagebox.showwarning("Atenção", "Faça uma consulta primeiro.")
            return
        self._copiar_para_area("\n".join(f"{c}: {v}" for c, v in self.cnpj_dados))
        self.lbl_status_cnpj.configure(text="✔ Dados copiados para a área de transferência.", text_color=_C("#00FF66"))

    # ================= UTILIDADES COMPARTILHADAS DAS ABAS NOVAS =================
    def _executar_async(self, funcao, ao_terminar):
        # Roda a função numa thread e chama ao_terminar("ok", resultado) ou ao_terminar("erro", excecao) na interface.
        import queue, threading
        fila = queue.Queue()

        def trabalho():
            try:
                fila.put(("ok", funcao()))
            except Exception as e:
                fila.put(("erro", e))

        threading.Thread(target=trabalho, daemon=True).start()

        def checar():
            try:
                tipo, valor = fila.get_nowait()
            except queue.Empty:
                self.after(150, checar)
                return
            ao_terminar(tipo, valor)

        self.after(150, checar)

    def _renderizar_linhas_copiaveis(self, scroll, dados):
        for w in scroll.winfo_children():
            w.destroy()
        for campo, valor in dados:
            linha = ctk.CTkFrame(scroll, fg_color=_C("#1A1A1A"), corner_radius=8)
            linha.pack(fill="x", pady=3, padx=3)
            ctk.CTkLabel(linha, text=campo, width=130, anchor="nw", justify="left", wraplength=125, font=_f("Montserrat", 11, "bold"), text_color=COLOR_SUBTITLE).pack(side="left", anchor="n", padx=(10, 4), pady=8)
            ctk.CTkButton(linha, text="Copiar", width=60, height=26, fg_color="transparent", border_width=1, border_color=COLOR_SUBTITLE, hover_color=COLOR_HOVER, text_color=COLOR_ACCENT, font=_f("Montserrat", 10, "bold"), command=lambda v=valor: self._copiar_para_area(v)).pack(side="right", anchor="n", padx=8, pady=8)
            ctk.CTkLabel(linha, text=valor, anchor="w", justify="left", wraplength=290, font=_f("Montserrat", 12), text_color=COLOR_ACCENT).pack(side="left", fill="x", expand=True, padx=4, pady=8)

    def _erro_rede_texto(self, tipo, valor, nao_encontrado=None):
        import urllib.error
        if nao_encontrado is not None and isinstance(valor, nao_encontrado):
            return "CEP não encontrado."
        if isinstance(valor, (urllib.error.URLError, TimeoutError)):
            return "Não foi possível conectar. Verifique sua internet."
        return f"Erro na consulta: {valor}"

    # ================= MÓDULO 7A: CONSULTA DE CEP =================
    def setup_aba_cep(self):
        aba = self.frames_conteudo[ABA_CEP]
        self.cep_dados = []

        ctk.CTkLabel(aba, text="CONSULTA DE CEP (BETA)", font=_f("Montserrat", 16, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(15, 4))
        ctk.CTkLabel(aba, text="Busca o endereço pelo CEP no ViaCEP (precisa de internet).", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE).pack(pady=(0, 10))

        linha = ctk.CTkFrame(aba, fg_color="transparent")
        linha.pack()
        self.entry_cep = ctk.CTkEntry(linha, width=220, height=38, justify="center", font=_f("Montserrat", 14), fg_color=_C("#262626"), border_width=0, placeholder_text="00000-000")
        self.entry_cep.pack(side="left", padx=(0, 8))
        self.entry_cep.bind("<Return>", lambda e: self.consultar_cep())
        ctk.CTkButton(linha, text="Colar", width=70, height=38, fg_color=_C("#262626"), hover_color=COLOR_HOVER, text_color=COLOR_ACCENT, font=_f("Montserrat", 12, "bold"), command=self._colar_cep).pack(side="left", padx=(0, 8))
        self.btn_cep = ctk.CTkButton(linha, text="Consultar", width=110, height=38, fg_color=COLOR_VITA_BLUE, font=_f("Montserrat", 12, "bold"), command=self.consultar_cep)
        self.btn_cep.pack(side="left")

        self.lbl_status_cep = ctk.CTkLabel(aba, text="", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE)
        self.lbl_status_cep.pack(pady=(8, 4))

        self.scroll_cep = ctk.CTkScrollableFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        self.scroll_cep.pack(expand=True, fill="both", padx=15, pady=(0, 8))
        ctk.CTkButton(aba, text="Copiar Tudo", height=36, fg_color=_C("#262626"), hover_color=COLOR_HOVER, text_color=COLOR_ACCENT, font=_f("Montserrat", 12, "bold"), command=self._copiar_tudo_cep).pack(fill="x", padx=15, pady=(0, 12))

    def _colar_cep(self):
        try:
            texto = self.clipboard_get()
        except tk.TclError:
            return
        self.entry_cep.delete(0, "end")
        self.entry_cep.insert(0, texto.strip())

    def consultar_cep(self):
        cep = re.sub(r"\D", "", self.entry_cep.get())
        if len(cep) != 8:
            self.lbl_status_cep.configure(text="O CEP deve ter 8 dígitos.", text_color=COLOR_DANGER)
            return
        self.entry_cep.delete(0, "end")
        self.entry_cep.insert(0, f"{cep[:5]}-{cep[5:]}")
        self.btn_cep.configure(state="disabled", text="Consultando...")
        self.lbl_status_cep.configure(text="Buscando o CEP no ViaCEP...", text_color=COLOR_SUBTITLE)
        self._executar_async(lambda: _consultar_cep(cep), self._ao_consultar_cep)

    def _ao_consultar_cep(self, tipo, valor):
        self.btn_cep.configure(state="normal", text="Consultar")
        if tipo != "ok":
            self.lbl_status_cep.configure(text=self._erro_rede_texto(tipo, valor, _CepNaoEncontrado), text_color=COLOR_DANGER)
            return
        r = valor
        cep = re.sub(r"\D", "", str(r.get("cep") or ""))
        cep_fmt = f"{cep[:5]}-{cep[5:]}" if len(cep) == 8 else cep
        cidade_uf = " - ".join(x for x in (r["cidade"], r["uf"]) if x)
        local = ", ".join(x for x in (r["bairro"], cidade_uf) if x)
        dados = []
        def add(campo, v):
            if v:
                dados.append((campo, str(v)))
        add("Endereço", " | ".join(x for x in (r["logradouro"], local, cep_fmt) if x))
        add("CEP", cep_fmt)
        add("Logradouro", r["logradouro"])
        add("Complemento", r["complemento"])
        add("Bairro", r["bairro"])
        add("Cidade", r["cidade"])
        add("UF", f"{r['uf']} ({r['estado']})" if r["uf"] and r["estado"] else r["uf"])
        add("Código IBGE", r["ibge"])
        add("DDD", r["ddd"])
        self.cep_dados = dados
        self._renderizar_linhas_copiaveis(self.scroll_cep, dados)
        aviso = "" if r["logradouro"] else " (CEP geral da cidade, sem rua)"
        self.lbl_status_cep.configure(text=f"✔ Consulta concluída via {r['fonte']}.{aviso}", text_color=_C("#00FF66"))

    def _copiar_tudo_cep(self):
        if not self.cep_dados:
            messagebox.showwarning("Atenção", "Faça uma consulta primeiro.")
            return
        self._copiar_para_area("\n".join(f"{c}: {v}" for c, v in self.cep_dados))
        self.lbl_status_cep.configure(text="✔ Dados copiados para a área de transferência.", text_color=_C("#00FF66"))

    # ================= MÓDULO 7B: CONFERÊNCIA DE CNPJ EM LOTE =================
    COLUNAS_LOTE = ["CNPJ", "Razão Social", "Nome Fantasia", "Situação Cadastral", "Data da Situação", "Início das Atividades",
                    "Natureza Jurídica", "Porte", "Capital Social", "Atividade Principal", "Endereço", "Telefone", "E-mail",
                    "Optante pelo Simples", "Optante pelo MEI", "Status da consulta"]

    def setup_aba_cnpj_lote(self):
        aba = self.frames_conteudo[ABA_CNPJ_LOTE]
        self.lote_linhas = []
        self._lote_cancelar = None

        ctk.CTkLabel(aba, text="CONFERÊNCIA DE CNPJ EM LOTE", font=_f("Montserrat", 16, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(15, 4))
        ctk.CTkLabel(aba, text="Cole uma lista de CNPJs (um por linha) e confira todos de uma vez (precisa de internet).", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE).pack(pady=(0, 10))

        self.txt_lote = ctk.CTkTextbox(aba, height=120, fg_color=_C("#262626"), text_color=_C("#FFFFFF"), font=_f("Montserrat", 12), border_width=0, wrap="word")
        self.txt_lote.pack(fill="x", padx=20)

        botoes = ctk.CTkFrame(aba, fg_color="transparent")
        botoes.pack(pady=(10, 0))
        ctk.CTkButton(botoes, text="Colar", width=70, height=36, fg_color=_C("#262626"), hover_color=COLOR_HOVER, text_color=COLOR_ACCENT, font=_f("Montserrat", 12, "bold"), command=self._colar_lote).pack(side="left", padx=(0, 8))
        ctk.CTkButton(botoes, text="Limpar", width=70, height=36, fg_color=_C("#262626"), hover_color=COLOR_HOVER, text_color=COLOR_ACCENT, font=_f("Montserrat", 12, "bold"), command=self._limpar_lote).pack(side="left", padx=(0, 8))
        self.btn_lote = ctk.CTkButton(botoes, text="Conferir", width=110, height=36, fg_color=COLOR_VITA_BLUE, font=_f("Montserrat", 12, "bold"), command=self.conferir_cnpj_lote)
        self.btn_lote.pack(side="left", padx=(0, 8))
        self.btn_lote_cancelar = ctk.CTkButton(botoes, text="Cancelar", width=90, height=36, fg_color=_C("#262626"), hover_color=COLOR_DANGER, text_color=COLOR_ACCENT, font=_f("Montserrat", 12, "bold"), state="disabled", command=self._cancelar_lote)
        self.btn_lote_cancelar.pack(side="left")

        self.lbl_status_lote = ctk.CTkLabel(aba, text="", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE)
        self.lbl_status_lote.pack(pady=(8, 4))

        self.txt_lote_resultado = ctk.CTkTextbox(aba, fg_color=_C("#262626"), text_color=_C("#FFFFFF"), font=_f("Montserrat", 11), border_width=0, wrap="none", state="disabled")
        self.txt_lote_resultado.pack(expand=True, fill="both", padx=20, pady=(0, 8))

        self.btn_lote_exportar = ctk.CTkButton(aba, text="Exportar para Excel", height=36, fg_color=COLOR_ACCENT, text_color=COLOR_BG, hover_color=COLOR_HOVER_WHITE, font=_f("Montserrat", 12, "bold"), state="disabled", command=self.exportar_lote_excel)
        self.btn_lote_exportar.pack(fill="x", padx=20, pady=(0, 12))

    def _colar_lote(self):
        try:
            texto = self.clipboard_get()
        except tk.TclError:
            return
        self.txt_lote.delete("1.0", "end")
        self.txt_lote.insert("1.0", texto.strip())

    def _limpar_lote(self):
        self.txt_lote.delete("1.0", "end")

    def _cancelar_lote(self):
        if self._lote_cancelar is not None:
            self._lote_cancelar.set()
            self.btn_lote_cancelar.configure(state="disabled")
            self.lbl_status_lote.configure(text="Cancelando após a consulta atual...", text_color=COLOR_SUBTITLE)

    def conferir_cnpj_lote(self):
        import queue, threading
        itens = [t for t in re.split(r"[\s,;]+", self.txt_lote.get("1.0", "end")) if t]
        cnpjs, vistos = [], set()
        for t in itens:
            c = _limpar_cnpj(t)
            if c in vistos:
                continue
            vistos.add(c)
            cnpjs.append((t, c))
        if not cnpjs:
            messagebox.showwarning("Atenção", "Cole pelo menos um CNPJ na caixa de texto.")
            return

        self.lote_linhas = []
        self.txt_lote_resultado.configure(state="normal")
        self.txt_lote_resultado.delete("1.0", "end")
        self.txt_lote_resultado.configure(state="disabled")
        self.btn_lote.configure(state="disabled", text="Conferindo...")
        self.btn_lote_cancelar.configure(state="normal")
        self.btn_lote_exportar.configure(state="disabled")
        self.lbl_status_lote.configure(text=f"Consultando 0/{len(cnpjs)}...", text_color=COLOR_SUBTITLE)

        fila = queue.Queue()
        self._lote_cancelar = threading.Event()
        cancelar = self._lote_cancelar
        threading.Thread(target=self._trabalho_lote, args=(cnpjs, fila, cancelar), daemon=True).start()
        self.after(200, lambda: self._checar_fila_lote(fila, len(cnpjs)))

    def _trabalho_lote(self, cnpjs, fila, cancelar):
        import time, urllib.error
        for t, c in cnpjs:
            if cancelar.is_set():
                break
            valido = len(c) == 14 and _cnpj_valido(c)
            linha = {"CNPJ": _fmt_cnpj(c) if len(c) == 14 else t}
            if not valido:
                linha["Status da consulta"] = "CNPJ inválido"
                fila.put(("linha", linha))
                continue
            tentativas = 0
            while True:
                try:
                    d = _consultar_cnpj_api(c)
                    linha.update(dict(self._montar_dados_cnpj(d)))
                    linha["CNPJ"] = _fmt_cnpj(c)
                    linha["Status da consulta"] = "OK"
                    break
                except urllib.error.HTTPError as e:
                    if e.code == 429 and tentativas < 2 and not cancelar.is_set():
                        tentativas += 1
                        time.sleep(3 * tentativas)
                        continue
                    linha["Status da consulta"] = {404: "Não encontrado na base", 400: "Não aceito pela API", 429: "Limite de consultas da API"}.get(e.code, f"Erro {e.code}")
                    break
                except (urllib.error.URLError, TimeoutError):
                    linha["Status da consulta"] = "Sem conexão"
                    break
                except Exception as e:
                    linha["Status da consulta"] = f"Erro: {e}"
                    break
            fila.put(("linha", linha))
            time.sleep(0.3)  # respeita o limite de consultas da API
        fila.put(("fim", None))

    def _checar_fila_lote(self, fila, total):
        import queue
        fim = False
        try:
            while True:
                tipo, linha = fila.get_nowait()
                if tipo == "linha":
                    self._adicionar_linha_lote(linha)
                    self.lbl_status_lote.configure(text=f"Consultando {len(self.lote_linhas)}/{total}...", text_color=COLOR_SUBTITLE)
                else:
                    fim = True
        except queue.Empty:
            pass
        if fim:
            self._finalizar_lote(total)
        else:
            self.after(200, lambda: self._checar_fila_lote(fila, total))

    def _adicionar_linha_lote(self, linha):
        self.lote_linhas.append(linha)
        status = linha.get("Status da consulta", "")
        if status == "OK":
            situacao = linha.get("Situação Cadastral", "")
            icone = "✔" if situacao.upper() == "ATIVA" else "⚠"
            resumo = f"{linha.get('Razão Social', '-')} | {situacao or '-'}"
        else:
            icone, resumo = "✖", status
        self.txt_lote_resultado.configure(state="normal")
        self.txt_lote_resultado.insert("end", f"{icone} {linha['CNPJ']} | {resumo}\n")
        self.txt_lote_resultado.see("end")
        self.txt_lote_resultado.configure(state="disabled")

    def _finalizar_lote(self, total):
        self.btn_lote.configure(state="normal", text="Conferir")
        self.btn_lote_cancelar.configure(state="disabled")
        feitos = len(self.lote_linhas)
        ativos = sum(1 for l in self.lote_linhas if l.get("Status da consulta") == "OK" and l.get("Situação Cadastral", "").upper() == "ATIVA")
        atencao = sum(1 for l in self.lote_linhas if l.get("Status da consulta") == "OK") - ativos
        falhas = feitos - ativos - atencao
        resumo = f"{ativos} ativo(s) ✔ | {atencao} com situação diferente de ATIVA ⚠ | {falhas} com falha ✖"
        if feitos < total:
            self.lbl_status_lote.configure(text=f"Cancelado em {feitos}/{total}. {resumo}", text_color=COLOR_DANGER)
        else:
            self.lbl_status_lote.configure(text=f"Concluído: {resumo}", text_color=_C("#00FF66"))
        if feitos:
            self.btn_lote_exportar.configure(state="normal")

    def exportar_lote_excel(self):
        if not self.lote_linhas:
            messagebox.showwarning("Atenção", "Faça a conferência primeiro.")
            return
        saida = filedialog.asksaveasfilename(title="Salvar planilha", initialfile="conferencia_cnpj_lote", defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
        if not saida:
            return
        try:
            tabela = pd.DataFrame(self.lote_linhas, columns=self.COLUNAS_LOTE)
            with pd.ExcelWriter(saida, engine="openpyxl") as escritor:
                tabela.to_excel(escritor, index=False, sheet_name="CNPJs")
                planilha = escritor.sheets["CNPJs"]
                for celula in planilha[1]:
                    celula.font = Font(bold=True)
                for coluna_celulas in planilha.columns:
                    maior = max((len(str(c.value)) for c in coluna_celulas if c.value is not None), default=10)
                    planilha.column_dimensions[coluna_celulas[0].column_letter].width = min(maior + 2, 50)
            messagebox.showinfo("Sucesso", f"Planilha salva com sucesso!\n{len(self.lote_linhas)} CNPJ(s) exportado(s).")
        except ImportError:
            return  # a mensagem de instalação já foi exibida
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao salvar a planilha:\n{e}")

    # ================= MÓDULO 7D: NÚMERO PARA EXTENSO =================
    def setup_aba_extenso(self):
        aba = self.frames_conteudo[ABA_EXTENSO]
        self._extenso_atual = ("", "")

        ctk.CTkLabel(aba, text="NÚMERO PARA EXTENSO", font=_f("Montserrat", 16, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(15, 4))
        ctk.CTkLabel(aba, text="Digite um número ou valor (ex.: 1.234,56) e veja como fica escrito por extenso.", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE).pack(pady=(0, 12))

        self.entry_extenso = ctk.CTkEntry(aba, width=320, height=40, justify="center", font=_f("Montserrat", 15), fg_color=_C("#262626"), border_width=0, placeholder_text="1.234,56")
        self.entry_extenso.pack()
        self.entry_extenso.bind("<KeyRelease>", lambda e: self._atualizar_extenso())

        self.seg_extenso = ctk.CTkSegmentedButton(aba, values=["Valor em reais (R$)", "Número simples"], fg_color=_C("#262626"), selected_color=COLOR_VITA_BLUE, unselected_color=_C("#262626"), font=_f("Montserrat", 12, "bold"), command=lambda v: self._atualizar_extenso())
        self.seg_extenso.set("Valor em reais (R$)")
        self.seg_extenso.pack(pady=(12, 8))

        self.lbl_status_extenso = ctk.CTkLabel(aba, text="", font=_f("Montserrat", 12), text_color=COLOR_DANGER)
        self.lbl_status_extenso.pack(pady=(0, 4))

        self.txt_extenso = ctk.CTkTextbox(aba, height=130, fg_color=_C("#262626"), text_color=_C("#FFFFFF"), font=_f("Montserrat", 15), border_width=0, wrap="word", state="disabled")
        self.txt_extenso.pack(fill="x", padx=20, pady=(0, 10))

        botoes = ctk.CTkFrame(aba, fg_color="transparent")
        botoes.pack(fill="x", padx=20)
        ctk.CTkButton(botoes, text="Copiar por extenso", height=38, font=_f("Montserrat", 12, "bold"), fg_color=COLOR_VITA_BLUE, command=lambda: self._copiar_extenso(False)).pack(side="left", expand=True, fill="x", padx=(0, 6))
        ctk.CTkButton(botoes, text="Copiar com o valor (entre parênteses)", height=38, font=_f("Montserrat", 12, "bold"), fg_color=COLOR_ACCENT, text_color=COLOR_BG, hover_color=COLOR_HOVER_WHITE, command=lambda: self._copiar_extenso(True)).pack(side="left", expand=True, fill="x", padx=(6, 0))

    def _atualizar_extenso(self):
        texto = self.entry_extenso.get().strip()
        extenso, valor_fmt, erro = "", "", ""
        if texto:
            try:
                extenso, valor_fmt = _numero_por_extenso(texto, moeda=self.seg_extenso.get().startswith("Valor"))
            except ValueError as e:
                erro = str(e)
        self._extenso_atual = (extenso, valor_fmt)
        self.lbl_status_extenso.configure(text=erro)
        self.txt_extenso.configure(state="normal")
        self.txt_extenso.delete("1.0", "end")
        self.txt_extenso.insert("1.0", extenso)
        self.txt_extenso.configure(state="disabled")

    def _copiar_extenso(self, com_valor):
        extenso, valor_fmt = self._extenso_atual
        if not extenso:
            messagebox.showwarning("Atenção", "Digite um número válido primeiro.")
            return
        self._copiar_para_area(f"{valor_fmt} ({extenso})" if com_valor else extenso)
        self.lbl_status_extenso.configure(text="✔ Copiado para a área de transferência.", text_color=_C("#00FF66"))
        self.after(2500, lambda: self.lbl_status_extenso.configure(text="", text_color=COLOR_DANGER))

    # ================= MÓDULO 10B: REDIMENSIONAR E COMPRIMIR IMAGENS =================
    def setup_aba_imagens_otimizar(self):
        aba = self.frames_conteudo[ABA_IMG_OTIM]
        self.arquivos_img_otim = []

        ctk.CTkLabel(aba, text="REDIMENSIONAR E COMPRIMIR IMAGENS (BETA)", font=_f("Montserrat", 16, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(15, 4))
        ctk.CTkLabel(aba, text="Reduza o peso e o tamanho de fotos e imagens (JPG, PNG, WEBP, BMP). Os originais não são alterados.", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE).pack(pady=(0, 10))

        painel = ctk.CTkFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        painel.pack(fill="x", padx=20, pady=(0, 10))

        linha = ctk.CTkFrame(painel, fg_color="transparent")
        linha.pack(fill="x", padx=15, pady=(15, 8))
        ctk.CTkButton(linha, text="Selecionar imagens", width=160, height=36, font=_f("Montserrat", 12, "bold"), fg_color=COLOR_ACCENT, text_color=COLOR_BG, hover_color=COLOR_HOVER_WHITE, command=self._selecionar_imagens_otim).pack(side="left")
        self.lbl_img_otim = ctk.CTkLabel(linha, text="Nenhuma imagem selecionada", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE)
        self.lbl_img_otim.pack(side="left", padx=12)

        linha = ctk.CTkFrame(painel, fg_color="transparent")
        linha.pack(fill="x", padx=15, pady=6)
        ctk.CTkLabel(linha, text="Largura máx. (px):", font=_f("Montserrat", 12), text_color=COLOR_ACCENT).pack(side="left")
        self.entry_img_larg = ctk.CTkEntry(linha, width=80, height=32, justify="center", fg_color=_C("#1A1A1A"), border_width=0, placeholder_text="opcional")
        self.entry_img_larg.pack(side="left", padx=(6, 18))
        ctk.CTkLabel(linha, text="Altura máx. (px):", font=_f("Montserrat", 12), text_color=COLOR_ACCENT).pack(side="left")
        self.entry_img_alt = ctk.CTkEntry(linha, width=80, height=32, justify="center", fg_color=_C("#1A1A1A"), border_width=0, placeholder_text="opcional")
        self.entry_img_alt.pack(side="left", padx=6)

        linha = ctk.CTkFrame(painel, fg_color="transparent")
        linha.pack(fill="x", padx=15, pady=6)
        ctk.CTkLabel(linha, text="Qualidade (JPG):", font=_f("Montserrat", 12), text_color=COLOR_ACCENT).pack(side="left")
        self.lbl_qualidade_img = ctk.CTkLabel(linha, text="75", width=30, font=_f("Montserrat", 12, "bold"), text_color=COLOR_VITA_BLUE)
        self.slider_qualidade_img = ctk.CTkSlider(linha, from_=10, to=100, number_of_steps=90, width=220, command=lambda v: self.lbl_qualidade_img.configure(text=str(int(v))))
        self.slider_qualidade_img.set(75)
        self.slider_qualidade_img.pack(side="left", padx=10)
        self.lbl_qualidade_img.pack(side="left")

        linha = ctk.CTkFrame(painel, fg_color="transparent")
        linha.pack(fill="x", padx=15, pady=6)
        ctk.CTkLabel(linha, text="Tamanho máx. por imagem (KB):", font=_f("Montserrat", 12), text_color=COLOR_ACCENT).pack(side="left")
        self.entry_img_kb = ctk.CTkEntry(linha, width=80, height=32, justify="center", fg_color=_C("#1A1A1A"), border_width=0, placeholder_text="opcional")
        self.entry_img_kb.pack(side="left", padx=8)

        linha = ctk.CTkFrame(painel, fg_color="transparent")
        linha.pack(fill="x", padx=15, pady=6)
        ctk.CTkLabel(linha, text="Formato de saída:", font=_f("Montserrat", 12), text_color=COLOR_ACCENT).pack(side="left")
        self.opt_img_formato = ctk.CTkOptionMenu(linha, values=["Manter formato original", "Converter para JPG", "Converter para PNG"], width=220, height=32, fg_color=_C("#1A1A1A"), button_color=COLOR_HOVER, font=_f("Montserrat", 12))
        self.opt_img_formato.pack(side="left", padx=8)

        self.btn_img_otim = ctk.CTkButton(painel, text="Processar e Salvar", height=40, font=_f("Montserrat", 12, "bold"), fg_color=COLOR_VITA_BLUE, command=self.processar_imagens_otim)
        self.btn_img_otim.pack(fill="x", padx=15, pady=(14, 8))
        self.lbl_status_img_otim = ctk.CTkLabel(painel, text="Dica: PNG não usa a qualidade; para pesar menos, reduza as dimensões ou converta para JPG.", font=_f("Montserrat", 11), text_color=COLOR_SUBTITLE, wraplength=560)
        self.lbl_status_img_otim.pack(padx=15, pady=(0, 14))

    def _selecionar_imagens_otim(self):
        arquivos = filedialog.askopenfilenames(title="Selecione as imagens", filetypes=[("Imagens", "*.jpg *.jpeg *.png *.webp *.bmp")])
        if not arquivos:
            return
        self.arquivos_img_otim = list(arquivos)
        n = len(self.arquivos_img_otim)
        self.lbl_img_otim.configure(text=f"{n} imagem(ns) selecionada(s)", text_color=COLOR_ACCENT)

    def processar_imagens_otim(self):
        if not self.arquivos_img_otim:
            messagebox.showwarning("Atenção", "Selecione as imagens primeiro.")
            return
        def numero(entry, rotulo):
            t = entry.get().strip()
            if not t:
                return None
            if not t.isdigit() or int(t) <= 0:
                raise ValueError(f"{rotulo}: digite um número inteiro maior que zero (ou deixe em branco).")
            return int(t)
        try:
            max_larg = numero(self.entry_img_larg, "Largura máxima")
            max_alt = numero(self.entry_img_alt, "Altura máxima")
            alvo_kb = numero(self.entry_img_kb, "Tamanho máximo")
        except ValueError as e:
            messagebox.showwarning("Atenção", str(e))
            return
        pasta = filedialog.askdirectory(title="Selecione a pasta para salvar as imagens")
        if not pasta:
            return
        qualidade = int(self.slider_qualidade_img.get())
        escolha = self.opt_img_formato.get()
        modo = "jpg" if "JPG" in escolha else ("png" if "PNG" in escolha else "manter")
        arquivos = list(self.arquivos_img_otim)

        def trabalho():
            ok, falhas, antes, depois = 0, [], 0, 0
            for caminho in arquivos:
                try:
                    _, a, d = _processar_imagem_otimizada(caminho, pasta, max_larg, max_alt, qualidade, alvo_kb, modo)
                    ok += 1
                    antes += a
                    depois += d
                except Exception as e:
                    falhas.append(f"{os.path.basename(caminho)}: {e}")
            return ok, falhas, antes, depois

        self.btn_img_otim.configure(state="disabled", text="Processando...")
        self.lbl_status_img_otim.configure(text=f"Processando {len(arquivos)} imagem(ns)...", text_color=COLOR_SUBTITLE)
        self._executar_async(trabalho, self._ao_processar_imagens_otim)

    def _ao_processar_imagens_otim(self, tipo, valor):
        self.btn_img_otim.configure(state="normal", text="Processar e Salvar")
        if tipo != "ok":
            self.lbl_status_img_otim.configure(text=f"Erro ao processar: {valor}", text_color=COLOR_DANGER)
            return
        ok, falhas, antes, depois = valor
        texto = f"✔ {ok} imagem(ns) salva(s)."
        if ok and antes:
            variacao = (1 - depois / antes) * 100
            texto += f" Tamanho: {_fmt_tamanho(antes)} → {_fmt_tamanho(depois)} ({'-' if variacao >= 0 else '+'}{abs(variacao):.0f}%)"
        if falhas:
            texto += f"  ✖ {len(falhas)} falha(s)."
            messagebox.showwarning("Algumas imagens falharam", "\n".join(falhas[:10]))
        self.lbl_status_img_otim.configure(text=texto, text_color=_C("#00FF66") if not falhas else COLOR_DANGER)

    # ================= MÓDULO S: CONFIGURAÇÕES (tema e fonte) E ATUALIZAÇÕES =================
    def setup_aba_config(self):
        aba = self.frames_conteudo[ABA_CONFIG]
        self._info_atualizacao = None
        self._verificando_atualizacao = False

        ctk.CTkLabel(aba, text="CONFIGURAÇÕES", font=_f("Montserrat", 16, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(15, 10))

        # ---- Aparência ----
        card = ctk.CTkFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        card.pack(fill="x", padx=20, pady=(0, 12))
        ctk.CTkLabel(card, text="APARÊNCIA", font=_f("Montserrat", 11, "bold"), text_color=COLOR_SUBTITLE).pack(anchor="w", padx=15, pady=(12, 6))

        def seletor(rotulo, valores, atual, comando):
            linha = ctk.CTkFrame(card, fg_color="transparent")
            linha.pack(fill="x", padx=15, pady=4)
            ctk.CTkLabel(linha, text=rotulo, width=110, anchor="w", font=_f("Montserrat", 12), text_color=COLOR_ACCENT).pack(side="left")
            seg = ctk.CTkSegmentedButton(linha, values=valores, command=comando, font=_f("Montserrat", 12, "bold"),
                                         fg_color=_C("#444444"), unselected_color=_C("#444444"), unselected_hover_color=_C("#555555"),
                                         selected_color=COLOR_VITA_BLUE, selected_hover_color=_C("#1A66CC"))
            seg.set(atual)
            seg.pack(side="left", fill="x", expand=True)
            return seg

        self.seg_tema = seletor("Tema", ["Escuro", "Claro"], "Claro" if CONFIG["tema"] == "light" else "Escuro", self._mudar_tema)
        self.seg_fonte = seletor("Tamanho da fonte", list(ESCALAS_FONTE), CONFIG["fonte"], self._mudar_fonte)
        ctk.CTkLabel(card, text="As mudanças valem na hora e ficam salvas para a próxima vez que abrir o app.", font=_f("Montserrat", 11), text_color=COLOR_SUBTITLE, wraplength=520, justify="left").pack(anchor="w", padx=15, pady=(6, 12))

        # ---- Atualizações ----
        card2 = ctk.CTkFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        card2.pack(fill="x", padx=20, pady=(0, 12))
        ctk.CTkLabel(card2, text="ATUALIZAÇÕES", font=_f("Montserrat", 11, "bold"), text_color=COLOR_SUBTITLE).pack(anchor="w", padx=15, pady=(12, 6))
        ctk.CTkLabel(card2, text=f"Versão instalada: {VERSAO_APP}", font=_f("Montserrat", 12), text_color=COLOR_ACCENT).pack(anchor="w", padx=15)

        self.lbl_status_atualizacao = ctk.CTkLabel(card2, text="", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE, wraplength=520, justify="left")
        self.lbl_status_atualizacao.pack(anchor="w", padx=15, pady=(6, 0))
        self.lbl_novidades_atualizacao = ctk.CTkLabel(card2, text="", font=_f("Montserrat", 11), text_color=COLOR_SUBTITLE, wraplength=520, justify="left")
        self.lbl_novidades_atualizacao.pack(anchor="w", padx=15, pady=(2, 0))

        botoes = ctk.CTkFrame(card2, fg_color="transparent")
        botoes.pack(fill="x", padx=15, pady=10)
        self.btn_verificar_atualizacao = ctk.CTkButton(botoes, text="Verificar agora", width=140, height=36, font=_f("Montserrat", 12, "bold"), fg_color=COLOR_VITA_BLUE, command=self.verificar_atualizacao)
        self.btn_verificar_atualizacao.pack(side="left")
        self.btn_baixar_atualizacao = ctk.CTkButton(botoes, text="Baixar atualização", width=160, height=36, font=_f("Montserrat", 12, "bold"), fg_color=COLOR_ACCENT, text_color=COLOR_BG, hover_color=COLOR_HOVER_WHITE, command=self._abrir_download_atualizacao)

        self.sw_verificar_auto = ctk.CTkSwitch(card2, text="Verificar atualizações ao abrir o app", font=_f("Montserrat", 12), command=self._alternar_verificacao_auto)
        if CONFIG["verificar_atualizacoes"]:
            self.sw_verificar_auto.select()
        self.sw_verificar_auto.pack(anchor="w", padx=15, pady=(0, 14))

    def _mudar_tema(self, valor):
        tema = "light" if valor == "Claro" else "dark"
        CONFIG["tema"] = tema
        _salvar_config()
        ctk.set_appearance_mode(tema)

    def _mudar_fonte(self, valor):
        CONFIG["fonte"] = valor
        _salvar_config()
        _aplicar_escala_fontes(ESCALAS_FONTE[valor])
        for refazer in self._refrescar_tags:  # tags de negrito/itálico/checkbox dos campos de texto
            try:
                refazer()
            except Exception:
                pass

    def _alternar_verificacao_auto(self):
        CONFIG["verificar_atualizacoes"] = bool(self.sw_verificar_auto.get())
        _salvar_config()

    def verificar_atualizacao(self, silencioso=False):
        if self._verificando_atualizacao:
            return
        self._verificando_atualizacao = True
        if not silencioso:
            self.btn_verificar_atualizacao.configure(state="disabled", text="Verificando...")
            self.lbl_status_atualizacao.configure(text="Consultando a versão mais recente...", text_color=COLOR_SUBTITLE)
            self.lbl_novidades_atualizacao.configure(text="")
        self._executar_async(_buscar_versao_remota, lambda tipo, valor: self._ao_verificar_atualizacao(tipo, valor, silencioso))

    def _ao_verificar_atualizacao(self, tipo, valor, silencioso):
        self._verificando_atualizacao = False
        self.btn_verificar_atualizacao.configure(state="normal", text="Verificar agora")
        if tipo != "ok":
            if not silencioso:
                self.lbl_status_atualizacao.configure(text="Não foi possível verificar agora. Confira sua internet e tente de novo.", text_color=COLOR_DANGER)
            return
        info = valor
        if _versao_tupla(info["versao"]) > _versao_tupla(VERSAO_APP):
            self._info_atualizacao = info
            self.lbl_status_atualizacao.configure(text=f"Nova versão disponível: {info['versao']} (você usa a {VERSAO_APP}).", text_color=_C("#00FF66"))
            self.lbl_novidades_atualizacao.configure(text=f"Novidades: {info['novidades']}" if info["novidades"] else "")
            self.btn_baixar_atualizacao.pack(side="left", padx=(10, 0))
            if silencioso:
                texto = f"Há uma nova versão da Central Vita & PráticaOn: {info['versao']} (você usa a {VERSAO_APP})."
                if info["novidades"]:
                    texto += f"\n\nNovidades: {info['novidades']}"
                if messagebox.askyesno("Atualização disponível", texto + "\n\nDeseja abrir a página de download agora?"):
                    self._abrir_download_atualizacao()
        else:
            self.btn_baixar_atualizacao.pack_forget()
            if not silencioso:
                self.lbl_status_atualizacao.configure(text=f"✔ Você já está na versão mais recente ({VERSAO_APP}).", text_color=_C("#00FF66"))

    def _abrir_download_atualizacao(self):
        link = (self._info_atualizacao or {}).get("link") or (URL_REPOSITORIO + "/releases/latest")
        if not link.lower().startswith("https://"):  # só abre links seguros
            link = URL_REPOSITORIO + "/releases/latest"
        webbrowser.open(link)

    # ================= MÓDULO 7C: GIRAR, EXTRAIR OU EXCLUIR PÁGINAS DE PDF =================
    def setup_aba_paginas_pdf(self):
        aba = self.frames_conteudo["🔄 Editar Páginas de PDF (BETA)"]
        self.paginas_pdf_arquivo = None
        self.paginas_pdf_total = 0

        card = ctk.CTkFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        card.pack(fill="x", padx=20, pady=(25, 15))
        ctk.CTkLabel(card, text="GIRAR, EXTRAIR OU EXCLUIR PÁGINAS (BETA)", font=_f("Montserrat", 16, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(20, 6))
        ctk.CTkLabel(card, text="Selecione o PDF, informe as páginas e escolha a ação.", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE).pack(pady=(0, 12))

        ctk.CTkButton(card, text="Selecionar PDF", width=200, height=38, font=_f("Montserrat", 12, "bold"), command=self.selecionar_pdf_paginas, fg_color=COLOR_ACCENT, text_color=COLOR_BG, hover_color=COLOR_HOVER_WHITE).pack()
        self.lbl_paginas_pdf = ctk.CTkLabel(card, text="Nenhum PDF selecionado.", font=_f("Montserrat", 12, "italic"), text_color=COLOR_SUBTITLE, wraplength=520)
        self.lbl_paginas_pdf.pack(pady=(8, 14))

        ctk.CTkLabel(card, text="Páginas (ex.: 1-3, 5, 8-10)", font=_f("Montserrat", 11, "bold"), text_color=COLOR_SUBTITLE).pack()
        self.entry_paginas_pdf = ctk.CTkEntry(card, width=260, height=36, justify="center", fg_color=_C("#1A1A1A"), border_width=0, placeholder_text="vazio = todas (só em Girar)")
        self.entry_paginas_pdf.pack(pady=(4, 12))

        ctk.CTkLabel(card, text="Rotação (usada em Girar)", font=_f("Montserrat", 11, "bold"), text_color=COLOR_SUBTITLE).pack()
        self.seg_rotacao_pdf = ctk.CTkSegmentedButton(card, values=["90° horário", "180°", "90° anti-horário"], selected_color=COLOR_VITA_BLUE, font=_f("Montserrat", 11, "bold"))
        self.seg_rotacao_pdf.set("90° horário")
        self.seg_rotacao_pdf.pack(pady=(4, 16))

        botoes = ctk.CTkFrame(card, fg_color="transparent")
        botoes.pack(pady=(0, 25))
        for texto, acao in (("Girar", "girar"), ("Extrair", "extrair"), ("Excluir", "excluir")):
            ctk.CTkButton(botoes, text=texto, width=120, height=40, font=_f("Montserrat", 12, "bold"), fg_color=COLOR_DANGER if acao == "excluir" else COLOR_VITA_BLUE, hover_color=_C("#AA0000") if acao == "excluir" else COLOR_HOVER, command=lambda a=acao: self._processar_paginas_pdf(a)).pack(side="left", padx=5)

    def selecionar_pdf_paginas(self):
        arquivo = filedialog.askopenfilename(title="Selecione o PDF", filetypes=[("Arquivos PDF", "*.pdf")])
        if not arquivo:
            return
        try:
            reader = PdfReader(arquivo)
            if reader.is_encrypted and not reader.decrypt(""):
                raise ValueError("O PDF está protegido por senha.")
            total = len(reader.pages)
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível abrir o PDF:\n{e}")
            return
        self.paginas_pdf_arquivo = arquivo
        self.paginas_pdf_total = total
        self.lbl_paginas_pdf.configure(text=f"{os.path.basename(arquivo)}  •  {total} página(s)", text_color=COLOR_ACCENT)

    def _processar_paginas_pdf(self, acao):
        if not self.paginas_pdf_arquivo:
            messagebox.showwarning("Atenção", "Selecione um PDF primeiro.")
            return
        origem, total = self.paginas_pdf_arquivo, self.paginas_pdf_total
        texto = self.entry_paginas_pdf.get().strip()
        try:
            if texto:
                selecionadas = _parse_paginas(texto, total)
            elif acao == "girar":
                selecionadas = list(range(total))
            else:
                raise ValueError("Informe as páginas (ex.: 1-3, 5, 8-10).")
        except ValueError as e:
            messagebox.showerror("Páginas inválidas", str(e))
            return
        if acao == "excluir" and len(selecionadas) >= total:
            messagebox.showerror("Erro", "Não é possível excluir todas as páginas do PDF.")
            return

        sufixos = {"girar": "girado", "extrair": "extraido", "excluir": "sem_paginas"}
        base = os.path.splitext(os.path.basename(origem))[0]
        saida = filedialog.asksaveasfilename(title="Salvar PDF como...", initialdir=os.path.dirname(origem), initialfile=f"{base}_{sufixos[acao]}.pdf", defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
        if not saida:
            return
        if os.path.abspath(saida) == os.path.abspath(origem):
            messagebox.showwarning("Atenção", "Escolha um nome diferente do arquivo original para não sobrescrevê-lo.")
            return
        try:
            reader = PdfReader(origem)
            if reader.is_encrypted:
                reader.decrypt("")
            writer = PdfWriter()
            if acao == "girar":
                graus = {"90° horário": 90, "180°": 180, "90° anti-horário": 270}[self.seg_rotacao_pdf.get()]
                alvo = set(selecionadas)
                for i, pagina in enumerate(reader.pages):
                    if i in alvo:
                        pagina.rotate(graus)
                    writer.add_page(pagina)
                resumo = f"{len(selecionadas)} página(s) girada(s) em {self.seg_rotacao_pdf.get()}."
            elif acao == "extrair":
                for i in selecionadas:
                    writer.add_page(reader.pages[i])
                resumo = f"{len(selecionadas)} página(s) extraída(s) para o novo PDF."
            else:
                excluir = set(selecionadas)
                for i, pagina in enumerate(reader.pages):
                    if i not in excluir:
                        writer.add_page(pagina)
                resumo = f"{len(excluir)} página(s) excluída(s); o PDF final tem {total - len(excluir)} página(s)."
            with open(saida, "wb") as f:
                writer.write(f)
            messagebox.showinfo("Sucesso", resumo)
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao processar o PDF:\n{e}")

    # ================= MÓDULO 11B: LEITOR DE NFS-E / CT-E (BETA) =================
    def setup_aba_nfse_cte(self):
        aba = self.frames_conteudo["📜 Leitor de NFS-e/CT-e (BETA)"]
        self.nfse_resumo = None
        self.nfse_campos = None
        self.nfse_modo_todos = False

        frame_topo = ctk.CTkFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        frame_topo.pack(fill="x", padx=20, pady=(20, 10))
        ctk.CTkLabel(frame_topo, text="LEITOR DE XML DE NFS-E E CT-E (BETA)", font=_f("Montserrat", 16, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(18, 8))
        ctk.CTkLabel(frame_topo, text="Selecione o XML de uma NFS-e (padrão nacional ou ABRASF) ou de um CT-e.\nO layout da NFS-e muda de prefeitura para prefeitura: se faltar algum campo,\nuse 'Ver Todos os Campos'.", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE, justify="center").pack(pady=(0, 12))

        botoes = ctk.CTkFrame(frame_topo, fg_color="transparent")
        botoes.pack(pady=(0, 18))
        ctk.CTkButton(botoes, text="Selecionar XML", width=150, height=38, font=_f("Montserrat", 12, "bold"), command=self.ler_xml_nfse_cte, fg_color=COLOR_ACCENT, text_color=COLOR_BG, hover_color=COLOR_HOVER_WHITE).pack(side="left", padx=(0, 8))
        self.btn_nfse_alternar = ctk.CTkButton(botoes, text="Ver Todos os Campos", width=160, height=38, font=_f("Montserrat", 12, "bold"), command=self.alternar_visao_nfse, fg_color="transparent", border_width=1, border_color=COLOR_SUBTITLE, text_color=COLOR_ACCENT, hover_color=COLOR_HOVER, state="disabled")
        self.btn_nfse_alternar.pack(side="left", padx=(0, 8))
        self.btn_nfse_exportar = ctk.CTkButton(botoes, text="Exportar para Excel", width=150, height=38, font=_f("Montserrat", 12, "bold"), command=self.exportar_nfse_excel, fg_color="transparent", border_width=1, border_color=COLOR_SUBTITLE, text_color=COLOR_ACCENT, hover_color=COLOR_HOVER, state="disabled")
        self.btn_nfse_exportar.pack(side="left")

        self.textbox_nfse = ctk.CTkTextbox(aba, fg_color=_C("#1A1A1A"), text_color=_C("#FFFFFF"), font=_f("Consolas", 12), border_width=0, wrap="word")
        self.textbox_nfse.pack(expand=True, fill="both", padx=20, pady=(0, 20))
        self._definir_texto(self.textbox_nfse, "Nenhum XML carregado ainda.")

    def _texto_do_resumo(self, resumo):
        linhas = []
        for campo, valor in resumo:
            if campo.startswith("== "):
                linhas.append(f"\n{campo}\n")
            else:
                valor = (valor or "-").replace("\n", "\n    ")
                linhas.append(f"{campo}: {valor}\n")
        return "".join(linhas).lstrip("\n")

    def ler_xml_nfse_cte(self):
        arquivo = filedialog.askopenfilename(title="Selecione o XML da NFS-e ou do CT-e", filetypes=[("Arquivo XML", "*.xml")])
        if not arquivo:
            return
        try:
            parser = etree.XMLParser(resolve_entities=False, no_network=True)
            raiz = etree.parse(arquivo, parser).getroot()
            tipo = _identificar_xml(raiz)
            if tipo == "nfe":
                messagebox.showinfo("Aviso", "Este XML é de NF-e (produtos). Use o 'Leitor de NF-e' no menu Fiscal.")
                return
            if tipo == "cte":
                resumo = _resumo_cte(raiz)
            elif tipo == "nfse":
                resumo = _resumo_nfse(raiz)
            else:
                resumo = [("== LAYOUT NÃO RECONHECIDO ==", ""), ("Aviso", "Não identifiquei este XML como NFS-e ou CT-e. Clique em 'Ver Todos os Campos' para ver o conteúdo.")]
            campos = _todos_os_campos(raiz)
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao ler o XML:\n{e}")
            return
        self.nfse_resumo, self.nfse_campos = resumo, campos
        self.nfse_modo_todos = False
        self.btn_nfse_alternar.configure(state="normal", text="Ver Todos os Campos")
        self.btn_nfse_exportar.configure(state="normal")
        self._definir_texto(self.textbox_nfse, self._texto_do_resumo(resumo))

    def alternar_visao_nfse(self):
        if self.nfse_resumo is None:
            return
        self.nfse_modo_todos = not self.nfse_modo_todos
        if self.nfse_modo_todos:
            texto = "\n".join(f"{c}: {v}" for c, v in self.nfse_campos) or "Nenhum campo encontrado."
            self.btn_nfse_alternar.configure(text="Ver Resumo")
        else:
            texto = self._texto_do_resumo(self.nfse_resumo)
            self.btn_nfse_alternar.configure(text="Ver Todos os Campos")
        self._definir_texto(self.textbox_nfse, texto)

    def exportar_nfse_excel(self):
        if self.nfse_resumo is None:
            messagebox.showwarning("Aviso", "Leia um XML primeiro.")
            return
        saida = filedialog.asksaveasfilename(title="Salvar planilha como...", defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
        if not saida:
            return
        try:
            df_resumo = pd.DataFrame(self.nfse_resumo, columns=["Campo", "Valor"])
            df_campos = pd.DataFrame(self.nfse_campos, columns=["Caminho", "Valor"])
            with pd.ExcelWriter(saida, engine="openpyxl") as escritor:
                for nome, df in (("Resumo", df_resumo), ("Todos os Campos", df_campos)):
                    df.to_excel(escritor, index=False, sheet_name=nome)
                    planilha = escritor.sheets[nome]
                    for celula in planilha[1]:
                        celula.font = Font(bold=True)
                    for coluna in planilha.columns:
                        maior = max((len(str(c.value)) for c in coluna if c.value is not None), default=10)
                        planilha.column_dimensions[coluna[0].column_letter].width = min(maior + 2, 60)
            messagebox.showinfo("Sucesso", "Dados exportados para Excel com sucesso!")
        except Exception as e:
            messagebox.showerror("Erro", f"Erro ao exportar para Excel:\n{e}")

    # ================= MÓDULO 11C: CONFERÊNCIA DE CHAVE DE ACESSO (BETA) =================
    def setup_aba_chave_nfe(self):
        aba = self.frames_conteudo["🔑 Conferência de Chave (BETA)"]
        topo = ctk.CTkFrame(aba, fg_color=_C("#262626"), corner_radius=12)
        topo.pack(fill="x", padx=20, pady=(20, 10))
        ctk.CTkLabel(topo, text="CONFERÊNCIA DE CHAVE DE ACESSO (BETA)", font=_f("Montserrat", 16, "bold"), text_color=COLOR_VITA_BLUE).pack(pady=(18, 8))
        ctk.CTkLabel(topo, text="Cole os 44 caracteres da chave de uma NF-e, NFC-e, CT-e ou MDF-e.\nO app confere o dígito verificador e mostra UF, emissão, CNPJ, modelo, série e número.", font=_f("Montserrat", 12), text_color=COLOR_SUBTITLE, justify="center").pack(pady=(0, 12))

        self.entry_chave = ctk.CTkEntry(topo, width=540, height=38, justify="center", font=_f("Consolas", 13), fg_color=_C("#1A1A1A"), border_width=0, placeholder_text="Cole a chave de acesso aqui")
        self.entry_chave.pack(pady=(0, 10))
        self.entry_chave.bind("<Return>", lambda e: self.conferir_chave())

        botoes = ctk.CTkFrame(topo, fg_color="transparent")
        botoes.pack(pady=(0, 18))
        ctk.CTkButton(botoes, text="Colar", width=90, height=36, fg_color=_C("#1A1A1A"), hover_color=COLOR_HOVER, text_color=COLOR_ACCENT, font=_f("Montserrat", 12, "bold"), command=self._colar_chave).pack(side="left", padx=(0, 8))
        ctk.CTkButton(botoes, text="Conferir", width=120, height=36, fg_color=COLOR_VITA_BLUE, font=_f("Montserrat", 12, "bold"), command=self.conferir_chave).pack(side="left", padx=(0, 8))
        ctk.CTkButton(botoes, text="Limpar", width=90, height=36, fg_color=_C("#1A1A1A"), hover_color=COLOR_HOVER, text_color=COLOR_ACCENT, font=_f("Montserrat", 12, "bold"), command=self._limpar_chave).pack(side="left")

        self.lbl_status_chave = ctk.CTkLabel(aba, text="", font=_f("Montserrat", 15, "bold"))
        self.lbl_status_chave.pack(pady=(0, 6))
        self.textbox_chave = ctk.CTkTextbox(aba, fg_color=_C("#1A1A1A"), text_color=_C("#FFFFFF"), font=_f("Consolas", 12), border_width=0, wrap="word")
        self.textbox_chave.pack(expand=True, fill="both", padx=20, pady=(0, 20))
        self._definir_texto(self.textbox_chave, "Nenhuma chave conferida ainda.")

    def _colar_chave(self):
        try:
            texto = self.clipboard_get()
        except tk.TclError:
            return
        self.entry_chave.delete(0, "end")
        self.entry_chave.insert(0, texto.strip())
        self.conferir_chave()

    def _limpar_chave(self):
        self.entry_chave.delete(0, "end")
        self.lbl_status_chave.configure(text="")
        self._definir_texto(self.textbox_chave, "Nenhuma chave conferida ainda.")

    def conferir_chave(self):
        chave = re.sub(r"[^0-9A-Za-z]", "", self.entry_chave.get()).upper()
        if len(chave) != 44:
            self.lbl_status_chave.configure(text=f"✖ A chave tem {len(chave)} caracteres; o correto são 44.", text_color=COLOR_DANGER)
            self._definir_texto(self.textbox_chave, "")
            return
        if not re.fullmatch(r"\d{6}[0-9A-Z]{12}\d{26}", chave):
            self.lbl_status_chave.configure(text="✖ Caracteres inválidos (só o CNPJ pode ter letras).", text_color=COLOR_DANGER)
            self._definir_texto(self.textbox_chave, "")
            return

        esperado = _dv_chave(chave[:43])
        valida = esperado == chave[43]
        if valida:
            self.lbl_status_chave.configure(text="✔ Dígito verificador confere.", text_color=_C("#00FF66"))
        else:
            self.lbl_status_chave.configure(text=f"✖ Dígito verificador não confere (esperado {esperado}, informado {chave[43]}).", text_color=COLOR_DANGER)

        ufs = {"11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO", "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF"}
        modelos = {"55": "NF-e", "65": "NFC-e", "57": "CT-e", "58": "MDF-e", "67": "CT-e OS", "59": "CF-e SAT", "63": "BP-e", "66": "NF3-e"}
        emissoes = {"1": "Normal", "2": "Contingência FS-IA", "3": "Contingência SCAN", "4": "Contingência EPEC", "5": "Contingência FS-DA", "6": "Contingência SVC-AN", "7": "Contingência SVC-RS", "9": "Contingência off-line NFC-e"}
        cnpj = chave[6:20]
        mes = int(chave[4:6])
        agrupada = " ".join(chave[i:i + 4] for i in range(0, 44, 4))
        linhas = [
            f"Chave:            {agrupada}",
            f"UF do emitente:   {ufs.get(chave[0:2], 'Código ' + chave[0:2] + ' desconhecido')}",
            f"Emissão (AAMM):   {chave[4:6]}/20{chave[2:4]}" + ("" if 1 <= mes <= 12 else "  (mês inválido)"),
            f"CNPJ emitente:    {_fmt_cnpj(cnpj)}  ({'CNPJ válido' if _cnpj_valido(cnpj) else 'dígitos do CNPJ não conferem'})",
            f"Modelo:           {chave[20:22]} - {modelos.get(chave[20:22], 'não identificado')}",
            f"Série:            {int(chave[22:25])}",
            f"Número:           {int(chave[25:34])}",
            f"Forma de emissão: {chave[34]} - {emissoes.get(chave[34], 'não identificada')}",
            f"Código numérico:  {chave[35:43]}",
            f"Dígito verif.:    {chave[43]}",
        ]
        self._definir_texto(self.textbox_chave, "\n".join(linhas))

    # ================= MÓDULO 12: DESLIGAMENTO =================
    def setup_aba_desligamento(self):
        aba = self.frames_conteudo["🔌 Desligamento Completo"]
        self.frame_center = ctk.CTkFrame(aba, fg_color="transparent")
        self.frame_center.place(relx=0.5, rely=0.5, anchor="center")

        self.alerta_label = ctk.CTkLabel(
            self.frame_center,
            text="Ao pressionar SIM, o equipamento será desligado em 10 segundos.\nAntes disso, o bot fará uma limpeza simples no sistema.\nPortanto, certifique-se de que o seu trabalho esteja finalizado e salvo.",
            font=_f("Montserrat", 12, "bold"), text_color=COLOR_DANGER, justify="center"
        )
        self.alerta_label.pack(pady=(0, 2))

        self.btn_sobre_limpeza = ctk.CTkLabel(self.frame_center, text="Sobre a limpeza simples.", font=_f("Montserrat", 11, "bold", "italic"), text_color=COLOR_ACCENT, cursor="hand2")
        self.btn_sobre_limpeza.pack(pady=(0, 25))
        self.btn_sobre_limpeza.bind("<Enter>", lambda e: self.btn_sobre_limpeza.configure(text_color=_C("#808080")))
        self.btn_sobre_limpeza.bind("<Leave>", lambda e: self.btn_sobre_limpeza.configure(text_color=COLOR_ACCENT))
        self.btn_sobre_limpeza.bind("<Button-1>", lambda e: self.mostrar_overlay_sobre_limpeza())

        self.btns_frame = ctk.CTkFrame(self.frame_center, fg_color="transparent")
        self.btns_frame.pack()

        self.btn_sim = ctk.CTkButton(self.btns_frame, text="SIM", fg_color=COLOR_DANGER, hover_color=_C("#AA0000"), text_color="white", width=120, height=45, font=_f("Montserrat", 12, "bold"), command=self.executar_desligamento)
        self.btn_sim.pack(side="left", padx=10)

        self.btn_nao = ctk.CTkButton(self.btns_frame, text="NÃO", fg_color=_C("#444444"), hover_color=_C("#555555"), text_color="white", width=120, height=45, font=_f("Montserrat", 12, "bold"), command=lambda: self.selecionar_aba("📄 Renomeação de PDFs"))
        self.btn_nao.pack(side="left", padx=10)

    def executar_desligamento(self):
        if self.nota_atual_id: self.salvar_nota_atual(silencioso=True)
        if self.senha_atual_id: self.salvar_senha_atual(silencioso=True)
        try: self.clipboard_clear()
        except: pass

        try:
            pastas_temp = [os.environ.get('TEMP'), os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Temp')]
            for pasta in pastas_temp:
                if pasta and os.path.exists(pasta):
                    try:
                        itens = os.listdir(pasta)
                    except Exception:
                        continue
                    for item in itens:
                        caminho_item = os.path.join(pasta, item)
                        try:
                            if os.path.isfile(caminho_item) or os.path.islink(caminho_item): os.unlink(caminho_item)
                            elif os.path.isdir(caminho_item): shutil.rmtree(caminho_item)
                        except: pass
        except Exception:
            pass

        try:
            import subprocess
            subprocess.Popen(["shutdown.exe", "/s", "/f", "/t", "10"], shell=False)
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível iniciar o desligamento:\n{e}")


    # ================= OVERLAYS E FUNÇÕES GERAIS =================
    def mostrar_overlay_sobre(self):
        if self.overlay_frame is not None: return
        self.overlay_frame = ctk.CTkFrame(self, fg_color=COLOR_OVERLAY_GRAY, corner_radius=0)
        self.overlay_frame.place(relx=0, rely=0, relwidth=1.0, relheight=1.0)
        
        card_popup = ctk.CTkFrame(self.overlay_frame, fg_color=COLOR_CARD, corner_radius=15, border_width=4, border_color=COLOR_VITA_BLUE, width=440, height=220)
        card_popup.place(relx=0.5, rely=0.5, anchor="center")
        card_popup.pack_propagate(False)
        
        content_frame = ctk.CTkFrame(card_popup, fg_color="transparent")
        content_frame.place(relx=0.5, rely=0.5, anchor="center")
        
        lbl_info = ctk.CTkLabel(content_frame, text="Para pedido de adição de funções, clique no e-mail para copiar:", font=_f("Montserrat", 12, "bold"), text_color=COLOR_ACCENT, wraplength=380, justify="center")
        lbl_info.pack(pady=(0, 10))
        
        lbl_email = ctk.CTkLabel(content_frame, text="fabio.sousa@vitacontabil.com.br", font=_f("Montserrat", 13, "bold", "underline"), text_color=COLOR_VITA_BLUE, cursor="hand2")
        lbl_email.pack(pady=(0, 5))
        
        lbl_status = ctk.CTkLabel(content_frame, text="", font=_f("Montserrat", 11, "bold", "italic"), text_color=_C("#00FF66"))
        lbl_status.pack(pady=(0, 15))
        
        def copiar_para_clipboard(event):
            self.clipboard_clear()
            self.clipboard_append("fabio.sousa@vitacontabil.com.br")
            self.update()
            lbl_status.configure(text="E-mail copiado para a área de transferência!")
            self.after(2500, lambda: lbl_status.configure(text="") if self.overlay_frame else None)
            
        lbl_email.bind("<Button-1>", copiar_para_clipboard)
        
        btn_fechar = ctk.CTkButton(content_frame, text="Fechar", width=100, height=35, fg_color=_C("#262626"), hover_color=COLOR_HOVER, text_color=COLOR_ACCENT, font=_f("Montserrat", 11, "bold"), command=self.fechar_overlays)
        btn_fechar.pack()

    def mostrar_overlay_sobre_limpeza(self):
        if self.overlay_frame is not None: return
        self.overlay_frame = ctk.CTkFrame(self, fg_color=COLOR_OVERLAY_GRAY, corner_radius=0)
        self.overlay_frame.place(relx=0, rely=0, relwidth=1.0, relheight=1.0)
        
        card_popup = ctk.CTkFrame(self.overlay_frame, fg_color=COLOR_CARD, corner_radius=15, border_width=4, border_color=COLOR_DANGER, width=600, height=480)
        card_popup.place(relx=0.5, rely=0.5, anchor="center")
        card_popup.pack_propagate(False)

        content_frame = ctk.CTkFrame(card_popup, fg_color="transparent")
        content_frame.place(relx=0.5, rely=0.5, anchor="center")

        titulo_frame_1 = ctk.CTkFrame(content_frame, fg_color="transparent")
        titulo_frame_1.pack(pady=(0, 5))
        ctk.CTkLabel(titulo_frame_1, text="O que irá acontecer?", font=_f("Fraunces 9pt Black Italic", 22), text_color=COLOR_ACCENT).pack()

        texto_oque = "• As pastas de arquivos temporários (temp e %temp%) serão esvaziadas;\n• A área de transferência (histórico de copiar e colar) será limpa."
        ctk.CTkLabel(content_frame, text=texto_oque, font=_f("Montserrat", 13), text_color=COLOR_ACCENT, justify="center").pack(pady=(0, 25))

        titulo_frame_2 = ctk.CTkFrame(content_frame, fg_color="transparent")
        titulo_frame_2.pack(pady=(0, 5))
        ctk.CTkLabel(titulo_frame_2, text="Por que será feito isso?", font=_f("Fraunces 9pt Black Italic", 22), text_color=COLOR_ACCENT).pack()

        texto_porque = (
            "Esta ação é realizada porque o acúmulo de lixo digital deixa o sistema\n"
            "lento com o tempo. Ao limpar os arquivos temporários, liberamos espaço\n"
            "em disco e garantimos que o computador inicie mais rápido no próximo uso.\n\n"
            "Além disso, limpamos a área de transferência por que é uma boa prática\n"
            "de segurança, evitando que dados sensíveis copiados fiquem expostos\n"
            "na memória."
        )
        
        ctk.CTkLabel(content_frame, text=texto_porque, font=_f("Montserrat", 13), text_color=COLOR_ACCENT, justify="center").pack(pady=(0, 30))
        ctk.CTkButton(content_frame, text="Entendi!", width=110, height=40, fg_color=_C("#262626"), hover_color=COLOR_HOVER, text_color=COLOR_ACCENT, font=_f("Montserrat", 12, "bold"), command=self.fechar_overlays).pack()

    def mostrar_overlay_local_salvamento(self):
        if self.overlay_frame is not None: return
        self.overlay_frame = ctk.CTkFrame(self, fg_color=COLOR_OVERLAY_GRAY, corner_radius=0)
        self.overlay_frame.place(relx=0, rely=0, relwidth=1.0, relheight=1.0)
        
        card_popup = ctk.CTkFrame(self.overlay_frame, fg_color=COLOR_CARD, corner_radius=15, border_width=4, border_color=_C("#FFFFFF"), width=500, height=280)
        card_popup.place(relx=0.5, rely=0.5, anchor="center")
        card_popup.pack_propagate(False)

        content_frame = ctk.CTkFrame(card_popup, fg_color="transparent")
        content_frame.place(relx=0.5, rely=0.5, anchor="center")

        lbl_titulo = ctk.CTkLabel(content_frame, text="Local de Salvamento", font=_f("Fraunces 9pt Black Italic", 22), text_color=COLOR_ACCENT)
        lbl_titulo.pack(pady=(0, 15))

        lbl_desc = ctk.CTkLabel(content_frame, text="Suas anotações estão sendo salvas com segurança no seguinte local do seu computador:", font=_f("Montserrat", 13), text_color=COLOR_ACCENT, wraplength=400, justify="center")
        lbl_desc.pack(pady=(0, 15))

        lbl_path = ctk.CTkLabel(content_frame, text=ARQUIVO_NOTAS, font=_f("Montserrat", 12, "bold", "underline"), text_color=COLOR_VITA_BLUE, wraplength=450, justify="center", cursor="hand2")
        lbl_path.pack(pady=(0, 25))
        
        lbl_path.bind("<Enter>", lambda e: lbl_path.configure(text_color=_C("#FFFFFF")))
        lbl_path.bind("<Leave>", lambda e: lbl_path.configure(text_color=COLOR_VITA_BLUE))
        
        def abrir_pasta_salvamento(event):
            try: os.startfile(PASTA_APPDATA)
            except Exception: pass
                
        lbl_path.bind("<Button-1>", abrir_pasta_salvamento)

        btn_fechar = ctk.CTkButton(content_frame, text="Fechar", width=100, height=35, fg_color=_C("#262626"), hover_color=COLOR_HOVER, text_color=COLOR_ACCENT, font=_f("Montserrat", 12, "bold"), command=self.fechar_overlays)
        btn_fechar.pack()

    def fechar_overlays(self):
        if self.overlay_frame:
            self.overlay_frame.destroy()
            self.overlay_frame = None

# --- EXECUÇÃO DO APLICATIVO ---
if __name__ == "__main__":
    app = App()
    app.mainloop()
