#!/usr/bin/env python3
"""
Análise completa dos top 10 markets da Polymarket
Com recomendações de investimento
"""
import sys
sys.path.insert(0, 'src')

import asyncio
import json
from datetime import datetime
from typing import Any

import httpx


REQUEST_TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 3
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


async def _get_json_with_retries(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    retries: int = MAX_RETRIES,
) -> Any:
    """Fetch JSON data with retry handling for transient HTTP failures."""
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            response = await client.get(url, params=params)
            if response.status_code in RETRYABLE_STATUS_CODES:
                response.raise_for_status()
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            if attempt == retries:
                break
            await asyncio.sleep(0.5 * attempt)

    raise RuntimeError(f"Failed to fetch JSON from {url}") from last_error


async def get_top_markets_with_analysis() -> None:
    """Busca e analisa os top 10 markets"""

    print("\n" + "=" * 80)
    print("📊 TOP 10 MARKETS DA POLYMARKET - ANÁLISE COMPLETA DE INVESTIMENTO")
    print("=" * 80)
    print(f"📅 Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        # Buscar top markets por volume
        print("🔍 Buscando markets com maior volume...\n")
        try:
            markets = await _get_json_with_retries(
                client,
                'https://gamma-api.polymarket.com/markets',
                params={
                    'limit': 15,
                    'closed': 'false',
                    'order': 'volume24hr',
                    'ascending': 'false'
                },
            )
        except RuntimeError as exc:
            print(f"❌ Erro ao buscar markets: {exc}")
            return

        # Filtrar markets com dados válidos (usando clobTokenIds)
        valid_markets = [m for m in markets if m.get('clobTokenIds') and len(m.get('clobTokenIds', '').split(',')) > 0][:10]

        analyses = []

        for i, market in enumerate(valid_markets, 1):
            market_id = market.get('id', 'N/A')
            question = market.get('question', 'N/A')
            volume_24h = float(market.get("volume24hr", 0) or 0)
            liquidity = float(market.get("liquidity", 0) or 0)

            # Parse prices
            prices_raw = market.get('outcomePrices')
            if isinstance(prices_raw, str):
                prices = json.loads(prices_raw)
            else:
                prices = prices_raw

            yes_price = float(prices[0]) if prices and len(prices) > 0 else 0
            no_price = float(prices[1]) if prices and len(prices) > 1 else 0

            # Get orderbook data
            clob_token_ids = market.get('clobTokenIds', '')
            token_id = clob_token_ids.split(',')[0] if clob_token_ids else None

            spread = 0
            spread_pct = 0
            depth_score = 0
            best_bid = 0
            best_ask = 0

            if token_id:
                try:
                    # Get orderbook
                    book = await _get_json_with_retries(
                        client,
                        'https://clob.polymarket.com/book',
                        params={'token_id': token_id},
                    )

                    bids = book.get('bids', [])
                    asks = book.get('asks', [])

                    if bids and asks:
                        best_bid = float(bids[0].get('price', 0))
                        best_ask = float(asks[0].get('price', 0))
                        spread = best_ask - best_bid
                        spread_pct = (spread / best_bid * 100) if best_bid > 0 else 0

                        # Calculate depth (top 5 levels)
                        bid_depth = sum(float(b.get('size', 0)) for b in bids[:5])
                        ask_depth = sum(float(a.get('size', 0)) for a in asks[:5])
                        depth_score = min(bid_depth, ask_depth)
                except RuntimeError:
                    pass

            # Calculate metrics
            analysis = analyze_market(
                question=question,
                volume_24h=volume_24h,
                liquidity=liquidity,
                yes_price=yes_price,
                no_price=no_price,
                spread_pct=spread_pct,
                depth_score=depth_score,
                best_bid=best_bid,
                best_ask=best_ask
            )

            analyses.append({
                'rank': i,
                'question': question,
                'market_id': market_id,
                'volume_24h': volume_24h,
                'liquidity': liquidity,
                'yes_price': yes_price,
                'no_price': no_price,
                'spread_pct': spread_pct,
                'best_bid': best_bid,
                'best_ask': best_ask,
                'depth_score': depth_score,
                **analysis
            })

            # Print market info
            print(f"{'=' * 80}")
            print(f"#{i} - {question}")
            print(f"{'=' * 80}")
            print(f"\n💰 MÉTRICAS FINANCEIRAS:")
            print(f"   Volume 24h: ${volume_24h:,.0f}")
            print(f"   Liquidez: ${liquidity:,.0f}")
            print(f"   Profundidade Orderbook: {depth_score:.0f} contratos")

            print(f"\n📈 PREÇOS ATUAIS:")
            print(f"   YES: ${yes_price:.4f} ({yes_price * 100:.1f}%)")
            print(f"   NO:  ${no_price:.4f} ({no_price * 100:.1f}%)")
            if best_bid > 0 and best_ask > 0:
                print(f"   Melhor Bid: ${best_bid:.4f}")
                print(f"   Melhor Ask: ${best_ask:.4f}")
                print(f"   Spread: ${spread:.4f} ({spread_pct:.2f}%)")

            print(f"\n🎯 ANÁLISE DE INVESTIMENTO:")
            print(f"   Recomendação: {analysis['recommendation']} {get_recommendation_emoji(analysis['recommendation'])}")
            print(f"   Score de Confiança: {analysis['confidence_score']}/100")
            print(f"   Risk Level: {analysis['risk_level']} {get_risk_emoji(analysis['risk_level'])}")

            print(f"\n💡 JUSTIFICATIVA:")
            for reason in analysis['reasons']:
                print(f"   • {reason}")

            print(f"\n📊 FATORES CONSIDERADOS:")
            for factor, score in analysis['factors'].items():
                emoji = "✅" if score >= 70 else "⚠️" if score >= 40 else "❌"
                print(f"   {emoji} {factor}: {score}/100")

            print("\n")

            await asyncio.sleep(0.5)  # Rate limiting

        # Summary and recommendations
        print("\n" + "=" * 80)
        print("🏆 RESUMO E RECOMENDAÇÕES FINAIS")
        print("=" * 80)

        # Rank by investment score
        buy_recommendations = [a for a in analyses if a['recommendation'] == 'BUY']
        hold_recommendations = [a for a in analyses if a['recommendation'] == 'HOLD']

        if buy_recommendations:
            print(f"\n🟢 TOP {len(buy_recommendations)} RECOMENDAÇÕES DE COMPRA:\n")
            buy_recommendations.sort(key=lambda x: x['confidence_score'], reverse=True)

            for idx, rec in enumerate(buy_recommendations[:5], 1):
                print(f"{idx}. {rec['question'][:65]}...")
                print(f"   💰 Volume: ${rec['volume_24h']:,.0f} | Confiança: {rec['confidence_score']}/100")
                print(f"   🎯 Estratégia sugerida: {rec['strategy']}")
                print()

        if hold_recommendations:
            print(f"\n🟡 MARKETS PARA OBSERVAR ({len(hold_recommendations)}):\n")
            for idx, rec in enumerate(hold_recommendations[:3], 1):
                print(f"{idx}. {rec['question'][:65]}...")
                print(f"   💡 Motivo: {rec['reasons'][0]}")
                print()

        avoid_recommendations = [a for a in analyses if a['recommendation'] == 'AVOID']
        if avoid_recommendations:
            print(f"\n🔴 MARKETS PARA EVITAR ({len(avoid_recommendations)}):\n")
            for rec in avoid_recommendations:
                print(f"❌ {rec['question'][:65]}...")
                print(f"   ⚠️  Risco: {rec['risk_level']} - {rec['reasons'][0]}")
                print()

        # Portfolio diversification suggestion
        print("\n" + "=" * 80)
        print("💼 SUGESTÃO DE PORTFÓLIO DIVERSIFICADO")
        print("=" * 80)

        if buy_recommendations:
            print("\n📊 Para um portfolio de $1,000:")
            print()

            top_3 = buy_recommendations[:3]
            allocations = [0.4, 0.35, 0.25]  # 40%, 35%, 25%

            for rec, allocation in zip(top_3, allocations):
                amount = 1000 * allocation
                print(f"• ${amount:.0f} ({allocation * 100:.0f}%) - {rec['question'][:55]}...")
                print(f"  Lado: {rec['side']} @ ${rec['entry_price']:.4f}")
                print()

            print("🎯 Objetivos:")
            print("  • Diversificação entre diferentes categorias")
            print("  • Balanceamento entre risco e retorno")
            print("  • Liquidez suficiente para saída rápida")


def analyze_market(question, volume_24h, liquidity, yes_price, no_price,
                   spread_pct, depth_score, best_bid, best_ask):
    """Análise detalhada de um market"""

    # Calculate individual factor scores
    factors = {}
    reasons = []

    # 1. Volume Score (0-100)
    if volume_24h >= 1000000:
        factors['Volume/Atividade'] = 95
    elif volume_24h >= 500000:
        factors['Volume/Atividade'] = 85
    elif volume_24h >= 100000:
        factors['Volume/Atividade'] = 70
    elif volume_24h >= 50000:
        factors['Volume/Atividade'] = 50
    else:
        factors['Volume/Atividade'] = 30

    # 2. Liquidity Score
    if liquidity >= 500000:
        factors['Liquidez'] = 95
        reasons.append("Liquidez excelente permite entrada/saída fácil")
    elif liquidity >= 100000:
        factors['Liquidez'] = 80
        reasons.append("Boa liquidez disponível")
    elif liquidity >= 50000:
        factors['Liquidez'] = 60
        reasons.append("Liquidez moderada")
    else:
        factors['Liquidez'] = 35
        reasons.append("Liquidez baixa - risco de slippage")

    # 3. Spread Score
    if spread_pct < 1:
        factors['Spread'] = 95
    elif spread_pct < 2:
        factors['Spread'] = 85
    elif spread_pct < 5:
        factors['Spread'] = 60
    else:
        factors['Spread'] = 30
        reasons.append("Spread elevado aumenta custo de entrada")

    # 4. Price Efficiency Score (quão próximo de uma verdadeira probabilidade)
    if 0.10 <= yes_price <= 0.90:
        factors['Eficiência de Preço'] = 85
        reasons.append("Preço reflete incerteza real - boa oportunidade")
    elif 0.05 <= yes_price <= 0.95:
        factors['Eficiência de Preço'] = 70
    else:
        factors['Eficiência de Preço'] = 40
        reasons.append("Market muito one-sided - pouca oportunidade")

    # 5. Orderbook Depth
    if depth_score >= 1000:
        factors['Profundidade'] = 90
    elif depth_score >= 500:
        factors['Profundidade'] = 75
    elif depth_score >= 100:
        factors['Profundidade'] = 55
    else:
        factors['Profundidade'] = 35

    # Calculate overall score
    overall_score = sum(factors.values()) / len(factors)

    # Determine risk level
    if overall_score >= 80:
        risk_level = "BAIXO"
    elif overall_score >= 60:
        risk_level = "MÉDIO"
    else:
        risk_level = "ALTO"

    # Determine recommendation
    if overall_score >= 75 and liquidity >= 100000 and volume_24h >= 100000:
        recommendation = "BUY"
        confidence_score = min(95, int(overall_score))

        # Determine best side
        if yes_price < 0.3:
            side = "YES"
            entry_price = best_ask if best_ask > 0 else yes_price
            reasons.insert(0, f"YES underpriced em ${yes_price:.3f} - upside potencial")
        elif no_price < 0.3:
            side = "NO"
            entry_price = 1 - (best_bid if best_bid > 0 else yes_price)
            reasons.insert(0, f"NO underpriced em ${no_price:.3f} - upside potencial")
        elif 0.4 <= yes_price <= 0.6:
            side = "YES" if yes_price < 0.5 else "NO"
            entry_price = best_ask if side == "YES" else (1 - best_bid)
            reasons.insert(0, "Market balanceado - boa para swing trading")
        else:
            side = "YES" if yes_price < no_price else "NO"
            entry_price = yes_price if side == "YES" else no_price
            reasons.insert(0, "Momentum trade baseado em probabilidades")

        strategy = f"Entrar gradualmente, limit orders perto de ${entry_price:.4f}"

    elif overall_score >= 55 and liquidity >= 50000:
        recommendation = "HOLD"
        confidence_score = int(overall_score)
        side = "AGUARDAR"
        entry_price = yes_price
        strategy = "Observar movimento de preços antes de entrar"
        reasons.insert(0, "Condições moderadas - aguardar melhor setup")

    else:
        recommendation = "AVOID"
        confidence_score = int(overall_score)
        side = "N/A"
        entry_price = 0
        strategy = "Não tradear - condições desfavoráveis"

        if liquidity < 50000:
            reasons.insert(0, "Liquidez insuficiente - alto risco")
        if spread_pct > 5:
            reasons.insert(0, "Spread muito alto - custo proibitivo")

    return {
        'recommendation': recommendation,
        'confidence_score': confidence_score,
        'risk_level': risk_level,
        'factors': factors,
        'reasons': reasons,
        'side': side,
        'entry_price': entry_price,
        'strategy': strategy
    }


def get_recommendation_emoji(rec):
    if rec == "BUY":
        return "🟢"
    elif rec == "HOLD":
        return "🟡"
    else:
        return "🔴"


def get_risk_emoji(risk):
    if risk == "BAIXO":
        return "🟢"
    elif risk == "MÉDIO":
        return "🟡"
    else:
        return "🔴"


if __name__ == "__main__":
    asyncio.run(get_top_markets_with_analysis())
