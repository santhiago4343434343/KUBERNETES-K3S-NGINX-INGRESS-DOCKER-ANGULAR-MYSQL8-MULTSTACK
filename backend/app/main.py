import os
import time
import uuid
import datetime
import hashlib
import html
import smtplib
import requests
import bcrypt
import jwt
from email.message import EmailMessage
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from fastapi import FastAPI, HTTPException, Header, Depends, BackgroundTasks, Response
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, Text, JSON, Boolean, DateTime, or_
from sqlalchemy.orm import declarative_base, sessionmaker

USER = os.getenv("MYSQL_USER", "catalogo_user")
PASSWORD = os.getenv("MYSQL_PASSWORD", "changeme")
HOST = os.getenv("MYSQL_HOST", "mysql")
DB = os.getenv("MYSQL_DATABASE", "catalogo")
TMDB_KEY = os.getenv("TMDB_API_KEY", "")
JWT_SECRET = os.getenv("JWT_SECRET", "changeme-in-production")
JWT_ALG = "HS256"
TURNSTILE_SECRET = os.getenv("TURNSTILE_SECRET", "")
MAIL_HOST = os.getenv("MAIL_HOST", "")
MAIL_PORT = int(os.getenv("MAIL_PORT", "2525"))
MAIL_USER = os.getenv("MAIL_USER", "")
MAIL_PASS = os.getenv("MAIL_PASS", "")
MAIL_FROM = os.getenv("MAIL_FROM", "catalogo@filmes.dev")
APP_URL = os.getenv("APP_URL", "http://localhost:8090")
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_SECRET = os.getenv("PAYPAL_SECRET", "")
PAYPAL_API = os.getenv("PAYPAL_API", "https://api-m.sandbox.paypal.com")
PREMIUM_MOEDA = os.getenv("PREMIUM_MOEDA", "BRL")
PREMIUM_PRECO = os.getenv("PREMIUM_PRECO", "19.90")

# --- Chatbot com IA (Groq - formato OpenAI) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELO = os.getenv("GROQ_MODELO", "openai/gpt-oss-20b")
# "personalidade" e conhecimento do bot sobre o servico
CHAT_SYSTEM = (
    "Voce e o assistente virtual do MOVIES TMDA, um catalogo de filmes online. "
    "O site e um catalogo pessoal: o usuario busca filmes, ve detalhes e trailers, e organiza "
    "sua propria lista (quero ver, assistindo, assistido). Nao e um servico de streaming. "
    "Responda sempre em portugues do Brasil, de forma simpatica, curta e direta. "
    "Escreva em texto simples e corrido: NAO use markdown, NAO use asteriscos (*), "
    "NAO use tabelas nem simbolos como | ou #. No maximo use emojis e quebras de linha. "
    f"A assinatura Premium custa {PREMIUM_MOEDA} {PREMIUM_PRECO} e da acesso a filmes em cartaz, "
    "estreias, area VIP (mais votados e tendencias do dia) e um selo Premium no perfil. "
    "O pagamento e feito pelo PayPal. O usuario pode pedir reembolso (estorno) a qualquer momento "
    "no botao 'Cancelar Premium e solicitar reembolso', e o valor volta pelo proprio PayPal. "
    "Cada e-mail so pode ter uma conta: o cadastro nao permite e-mail nem nome de usuario repetidos. "
    "Para trocar a senha, use 'Esqueci minha senha' na tela de login. "
    "Duvidas podem ser enviadas pelo formulario de contato do site. "
    "Para perguntas sobre filmes (catalogo, em cartaz, lancamentos, novembro, 2027), use APENAS "
    "a lista de filmes reais fornecida abaixo no contexto do sistema. Nao invente titulos fora dessa lista. "
    "Se o filme que a pessoa procura nao estiver na lista, sugira usar a barra de busca do site. "
    "REGRA DE OURO: se a resposta para uma pergunta NAO estiver claramente nas informacoes acima, "
    "nao invente nem chute uma politica ou dado. Diga com simpatia que nao tem essa informacao "
    "no momento e que a pessoa pode falar com o atendimento pelo formulario de contato do site. "
    "Se perguntarem algo fora do tema de filmes ou do servico, responda com simpatia e "
    "traga a conversa de volta ao MOVIES TMDA."
)

DATABASE_URL = f"mysql+pymysql://{USER}:{PASSWORD}@{HOST}:3306/{DB}"
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Filme(Base):
    __tablename__ = "filmes"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(80), index=True)
    titulo = Column(String(200))
    status = Column(String(50))
    ano = Column(String(10))
    nota = Column(Float)
    sinopse = Column(Text)
    generos = Column(JSON)
    classificacao = Column(String(10))
    poster_url = Column(String(300))
    trailers = Column(JSON)
    imagens = Column(JSON)


class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(80), unique=True, index=True)
    email = Column(String(120))
    senha_hash = Column(String(200))
    confirmado = Column(Boolean, default=False)
    token_confirmacao = Column(String(64))
    premium = Column(Boolean, default=False)
    token_reset = Column(String(64))
    paypal_capture_id = Column(String(64))


class Transacao(Base):
    __tablename__ = "transacoes"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(80), index=True)
    tipo = Column(String(20))            # "pagamento" ou "estorno"
    capture_id = Column(String(64))
    valor = Column(String(20))
    moeda = Column(String(10))
    status = Column(String(30))          # COMPLETED, REFUNDED...
    criado_em = Column(DateTime)


def registrar_transacao(db, username, tipo, capture_id, status):
    # DRY: um unico lugar cria a linha do "livro-razao"
    t = Transacao(
        username=username, tipo=tipo, capture_id=capture_id,
        valor=PREMIUM_PRECO, moeda=PREMIUM_MOEDA, status=status,
        criado_em=datetime.datetime.now(datetime.timezone.utc),
    )
    db.add(t)


