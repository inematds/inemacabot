# Exemplo de integração de skill: HeyGen

## Estado

Este documento descreve uma proposta de integração. O suporte ao HeyGen ainda
não está implementado no InemacaBot.

A skill atual `plano-video` produz somente planejamento, roteiro e cenas em
texto. Ela não chama o HeyGen e não renderiza mídia.

## Objetivo

Adicionar duas skills assíncronas:

- `heygen-avatar`: cria e mantém um apresentador reutilizável, com avatar e
  voz;
- `heygen-video`: gera um vídeo a partir de um tema ou roteiro e entrega o MP4
  ou o link pelo Telegram.

O fluxo proposto preserva a separação entre conversa e execução de jobs:

```text
Telegram → autorização → criação do job → SQLite → worker videos
         → HeyGen Video Agent v3 → resultado → watcher → Telegram
```

O cliente de conversa não deve executar o HeyGen diretamente. A integração
deve ficar em um executor próprio, usado somente pelo worker da fila `videos`.

## Como seria usado no Telegram

Comandos explícitos são recomendados para a primeira versão:

```text
/avatar <descrição>
/video <tema ou instrução>
/videoestoque <tema ou instrução>
/job <id>
/cancelar <id>
```

Exemplos:

```text
/avatar Apresentador brasileiro, profissional, voz calma e acolhedora
```

```text
/video Crie um vídeo vertical de 30 segundos apresentando o InemacaBot
```

```text
/videoestoque Explique em português, em 45 segundos, como funcionam as filas
```

`/avatar` inicia a configuração de uma identidade persistente. A criação deve
parar nos pontos que exigem aprovação do usuário, como aparência e escolha de
voz. `/video` usa o avatar salvo. `/videoestoque` não exige avatar próprio e
permite uma primeira entrega mais simples.

Ao aceitar a solicitação, o bot deve responder imediatamente com o ID do job.
O usuário acompanha o processamento com `/job <id>` e pode solicitar
cancelamento com `/cancelar <id>`. Quando a geração terminar, o watcher envia o
arquivo ou um link de acesso.

## Configuração prevista

O servidor precisa do HeyGen CLI autenticado ou de uma chave configurada no
ambiente do serviço. Para um worker executado pelo systemd, a configuração
prevista é:

```dotenv
HEYGEN_API_KEY=valor_configurado_diretamente_no_servidor
```

Nunca envie a chave pelo Telegram, não a coloque no código e não a versione. O
arquivo `.env` deve continuar ignorado pelo Git e com permissão `600`.

O HeyGen CLI deve ser instalado e validado no mesmo usuário do sistema que
executa o worker:

```bash
curl -fsSL https://static.heygen.ai/cli/install.sh | bash
heygen --version
heygen auth status
```

O executor deve usar somente comandos com argumentos separados, por meio de
`asyncio.create_subprocess_exec`. Não deve usar `shell=True`, interpolar texto
do usuário em uma linha de shell nem registrar chaves, cabeçalhos ou URLs que
contenham credenciais.

## Como uma nova skill entra no sistema

A integração HeyGen serve como exemplo do processo necessário para incluir
qualquer skill com execução externa:

1. Definir o comportamento observável, os campos obrigatórios e a fila.
2. Registrar a skill em `skills/registry.json`, inicialmente desabilitada.
3. Adicionar o nome do executor à lista permitida em `skills/registry.py`.
4. Implementar um executor em `agents/`, com entrada e saída compatíveis com
   `AgentRequest` e `AgentResult`.
5. Registrar o executor explicitamente em `agents/factory.py`.
6. Criar um comando do Telegram ou uma regra validada de roteamento.
7. Executar a tarefa em uma pasta isolada sob `data/jobs/<job_id>`.
8. Persistir somente IDs, estado, progresso e resultados necessários.
9. Entregar o resultado pelo watcher, respeitando os limites do Telegram.
10. Adicionar testes de sucesso, erro, timeout, cancelamento, autorização e
    proteção de segredos.
11. Atualizar `.env.example`, README e serviços somente quando a implementação
    estiver pronta.

Uma definição futura no registro poderia seguir este formato:

```json
{
  "heygen-video": {
    "queue": "videos",
    "description": "Gera um vídeo pelo HeyGen Video Agent",
    "enabled": false,
    "requiredFields": ["prompt"],
    "executor": "heygen",
    "instruction": "Gere um único vídeo a partir do prompt validado."
  }
}
```

O exemplo permanece com `enabled: false` até que autenticação, executor,
worker, entrega e testes estejam concluídos. Adicionar somente a entrada JSON
não torna a skill operacional.

## Responsabilidades do executor HeyGen

O executor deve:

- validar tamanho e conteúdo do prompt;
- usar a API v3 por meio do HeyGen CLI;
- criar uma sessão do Video Agent e guardar imediatamente `session_id` e
  `video_id`;
- acompanhar o estado com limite de tempo e suporte a cancelamento;
- tratar limites de uso e falhas sem expor detalhes internos;
- baixar o MP4 para `data/jobs/<job_id>/files`, quando o tamanho permitir;
- retornar resumo, duração, link e arquivos no `AgentResult`;
- nunca confiar permanentemente em um `look_id` de avatar: o look deve ser
  resolvido novamente a partir do grupo do avatar;
- manter o cliente HeyGen separado do cliente de conversa e do executor Codex.

Para vídeos com avatar próprio, a identidade estável deve guardar o grupo do
avatar e a voz escolhida. Antes de cada geração, o executor resolve um look
compatível com a orientação desejada.

## Implantação incremental sugerida

### Etapa 1 — vídeo com apresentador automático

- instalar e autenticar o HeyGen CLI;
- implementar `heygen-video`;
- adicionar `/videoestoque`;
- iniciar o worker `videos`;
- entregar link e MP4;
- validar timeout, cancelamento e consumo de créditos.

Essa etapa evita o fluxo interativo de criação de avatar e permite validar a
infraestrutura com menor risco.

### Etapa 2 — avatar persistente

- implementar `heygen-avatar`;
- guardar identidade e voz sem expor IDs ao usuário;
- adicionar os pontos de aprovação de aparência e voz;
- usar o avatar salvo em `/video`.

### Etapa 3 — roteamento natural

Depois que os comandos explícitos estiverem estáveis, o roteador pode mapear
pedidos em linguagem natural para `heygen-video`. Isso exige
`QUEUE_ROUTING_ENABLED=true` e deve continuar sujeito à autorização, validação
de payload e confirmação antes de consumir créditos.

## Referências oficiais

- [HeyGen CLI](https://developers.heygen.com/cli)
- [Criar sessão do Video Agent v3](https://developers.heygen.com/reference/create-video-agent-session)
- [Consultar vídeo gerado](https://developers.heygen.com/reference/get-video)
- [Orientações para agentes de IA](https://developers.heygen.com/docs/for-ai-agents)
