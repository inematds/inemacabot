# InemacaBot

Assistente pessoal para Telegram feito em Python. O bot:

- aceita somente um usuário autorizado;
- responde mensagens de texto usando o Codex CLI autenticado na máquina;
- transcreve mensagens de voz e arquivos de áudio com o Groq;
- mantém um histórico curto em memória;
- divide respostas maiores que o limite do Telegram;
- preserva os comandos `/start`, `/limpar` e `/ajuda`;
- oferece uma camada experimental de filas SQLite, desabilitada por padrão.
- pode gerar vídeos de reforma com a Agnes quando a integração opcional está
  configurada.

## Como funciona

```text
Texto no Telegram ────────────────┐
                                  ├─→ Codex CLI ─→ resposta no Telegram
Voz/áudio ─→ Groq ─→ transcrição ┘
```

Com `QUEUE_ROUTING_ENABLED=true`, tarefas demoradas podem seguir este fluxo:

```text
Telegram → roteador → SQLite → worker → executor → watcher → Telegram
```

Existem três filas (`servicos`, `textos` e `videos`), limitadas a um job em
execução cada. As três filas podem trabalhar simultaneamente.

O bot não usa uma chave da API OpenAI. Ele executa `codex exec` com a
autenticação da assinatura do Codex/ChatGPT já ativa no usuário do sistema. Cada
consulta é efêmera, usa um diretório temporário vazio e deixa as ferramentas do
modelo em sandbox somente leitura.

O Codex continua sujeito aos limites de uso da assinatura. A chave do Groq é
necessária somente para mensagens de voz ou áudio.

## Pré-requisitos

- Python 3.11 ou superior;
- Codex CLI instalado;
- uma assinatura com acesso ao Codex;
- um bot criado no Telegram;
- uma chave do Groq, se a transcrição de áudio for utilizada.

Confira os comandos:

```bash
python3 --version
codex --version
codex login status
```

Se o Codex ainda não estiver autenticado, execute:

```bash
codex login
```

Conclua o acesso usando a mesma conta que possui a assinatura do Codex.

## 1. Criar o bot com o BotFather

1. Abra o Telegram e inicie uma conversa com `@BotFather`.
2. Envie `/newbot`.
3. Escolha o nome visível do bot.
4. Escolha um username terminado em `bot`.
5. Guarde o token entregue pelo BotFather.

Não publique esse token e não o coloque diretamente no código.

## 2. Descobrir seu ID do Telegram

Envie qualquer mensagem ao bot recém-criado. Em seguida, substitua
`SEU_TOKEN` apenas no terminal e consulte as atualizações:

```bash
curl "https://api.telegram.org/botSEU_TOKEN/getUpdates"
```

No resultado, procure por:

```json
{"from":{"id":123456789}}
```

O número de `from.id` é o valor de `TELEGRAM_ALLOWED_USER_ID`. Evite salvar o
comando contendo o token no histórico do terminal; outra opção é usar
temporariamente uma variável local:

```bash
read -rsp "Token do Telegram: " TELEGRAM_SETUP_TOKEN
curl "https://api.telegram.org/bot${TELEGRAM_SETUP_TOKEN}/getUpdates"
unset TELEGRAM_SETUP_TOKEN
```

## 3. Instalar o projeto

Na raiz do projeto:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 4. Configurar o ambiente

Copie o exemplo:

```bash
cp .env.example .env
chmod 600 .env
```

Edite `.env` e preencha inicialmente:

```env
TELEGRAM_BOT_TOKEN=token_entregue_pelo_botfather
TELEGRAM_ALLOWED_USER_ID=123456789
```

Para aceitar voz e áudio, preencha depois:

```env
GROQ_API_KEY=sua_chave_do_groq
```

Configurações disponíveis:

