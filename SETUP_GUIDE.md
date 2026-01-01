# 🚀 GUIA DE SETUP - POLYMARKET MCP

## ✅ MCP ADICIONADO AO CLAUDE DESKTOP!

O Polymarket MCP foi configurado com sucesso no Claude Desktop em:
```
~/Library/Application Support/Claude/claude_desktop_config.json
```

---

## 📋 PRÓXIMOS PASSOS

### 1️⃣ CONFIGURAR CREDENCIAIS

Você precisa adicionar suas credenciais da wallet Polygon. Há **2 opções**:

#### **OPÇÃO A: Editar diretamente o config do Claude Desktop** (Recomendado)

Abra o arquivo:
```bash
code ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

E substitua estas linhas na seção `polymarket`:
```json
"POLYGON_PRIVATE_KEY": "SUA_PRIVATE_KEY_AQUI_SEM_0x",
"POLYGON_ADDRESS": "0xSeuEnderecoPolygon"
```

#### **OPÇÃO B: Usar arquivo .env** (Mais seguro)

1. Copie o template:
```bash
cd polymarket-mcp-server
cp .env.example .env
```

2. Edite o .env:
```bash
nano .env
```

3. Adicione suas credenciais:
```env
POLYGON_PRIVATE_KEY=sua_private_key_sem_0x
POLYGON_ADDRESS=0xSeuEndereco
```

4. Remova o bloco "env" do claude_desktop_config.json (o .env será usado automaticamente)

---

### 2️⃣ OBTER CREDENCIAIS DA POLYGON

Se você não tem uma wallet Polygon ainda:

**Opção 1: MetaMask**
1. Abra MetaMask
2. Mude para rede Polygon
3. Vá em Settings → Advanced → Show Private Key
4. Use esse private key (⚠️ NUNCA compartilhe!)

**Opção 2: Criar nova wallet**
```bash
cd polymarket-mcp-server
python3 -c "
from eth_account import Account
import secrets
priv = secrets.token_hex(32)
account = Account.from_key(priv)
print(f'Private Key: {priv}')
print(f'Address: {account.address}')
"
```

**⚠️ IMPORTANTE:**
- Guarde a private key em local SEGURO
- NUNCA commite no git
- NUNCA compartilhe com ninguém
- Comece com quantias PEQUENAS para testar

---

### 3️⃣ FUNDING DA WALLET

Para usar o MCP de trading, você precisa:

1. **USDC na Polygon**
   - Deposite USDC na sua wallet Polygon
   - Mínimo: $50-100 para testes
   - Você pode comprar USDC e fazer bridge para Polygon via:
     - [Polymarket UI](https://polymarket.com)
     - [Polygon Bridge](https://wallet.polygon.technology/polygon/bridge)

2. **MATIC para gas**
   - Deposite ~$2-5 em MATIC para pagar gas fees
   - Polygon tem fees baixíssimas (~$0.01 por transação)

---

### 4️⃣ RESTART CLAUDE DESKTOP

Após configurar as credenciais:

1. **Quit Claude Desktop completamente**:
   ```bash
   killall Claude
   ```

2. **Reabra Claude Desktop**

3. **Verifique se o MCP está ativo**:
   - Procure por um ícone de 🔌 ou indicação de MCPs conectados
   - O Polymarket MCP deve aparecer como "polymarket"

---

### 5️⃣ TESTAR O MCP

No Claude Desktop, pergunte:

```
"Mostre os 5 markets com mais volume na Polymarket hoje"
```

Ou:

```
"Analise oportunidades de trading na Polymarket"
```

Ou:

```
"Qual meu portfolio atual na Polymarket?"
```

Se funcionar, você verá dados REAIS da Polymarket! 🎉

---

## 🛠️ TROUBLESHOOTING

### Erro: "Module not found: polymarket_mcp"

**Solução:**
```bash
cd polymarket-mcp-server
python3 -m pip install -e .
```

### Erro: "No API credentials"

**Solução:**
- As API credentials serão criadas AUTOMATICAMENTE na primeira execução
- Aguarde 10-20 segundos na primeira vez
- Logs aparecerão com suas novas credenciais (salve-as!)

### Erro: "Private key invalid"

**Solução:**
- Certifique-se que a private key está SEM o prefixo "0x"
- Deve ter exatamente 64 caracteres hexadecimais
- Formato correto: `abc123def456...` (64 chars)
- Formato errado: `0xabc123def456...`

### MCP não aparece no Claude Desktop

**Solução:**
1. Verifique o JSON está válido:
```bash
python3 -m json.tool ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

