---
stepNumber: 5
stepId: review
nextStepFile: step-06-report.md
---

# Step 5: Two-Pass Review Queue

**Goal:** Resolver os desconhecidos (Pass 1) e, somente após Pass 1 fechado, rodar os prompts de fronteira de mês (Pass 2). Capturar gastos em dinheiro entre os dois passos. Persistir todas as decisões em `suppliers.json`, `tags.json`, `categories.json` e no CSV do mês.

## Architectural Invariants (binding)

- **Ordering (data-model §6 invariant 8):** Pass 1 MUST close completely (zero itens pendentes em categorias, fornecedores E tags) antes de qualquer chamada a Pass 2. Boundary depende de `supplier.movable` resolvido em Pass 1.
- **Boundary scope (data-model §6 invariant 9):** Pass 2 só dispara para transações com `is_boundary_day(data_caixa) AND supplier.movable == true AND source_type != 'fatura'`. Fora desse escopo, nenhum prompt.
- **`data_caixa` immutable:** Pass 2 atualiza SOMENTE `data_competencia`. NUNCA toca `data_caixa`.
- **Skip-default (Q13a):** A ação default em Pass 2 é "manter" → `data_competencia = data_caixa`. Sem flag silencioso, sem auto-push.
- **PT-BR:** Todos os strings exibidos ao usuário em português brasileiro. Nomes de funções de lib, paths, e identificadores de coluna permanecem em inglês.

## Mandatory Sequence

### Section 1 — Pass 1 (Resolução de desconhecidos)

1. Carregar:
   - `{DASHBOARD_DATA}/{MONTH}/transactions.csv` (o CSV escrito por step-04).
   - `{CONFIG_DIR}/suppliers.json` via `lib.suppliers.load_suppliers`.
   - `{CONFIG_DIR}/tags.json` via `lib.tags.load_tags`.
   - `{CONFIG_DIR}/categories.json` (dict cru — `lib.queue.build_pass_1_queue` lê `movable_hint` por categoria).

2. Construir a fila Pass 1 chamando `lib.queue.build_pass_1_queue(transactions, suppliers_index, categories_data, tags_index)`. A fila já vem agrupada por `item_type` na ordem `category` → `supplier` → `tag`, ordenada por data dentro de cada grupo.

3. Processar a fila por item_type, em batches de 5–7 itens. Se um item_type estiver vazio, pular silenciosamente para o próximo (não exibir seção vazia).

   **Batch — categorias:**
   - Para cada item, mostrar: `descrição · valor · data` e a lista de categorias disponíveis a partir do bloco `categories` em `categories.json`.
   - Aceitar com uma tecla a sugestão default (se houver) — alvo ≤15s/item per spec §T2.
   - Permitir digitação livre para criar nova categoria; nesse caso, atualizar `categories.json` (bloco `categories`) inserindo a nova entrada com `movable_hint` perguntado ao usuário (`movable | non-movable | mixed`).
   - Aplicar a resposta com `lib.queue.apply_pass_1_resolution(transactions, item, {"category": "<valor>"})`.
   - Se a categorização implicar novo fornecedor (ou novo alias num fornecedor existente), anexar a entrada em `suppliers.json` com `default_category` correspondente. (Single layer post-Phase-6 — não existe mais `vendor_mappings` em `categories.json`.)

   **Batch — fornecedores:**
   - Para cada item, mostrar: `descrição · valor · data · categoria já resolvida`.
   - Pedir o `canonical` (nome canônico) e os `aliases` (lista; pelo menos a descrição original).
   - Pedir o `movable` (`true | false`) — obrigatório SEMPRE que `categories[<categoria>].movable_hint == 'mixed'`. Para `movable_hint == 'movable'` ou `'non-movable'`, pré-preencher o default e aceitar com uma tecla; o usuário pode sobrescrever.
   - Pedir o `default_category` (sugerir a categoria já resolvida no item).
   - Persistir em `suppliers.json` (novo slug em `suppliers`, com `canonical`, `aliases`, `movable`, `default_category`). Recarregar o `SupplierIndex` após cada gravação.
   - Aplicar com `lib.queue.apply_pass_1_resolution(transactions, item, {"canonical": "<canonical>", "match_confidence": "exact"})`.

   **Batch — tags:**
   - Para cada item, mostrar: `proposed_token · descrição · valor`.
   - Prompt de três opções:
     - `[A] Aceitar` — adiciona a tag ao dicionário e à coluna `tags` da transação.
     - `[M] Mesclar com tag existente` — pedir o `existing_token` (do bloco `tags` em `tags.json`); substitui o `proposed_token` pelo existente na coluna `tags` da transação.
     - `[R] Rejeitar` — anota razão; incrementa `return_count`. Antes de chamar `lib.tags.reject_tag` em rejeições subsequentes do mesmo token, chamar `lib.tags.should_resurface(token, index)`; se `True`, re-apresentar ao usuário com a mensagem "Esta tag voltou — reconsiderar?" antes de incrementar.
   - Validar `proposed_token` com `lib.tags.is_valid_token` antes de aceitar/rejeitar.
   - Aplicar:
     - Aceitar → `lib.tags.accept_tag(token, label, notes, today, tag_index)`, persistir com `lib.tags.save_tags`, e `lib.queue.apply_pass_1_resolution(transactions, item, {"decision": "accept", "token": "<token>"})`.
     - Mesclar → `lib.tags.merge_tag(proposed, existing, today, tag_index)`, persistir, e `apply_pass_1_resolution` com `{"decision": "merge", "token": "<proposed>", "merge_into": "<existing>"}`.
     - Rejeitar → `lib.tags.reject_tag(token, reason, today, tag_index)`, persistir, e `apply_pass_1_resolution` com `{"decision": "reject", "token": "<token>"}`.
   - Ler/escrever a coluna `tags` da transação SEMPRE via `lib.tags.parse_tag_column` e `lib.tags.serialize_tag_column` (formato semicolon-separated por data-model §1.3).

