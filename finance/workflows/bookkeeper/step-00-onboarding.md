---
stepId: onboarding
nextStepFile: null
---

# Step 00: Source Onboarding

**Quando executar.** Este step só é chamado quando `{CONFIG_DIR}/sources.yaml` está vazio (sem entradas sob `sources:`). Se o arquivo já tem pelo menos uma entrada, pular direto para o step de preflight do fluxo escolhido. Não executar durante um fechamento normal.

**Objetivo.** Guiar o usuário na seleção das suas fontes de dados (bancos, corretoras, exchanges) a partir do manifesto público e popular `sources.yaml` com as fontes escolhidas. Para fontes ainda não suportadas, acionar `tool-builder` para criar o parser.

---

## Mandatory Sequence

### Section 1 — Apresentar o manifesto

1. Ler o manifesto público: `3-resources/tools/sb-os/finance/docs/sources-manifest.md`.
2. Exibir ao usuário (PT-BR) a lista de fontes disponíveis, agrupadas por categoria:

   ```
   Fontes de despesas disponíveis:
     [ ] bradesco_extrato — Bradesco — Extrato Conta Corrente (csv)
     [ ] santander_extrato — Santander — Extrato Conta Corrente (pdf)
     [ ] santander_fatura — Santander — Fatura Cartão Visa (pdf)
     [ ] mp_extrato — Mercado Pago — Extrato Conta (csv)
     [ ] mp_fatura — Mercado Pago — Fatura Cartão (pdf)
     [ ] wise_extrato — Wise — Extrato Multi-Moeda (csv)
     [ ] manual_cash — Gastos em Dinheiro — Entrada Manual
     [ ] nubank_fatura — Nubank — Fatura Cartão (pdf) [historical only]
     [ ] xp_fatura — XP — Fatura Cartão (csv) [historical only]

   Fontes de investimentos disponíveis:
     [ ] safra — Banco Safra / Safra Corretora (pdf, csv)
     [ ] b3 — B3 — Bolsa Brasileira via Safra (pdf, csv)
     [ ] avenue — Avenue Securities (csv)
     [ ] mercado_bitcoin — Mercado Bitcoin (csv)
     [ ] bipa — Bipa (csv)
     [ ] funds — Fundos de Investimento via Safra (pdf, csv)

   Quais fontes você usa? Liste os ids separados por vírgula, ou "todas" para selecionar todas as fontes ativas.
   ```

3. STOP. Aguardar resposta do usuário.

### Section 2 — Emitir instruções por fonte selecionada

Para cada fonte selecionada pelo usuário (na ordem em que aparecem no manifesto):

1. Exibir as instruções de download/extração da fonte conforme o manifesto:

   ```
   📥 {name}
   Formato: {input_format}
   Como baixar: {download_instructions}
   {extraction_instructions, se existir}
   ```

2. Perguntar se a fonte deve ser habilitada para fechamentos futuros ou apenas para backfill (historical):

   ```
   Usar {name} em fechamentos mensais regulares?
     [S] Sim — habilitada para novos fechamentos
     [N] Não — somente para reprocessamento de meses anteriores (historical)
   ```

3. STOP. Aguardar confirmação para cada fonte antes de prosseguir.

### Section 3 — Fontes não listadas (desvio-para-estrutura)

Se o usuário mencionar uma fonte que NÃO consta no manifesto:

1. Seguir **Rule A** do `gatekeeper-loop.md` — nomear o desvio em PT-BR:

   ```
   A fonte "{nome_informado}" não tem parser neste sistema.

   Como proceder?
     [A] Construir o parser agora — você nos envia um arquivo de exemplo e
         acionamos o tool-builder para criar e testar o parser.
     [B] Ignorar esta fonte no momento — registramos como pendência.
     [C] Você descreve o formato agora e registramos para build posterior.
   ```

2. STOP. Aguardar escolha do usuário.

3. Roteamento:
   - `[A]` → Acionar **Rule B / Seam 1 (`tool-builder`)** do `gatekeeper-loop.md`:
     - Solicitar ao usuário um arquivo de amostra real da fonte.
     - Despachar `tool-builder` via Agent tool com o contexto de despacho:
       ```
       need: "Parser para a fonte '{nome}' (formato {formato})"
       class: write
       use: parser
       destination_artifact: transactions.csv  # (ou o artefato correto para a scope)
       real_sample: {caminho do arquivo fornecido pelo usuário}
       ```
     - Depois que `tool-builder` retornar o parser aceito, acionar **Seam 2 (`doc-maintainer`)** para atualizar `sources-manifest.md` com a nova entrada.
   - `[B]` → Registrar a fonte como pendência (um item no log de pendências). Não bloquear o onboarding.
   - `[C]` → Registrar a descrição do formato e despachar `doc-maintainer` para criar um rascunho de entrada no manifesto. Marcar `last_validated: pending` na entrada criada.

### Section 4 — Popular `sources.yaml` e confirmar

1. Para cada fonte confirmada pelo usuário, escrever uma entrada em `{CONFIG_DIR}/sources.yaml`:

   ```yaml
   - id: {source_id}
     enabled_for_close: {true|false}   # true se Section 2 resposta [S]; false se [N]
     note: {nota opcional, ex: "historical only"}
   ```

2. Salvar `sources.yaml`.

3. Confirmar ao usuário (PT-BR):

   ```
   Onboarding concluído. {N} fontes registradas em sources.yaml.
   {N_enabled} habilitadas para fechamentos regulares.
   {N_pending} pendências registradas.

   Para iniciar o fechamento, execute bookkeeper novamente.
   ```

4. STOP. O workflow encerra aqui. O usuário executa `bookkeeper` de novo para iniciar o fechamento com as fontes configuradas.

---

## Step Menu

- **Gatekeeper checkpoint** → antes de encerrar, rodar § Per-Step Checkpoint em `../gatekeeper-loop.md`. Uma nova fonte adicionada ao manifesto (Seam 1 + Seam 2 completos) = estrutura + docs atualizados = desvio resolvido.
- **[X] Sair** → encerrar sem salvar (sources.yaml permanece vazio; onboarding será executado novamente na próxima ativação).
