#!/bin/bash
# Script rápido para abrir o config do Claude Desktop

echo "🔧 Abrindo configuração do Claude Desktop..."
echo ""

CONFIG_PATH="$HOME/Library/Application Support/Claude/claude_desktop_config.json"

if [ -f "$CONFIG_PATH" ]; then
    echo "✅ Arquivo encontrado: $CONFIG_PATH"
    echo ""
    echo "📝 Instruções:"
    echo "   1. Encontre a seção 'polymarket'"
    echo "   2. Substitua POLYGON_PRIVATE_KEY com sua private key (sem 0x)"
    echo "   3. Substitua POLYGON_ADDRESS com seu endereço"
    echo "   4. Salve o arquivo (Cmd+S)"
    echo "   5. Reinicie Claude Desktop: killall Claude"
    echo ""
    echo "Abrindo em 3 segundos..."
    sleep 3

    # Tentar abrir com VSCode, senão com editor padrão
    if command -v code &> /dev/null; then
        code "$CONFIG_PATH"
    else
        open -a TextEdit "$CONFIG_PATH"
    fi
else
    echo "❌ Arquivo não encontrado: $CONFIG_PATH"
    echo ""
    echo "💡 Certifique-se que Claude Desktop está instalado"
fi