for tentativa in range(10):
    try:
        Base.metadata.create_all(engine)
        break
    except Exception as e:
        print(f"MySQL ainda nao respondeu ({e}); tentando de novo...")
        time.sleep(3)

app = FastAPI()


# ==================== AUTENTICACAO ====================
class UsuarioIn(BaseModel):
    username: str
    senha: str
    email: str = ""
    captcha: str = ""


def criar_hash(senha: str) -> str:
    return bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode()


def conferir_senha(senha: str, senha_hash: str) -> bool:
    return bcrypt.checkpw(senha.encode(), senha_hash.encode())


def senha_vazou(senha: str) -> int:
    """Have I Been Pwned (k-anonymity): devolve quantas vezes a senha ja apareceu
    em vazamentos publicos. 0 = nao encontrada. Nunca envia a senha nem o hash
    inteiro: manda SO os 5 primeiros caracteres do SHA-1 e compara o resto aqui."""
    try:
        sha1 = hashlib.sha1(senha.encode("utf-8")).hexdigest().upper()
        prefixo, sufixo = sha1[:5], sha1[5:]
        r = requests.get(
            f"https://api.pwnedpasswords.com/range/{prefixo}",
            headers={"User-Agent": "catalogo-filmes-app", "Add-Padding": "true"},
            timeout=5,
        )
        if r.status_code != 200:
            return 0
        for linha in r.text.splitlines():
            parte = linha.split(":")
            if len(parte) == 2 and parte[0] == sufixo:
                return int(parte[1])
        return 0
    except Exception as e:
        # se o HIBP cair, NAO bloqueia o usuario (fail-open): essa e uma camada
        # EXTRA de seguranca e nao pode derrubar o cadastro/reset por falha de rede.
        print(f"HIBP indisponivel, pulando checagem: {e}", flush=True)
        return 0


def bloquear_se_vazou(senha: str):
    vezes = senha_vazou(senha)
    if vezes:
        qtd = f"{vezes:,}".replace(",", ".")
        raise HTTPException(
            status_code=400,
            detail=f"Essa senha ja apareceu em vazamentos publicos de dados ({qtd} vezes). Por seguranca, escolha outra.",
        )


def verificar_turnstile(token: str):
    # se nao houver chave configurada, nao bloqueia (util em dev)
    if not TURNSTILE_SECRET:
        return
    r = requests.post(
        "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        data={"secret": TURNSTILE_SECRET, "response": token},
        timeout=10,
    )
    if not r.json().get("success"):
        raise HTTPException(status_code=400, detail="Verificacao anti-robo falhou. Tente de novo.")


def enviar_email(destino: str, assunto: str, corpo_html: str, anexo: bytes = None, anexo_nome: str = "documento.pdf"):
    # se o Mailtrap nao estiver configurado, apenas ignora (nao quebra o cadastro)
    if not MAIL_HOST or not MAIL_USER:
        print("Mailtrap nao configurado; e-mail ignorado", flush=True)
        return
    try:
        msg = EmailMessage()
        msg["Subject"] = assunto
        msg["From"] = MAIL_FROM
        msg["To"] = destino
        msg.set_content("Seu cliente de e-mail nao suporta HTML.")
        msg.add_alternative(corpo_html, subtype="html")
        if anexo:
            msg.add_attachment(anexo, maintype="application", subtype="pdf", filename=anexo_nome)
        with smtplib.SMTP(MAIL_HOST, MAIL_PORT) as s:
            s.starttls()
            s.login(MAIL_USER, MAIL_PASS)
            s.send_message(msg)
        print(f"E-mail enviado para {destino}", flush=True)
    except Exception as e:
        print(f"Falha ao enviar e-mail: {e}", flush=True)


LOGO_PAYPAL = os.path.join(os.path.dirname(__file__), "paypal.png")


