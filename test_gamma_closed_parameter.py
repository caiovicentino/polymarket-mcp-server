#!/usr/bin/env python3
"""
Test to verify Gamma API returns current data with closed=false parameter.

This demonstrates the issue and the fix:
- Without closed=false: returns historical data (2020-2021)
- With closed=false: returns current data (2024-2027)
"""
import asyncio
import httpx
from datetime import datetime


async def test_gamma_api_closed_parameter():
    print("=" * 70)
    print("GAMMA API: Testing closed=false Parameter")
    print("=" * 70)
    print()

    url = 'https://gamma-api.polymarket.com/markets'

    # Test 1: Without closed=false (original behavior)
    print("Test 1: WITHOUT closed=false parameter (original)")
    print("-" * 70)
    async with httpx.AsyncClient(timeout=30.0) as client:
        params = {'active': 'true', 'limit': 3}
        response = await client.get(url, params=params)
        markets = response.json()

        years = []
        for m in markets:
            year = datetime.fromisoformat(m['endDate'].replace('Z', '+00:00')).year
            years.append(year)
            print(f"  Year: {year} {'❌ Historical' if year < 2024 else '✅ Current'}")
            print(f"  Question: {m['question'][:60]}...")
            print()

        avg_year = sum(years) / len(years)
        print(f"Average year: {avg_year:.1f}")
        print(f"Result: {'❌ Returns HISTORICAL data' if avg_year < 2024 else '✅ Returns CURRENT data'}")
        print()

    # Test 2: With closed=false (fixed behavior)
    print("Test 2: WITH closed=false parameter (FIXED)")
    print("-" * 70)
    async with httpx.AsyncClient(timeout=30.0) as client:
        params = {'closed': 'false', 'active': 'true', 'limit': 3}
        response = await client.get(url, params=params)
        markets = response.json()

        years = []
        for m in markets:
            year = datetime.fromisoformat(m['endDate'].replace('Z', '+00:00')).year
            years.append(year)
            print(f"  Year: {year} {'❌ Historical' if year < 2024 else '✅ Current'}")
            print(f"  Question: {m['question'][:60]}...")
            print()

        avg_year = sum(years) / len(years)
        print(f"Average year: {avg_year:.1f}")
        print(f"Result: {'❌ Returns HISTORICAL data' if avg_year < 2024 else '✅ Returns CURRENT data'}")
        print()

    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print()
    print("The fix is simple: Add 'closed=false' parameter to all Gamma API calls.")
    print()
    print("Before fix:")
    print("  params = {'active': 'true'}  # Returns historical data")
    print()
    print("After fix:")
    print("  params = {'closed': 'false', 'active': 'true'}  # Returns current data")
    print()
    print("✅ This ensures market discovery tools return current (2024-2027) data")
    print("✅ instead of historical data from 2020-2021.")
    print()


if __name__ == '__main__':
    asyncio.run(test_gamma_api_closed_parameter())