| Variável | Obrigatória | Finalidade |
|---|---:|---|
| `TELEGRAM_BOT_TOKEN` | sim | Token entregue pelo BotFather |
| `TELEGRAM_ALLOWED_USER_ID` | sim | Único usuário autorizado |
| `CODEX_BINARY` | não | Executável do Codex; padrão `codex` |
| `CODEX_MODEL` | não | Modelo solicitado ao Codex; vazio usa o padrão |
| `CODEX_TIMEOUT_SECONDS` | não | Tempo máximo de uma resposta |
| `HISTORY_MAX_EXCHANGES` | não | Quantidade de pares mantidos em memória |
| `AI_SYSTEM_PROMPT` | não | Comportamento principal do assistente |
| `GROQ_API_KEY` | para áudio | Chave usada somente na transcrição |
| `GROQ_TRANSCRIPTION_MODEL` | não | Padrão `whisper-large-v3-turbo` |
| `GROQ_TRANSCRIPTION_LANGUAGE` | não | Idioma ISO-639-1; padrão `pt` |
| `MAX_AUDIO_MB` | não | Limite local antes do envio ao Groq |
| `QUEUE_ROUTING_ENABLED` | não | Ativa decisões `reply`, `clarify` e `enqueue` |
| `QUEUE_DATABASE_PATH` | não | Banco SQLite; padrão `data/inemacabot.sqlite3` |
| `SKILLS_REGISTRY_PATH` | não | Registro central das skills |
| `WORKER_POLL_INTERVAL_MS` | não | Intervalo de consulta dos workers |
| `JOB_LOCK_TIMEOUT_MINUTES` | não | Expiração do lock de execução |
| `JOB_WORK_ROOT` | não | Pastas isoladas dos jobs |
| `JOB_EXECUTION_TIMEOUT_SECONDS` | não | Timeout do agente temporário |
| `DELIVERY_MAX_ATTEMPTS` | não | Limite de tentativas de entrega |
| `AGNES_API_KEY` | para virtual staging | Chave da API Agnes, mantida somente no `.env` |
| `VSV_SKILLS_ROOT` | não | Diretório das skills clonadas de `vsvideo-skill` |
| `VSV_MAX_IMAGE_MB` | não | Limite da foto enviada para `/vsvideo`; padrão 10 MB |

O arquivo `.env` é ignorado pelo Git.

## 5. Iniciar o bot

Com o ambiente virtual ativado:

```bash
python bot.py
```

O processo continuará ativo por long polling. Para encerrar, pressione
`Ctrl+C`.

## 6. Testar a integração

Execute primeiro os testes locais:

```bash
python -m unittest discover -v
```

Depois, no Telegram:

1. envie `/start`;
2. envie uma pergunta curta;
3. faça uma pergunta relacionada para confirmar o histórico;
4. envie `/limpar` e confirme que o contexto foi apagado;
5. envie uma mensagem por outra conta e confirme que não há resposta;
6. depois de configurar o Groq, envie uma mensagem de voz.

Os erros básicos aparecem no terminal, sem registrar os tokens.

### Testar as filas experimentais

As Fases 0–7 estão disponíveis para teste. A Fase 8 — serviços de produção,
retenção, backup e endurecimento operacional — ainda não foi iniciada.

Para o primeiro teste, mantenha `QUEUE_ROUTING_ENABLED=false` e inicie, em
terminais separados:

```bash
.venv/bin/python bot.py
.venv/bin/python -m workers.runner --queue servicos
.venv/bin/python -m workers.runner --queue textos
.venv/bin/python -m workers.runner --queue videos
.venv/bin/python -m delivery.watcher
```

No Telegram, envie:

```text
/testefila Olá, fila
```

O worker aguardará 10 segundos, criará `resultado.txt` e o watcher enviará o
resultado. Para testar roteamento natural, altere para
`QUEUE_ROUTING_ENABLED=true`, reinicie o bot e envie:

```text
Crie um roteiro sobre filas assíncronas.
Crie um plano de vídeo sobre agentes temporários.
```

`plano-video` gera planejamento, roteiro e cenas em texto; não renderiza mídia.

Comandos de acompanhamento:

```text
/status
/filas
/meusjobs
/job <id>
/cancelar <id>
/repetir <id>
/skills
```

### Gerar vídeo de reforma com Agnes

Clone e configure as skills:

```bash
git clone https://github.com/inematds/vsvideo-skill.git \
  /root/projetos/vsvideo-skill
```

Defina `AGNES_API_KEY` diretamente no `.env`, mantenha
`VSV_SKILLS_ROOT=/root/projetos/vsvideo-skill/skills` e inicie o worker
`videos` e o watcher.

No Telegram, envie uma foto de um interior finalizado e use exatamente esta
legenda:

```text
/vsvideo
```

O bot baixa a imagem somente depois da autorização, cria um job isolado sob
`data/jobs`, executa a skill `vsvideo-agnes` e entrega o MP4 quando terminar.
Não use imagens confidenciais no plano gratuito da Agnes.

### Exemplo de nova skill: integração HeyGen

O projeto contém uma proposta documentada para adicionar `heygen-avatar` e
`heygen-video` à fila `videos`. Ela mostra o ciclo completo necessário para
incluir uma skill externa: registro, executor permitido, comando ou roteamento,
worker isolado, acompanhamento do job, entrega, configuração e testes.

Essa integração **ainda não está implementada**. A skill atual `plano-video`
gera somente planejamento e roteiro em texto; ela não renderiza vídeos.

O uso proposto pelo Telegram é:

```text
/avatar <descrição>
/video <tema ou instrução>
/videoestoque <tema ou instrução>
/job <id>
/cancelar <id>
```

Exemplo:

```text
/video Crie um vídeo vertical de 30 segundos apresentando o InemacaBot
```

Consulte [Exemplo de integração de skill: HeyGen](doc/exemplo_integracao_skill_heygen.md)
para ver a arquitetura, configuração segura, etapas de implantação e o roteiro
reutilizável para adicionar outras skills ao sistema.

## 7. Manter o bot ativo em uma VPS

Primeiro descubra os caminhos absolutos:

```bash
pwd
command -v codex
```

Coloque o caminho retornado por `command -v codex` em `CODEX_BINARY` no `.env`.
O serviço precisa executar com o mesmo usuário Linux que realizou `codex login`.

Crie `/etc/systemd/system/inemacabot.service`:

```ini
[Unit]
Description=Assistente pessoal do Telegram
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=SEU_USUARIO
WorkingDirectory=/CAMINHO/ABSOLUTO/inemacabot
EnvironmentFile=/CAMINHO/ABSOLUTO/inemacabot/.env
ExecStart=/CAMINHO/ABSOLUTO/inemacabot/.venv/bin/python bot.py
Restart=on-failure
RestartSec=5
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

Ative o serviço:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now inemacabot
sudo systemctl status inemacabot
```

Para acompanhar os registros:

```bash
sudo journalctl -u inemacabot -f
```

## Solução de problemas

### O bot não inicia

Confira as variáveis obrigatórias e o ID numérico:

```bash
source .venv/bin/activate
python bot.py
```

### O Telegram responde com erro genérico

Verifique a autenticação do Codex no mesmo usuário que executa o bot:

```bash
codex login status
```

Confira também o caminho configurado em `CODEX_BINARY` e os logs do processo.

### A mensagem de voz não funciona

Confirme que `GROQ_API_KEY` foi definida e reinicie o bot. O projeto usa o
endpoint oficial de transcrição do Groq e, por padrão, o modelo
`whisper-large-v3-turbo`.

### O contexto sumiu

O histórico é intencionalmente pequeno e fica somente na memória. Ele é apagado
por `/limpar` e sempre que o processo é reiniciado.

## Referências

- [Codex CLI — execução não interativa](https://developers.openai.com/codex/cli)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Groq Speech to Text](https://console.groq.com/docs/speech-to-text)
- [Exemplo de integração de skill: HeyGen](doc/exemplo_integracao_skill_heygen.md)