def gerar_comprovante_pdf(username, email, metodo, capture_id, data_str):
    # gera um comprovante de pagamento em PDF (em memoria) para anexar no e-mail
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 18)
        pdf.cell(0, 12, "MOVIES TMDA - Comprovante de Pagamento", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_draw_color(79, 70, 229)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(6)
        linhas = [
            ("Cliente", username),
            ("E-mail", email),
            ("Plano", "Premium"),
            ("Valor", f"{PREMIUM_MOEDA} {PREMIUM_PRECO}"),
            ("Metodo de pagamento", metodo),
            ("ID da transacao", capture_id or "-"),
            ("Data", data_str),
            ("Status", "PAGO"),
        ]
        for rotulo, valor in linhas:
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(55, 9, f"{rotulo}:", border=0)
            pdf.set_font("Helvetica", "", 12)
            pdf.cell(0, 9, str(valor), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(12)
        y = pdf.get_y()
        try:
            pdf.image(LOGO_PAYPAL, x=(210 - 45) / 2, y=y, w=45)   # logo oficial do PayPal (centralizada)
            pdf.set_y(y + 20)
        except Exception:
            pass   # se o arquivo da logo nao existir, o comprovante sai normal (sem a logo)
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(90, 90, 90)
        pdf.cell(0, 6, "technology in payments", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(3)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(130, 130, 130)
        pdf.multi_cell(0, 5, "Documento gerado automaticamente para fins de demonstracao (projeto academico). Pagamento processado em ambiente sandbox do PayPal - sem cobranca real.", align="C")
        return bytes(pdf.output())
    except Exception as e:
        print(f"Falha ao gerar PDF: {e}", flush=True)
        return None


def gerar_comprovante_estorno_pdf(username, email, refund_id, data_str):
    # gera um comprovante de ESTORNO em PDF (em memoria) para anexar no e-mail
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 18)
        pdf.cell(0, 12, "MOVIES TMDA - Comprovante de Estorno", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_draw_color(220, 38, 38)   # linha vermelha (estorno)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(6)
        linhas = [
            ("Cliente", username),
            ("E-mail", email),
            ("Plano", "Premium (cancelado)"),
            ("Valor estornado", f"{PREMIUM_MOEDA} {PREMIUM_PRECO}"),
            ("ID do estorno", refund_id or "-"),
            ("Data", data_str),
            ("Status", "ESTORNADO"),
        ]
        for rotulo, valor in linhas:
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(55, 9, f"{rotulo}:", border=0)
            pdf.set_font("Helvetica", "", 12)
            pdf.cell(0, 9, str(valor), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(12)
        y = pdf.get_y()
        try:
            pdf.image(LOGO_PAYPAL, x=(210 - 45) / 2, y=y, w=45)   # logo oficial do PayPal (centralizada)
            pdf.set_y(y + 20)
        except Exception:
            pass   # se a logo nao existir, o comprovante sai normal (sem a logo)
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(90, 90, 90)
        pdf.cell(0, 6, "technology in payments", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(3)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(130, 130, 130)
        pdf.multi_cell(0, 5, "Documento gerado automaticamente para fins de demonstracao (projeto academico). Estorno processado em ambiente sandbox do PayPal - sem movimentacao financeira real.", align="C")
        return bytes(pdf.output())
    except Exception as e:
        print(f"Falha ao gerar PDF de estorno: {e}", flush=True)
        return None


def criar_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def usuario_logado(authorization: str = Header(default="")) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Faca login para continuar")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        return payload["sub"]
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Sessao expirada, entre de novo")


def usuario_opcional(authorization: str = Header(default="")) -> str | None:
    # igual ao usuario_logado, mas NAO bloqueia se nao houver token (usado no chat, que e publico)
    if not authorization.startswith("Bearer "):
        return None
    try:
        payload = jwt.decode(authorization.split(" ", 1)[1], JWT_SECRET, algorithms=[JWT_ALG])
        return payload["sub"]
    except jwt.PyJWTError:
        return None


@app.post("/api/register")
def register(dados: UsuarioIn, tarefas: BackgroundTasks):
    verificar_turnstile(dados.captcha)
    username = dados.username.strip()
    email = dados.email.strip()
    senha = dados.senha
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="Usuario precisa de ao menos 3 caracteres")
    if "@" not in email or "." not in email:
        raise HTTPException(status_code=400, detail="Informe um e-mail valido")
    senha_forte = (
        len(senha) >= 8
        and any(c.isupper() for c in senha)
        and any(c.isdigit() for c in senha)
        and any(not c.isalnum() for c in senha)
    )
    if not senha_forte:
        raise HTTPException(status_code=400, detail="Senha fraca: use 8+ caracteres, uma maiuscula, um numero e um caractere especial")
    bloquear_se_vazou(senha)
    db = SessionLocal()
    try:
        if db.query(Usuario).filter(Usuario.username == username).first():
            raise HTTPException(status_code=400, detail="Esse usuario ja existe")
        if db.query(Usuario).filter(Usuario.email == email).first():
            raise HTTPException(status_code=400, detail="Esse e-mail ja esta cadastrado")
        token_conf = uuid.uuid4().hex
        u = Usuario(
            username=username, email=email, senha_hash=criar_hash(dados.senha),
            confirmado=False, token_confirmacao=token_conf,
        )
        db.add(u)
        db.commit()
        link = f"{APP_URL}/?confirmar={token_conf}"
        corpo = (
            '<div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;">'
            '<h2 style="color:#4f46e5;">🎬 MOVIES TMDA</h2>'
            f'<p>Ola, <strong>{username}</strong>! Falta um passo para ativar sua conta.</p>'
            f'<p style="margin:24px 0;"><a href="{link}" style="background:#4f46e5;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;">Confirmar meu cadastro</a></p>'
            f'<p style="color:#64748b;font-size:13px;">Ou copie e cole este link no navegador:<br>{link}</p>'
            '<p style="color:#64748b;font-size:13px;margin-top:24px;">MOVIES TMDA &middot; Powered by TMDB</p>'
            '</div>'
        )
        tarefas.add_task(enviar_email, email, "Confirme seu cadastro - MOVIES TMDA", corpo)
        return {"mensagem": "Conta criada! Enviamos um e-mail para voce confirmar o cadastro."}
    finally:
        db.close()


@app.post("/api/login")
def login(dados: UsuarioIn):
    verificar_turnstile(dados.captcha)
    db = SessionLocal()
    try:
        ident = dados.username.strip()
        u = db.query(Usuario).filter(
            or_(Usuario.username == ident, Usuario.email == ident)
        ).first()
        if not u or not conferir_senha(dados.senha, u.senha_hash):
            raise HTTPException(status_code=401, detail="Usuario ou senha invalidos")
        if not u.confirmado:
            raise HTTPException(status_code=403, detail="Confirme seu e-mail antes de entrar. Verifique sua caixa de entrada.")
        return {"token": criar_token(u.username), "username": u.username, "premium": bool(u.premium)}
    finally:
        db.close()


@app.get("/api/me")
def me(usuario: str = Depends(usuario_logado)):
    db = SessionLocal()
    try:
        u = db.query(Usuario).filter(Usuario.username == usuario).first()
        return {"username": usuario, "premium": bool(u and u.premium)}
    finally:
        db.close()


@app.get("/api/confirmar")
def confirmar(token: str):
    db = SessionLocal()
    try:
        u = db.query(Usuario).filter(Usuario.token_confirmacao == token).first()
        if not u:
            raise HTTPException(status_code=400, detail="Link invalido ou ja utilizado")
        u.confirmado = True
        u.token_confirmacao = None
        db.commit()
        return {"mensagem": "Conta confirmada com sucesso!", "username": u.username}
    finally:
        db.close()


class EmailIn(BaseModel):
    email: str


class ResetIn(BaseModel):
    token: str
    senha: str


@app.post("/api/esqueci-senha")
def esqueci_senha(dados: EmailIn, tarefas: BackgroundTasks):
    db = SessionLocal()
    try:
        u = db.query(Usuario).filter(Usuario.email == dados.email.strip()).first()
        if u:
            token = uuid.uuid4().hex
            u.token_reset = token
            db.commit()
            link = f"{APP_URL}/?resetar={token}"
            corpo = (
                '<div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;">'
                '<h2 style="color:#4f46e5;">🔑 Redefinir senha</h2>'
                f'<p>Ola, <strong>{u.username}</strong>! Recebemos um pedido para redefinir sua senha.</p>'
                f'<p style="margin:24px 0;"><a href="{link}" style="background:#4f46e5;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;">Criar uma nova senha</a></p>'
                f'<p style="color:#64748b;font-size:13px;">Ou copie e cole este link no navegador:<br>{link}</p>'
                '<p style="color:#64748b;font-size:13px;margin-top:24px;">Se voce nao pediu isso, pode ignorar este e-mail. MOVIES TMDA &middot; Powered by TMDB</p>'
                '</div>'
            )
            tarefas.add_task(enviar_email, u.email, "Redefinir sua senha - MOVIES TMDA", corpo)
        # resposta igual sempre, exista o e-mail ou nao (nao revela quem tem conta)
        return {"mensagem": "Se o e-mail estiver cadastrado, enviamos um link para redefinir a senha."}
    finally:
        db.close()


@app.post("/api/reenviar-confirmacao")
def reenviar_confirmacao(dados: EmailIn, tarefas: BackgroundTasks):
    # reenvia o e-mail de confirmacao para quem se cadastrou mas ainda nao confirmou
    db = SessionLocal()
    try:
        u = db.query(Usuario).filter(Usuario.email == dados.email.strip()).first()
        if u and not u.confirmado:
            if not u.token_confirmacao:
                u.token_confirmacao = uuid.uuid4().hex
                db.commit()
            link = f"{APP_URL}/?confirmar={u.token_confirmacao}"
            corpo = (
                '<div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;">'
                '<h2 style="color:#4f46e5;">🎬 MOVIES TMDA</h2>'
                f'<p>Ola, <strong>{u.username}</strong>! Aqui esta um novo link para confirmar seu cadastro.</p>'
                f'<p style="margin:24px 0;"><a href="{link}" style="background:#4f46e5;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;">Confirmar meu cadastro</a></p>'
                f'<p style="color:#64748b;font-size:13px;">Ou copie e cole este link no navegador:<br>{link}</p>'
                '<p style="color:#64748b;font-size:13px;margin-top:24px;">MOVIES TMDA &middot; Powered by TMDB</p>'
                '</div>'
            )
            tarefas.add_task(enviar_email, u.email, "Confirme seu cadastro - MOVIES TMDA", corpo)
        # resposta igual sempre (nao revela quem tem conta nem quem ja confirmou)
        return {"mensagem": "Se o e-mail estiver cadastrado e pendente, reenviamos a confirmacao."}
    finally:
        db.close()


@app.post("/api/resetar-senha")
def resetar_senha(dados: ResetIn):
    senha = dados.senha
    senha_forte = (
        len(senha) >= 8
        and any(c.isupper() for c in senha)
        and any(c.isdigit() for c in senha)
        and any(not c.isalnum() for c in senha)
    )
    if not senha_forte:
        raise HTTPException(status_code=400, detail="Senha fraca: use 8+ caracteres, uma maiuscula, um numero e um caractere especial")
    bloquear_se_vazou(senha)
    db = SessionLocal()
    try:
        u = db.query(Usuario).filter(Usuario.token_reset == dados.token).first()
        if not u:
            raise HTTPException(status_code=400, detail="Link invalido ou ja utilizado")
        if conferir_senha(senha, u.senha_hash):
            raise HTTPException(status_code=400, detail="Essa senha e igual a sua senha atual. Escolha uma senha diferente.")
        u.senha_hash = criar_hash(senha)
        u.token_reset = None
        db.commit()
        return {"mensagem": "Senha redefinida com sucesso! Agora e so entrar."}
    finally:
        db.close()


# ==================== TMDB ====================
class FilmeIn(BaseModel):
    titulo: str
    status: str = "quero ver"
    tmdb_id: int = 0


def extrair_classificacao(filme: dict) -> str:
    for pais in filme.get("release_dates", {}).get("results", []):
        if pais.get("iso_3166_1") == "BR":
            for r in pais.get("release_dates", []):
                if r.get("certification"):
                    return r["certification"]
    return ""


def detalhes_tmdb(movie_id: int) -> dict:
    if not TMDB_KEY:
        return {}
    det = requests.get(
        f"https://api.themoviedb.org/3/movie/{movie_id}",
        params={
            "api_key": TMDB_KEY,
            "language": "pt-BR",
            "append_to_response": "videos,images,release_dates",
            "include_image_language": "pt,en,null",
        },
        timeout=10,
    )
    filme = det.json()

    videos = filme.get("videos", {}).get("results", [])
    trailers = [
        v["key"] for v in videos
        if v.get("site") == "YouTube" and v.get("type") in ("Trailer", "Teaser")
    ]
    backdrops = filme.get("images", {}).get("backdrops", [])
    imagens = [f"https://image.tmdb.org/t/p/w780{b['file_path']}" for b in backdrops[:8]]
    poster = filme.get("poster_path")

    return {
        "id": movie_id,
        "titulo": filme.get("title", ""),
        "ano": (filme.get("release_date") or "")[:4],
        "nota": round(filme.get("vote_average") or 0, 1),
        "sinopse": filme.get("overview", ""),
        "generos": [g["name"] for g in filme.get("genres", [])],
        "classificacao": extrair_classificacao(filme),
        "poster_url": f"https://image.tmdb.org/t/p/w500{poster}" if poster else "",
        "trailers": trailers,
        "imagens": imagens,
    }


def buscar_tmdb(titulo: str) -> dict:
    if not TMDB_KEY:
        return {}
    busca = requests.get(
        "https://api.themoviedb.org/3/search/movie",
        params={"api_key": TMDB_KEY, "query": titulo, "language": "pt-BR"},
        timeout=10,
    )
    resultados = busca.json().get("results", [])
    if not resultados:
        return {}
    return detalhes_tmdb(resultados[0]["id"])


def to_dict(f: Filme) -> dict:
    return {
        "id": f.id, "titulo": f.titulo, "status": f.status,
        "ano": f.ano, "nota": f.nota, "sinopse": f.sinopse,
        "generos": f.generos or [], "classificacao": f.classificacao,
        "poster_url": f.poster_url,
        "trailers": f.trailers or [], "imagens": f.imagens or [],
    }


# ==================== DESTAQUES (vitrine da home) ====================
def _mapear(resultados: list) -> list:
    itens = []
    for m in resultados[:12]:
        poster = m.get("poster_path")
        backdrop = m.get("backdrop_path")
        itens.append({
            "id": m.get("id"),
            "titulo": m.get("title", ""),
            "ano": (m.get("release_date") or "")[:4],
            "nota": round(m.get("vote_average") or 0, 1),
            "sinopse": m.get("overview", ""),
            "poster_url": f"https://image.tmdb.org/t/p/w500{poster}" if poster else "",
            "backdrop_url": f"https://image.tmdb.org/t/p/w1280{backdrop}" if backdrop else "",
        })
    return itens


def _tmdb_lista(path: str, extra: dict) -> list:
    if not TMDB_KEY:
        return []
    params = {"api_key": TMDB_KEY, "language": "pt-BR"}
    params.update(extra)
    try:
        r = requests.get(f"https://api.themoviedb.org/3{path}", params=params, timeout=10)
        return _mapear(r.json().get("results", []))
    except Exception:
        return []


@app.get("/api/destaques")
def destaques():
    return {
        "em_alta": _tmdb_lista("/trending/movie/week", {}),
        "lancamentos": _tmdb_lista("/movie/upcoming", {"region": "BR"}),
        "populares": _tmdb_lista("/movie/popular", {"region": "BR"}),
        "ano_2027": _tmdb_lista("/discover/movie", {"primary_release_year": 2027, "sort_by": "popularity.desc"}),
        "novembro": _tmdb_lista("/discover/movie", {
            "primary_release_date.gte": "2026-11-01",
            "primary_release_date.lte": "2026-11-30",
            "sort_by": "popularity.desc",
        }),
    }


@app.get("/api/buscar")
def buscar(q: str, usuario: str = Depends(usuario_logado)):
    if not q.strip():
        return []
    return _tmdb_lista("/search/movie", {"query": q})


@app.get("/api/detalhes/{tmdb_id}")
def detalhes_filme(tmdb_id: int):
    # publico: a vitrine mostra detalhes sem precisar de login
    info = detalhes_tmdb(tmdb_id)
    if not info:
        raise HTTPException(status_code=404, detail="Filme nao encontrado")
    return info


# ==================== PREMIUM (PayPal Sandbox) ====================
class PagamentoIn(BaseModel):
    order_id: str


def paypal_token() -> str:
    # pega um token de acesso do PayPal (OAuth2) usando Client ID + Secret
    r = requests.post(
        f"{PAYPAL_API}/v1/oauth2/token",
        auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET),
        data={"grant_type": "client_credentials"},
        timeout=15,
    )
    return r.json().get("access_token", "")


@app.post("/api/assinar")
def assinar(usuario: str = Depends(usuario_logado)):
    # FASE 2: cria uma ordem no PayPal e devolve o link de aprovacao (sandbox)
    if not PAYPAL_CLIENT_ID or not PAYPAL_SECRET:
        raise HTTPException(status_code=400, detail="PayPal nao configurado")
    token = paypal_token()
    r = requests.post(
        f"{PAYPAL_API}/v2/checkout/orders",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "intent": "CAPTURE",
            "purchase_units": [{
                "amount": {"currency_code": PREMIUM_MOEDA, "value": PREMIUM_PRECO},
                "description": "Assinatura Premium - MOVIES TMDA",
            }],
            "application_context": {
                "brand_name": "MOVIES TMDA",
                "user_action": "PAY_NOW",
                "return_url": f"{APP_URL}/?pago=sucesso",
                "cancel_url": f"{APP_URL}/?pago=cancelado",
            },
        },
        timeout=15,
    )
    dados = r.json()
    link = next((l["href"] for l in dados.get("links", []) if l.get("rel") == "approve"), None)
    if not link:
        print(f"Falha ao criar ordem PayPal: {dados}", flush=True)
        raise HTTPException(status_code=400, detail="Nao foi possivel iniciar o pagamento")
    return {"url": link}


@app.post("/api/confirmar-pagamento")
def confirmar_pagamento(dados: PagamentoIn, tarefas: BackgroundTasks, usuario: str = Depends(usuario_logado)):
    # captura a ordem aprovada; se concluida, ativa o premium do usuario
    token = paypal_token()
    r = requests.post(
        f"{PAYPAL_API}/v2/checkout/orders/{dados.order_id}/capture",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=15,
    )
    resultado = r.json()
    if resultado.get("status") != "COMPLETED":
        print(f"Pagamento nao concluido: {resultado}", flush=True)
        raise HTTPException(status_code=400, detail="Pagamento nao confirmado")
    # guarda o capture_id — e a "chave" que o estorno vai precisar depois
    capture_id = None
    try:
        capture_id = resultado["purchase_units"][0]["payments"]["captures"][0]["id"]
    except (KeyError, IndexError):
        pass
    # detalhes do metodo de pagamento (cartao ou saldo PayPal)
    metodo = "PayPal"
    try:
        ps = resultado.get("payment_source", {})
        if "card" in ps:
            c = ps["card"]
            metodo = f"Cartao {c.get('brand', '')} final {c.get('last_digits', '')}".strip()
        elif "paypal" in ps:
            metodo = "Saldo / conta PayPal"
    except Exception:
        pass
    db = SessionLocal()
    try:
        u = db.query(Usuario).filter(Usuario.username == usuario).first()
        if u:
            u.premium = True
            u.paypal_capture_id = capture_id
            registrar_transacao(db, usuario, "pagamento", capture_id, "COMPLETED")
            db.commit()
            data_str = datetime.datetime.now(datetime.timezone.utc).strftime("%d/%m/%Y %H:%M")
            pdf = gerar_comprovante_pdf(u.username, u.email, metodo, capture_id, data_str)
            corpo = (
                '<div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;">'
                '<h2 style="color:#4f46e5;">✨ Assinatura Premium confirmada!</h2>'
                f'<p>Ola, <strong>{u.username}</strong>! Seu pagamento foi aprovado e sua conta Premium esta ativa.</p>'
                '<div style="background:#fef3c7;border-radius:8px;padding:16px;margin:16px 0;">'
                '<p style="margin:0;"><strong>Plano:</strong> Premium</p>'
                f'<p style="margin:4px 0 0;"><strong>Valor:</strong> {PREMIUM_MOEDA} {PREMIUM_PRECO}</p>'
                f'<p style="margin:4px 0 0;"><strong>Metodo:</strong> {metodo}</p>'
                f'<p style="margin:4px 0 0;"><strong>ID da transacao:</strong> {capture_id}</p>'
                f'<p style="margin:4px 0 0;"><strong>Conta:</strong> {u.email}</p>'
                '<p style="margin:4px 0 0;"><strong>Beneficios:</strong> acesso as estreias em cartaz, exclusivo para assinantes</p>'
                '</div>'
                '<p>Em anexo voce encontra o <strong>comprovante em PDF</strong>. Agradecemos a preferencia!</p>'
                '<p style="color:#64748b;font-size:13px;margin-top:24px;">MOVIES TMDA &middot; Powered by TMDB</p>'
                '</div>'
            )
            tarefas.add_task(enviar_email, u.email, "Assinatura Premium confirmada - MOVIES TMDA", corpo, pdf, "comprovante_premium.pdf")
        return {"premium": True, "id": capture_id}
    finally:
        db.close()


@app.post("/api/estornar")
def estornar(tarefas: BackgroundTasks, usuario: str = Depends(usuario_logado)):
    # estorno (refund): devolve o pagamento no PayPal e volta a conta ao gratuito
    db = SessionLocal()
    try:
        u = db.query(Usuario).filter(Usuario.username == usuario).first()
        if not u:
            raise HTTPException(status_code=404, detail="Usuario nao encontrado")
        if not u.paypal_capture_id:
            # sem pagamento registrado para estornar: so cancela o premium (sem reembolso)
            u.premium = False
            db.commit()
            return {"ok": True, "premium": False, "reembolsado": False}
        token = paypal_token()   # DRY: a MESMA autenticacao do assinar / confirmar-pagamento
        r = requests.post(
            f"{PAYPAL_API}/v2/payments/captures/{u.paypal_capture_id}/refund",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={},             # body vazio = reembolso total
            timeout=15,
        )
        resultado = r.json()
        if resultado.get("status") not in ("COMPLETED", "PENDING"):
            print(f"Estorno nao concluido: {resultado}", flush=True)
            raise HTTPException(status_code=400, detail="Nao foi possivel processar o estorno")
        refund_id = resultado.get("id")   # ID do estorno (o "NSU" do PayPal)
        u.premium = False
        registrar_transacao(db, usuario, "estorno", refund_id, "REFUNDED")
        u.paypal_capture_id = None
        db.commit()
        # e-mail de estorno (DRY: reaproveita o enviar_email de sempre)
        corpo = (
            '<div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;">'
            '<h2 style="color:#4f46e5;">💸 Reembolso processado</h2>'
            f'<p>Ola, <strong>{u.username}</strong>! Seu estorno foi processado com sucesso.</p>'
            '<div style="background:#f1f5f9;border-radius:8px;padding:16px;margin:16px 0;">'
            f'<p style="margin:0;"><strong>Valor estornado:</strong> {PREMIUM_MOEDA} {PREMIUM_PRECO}</p>'
            f'<p style="margin:4px 0 0;"><strong>ID da transacao:</strong> {refund_id}</p>'
            f'<p style="margin:4px 0 0;"><strong>Conta:</strong> {u.email}</p>'
            '<p style="margin:4px 0 0;"><strong>Status do plano:</strong> voltou ao gratuito</p>'
            '</div>'
            '<p>O valor deve aparecer na sua forma de pagamento em alguns dias uteis. Esperamos te ver em breve!</p>'
            '<p>Em anexo voce encontra o <strong>comprovante de estorno em PDF</strong>.</p>'
            '<p style="color:#64748b;font-size:13px;margin-top:24px;">MOVIES TMDA &middot; Powered by TMDB</p>'
            '</div>'
        )
        data_str = datetime.datetime.now(datetime.timezone.utc).strftime("%d/%m/%Y %H:%M")
        pdf = gerar_comprovante_estorno_pdf(u.username, u.email, refund_id, data_str)
        tarefas.add_task(enviar_email, u.email, "Reembolso processado - MOVIES TMDA", corpo, pdf, "comprovante_estorno.pdf")
        return {"ok": True, "premium": False, "reembolsado": True, "id": refund_id}
    finally:
        db.close()


@app.get("/api/transacoes")
def listar_transacoes(usuario: str = Depends(usuario_logado)):
    # historico (livro-razao) do usuario logado, do mais recente para o mais antigo
    db = SessionLocal()
    try:
        linhas = (
            db.query(Transacao)
            .filter(Transacao.username == usuario)
            .order_by(Transacao.criado_em.desc())
            .all()
        )
        return [
            {
                "id": t.id,
                "tipo": t.tipo,
                "valor": t.valor,
                "moeda": t.moeda,
                "status": t.status,
                "data": t.criado_em.strftime("%d/%m/%Y %H:%M") if t.criado_em else "",
            }
            for t in linhas
        ]
    finally:
        db.close()


@app.delete("/api/transacoes/{tid}")
def apagar_transacao(tid: int, usuario: str = Depends(usuario_logado)):
    # apaga uma linha do historico — SO se for do proprio usuario logado (seguranca)
    db = SessionLocal()
    try:
        db.query(Transacao).filter(
            Transacao.id == tid, Transacao.username == usuario
        ).delete()
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.get("/api/transacoes/{tid}/comprovante")
def baixar_comprovante(tid: int, usuario: str = Depends(usuario_logado)):
    # gera e devolve o comprovante em PDF - SO se a transacao for do proprio usuario (anti-IDOR)
    db = SessionLocal()
    try:
        t = db.query(Transacao).filter(
            Transacao.id == tid, Transacao.username == usuario
        ).first()
        if not t:
            # mesma resposta para "nao existe" e "nao e sua" - nao revela nada
            raise HTTPException(status_code=404, detail="Comprovante nao encontrado")
        u = db.query(Usuario).filter(Usuario.username == usuario).first()
        email = u.email if u else ""
        data_str = t.criado_em.strftime("%d/%m/%Y %H:%M") if t.criado_em else ""
        if t.tipo == "estorno":
            pdf = gerar_comprovante_estorno_pdf(usuario, email, t.capture_id, data_str)
            nome = f"comprovante_estorno_{t.id}.pdf"
        else:
            pdf = gerar_comprovante_pdf(usuario, email, "PayPal", t.capture_id, data_str)
            nome = f"comprovante_pagamento_{t.id}.pdf"
        if not pdf:
            raise HTTPException(status_code=500, detail="Nao foi possivel gerar o comprovante")
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{nome}"'},
        )
    finally:
        db.close()


@app.get("/api/premium/filmes")
def premium_filmes(usuario: str = Depends(usuario_logado)):
    # protegido E exclusivo: so responde para quem e premium
    db = SessionLocal()
    try:
        u = db.query(Usuario).filter(Usuario.username == usuario).first()
        if not u or not u.premium:
            raise HTTPException(status_code=403, detail="Conteudo exclusivo para assinantes Premium")
        return {
            "em_cartaz": _tmdb_lista("/movie/now_playing", {"region": "BR"}),
            "mais_votados": _tmdb_lista("/movie/top_rated", {"region": "BR"}),
            "tendencias": _tmdb_lista("/trending/movie/day", {}),
        }
    finally:
        db.close()


class ContatoIn(BaseModel):
    nome: str
    email: str
    mensagem: str


@app.post("/api/contato")
def contato(dados: ContatoIn, tarefas: BackgroundTasks):
    # escapa o conteudo pra evitar injecao de HTML no corpo do e-mail
    nome = html.escape(dados.nome.strip())
    email = html.escape(dados.email.strip())
    mensagem = html.escape(dados.mensagem.strip())
    if not nome or not mensagem:
        raise HTTPException(status_code=400, detail="Preencha seu nome e a mensagem")
    if "@" not in dados.email or "." not in dados.email:
        raise HTTPException(status_code=400, detail="Informe um e-mail valido")
    corpo = (
        '<div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;">'
        '<h2 style="color:#4f46e5;">📩 Nova mensagem de contato</h2>'
        f'<p><strong>Nome:</strong> {nome}</p>'
        f'<p><strong>E-mail:</strong> {email}</p>'
        '<p><strong>Mensagem:</strong></p>'
        f'<p style="background:#f1f5f9;border-radius:8px;padding:12px;white-space:pre-wrap;">{mensagem}</p>'
        '</div>'
    )
    tarefas.add_task(enviar_email, "contato@tdmbmovies.dev", f"Contato de {dados.nome.strip()}", corpo)
    return {"ok": True, "mensagem": "Mensagem enviada! Em breve retornaremos."}


class ChatMensagem(BaseModel):
    role: str       # "user" (voce) ou "assistant" (o bot)
    content: str


class ChatIn(BaseModel):
    mensagens: list[ChatMensagem]


# cache simples dos filmes em destaque (evita bater no TMDB a cada mensagem do chat)
_cache_filmes = {"texto": "", "quando": 0.0}


def _contexto_filmes() -> str:
    # monta a lista de filmes REAIS do site (reusa /api/destaques), com cache de 10 min
    agora = time.time()
    if _cache_filmes["texto"] and (agora - _cache_filmes["quando"] < 600):
        return _cache_filmes["texto"]
    try:
        dados = destaques()
    except Exception:
        dados = {}
    secoes = [
        ("Em alta esta semana", dados.get("em_alta", [])),
        ("Proximos lancamentos", dados.get("lancamentos", [])),
        ("Populares", dados.get("populares", [])),
        ("Lancamentos de 2027", dados.get("ano_2027", [])),
        ("Destaques de novembro", dados.get("novembro", [])),
    ]
    linhas = []
    for nome, lista in secoes:
        titulos = [f"{f.get('titulo')} ({f.get('ano')})" for f in lista[:8] if f.get("titulo")]
        if titulos:
            linhas.append(f"- {nome}: " + "; ".join(titulos))
    texto = "\n".join(linhas) if linhas else "Nenhum filme em destaque no momento."
    _cache_filmes["texto"] = texto
    _cache_filmes["quando"] = agora
    return texto


@app.post("/api/chat")
def chat(dados: ChatIn, usuario: str = Depends(usuario_opcional)):
    # chatbot com IA (Groq) + RAG: injeta filmes reais do site e dados da conta no contexto
    if not GROQ_API_KEY:
        raise HTTPException(status_code=503, detail="Chat indisponivel no momento.")

    # ----- contexto dinamico (RAG): o que o bot "enxerga" do site agora -----
    contexto = "FILMES REAIS NO SITE AGORA (use estes para falar de catalogo, lancamentos, 2027 e novembro):\n"
    contexto += _contexto_filmes()
    if usuario:
        db = SessionLocal()
        try:
            u = db.query(Usuario).filter(Usuario.username == usuario).first()
            if u:
                plano = "Premium (ja assinante)" if u.premium else "gratuito (ainda nao e Premium)"
                contexto += f"\n\nUSUARIO LOGADO: {u.username}, plano {plano}. Trate-o pelo nome."
        finally:
            db.close()
    else:
        contexto += "\n\nO usuario nao esta logado. Convide-o a entrar/criar conta quando fizer sentido."

    # monta a conversa: system fixo + contexto dinamico (RAG) + ultimas mensagens
    historico = [
        {"role": "system", "content": CHAT_SYSTEM},
        {"role": "system", "content": contexto},
    ]
    for m in dados.mensagens[-10:]:                 # so as 10 ultimas (economia de tokens)
        if m.role in ("user", "assistant") and m.content.strip():
            historico.append({"role": m.role, "content": m.content.strip()[:1000]})

    if len(historico) == 2:                         # so os 2 system, nenhuma msg do usuario
        raise HTTPException(status_code=400, detail="Envie uma mensagem.")

    try:
        r = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": GROQ_MODELO,
                "messages": historico,
                "temperature": 0.5,
                "max_tokens": 500,
            },
            timeout=30,
        )
        r.raise_for_status()
        resposta = r.json()["choices"][0]["message"]["content"].strip()
        return {"resposta": resposta}
    except Exception as e:
        print(f"Falha no chat (Groq): {e}", flush=True)
        raise HTTPException(status_code=502, detail="O assistente esta indisponivel. Tente de novo em instantes.")


