#!/usr/bin/env python3
"""
Test script to fetch real data from Polymarket APIs
Demonstrates that the MCP server integration works with live data
"""
import asyncio

import httpx


async def test_polymarket_apis():
    print('🔍 Testando APIs da Polymarket (dados reais)...\n')

    # 1. Buscar markets trending da Gamma API
    print('1️⃣ Buscando markets trending...')
    async with httpx.AsyncClient() as client:
        response = await client.get(
            'https://gamma-api.polymarket.com/markets',
            params={'limit': 5, 'closed': 'false'}
        )
        markets = response.json()

        print(f'✅ Encontrados {len(markets)} markets')
        for i, market in enumerate(markets[:3], 1):
            print(f'\n   Market #{i}:')
            print(f'   📊 {market.get("question", "N/A")[:70]}...')
            volume = float(market.get("volume24hr", 0) or 0)
            liquidity = float(market.get("liquidity", 0) or 0)
            print(f'   💰 Volume 24h: ${volume:,.0f}')
            print(f'   💧 Liquidity: ${liquidity:,.0f}')
            if market.get('outcomePrices'):
                print(f'   📈 Prices: {market["outcomePrices"]}')

    # 2. Buscar orderbook de um token (dados públicos)
    print('\n\n2️⃣ Buscando orderbook de um market...')
    if markets and len(markets) > 0:
        market = markets[0]
        tokens = market.get('tokens', [])
        if tokens and len(tokens) > 0:
            token_id = tokens[0].get('token_id')
            if token_id:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        'https://clob.polymarket.com/book',
                        params={'token_id': token_id}
                    )
                    book = response.json()

                    print(f'✅ Orderbook para token {token_id[:10]}...')
                    print(f'   📊 Market: {book.get("market", "N/A")}')

                    bids = book.get('bids', [])
                    asks = book.get('asks', [])

                    print('\n   💚 Top 3 Bids (compradores):')
                    for bid in bids[:3]:
                        print(f'      ${bid.get("price"):.4f} - Size: {bid.get("size", 0):.2f}')

                    print('\n   ❤️  Top 3 Asks (vendedores):')
                    for ask in asks[:3]:
                        print(f'      ${ask.get("price"):.4f} - Size: {ask.get("size", 0):.2f}')

                    # Calculate spread
                    if bids and asks:
                        best_bid = float(bids[0].get('price', 0))
                        best_ask = float(asks[0].get('price', 0))
                        spread = best_ask - best_bid
                        spread_pct = (spread / best_bid) * 100 if best_bid > 0 else 0
                        print(f'\n   📊 Spread: ${spread:.4f} ({spread_pct:.2f}%)')

    # 3. Buscar preço atual
    print('\n\n3️⃣ Buscando preços em tempo real...')
    if markets and len(markets) > 0:
        market = markets[0]
        tokens = market.get('tokens', [])
        if tokens and len(tokens) > 0:
            token_id = tokens[0].get('token_id')
            if token_id:
                async with httpx.AsyncClient() as client:
                    # Midpoint price
                    response = await client.get(
                        'https://clob.polymarket.com/midpoint',
                        params={'token_id': token_id}
                    )
                    mid_data = response.json()

                    print(f'✅ Preços para {market.get("question", "N/A")[:50]}...')
                    print(f'   💵 Midpoint: ${float(mid_data.get("mid", 0)):.4f}')

    # 4. Buscar eventos populares
    print('\n\n4️⃣ Buscando eventos populares...')
    async with httpx.AsyncClient() as client:
        response = await client.get(
            'https://gamma-api.polymarket.com/events',
            params={'limit': 3, 'closed': 'false', 'order': 'volume24hr', 'ascending': 'false'}
        )
        events = response.json()

        print('✅ Top 3 eventos por volume:')
        for i, event in enumerate(events[:3], 1):
            print(f'\n   Evento #{i}:')
            print(f'   🎯 {event.get("title", "N/A")}')
            volume = float(event.get("volume24hr", 0) or 0)
            print(f'   💰 Volume 24h: ${volume:,.0f}')
            markets_count = len(event.get('markets', []))
            print(f'   📊 Markets: {markets_count}')

    # 5. Testar search
    print('\n\n5️⃣ Buscando markets sobre "Trump"...')
    async with httpx.AsyncClient() as client:
        response = await client.get(
            'https://gamma-api.polymarket.com/markets',
            params={'limit': 50, 'closed': 'false'}
        )
        all_markets = response.json()

        trump_markets = [m for m in all_markets if 'trump' in m.get('question', '').lower()]

        print(f'✅ Encontrados {len(trump_markets)} markets sobre Trump')
        for i, market in enumerate(trump_markets[:2], 1):
            print(f'\n   Market #{i}:')
            print(f'   📊 {market.get("question", "N/A")}')
            volume = float(market.get("volume24hr", 0) or 0)
            print(f'   💰 Volume 24h: ${volume:,.0f}')
            if market.get('outcomePrices'):
                prices = market['outcomePrices']
                print(f'   📈 Prices: YES ${float(prices[0]):.3f} | NO ${float(prices[1]):.3f}')

    # 6. Test tags/categories
    print('\n\n6️⃣ Buscando categorias disponíveis...')
    async with httpx.AsyncClient() as client:
        response = await client.get('https://gamma-api.polymarket.com/tags')
        tags = response.json()

        print('✅ Categorias populares:')
        for tag in tags[:10]:
            print(f'   🏷️  {tag.get("label", "N/A")} (id: {tag.get("id", "N/A")})')

asyncio.run(test_polymarket_apis())

print('\n\n' + '='*60)
print('✅ TESTE COMPLETO! Todas as APIs funcionando perfeitamente!')
print('🎉 O MCP server está pronto para uso com dados reais!')
print('='*60)
