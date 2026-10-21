import { Component, signal, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';

interface Filme {
  id: number;
  titulo: string;
  status: string;
  ano: string;
  nota: number;
  sinopse: string;
  generos: string[];
  classificacao: string;
  poster_url: string;
  trailers: string[];
  imagens: string[];
}

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App {
  private sanitizer = inject(DomSanitizer);
  private trailerCache = new Map<string, SafeResourceUrl>();

  filmes = signal<Filme[]>([]);
  novoStatus = 'quero ver';
  termoBusca = '';
  resultados = signal<any[]>([]);
  buscando = signal(false);
  toast = signal('');                 // aviso rapido (ex.: "filme adicionado")
  private toastTimer: any = null;
  private buscaTimer: any = null;     // debounce da busca ao vivo
  filmeParaApagar = signal<Filme | null>(null);
  transacaoParaApagar = signal<any | null>(null);   // confirmação de exclusão no histórico

  filmeSelecionado = signal<Filme | null>(null);
  imgAtual = signal(0);
  trailerAtual = signal(0);

  cookieBanner = signal(false);
  cookieAberto = signal(false);
  analytics = signal(false);
  marketing = signal(false);

  usuario = signal<string | null>(null);
  ehPremium = signal(false);
  premiumFilmes = signal<any>({});
  transacoes = signal<any[]>([]);
  secoesPremium = [
    { titulo: '🍿 Em cartaz agora', chave: 'em_cartaz' },
    { titulo: '⭐ Mais votados de sempre', chave: 'mais_votados' },
    { titulo: '🔥 Tendências do dia', chave: 'tendencias' },
  ];
  pagamentoMsg = signal('');
  assinaturaAberta = signal(false);
  paypalUrl = signal('');
  assinaturaErro = signal('');
  politicasAberto = signal(false);
  politicaAba = signal<'privacidade' | 'assinatura' | 'contato'>('privacidade');
  estornoAberto = signal(false);
  estornoMsg = signal('');
  contatoNome = '';
  contatoEmail = '';
  contatoMensagem = '';
  contatoMsg = signal('');
  contatoErro = signal('');
  // ----- Chatbot (IA via Groq) -----
  chatAberto = signal(false);
  chatMensagens = signal<{ role: string; content: string }[]>([]);
  chatCarregando = signal(false);
  chatTexto = '';
  sairAberto = signal(false);
  contaAberta = signal(false);
  authAberto = signal(false);
  authModo = signal<'login' | 'registro' | 'esqueci' | 'resetar' | 'reenviar'>('login');
  resetToken = signal('');
  authUsername = '';
  authEmail = '';
  authSenha = '';
  authSenha2 = '';
  mostrarSenha = signal(false);       // olhinho: mostra/oculta a senha enquanto digita
  paginaNaoEncontrada = signal(false);  // telinha 404 para caminhos desconhecidos
  authErro = signal('');
  authMensagem = signal('');
  turnstileToken = signal('');

  destaques = signal<any>({});
  heroAtual = signal(0);
  private heroTimer: any;
  secoes = [
    { titulo: '🔥 Em alta', chave: 'em_alta' },
    { titulo: '🎬 Próximos lançamentos', chave: 'lancamentos' },
    { titulo: '⭐ Populares', chave: 'populares' },
    { titulo: '📅 Destaques de 2027', chave: 'ano_2027' },
    { titulo: '🗓️ Destaques de novembro', chave: 'novembro' },
  ];

  constructor() {
    this.carregarDestaques();
    this.iniciarAutoRotate();
    if (!this.getCookie('consentimento')) {
      this.cookieBanner.set(true);
    } else {
      this.analytics.set(this.getCookie('analytics') === '1');
      this.marketing.set(this.getCookie('marketing') === '1');
    }
    const user = localStorage.getItem('usuario');
    if (user && localStorage.getItem('token')) {
      this.usuario.set(user);
      this.carregar();
      this.checarPremium();
    }
    this.checarConfirmacao();
    this.checarPagamento();
    this.checarReset();
    if (window.location.pathname !== '/') {   // caminho desconhecido -> telinha 404
      this.paginaNaoEncontrada.set(true);
    }
  }

  voltarInicio() {
    window.history.replaceState({}, '', '/');   // limpa a URL
    this.paginaNaoEncontrada.set(false);         // sai do 404 e mostra o catálogo
  }

  // ---------- Helpers de requisição (DRY) ----------
  // monta os headers com o token num lugar só (se um dia trocar o storage, muda aqui e pronto)
  private authHeaders(extra: Record<string, string> = {}): Record<string, string> {
    const token = localStorage.getItem('token') || '';
    return { 'Authorization': 'Bearer ' + token, ...extra };
  }

  // se o token expirou (401), desloga e pede login — em vez de mostrar lista vazia sem explicar
  private sessaoExpirou(r: Response): boolean {
    if (r.status === 401 && this.usuario()) {
      this.sair();
      this.abrirAuth('login');
      this.authErro.set('Sua sessão expirou. Entre de novo.');
      return true;
    }
    return false;
  }

  checarConfirmacao() {
    const token = new URLSearchParams(window.location.search).get('confirmar');
    if (!token) return;
    fetch('/api/confirmar?token=' + token)
      .then(async r => {
        const dados = await r.json();
        if (!r.ok) throw new Error(dados.detail || 'Falha na confirmação');
        return dados;
      })
      .then(() => {
        window.history.replaceState({}, '', '/');   // tira o ?confirmar da URL
        this.abrirAuth('login');
        this.authMensagem.set('✅ Conta confirmada! Agora é só entrar.');
      })
      .catch(err => {
        window.history.replaceState({}, '', '/');
        this.abrirAuth('login');
        this.authErro.set(err.message);
      });
  }

  carregar() {
    fetch('/api/filmes', {
      headers: this.authHeaders(),
    })
      .then(r => { if (this.sessaoExpirou(r)) return []; return r.ok ? r.json() : []; })
      .then(dados => this.filmes.set(dados))
      .catch(() => this.filmes.set([]));
    this.carregarTransacoes();
  }

  carregarTransacoes() {
    fetch('/api/transacoes', {
      headers: this.authHeaders(),
    })
      .then(r => { if (this.sessaoExpirou(r)) return []; return r.ok ? r.json() : []; })
      .then(dados => this.transacoes.set(dados))
      .catch(() => this.transacoes.set([]));
  }

  carregarDestaques() {
    fetch('/api/destaques')
      .then(r => r.json())
      .then(d => this.destaques.set(d))
      .catch(() => this.destaques.set({}));
  }

  checarPremium() {
    fetch('/api/me', {
      headers: this.authHeaders(),
    })
      .then(r => { if (this.sessaoExpirou(r)) return null; return r.ok ? r.json() : null; })
      .then(dados => {
        this.ehPremium.set(!!(dados && dados.premium));
        if (this.ehPremium()) this.carregarPremium();
      })
      .catch(() => { });
  }

  carregarPremium() {
    fetch('/api/premium/filmes', {
      headers: this.authHeaders(),
    })
      .then(r => { if (this.sessaoExpirou(r)) return {}; return r.ok ? r.json() : {}; })
      .then(dados => this.premiumFilmes.set(dados))
      .catch(() => this.premiumFilmes.set({}));
  }

  assinar() {
    // abre o banner de marca na hora e ja vai criando a ordem no PayPal em segundo plano
    this.assinaturaErro.set('');
    this.paypalUrl.set('');
    this.assinaturaAberta.set(true);
    fetch('/api/assinar', {
      method: 'POST',
      headers: this.authHeaders(),
    })
      .then(r => (r.ok ? r.json() : null))
      .then(dados => {
        if (dados && dados.url) {
          this.paypalUrl.set(dados.url);          // libera o botao "Continuar para o PayPal"
        } else {
          this.assinaturaErro.set('Não foi possível iniciar o pagamento. Tente de novo.');
        }
      })
      .catch(() => this.assinaturaErro.set('Não foi possível iniciar o pagamento. Tente de novo.'));
  }

  irParaPaypal() {
    if (this.paypalUrl()) {
      window.location.href = this.paypalUrl();   // so agora sai pro PayPal sandbox
    }
  }

  fecharAssinatura() {
    this.assinaturaAberta.set(false);
    this.paypalUrl.set('');
    this.assinaturaErro.set('');
  }

  abrirPoliticas(aba: 'privacidade' | 'assinatura' = 'privacidade') {
    this.politicaAba.set(aba);
    this.politicasAberto.set(true);
  }
  fecharPoliticas() {
    this.politicasAberto.set(false);
  }

  checarPagamento() {
    const params = new URLSearchParams(window.location.search);
    const pago = params.get('pago');
    if (!pago) return;
    if (pago !== 'sucesso') {                         // cancelou lá no PayPal
      window.history.replaceState({}, '', '/');
      return;
    }
    const orderId = params.get('token');              // o PayPal devolve o id da ordem como "token"
    if (!orderId) { window.history.replaceState({}, '', '/'); return; }
    this.pagamentoMsg.set('Confirmando seu pagamento...');
    fetch('/api/confirmar-pagamento', {
      method: 'POST',
      headers: this.authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ order_id: orderId }),
    })
      .then(r => (r.ok ? r.json() : null))
      .then(dados => {
        window.history.replaceState({}, '', '/');     // limpa a URL que veio do PayPal
        if (dados && dados.premium) {
          this.ehPremium.set(true);
          this.carregarTransacoes();
          this.pagamentoMsg.set('✅ Sucesso! Pagamento confirmado. Agradecemos a preferência — um momento, você será direcionado ao portal MOVIES TMDA...');
          setTimeout(() => { this.pagamentoMsg.set(''); this.carregarPremium(); }, 4500);
        } else {
          this.pagamentoMsg.set('');
        }
      })
      .catch(() => { window.history.replaceState({}, '', '/'); this.pagamentoMsg.set(''); });
  }

  heroFilme() {
    const lista = this.destaques()?.em_alta || [];
    return lista[this.heroAtual()] || null;
  }

  iniciarAutoRotate() {
    clearInterval(this.heroTimer);                                 // zera o cronometro anterior
    this.heroTimer = setInterval(() => this.avancarHero(), 5000);  // e comeca de novo
  }
  private avancarHero() {
    const lista = this.destaques()?.em_alta || [];
    if (lista.length) this.heroAtual.update(i => (i + 1) % lista.length);
  }
  proxHero() { this.avancarHero(); this.iniciarAutoRotate(); }      // seta da direita
  antHero() {
    const lista = this.destaques()?.em_alta || [];
    if (lista.length) this.heroAtual.update(i => (i - 1 + lista.length) % lista.length);
    this.iniciarAutoRotate();                                       // seta da esquerda
  }
  irHero(i: number) { this.heroAtual.set(i); this.iniciarAutoRotate(); }  // bolinhas

  buscar() {
    const q = this.termoBusca.trim();
    if (!q) return;
    this.buscando.set(true);
    fetch('/api/buscar?q=' + encodeURIComponent(q), {
      headers: this.authHeaders(),
    })
      .then(r => { if (this.sessaoExpirou(r)) return []; return r.ok ? r.json() : []; })
      .then(dados => { this.resultados.set(dados); this.buscando.set(false); })
      .catch(() => { this.resultados.set([]); this.buscando.set(false); });
  }

  // busca ao vivo: dispara sozinha 400ms depois que o usuario para de digitar (debounce)
  buscarAoDigitar() {
    clearTimeout(this.buscaTimer);
    if (!this.termoBusca.trim()) {        // campo vazio -> limpa a grade na hora
      this.resultados.set([]);
      this.buscando.set(false);
      return;
    }
    this.buscaTimer = setTimeout(() => this.buscar(), 400);
  }

  adicionarFilme(r: any) {
    fetch('/api/filmes', {
      method: 'POST',
      headers: this.authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ tmdb_id: r.id, titulo: r.titulo, status: this.novoStatus }),
    })
      .then(resp => {
        if (this.sessaoExpirou(resp)) return;
        if (resp.ok) {
          this.mostrarToast('✅ "' + r.titulo + '" adicionado à sua lista!');
          this.carregar();
        } else {
          this.mostrarToast('❌ Não foi possível adicionar. Tente de novo.');
        }
      })
      .catch(() => this.mostrarToast('❌ Erro de conexão. Tente de novo.'));
  }

  // mostra um aviso curto no rodape e some sozinho depois de ~2.8s
  private mostrarToast(msg: string) {
    this.toast.set(msg);
    clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => this.toast.set(''), 2800);
  }

  pedirApagar(filme: Filme) { this.filmeParaApagar.set(filme); }
  cancelarApagar() { this.filmeParaApagar.set(null); }
  confirmarApagar() {
    const f = this.filmeParaApagar();
    if (!f) return;
    fetch('/api/filmes/' + f.id, {
      method: 'DELETE',
      headers: this.authHeaders(),
    }).then(() => { this.filmeParaApagar.set(null); this.carregar(); });
  }

  corDoStatus(status: string): string {
    if (status === 'assistido') return 'bg-green-100 text-green-700 text-sm font-medium px-2 py-0.5 rounded-full';
    if (status === 'assistindo') return 'bg-blue-100 text-blue-700 text-sm font-medium px-2 py-0.5 rounded-full';
    return 'bg-slate-100 text-slate-600 text-sm font-medium px-2 py-0.5 rounded-full';
  }

  abrirDetalhes(filme: Filme) {
    this.filmeSelecionado.set(filme);
    this.imgAtual.set(0);
    this.trailerAtual.set(0);
  }
  fecharDetalhes() { this.filmeSelecionado.set(null); }

  abrirDetalhesVitrine(f: any) {
    // os cards da vitrine so tem dados basicos; buscamos os detalhes completos
    // (trailers, imagens, generos, classificacao) pelo id antes de abrir o modal
    fetch('/api/detalhes/' + f.id)
      .then(r => (r.ok ? r.json() : null))
      .then(info => {
        if (!info) return;
        this.filmeSelecionado.set(info);
        this.imgAtual.set(0);
        this.trailerAtual.set(0);
      });
  }

  proxImg() {
    const f = this.filmeSelecionado();
    if (!f || !f.imagens.length) return;
    this.imgAtual.update(i => (i + 1) % f.imagens.length);
  }
  antImg() {
    const f = this.filmeSelecionado();
    if (!f || !f.imagens.length) return;
    this.imgAtual.update(i => (i - 1 + f.imagens.length) % f.imagens.length);
  }
  proxTrailer() {
    const f = this.filmeSelecionado();
    if (!f || !f.trailers.length) return;
    this.trailerAtual.update(i => (i + 1) % f.trailers.length);
  }
  antTrailer() {
    const f = this.filmeSelecionado();
    if (!f || !f.trailers.length) return;
    this.trailerAtual.update(i => (i - 1 + f.trailers.length) % f.trailers.length);
  }
  urlTrailer(key: string): SafeResourceUrl {
    // devolve SEMPRE o mesmo objeto para a mesma key: assim o Angular nao recria
    // o <iframe> a cada change detection (o setInterval do hero roda de 5 em 5s),
    // e o trailer para de reiniciar sozinho
    let url = this.trailerCache.get(key);
    if (!url) {
      url = this.sanitizer.bypassSecurityTrustResourceUrl('https://www.youtube.com/embed/' + key);
      this.trailerCache.set(key, url);
    }
    return url;
  }

  abrirAuth(modo: 'login' | 'registro' | 'esqueci' | 'resetar' | 'reenviar') {
    this.authModo.set(modo);
    this.authErro.set('');
    this.authMensagem.set('');
    this.turnstileToken.set('');
    this.mostrarSenha.set(false);       // cada vez que abre, a senha começa oculta
    this.authAberto.set(true);
    if (modo === 'login' || modo === 'registro') {
      this.renderTurnstile();   // turnstile so no login/cadastro
    }
  }
  fecharAuth() {
    this.authAberto.set(false);
    this.authUsername = '';
    this.authEmail = '';
    this.authSenha = '';
    this.authSenha2 = '';
    this.authMensagem.set('');
    this.turnstileToken.set('');
  }
  renderTurnstile(tentativas = 0) {
    const el = document.getElementById('turnstile-box');
    const ts = (window as any).turnstile;
    if (el && ts) {
      el.innerHTML = '';
      ts.render(el, {
        sitekey: '0x4AAAAAAFKe-WhNDmfch0hH',
        callback: (token: string) => this.turnstileToken.set(token),
      });
    } else if (tentativas < 20) {
      setTimeout(() => this.renderTurnstile(tentativas + 1), 150);
    }
  }
  emailValido(email: string): boolean {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
  }
  senhaForte() {
    const s = this.authSenha;
    return {
      tamanho: s.length >= 8,
      maiuscula: /[A-Z]/.test(s),
      numero: /[0-9]/.test(s),
      especial: /[^A-Za-z0-9]/.test(s),
    };
  }
  senhaOk(): boolean {
    const r = this.senhaForte();
    return r.tamanho && r.maiuscula && r.numero && r.especial;
  }

  // ---------- Esqueci minha senha: pedir o link por e-mail ----------
  enviarEsqueci() {
    this.authErro.set('');
    if (!this.emailValido(this.authEmail)) {
      this.authErro.set('Insira um e-mail válido');
      return;
    }
    fetch('/api/esqueci-senha', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: this.authEmail.trim() }),
    })
      .then(async r => {
        const dados = await r.json();
        if (!r.ok) throw new Error(dados.detail || 'Falha ao solicitar');
        return dados;
      })
      .then(dados => {
        this.authMensagem.set('📧 ' + dados.mensagem + ' Verifique sua caixa de entrada (ou o spam).');
        this.authEmail = '';
      })
      .catch(err => this.authErro.set(err.message));
  }

  // ---------- Reenviar e-mail de confirmação de cadastro ----------
  reenviarConfirmacao() {
    this.authErro.set('');
    if (!this.emailValido(this.authEmail)) {
      this.authErro.set('Insira um e-mail válido');
      return;
    }
    fetch('/api/reenviar-confirmacao', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: this.authEmail.trim() }),
    })
      .then(async r => {
        const dados = await r.json();
        if (!r.ok) throw new Error(dados.detail || 'Falha ao reenviar');
        return dados;
      })
      .then(dados => {
        this.authMensagem.set('📧 ' + dados.mensagem + ' Verifique sua caixa de entrada (ou o spam).');
        this.authEmail = '';
      })
      .catch(err => this.authErro.set(err.message));
  }

  // ---------- Esqueci minha senha: chegou pelo link do e-mail (?resetar=) ----------
  checarReset() {
    const token = new URLSearchParams(window.location.search).get('resetar');
    if (!token) return;
    this.resetToken.set(token);
    window.history.replaceState({}, '', '/');   // tira o ?resetar da URL
    this.authSenha = '';
    this.authSenha2 = '';
    this.abrirAuth('resetar');
  }

  // ---------- Esqueci minha senha: gravar a nova senha ----------
  resetarSenha() {
    this.authErro.set('');
    if (!this.senhaOk()) {
      this.authErro.set('Senha fraca: use 8+ caracteres, uma maiúscula, um número e um caractere especial');
      return;
    }
    if (this.authSenha !== this.authSenha2) {
      this.authErro.set('As senhas não conferem');
      return;
    }
    fetch('/api/resetar-senha', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: this.resetToken(), senha: this.authSenha }),
    })
      .then(async r => {
        const dados = await r.json();
        if (!r.ok) throw new Error(dados.detail || 'Falha ao redefinir');
        return dados;
      })
      .then(dados => {
        this.authSenha = '';
        this.authSenha2 = '';
        this.abrirAuth('login');
        this.authMensagem.set('✅ ' + dados.mensagem);
      })
      .catch(err => this.authErro.set(err.message));
  }

  autenticar() {
    this.authErro.set('');
    if (this.authModo() === 'registro') {
      if (!this.emailValido(this.authEmail)) { this.authErro.set('Insira um e-mail válido'); return; }
      if (!this.senhaOk()) { this.authErro.set('Senha fraca: use 8+ caracteres, uma maiúscula, um número e um caractere especial'); return; }
      if (this.authSenha !== this.authSenha2) { this.authErro.set('As senhas não conferem'); return; }
    }
    if (!this.turnstileToken()) {
      this.authErro.set('Confirme que você não é um robô 🤖');
      return;
    }
    const rota = this.authModo() === 'login' ? '/api/login' : '/api/register';
    fetch(rota, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: this.authUsername.trim(), email: this.authEmail.trim(), senha: this.authSenha, captcha: this.turnstileToken() }),
    })
      .then(async r => {
        const dados = await r.json();
        if (!r.ok) throw new Error(dados.detail || 'Falha na autenticação');
        return dados;
      })
      .then(dados => {
        if (this.authModo() === 'registro') {
          // double opt-in: NAO loga; pede pra confirmar o e-mail
          this.authMensagem.set('📧 Você receberá um e-mail para confirmação de cadastro. Verifique seu e-mail (ou a caixa de spam) para mais informações.');
          this.authUsername = '';
          this.authEmail = '';
          this.authSenha = '';
          this.authSenha2 = '';
          return;
        }
        localStorage.setItem('token', dados.token);
        localStorage.setItem('usuario', dados.username);
        this.usuario.set(dados.username);
        this.ehPremium.set(!!dados.premium);
        this.carregar();
        if (this.ehPremium()) this.carregarPremium();
        this.fecharAuth();
      })
      .catch(err => this.authErro.set(err.message));
  }
  sair() {
    localStorage.removeItem('token');
    localStorage.removeItem('usuario');
    this.usuario.set(null);
    this.filmes.set([]);
    this.ehPremium.set(false);
    this.premiumFilmes.set({});
  }

  // ---------- Confirmação de sair ----------
  pedirSair() { this.sairAberto.set(true); }
  fecharSair() { this.sairAberto.set(false); }
  confirmarSair() { this.sairAberto.set(false); this.sair(); }

  // ---------- Cancelamento de conta (permanente) ----------
  pedirCancelarConta() { this.contaAberta.set(true); }
  fecharCancelarConta() { this.contaAberta.set(false); }
  confirmarCancelarConta() {
    fetch('/api/conta', {
      method: 'DELETE',
      headers: this.authHeaders(),
    }).then(() => { this.contaAberta.set(false); this.sair(); });
  }

  // ---------- Cancelar Premium + reembolso num passo só (refund no PayPal) ----------
  pedirEstorno() { this.estornoMsg.set(''); this.estornoAberto.set(true); }
  fecharEstorno() { this.estornoAberto.set(false); }
  confirmarEstorno() {
    this.estornoMsg.set('');
    fetch('/api/estornar', {
      method: 'POST',
      headers: this.authHeaders(),
    })
      .then(async r => {
        const dados = await r.json();
        if (!r.ok) throw new Error(dados.detail || 'Falha no estorno');
        return dados;
      })
      .then(dados => {
        this.estornoAberto.set(false);
        this.ehPremium.set(false);        // reembolsou -> volta ao gratuito
        this.premiumFilmes.set({});
        this.carregarTransacoes();
        const id = dados.id ? ' · ID da transação: ' + dados.id : '';
        this.pagamentoMsg.set('✅ Estorno confirmado! Verifique mais informações sobre o estorno no seu e-mail. Em caso de dúvidas, contate-nos pelos nossos canais de atendimento.' + id);
        setTimeout(() => this.pagamentoMsg.set(''), 9000);
      })
      .catch(err => this.estornoMsg.set(err.message));
  }

  // ---------- Apagar uma linha do histórico (com confirmação) ----------
  pedirApagarTransacao(t: any) { this.transacaoParaApagar.set(t); }
  cancelarApagarTransacao() { this.transacaoParaApagar.set(null); }
  confirmarApagarTransacao() {
    const t = this.transacaoParaApagar();
    if (!t) return;
    fetch('/api/transacoes/' + t.id, {
      method: 'DELETE',
      headers: this.authHeaders(),
    }).then(() => { this.transacaoParaApagar.set(null); this.carregarTransacoes(); });
  }

  // baixa o comprovante em PDF (o backend só devolve se a transação for do usuário logado)
  baixarComprovante(t: any) {
    fetch('/api/transacoes/' + t.id + '/comprovante', { headers: this.authHeaders() })
      .then(async r => {
        if (this.sessaoExpirou(r)) return;
        if (!r.ok) { this.mostrarToast('❌ Não foi possível baixar o comprovante.'); return; }
        const blob = await r.blob();                 // o PDF vem como blob
        const url = URL.createObjectURL(blob);        // cria uma URL temporária na memória
        const a = document.createElement('a');
        a.href = url;
        a.download = (t.tipo === 'estorno' ? 'comprovante_estorno_' : 'comprovante_pagamento_') + t.id + '.pdf';
        a.click();                                    // dispara o download
        URL.revokeObjectURL(url);                     // libera a memória
      })
      .catch(() => this.mostrarToast('❌ Erro ao baixar o comprovante.'));
  }

  // ---------- Formulário de contato (dispara e-mail via backend -> Mailtrap) ----------
  enviarContato() {
    this.contatoErro.set('');
    this.contatoMsg.set('');
    if (!this.contatoNome.trim() || !this.contatoMensagem.trim()) {
      this.contatoErro.set('Preencha seu nome e a mensagem');
      return;
    }
    if (!this.emailValido(this.contatoEmail)) {
      this.contatoErro.set('Informe um e-mail válido');
      return;
    }
    fetch('/api/contato', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nome: this.contatoNome.trim(), email: this.contatoEmail.trim(), mensagem: this.contatoMensagem.trim() }),
    })
      .then(async r => {
        const dados = await r.json();
        if (!r.ok) throw new Error(dados.detail || 'Falha ao enviar');
        return dados;
      })
      .then(dados => {
        this.contatoMsg.set('✅ ' + dados.mensagem);
        this.contatoNome = '';
        this.contatoEmail = '';
        this.contatoMensagem = '';
      })
      .catch(err => this.contatoErro.set(err.message));
  }

  getCookie(nome: string): string {
    const m = document.cookie.match(new RegExp('(^| )' + nome + '=([^;]+)'));
    return m ? m[2] : '';
  }
  setCookie(nome: string, valor: string, dias: number) {
    const d = new Date();
    d.setTime(d.getTime() + dias * 24 * 60 * 60 * 1000);
    document.cookie = nome + '=' + valor + ';expires=' + d.toUTCString() + ';path=/';
  }
  salvarPrefs() {
    this.setCookie('consentimento', '1', 365);
    this.setCookie('analytics', this.analytics() ? '1' : '0', 365);
    this.setCookie('marketing', this.marketing() ? '1' : '0', 365);
    this.cookieBanner.set(false);
    this.cookieAberto.set(false);
  }
  abrirCookies() { this.cookieAberto.set(true); }
  fecharCookies() { this.cookieAberto.set(false); }
  toggleAnalytics() { this.analytics.update(v => !v); }
  toggleMarketing() { this.marketing.update(v => !v); }
  salvarCookies() { this.salvarPrefs(); }
  aceitarTodosCookies() {
    this.analytics.set(true);
    this.marketing.set(true);
    this.salvarPrefs();
  }

  // ---------- Chatbot: abrir, fechar e conversar com a IA (/api/chat) ----------
  abrirChat() {
    this.chatAberto.set(true);
    if (this.chatMensagens().length === 0) {
      this.chatMensagens.set([{
        role: 'assistant',
        content: 'Olá! 👋 Sou o assistente do MOVIES TMDA. Posso ajudar com Premium, reembolso, vantagens e mais. Como posso ajudar?',
      }]);
    }
    this.rolarChat();
  }
  fecharChat() { this.chatAberto.set(false); }
  enviarChat() {
    const texto = this.chatTexto.trim();
    if (!texto || this.chatCarregando()) return;
    this.chatMensagens.update(m => [...m, { role: 'user', content: texto }]);  // mostra a pergunta
    this.chatTexto = '';
    this.chatCarregando.set(true);
    this.rolarChat();                                              // rola apos a pergunta
    fetch('/api/chat', {
      method: 'POST',
      headers: this.authHeaders({ 'Content-Type': 'application/json' }),   // pro bot saber da conta
      body: JSON.stringify({ mensagens: this.chatMensagens() }),   // manda o historico inteiro
    })
      .then(async r => {
        const dados = await r.json();
        if (!r.ok) throw new Error(dados.detail || 'Falha');
        return dados;
      })
      .then(dados => {
        this.chatMensagens.update(m => [...m, { role: 'assistant', content: dados.resposta }]);
        this.chatCarregando.set(false);
        this.rolarChat();                                          // rola apos a resposta
      })
      .catch(() => {
        this.chatMensagens.update(m => [...m, { role: 'assistant', content: 'Ops! Tive um probleminha agora. Tente de novo em instantes. 😅' }]);
        this.chatCarregando.set(false);
        this.rolarChat();
      });
  }
  // rola a janela de mensagens sempre pro final (ultima mensagem visivel)
  private rolarChat() {
    setTimeout(() => {
      const el = document.getElementById('chatScroll');
      if (el) el.scrollTop = el.scrollHeight;
    }, 50);
  }
}