@app.delete("/api/conta")
def cancelar_conta(usuario: str = Depends(usuario_logado)):
    # cancelamento: remove a conta e todos os filmes do usuario (acao permanente)
    db = SessionLocal()
    try:
        db.query(Filme).filter(Filme.username == usuario).delete()
        db.query(Transacao).filter(Transacao.username == usuario).delete()   # <- NEW 
        db.query(Usuario).filter(Usuario.username == usuario).delete()
        db.commit()
        return {"ok": True}
    finally:
        db.close()


# ==================== ROTAS DE FILMES ====================
@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/filmes")
def listar(usuario: str = Depends(usuario_logado)):
    db = SessionLocal()
    try:
        filmes = db.query(Filme).filter(Filme.username == usuario).all()
        return [to_dict(f) for f in filmes]
    finally:
        db.close()


@app.post("/api/filmes")
def criar(dados: FilmeIn, usuario: str = Depends(usuario_logado)):
    info = detalhes_tmdb(dados.tmdb_id) if dados.tmdb_id else buscar_tmdb(dados.titulo)
    db = SessionLocal()
    try:
        filme = Filme(
            username=usuario,
            titulo=dados.titulo, status=dados.status,
            ano=info.get("ano", ""), nota=info.get("nota", 0),
            sinopse=info.get("sinopse", ""),
            generos=info.get("generos", []),
            classificacao=info.get("classificacao", ""),
            poster_url=info.get("poster_url", ""),
            trailers=info.get("trailers", []),
            imagens=info.get("imagens", []),
        )
        db.add(filme)
        db.commit()
        db.refresh(filme)
        return to_dict(filme)
    finally:
        db.close()


@app.delete("/api/filmes/{filme_id}")
def apagar(filme_id: int, usuario: str = Depends(usuario_logado)):
    db = SessionLocal()
    try:
        filme = db.get(Filme, filme_id)
        if not filme or filme.username != usuario:
            raise HTTPException(status_code=404, detail="Filme nao encontrado")
        db.delete(filme)
        db.commit()
        return {"ok": True}
    finally:
        db.close()