2. Check logs do Claude:
```bash
tail -f ~/Library/Logs/Claude/mcp*.log
```

3. Reinicie completamente:
```bash
killall Claude
open -a Claude
```

---

## ⚙️ CONFIGURAÇÕES AVANÇADAS

### Safety Limits (já configurados no config)

```env
MAX_ORDER_SIZE_USD=1000              # Máximo $1000 por ordem
MAX_TOTAL_EXPOSURE_USD=5000          # Máximo $5000 exposição total
MAX_POSITION_SIZE_PER_MARKET=2000    # Máximo $2000 por market
MIN_LIQUIDITY_REQUIRED=10000         # Mínimo $10k liquidez no market
MAX_SPREAD_TOLERANCE=0.05            # Máximo 5% spread
REQUIRE_CONFIRMATION_ABOVE_USD=500   # Confirmar se > $500
```

### Ajustar Limites

Edite diretamente no `claude_desktop_config.json` ou no `.env`:

**Para trading mais conservador:**
```env
MAX_ORDER_SIZE_USD=100
MAX_TOTAL_EXPOSURE_USD=500
REQUIRE_CONFIRMATION_ABOVE_USD=50
```

**Para trading mais agressivo:**
```env
MAX_ORDER_SIZE_USD=5000
MAX_TOTAL_EXPOSURE_USD=20000
REQUIRE_CONFIRMATION_ABOVE_USD=2000
```

---

## 🎯 FEATURES DISPONÍVEIS

Com o MCP configurado, você pode pedir para Claude:

### 📊 Market Discovery
- "Busque markets sobre Trump"
- "Mostre os 10 markets com mais volume"
- "Quais markets fecham hoje?"

### 📈 Market Analysis
- "Analise o market sobre X"
- "Qual o spread do market Y?"
- "Compare estes 3 markets: A, B, C"

### 💼 Trading
- "Compre $100 de YES no market X"
- "Cancele todas minhas ordens"
- "Execute um smart trade de $500 em Y"

### 📊 Portfolio
- "Mostre minhas posições"
- "Qual meu P&L total?"
- "Analise os riscos do meu portfolio"

### ⚡ Real-time
- "Subscribe aos preços do market X"
- "Me avise quando houver mudanças grandes"

---

## 🔐 SEGURANÇA

### ✅ BOM:
- Private key em variáveis de ambiente
- Safety limits configurados
- Confirmações para ordens grandes
- Logs de todas operações

### ⚠️ CUIDADO:
- Comece com valores PEQUENOS ($50-100)
- Teste primeiro em markets de baixo risco
- Monitore suas posições regularmente
- NUNCA compartilhe private key

### ❌ EVITE:
- Colocar TODO seu capital
- Trading sem entender o market
- Ignorar safety limits
- Deixar bot rodando sem supervisão inicial

---

## 📚 DOCUMENTAÇÃO COMPLETA

- **README.md**: Visão geral do projeto
- **TOOLS_REFERENCE.md**: Referência de todas as tools

---

## 🆘 SUPORTE

Se tiver problemas:

1. Verifique os logs:
```bash
tail -f ~/Library/Logs/Claude/mcp-server-polymarket.log
```

2. Teste o MCP diretamente:
```bash
cd polymarket-mcp-server
python3 -m polymarket_mcp.server
```

3. Execute os testes (seleção offline — não requer credenciais):
```bash
pytest tests/ -m "not integration and not slow and not real_api and not performance"
```

Um comando `pytest` sem seleção executa todos os tiers, incluindo os testes que
falam com as APIs reais da Polymarket — eles falham sem credenciais e geram
tráfego de rede. A seleção acima roda apenas as suítes offline; detalhes em
CONTRIBUTING.md (seção Testing).

---

## ✅ CHECKLIST FINAL

Antes de usar em produção, confirme:

- [ ] Private key configurada corretamente
- [ ] Wallet tem USDC suficiente
- [ ] Wallet tem MATIC para gas
- [ ] Claude Desktop reiniciado
- [ ] MCP aparece como conectado
- [ ] Teste com queries simples funcionou
- [ ] Safety limits ajustados para seu perfil
- [ ] Backup da private key guardado em local seguro

---

**🎉 PRONTO! Agora Claude pode tradear autonomamente na Polymarket para você!**

**💰 Boa sorte com seus trades! 🚀**