4. Quando todas as três filas zerarem, **declarar Pass 1 fechado**. Salvar o CSV intermediário (`transactions.csv`) com as resoluções aplicadas. Confirmar ao usuário: `Pass 1 fechado. {N_cat} categorias, {N_sup} fornecedores, {N_tag} tags resolvidos.`

> ⛔ **Gate:** Não prosseguir para Section 3 (Pass 2) até este ponto. A chamada a `lib.queue.build_pass_2_queue` levanta `QueueOrderingError` se houver qualquer transação com categoria/fornecedor não resolvido.

### Section 2 — Gastos em dinheiro

Perguntar ao usuário em PT-BR:

> "Houve gastos em dinheiro este mês que não aparecem nos extratos bancários?"

Se sim, para cada despesa em dinheiro, anexar uma linha ao CSV com:

| Campo | Valor |
|-------|-------|
| `bank` | `manual` |
| `source_type` | `dinheiro` |
| `match_confidence` | `manual` |
| `data_caixa` | data informada pelo usuário |
| `data_competencia` | igual a `data_caixa` (default; usuário pode sobrescrever) |
| `supplier_canonical` | `Cash` |
| `tags` | `""` (string vazia — sem tags) |
| `category` | categoria informada pelo usuário |
| `amount`, `description` | informados pelo usuário |

Salvar o CSV.

### Section 3 — Pass 2 (Limites de mês)

1. Recarregar `transactions.csv` (com resoluções de Pass 1 + gastos em dinheiro), `suppliers.json` (atualizado em Pass 1) e `categories.json`.

2. Construir a fila Pass 2 chamando `lib.queue.build_pass_2_queue(transactions, suppliers_index, categories_data)`. A função internamente:
   - Verifica que toda transação tem categoria e fornecedor resolvidos (caso contrário levanta `QueueOrderingError` — sinal de bug em Pass 1).
   - Resolve o `movable` efetivo via `lib.suppliers.get_supplier_movable(canonical, index, category_hint)`. Se levantar `UnresolvedMovableError`, retornar a Pass 1 e tratar o fornecedor com `movable_hint == 'mixed'` antes de prosseguir.
   - Filtra por `lib.boundary.needs_boundary_prompt(transaction, supplier_movable, data_caixa)` — só itens onde `is_boundary_day(data_caixa) AND supplier_movable AND source_type != 'fatura'`.
   - Cada item retornado tem `prompt_default = 'keep'` (Q13a).

3. Se a fila vier vazia, informar `Sem candidatos para Pass 2.` e seguir para Section 4.

4. Para cada item, em ordem cronológica:
   - Mostrar: `descrição · valor · data_caixa · supplier_canonical · data_competencia atual`.
   - Prompt em PT-BR:

     ```
     [M] Manter competência = caixa (default)
     [V] Mover competência para outro mês — informar nova data ISO (YYYY-MM-DD)
     ```

   - Tecla única ENTER ou `[M]` → ação `keep`. Não modifica nada. (Skip-default Q13a.)
   - `[V]` + data → ação `move`. Aplicar com `lib.queue.apply_pass_2_resolution(transactions, item, {"action": "move", "new_date": <date>})`. SOMENTE `data_competencia` é atualizada — `data_caixa` permanece imutável.

### Section 4 — Salvar e continuar

1. Escrever o CSV final em `{DASHBOARD_DATA}/{MONTH}/transactions.csv` (sobrescreve o intermediário).
2. Confirmar ao usuário em PT-BR: `Revisão concluída. {N_pass1} resoluções (Pass 1) + {N_cash} gastos em dinheiro + {N_pass2_moved} competências movidas (Pass 2). CSV salvo.`
3. STOP. Aguardar confirmação para seguir.

## Step Menu

- **[C] Continuar** → seguir para o Step 06 (Gerar Relatório)
- **[X] Sair** → encerrar workflow
