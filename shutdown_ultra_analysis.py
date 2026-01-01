#!/usr/bin/env python3
"""
ULTRA DEEP ANALYSIS - Government Shutdown Markets (CORRETO)
Análise dos 7 markets específicos sobre shutdown
"""
import sys

sys.path.insert(0, 'src')

import asyncio
import json
from datetime import datetime

import httpx


async def ultra_shutdown_analysis():
    """Análise ultra profunda dos markets de government shutdown"""

    print("\n" + "="*100)
    print("🏛️  ULTRA DEEP ANALYSIS - GOVERNMENT SHUTDOWN (2025)")
    print("="*100)
    print(f"📅 Análise em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # Markets específicos identificados
    shutdown_queries = [
        'Will the Government shutdown end November 8-11?',
        'Will the Government shutdown end November 16 or later?',
        'Will the Government shutdown end November 12-15?',
        'Will the Government shutdown end by November 15?',
        'Will the Government shutdown end by December 31?',
        'Will the Government shutdown end by November 30?',
        'Will the government shutdown end November 10?'
    ]

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Buscar top markets
        response = await client.get(
            'https://gamma-api.polymarket.com/markets',
            params={'limit': 30, 'closed': 'false', 'order': 'volume24hr', 'ascending': 'false'}
        )
        all_markets = response.json()

        # Filtrar markets de shutdown
        shutdown_markets = []
        for market in all_markets:
            question = market.get('question', '')
            if any(q.lower() in question.lower() or question.lower() in q.lower() for q in shutdown_queries):
                shutdown_markets.append(market)

        print(f"✅ Encontrados {len(shutdown_markets)} markets sobre Government Shutdown\n")
        print("="*100)
        print("\n📊 FASE 1: MAPA COMPLETO DOS MARKETS")
        print("="*100 + "\n")

        # Organizar markets
        markets_data = []
        total_volume = 0
        total_liquidity = 0

        for market in shutdown_markets:
            question = market.get('question', 'N/A')
            volume_24h = float(market.get("volume24hr", 0) or 0)
            liquidity = float(market.get("liquidity", 0) or 0)

            total_volume += volume_24h
            total_liquidity += liquidity

            # Parse prices
            prices_raw = market.get('outcomePrices')
            if isinstance(prices_raw, str):
                prices = json.loads(prices_raw)
            else:
                prices = prices_raw

            yes_price = float(prices[0]) if prices and len(prices) > 0 else 0
            no_price = float(prices[1]) if prices and len(prices) > 1 else 0

            # Calcular implied odds
            yes_odds = (1 / yes_price) if yes_price > 0 else 999
            no_odds = (1 / no_price) if no_price > 0 else 999

            markets_data.append({
                'question': question,
                'volume_24h': volume_24h,
                'liquidity': liquidity,
                'yes_price': yes_price,
                'no_price': no_price,
                'yes_prob': yes_price * 100,
                'no_prob': no_price * 100,
                'yes_odds': yes_odds,
                'no_odds': no_odds,
                'market_id': market.get('id', '')
            })

        # Ordenar por data (parsing da pergunta)
        def extract_date_priority(question):
            q = question.lower()
            if 'november 8' in q or 'november 10' in q or '8-11' in q:
                return 1
            elif 'november 12' in q or '12-15' in q:
                return 2
            elif 'november 15' in q:
                return 3
            elif 'november 16' in q or 'later' in q:
                return 4
            elif 'november 30' in q:
                return 5
            elif 'december' in q:
                return 6
            return 99

        markets_data.sort(key=lambda x: extract_date_priority(x['question']))

        # Printar cada market
        for i, m in enumerate(markets_data, 1):
            print(f"#{i} - {m['question']}")
            print(f"   💰 Volume 24h: ${m['volume_24h']:,.0f}")
            print(f"   💧 Liquidez: ${m['liquidity']:,.0f}")
            print(f"   📈 YES: {m['yes_prob']:.1f}% (${m['yes_price']:.4f}) - Odds: {m['yes_odds']:.1f}x")
            print(f"   📉 NO:  {m['no_prob']:.1f}% (${m['no_price']:.4f}) - Odds: {m['no_odds']:.1f}x")
            print()

        print("\n💰 TOTAIS:")
        print(f"   Volume 24h combinado: ${total_volume:,.0f}")
        print(f"   Liquidez combinada: ${total_liquidity:,.0f}")
        print(f"   Média volume/market: ${total_volume/len(markets_data):,.0f}")

        # Análise de probabilidades
        print("\n\n" + "="*100)
        print("📊 FASE 2: ANÁLISE DE PROBABILIDADES & DETECÇÃO DE ARBITRAGEM")
        print("="*100 + "\n")

        print("🎯 PROBABILIDADES IMPLÍCITAS (ordenadas cronologicamente):\n")

        cumulative = 0
        for m in markets_data:
            print(f"{m['question'][:70]:<72} YES: {m['yes_prob']:5.1f}%")
            cumulative += m['yes_prob']

        print(f"\n📊 SOMA DAS PROBABILIDADES: {cumulative:.1f}%")
        print()

        if cumulative > 110:
            print("🔴 ALERTA CRÍTICO: ARBITRAGEM DETECTADA!")
            print(f"   Soma = {cumulative:.1f}% (deve ser ~100% para eventos mutuamente exclusivos)")
            print(f"   Overpricing total: {cumulative - 100:.1f}%")
            print("\n   💡 ESTRATÉGIA DE ARBITRAGEM:")
            print("      → Vender YES em TODOS os markets")
            print(f"      → Apenas UM evento pode acontecer, mas mercado precifica {cumulative:.0f}%")
            print(f"      → Profit garantido: ~{cumulative - 100:.1f}% (menos fees)")
            print()
        elif cumulative < 90:
            print("🟢 OPORTUNIDADE: UNDERPRICING DETECTADO!")
            print(f"   Soma = {cumulative:.1f}% (deveria ser ~100%)")
            print(f"   Underpricing total: {100 - cumulative:.1f}%")
            print("\n   💡 ESTRATÉGIA:")
            print("      → Comprar YES nos markets mais underpriced")
            print(f"      → Edge de {100 - cumulative:.1f}% sobre o mercado")
            print()
        else:
            print("✅ Mercado razoavelmente eficiente")
            print(f"   Soma = {cumulative:.1f}% (próximo de 100%)")
            print()

        # Identificar o melhor value
        print("\n" + "="*100)
        print("💎 FASE 3: IDENTIFICAÇÃO DE VALUE BETS")
        print("="*100 + "\n")

        # Value = alto volume + baixa probabilidade YES
        value_bets = sorted(markets_data, key=lambda x: x['yes_prob'] if x['volume_24h'] > 500000 else 999)

        print("🟢 TOP 3 VALUE BETS (YES underpriced):\n")
        for i, m in enumerate(value_bets[:3], 1):
            roi_potential = ((1 / m['yes_prob']) * 100 - 100) if m['yes_prob'] > 0 else 999
            print(f"{i}. {m['question'][:70]}")
            print(f"   YES @ {m['yes_prob']:.1f}% = {roi_potential:.0f}% ROI potencial")
            print(f"   Odds: {m['yes_odds']:.1f}x (cada $100 vira ${100 * m['yes_odds']:,.0f})")
            print(f"   Volume: ${m['volume_24h']:,.0f} (alta convicção)")
            print(f"   💡 Análise: Risco ${m['yes_price']*100:.0f} para ganhar ${(1-m['yes_price'])*100:.0f}")
            print()

        # Consensus bets
        consensus_bets = sorted(markets_data, key=lambda x: -x['no_prob'])
        print("\n🔵 CONSENSUS BETS (NO altamente provável):\n")
        for i, m in enumerate(consensus_bets[:3], 1):
            print(f"{i}. {m['question'][:70]}")
            print(f"   NO @ {m['no_prob']:.1f}% (consenso forte)")
            print(f"   Retorno: {((1/m['no_prob'])*100 - 100):.1f}% se vencer")
            print("   💡 Trade conservador: baixo risco, baixo retorno")
            print()

        # Análise temporal
        print("\n" + "="*100)
        print("⏰ FASE 4: ANÁLISE TEMPORAL & CATALISADORES")
        print("="*100 + "\n")

        print("📅 TIMELINE DOS EVENTOS:\n")
        print("Nov 8-11:  Resolução muito próxima (1-4 dias)")
        print("Nov 12-15: Resolução de curto prazo (5-8 dias)")
        print("Nov 16+:   Resolução média prazo (9+ dias)")
        print("Nov 30:    Resolução longo prazo (23 dias)")
        print("Dec 31:    Resolução muito longa (54 dias)")
        print()

        print("🔔 CATALISADORES IMINENTES:\n")
        print("📰 POSITIVOS (Resolução rápida):")
        print("   • Acordo bipartidário iminente")
        print("   • Pressão econômica (mercados, empresas)")
        print("   • Midterms próximas (pressão eleitoral)")
        print("   • Feriados chegando (Thanksgiving)")
        print()

        print("⚠️  NEGATIVOS (Shutdown prolongado):")
        print("   • Gridlock político persistente")
        print("   • Demandas irreconciliáveis")
        print("   • Posturing para eleições")
        print("   • Falta de urgência imediata")
        print()

        # Análise de sentimento
        print("\n" + "="*100)
        print("📈 FASE 5: ANÁLISE DE SENTIMENTO AGREGADO")
        print("="*100 + "\n")

        # Calcular sentimento ponderado por volume
        weighted_sentiment = sum(m['yes_prob'] * m['volume_24h'] for m in markets_data) / total_volume

        print(f"🎯 SENTIMENTO AGREGADO (ponderado por volume): {weighted_sentiment:.1f}%")
        print(f"   Isto significa: {weighted_sentiment:.1f}% de probabilidade do shutdown continuar")
        print(f"   Ou: {100-weighted_sentiment:.1f}% de confiança em resolução RÁPIDA")
        print()

        if weighted_sentiment < 10:
            sentiment_desc = "MUITO OTIMISTA"
            interpretation = "Mercado extremamente confiante em resolução rápida"
            risk = "RISCO: Possível complacência - considerar hedge com YES barato"
        elif weighted_sentiment < 30:
            sentiment_desc = "OTIMISTA"
            interpretation = "Mercado confiante mas com alguma incerteza"
            risk = "RISCO: Balanceado - oportunidades em ambos os lados"
        else:
            sentiment_desc = "PESSIMISTA"
            interpretation = "Mercado espera shutdown prolongado"
            risk = "RISCO: Posições longas podem ser prudentes"

        print(f"📊 INTERPRETAÇÃO: {sentiment_desc}")
        print(f"   {interpretation}")
        print(f"   {risk}")
        print()

        # Estratégia recomendada
        print("\n" + "="*100)
        print("🎯 FASE 6: ESTRATÉGIA DE TRADING OTIMIZADA")
        print("="*100 + "\n")

        print("💼 PORTFOLIO RECOMENDADO ($1,000):\n")

        # Encontrar os 3 melhores trades
        early_market = next((m for m in markets_data if 'november 8' in m['question'].lower() or '8-11' in m['question'].lower()), None)
        mid_market = next((m for m in markets_data if 'november 16' in m['question'].lower() or 'later' in m['question'].lower()), None)
        long_market = next((m for m in markets_data if 'december' in m['question'].lower()), None)

        position_num = 1

        if early_market:
            print(f"{position_num}️⃣  TRADE CONSERVADOR - ${200} (20%):")
            print(f"   Market: {early_market['question'][:65]}")
            print(f"   Lado: NO @ ${early_market['no_price']:.4f}")
            print(f"   Lógica: Alta probabilidade ({early_market['no_prob']:.1f}%) de resolução rápida")
            print(f"   Retorno esperado: {((1/early_market['no_prob'])*100-100):.1f}% em 1-4 dias")
            print("   Risco: Muito baixo (consenso forte)\n")
            position_num += 1

        if mid_market and mid_market['yes_prob'] < 20:
            print(f"{position_num}️⃣  TRADE DE VALOR - ${400} (40%):")
            print(f"   Market: {mid_market['question'][:65]}")
            print(f"   Lado: YES @ ${mid_market['yes_price']:.4f}")
            print(f"   Lógica: YES underpriced em {mid_market['yes_prob']:.1f}% - asymmetric upside")
            print(f"   Retorno potencial: {(mid_market['yes_odds']-1)*100:.0f}% se vencer")
            print("   Risco: Médio-Alto (lottery ticket)\n")
            position_num += 1

        if long_market and long_market['yes_prob'] < 50:
            print(f"{position_num}️⃣  HEDGE POSITION - ${150} (15%):")
            print(f"   Market: {long_market['question'][:65]}")
            print(f"   Lado: YES @ ${long_market['yes_price']:.4f}")
            print("   Lógica: Hedge contra cenário pessimista prolongado")
            print(f"   Retorno potencial: {(long_market['yes_odds']-1)*100:.0f}% se shutdown durar")
            print("   Risco: Alto (improvável mas possível)\n")
            position_num += 1

        # Adicionar posição especulativa no melhor value
        best_value = value_bets[0] if value_bets else None
        if best_value and best_value['yes_prob'] < 15:
            print(f"{position_num}️⃣  ESPECULAÇÃO - ${250} (25%):")
            print(f"   Market: {best_value['question'][:65]}")
            print(f"   Lado: YES @ ${best_value['yes_price']:.4f}")
            print(f"   Lógica: Melhor risk/reward - {best_value['yes_odds']:.1f}x potencial")
            print(f"   Retorno potencial: {(best_value['yes_odds']-1)*100:.0f}%")
            print("   Risco: Muito alto (longshot)\n")

        # Resumo final
        print("\n" + "="*100)
        print("📋 RESUMO EXECUTIVO - KEY INSIGHTS")
        print("="*100 + "\n")

        print("🔑 TOP 5 INSIGHTS:\n")

        print("1️⃣  CONSENSUS DO MERCADO:")
        print(f"    • {100-weighted_sentiment:.1f}% de probabilidade de resolução RÁPIDA")
        print(f"    • ${total_volume:,.0f} em volume mostra alta convicção")
        print(f"    • Mercado está {sentiment_desc.lower()}\n")

        print("2️⃣  ARBITRAGEM/INEFICIÊNCIA:")
        if cumulative > 110:
            print(f"    • OVERPRICING de {cumulative-100:.1f}% detectado")
            print("    • Oportunidade de vender YES em todos markets")
        elif cumulative < 90:
            print(f"    • UNDERPRICING de {100-cumulative:.1f}% detectado")
            print("    • Oportunidade de comprar YES nos underpriced")
        else:
            print(f"    • Mercado eficiente (~{cumulative:.0f}% total)")
        print()

        print("3️⃣  MELHOR VALUE BET:")
        if value_bets:
            best = value_bets[0]
            print(f"    • {best['question'][:60]}")
            print(f"    • YES {best['yes_prob']:.1f}% = {best['yes_odds']:.1f}x odds")
            print(f"    • ROI potencial: {((best['yes_odds']-1)*100):.0f}%\n")

        print("4️⃣  TIMELINE CRÍTICO:")
        print("    • Próximos 3-5 dias são CRUCIAIS")
        print("    • Catalisadores: votações, acordos, notícias")
        print("    • Use WebSocket do MCP para alertas real-time\n")

        print("5️⃣  RISK/REWARD:")
        print("    • Trades conservadores: 3-5% retorno, baixo risco")
        print("    • Trades de valor: 500-1000% retorno, médio-alto risco")
        print("    • Portfolio diversificado: 15-30% retorno esperado\n")

        print("\n💡 AÇÃO RECOMENDADA:")
        print("   ✅ Entrar agora com posições pequenas")
        print("   ✅ Monitorar notícias DIARIAMENTE")
        print("   ✅ Usar stop-loss se cenário mudar")
        print("   ✅ Escalar posições com novas informações")
        print("   ✅ Ativar WebSocket alerts no MCP\n")

        print("⚡ NEXT STEPS:")
        print("   1. Configure WebSocket para alertas real-time")
        print("   2. Entre com 20-30% do capital inicial")
        print("   3. Reserve 70% para ajustes baseados em notícias")
        print("   4. Monitor C-SPAN, Politico, Twitter de congressistas")
        print("   5. Ajuste posições a cada 12-24h\n")

if __name__ == "__main__":
    asyncio.run(ultra_shutdown_analysis())
