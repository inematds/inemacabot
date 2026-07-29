# InemacaBot

Assistente pessoal para Telegram feito em Python. O bot:

- aceita somente um usuário autorizado;
- responde mensagens de texto usando o Codex CLI autenticado na máquina;
- transcreve mensagens de voz e arquivos de áudio com o Groq;
- mantém um histórico curto em memória;
- divide respostas maiores que o limite do Telegram;
- oferece apenas os comandos `/start`, `/limpar` e `/ajuda`.

## Como funciona

```text
Texto no Telegram ────────────────┐
                                  ├─→ Codex CLI ─→ resposta no Telegram
Voz/áudio ─→ Groq ─→ transcrição ┘
```

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
