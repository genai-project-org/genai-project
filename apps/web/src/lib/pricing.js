import { useEffect, useState } from 'react';
import api from '@/lib/api';

// One source of truth: GET /api/pricing (packs, pay-as-you-go rate, welcome/daily credits).
// Nothing in the web app hardcodes a price or a credit amount.
let cache = null;
let inflight = null;

export function loadPricing(force = false) {
  if (cache && !force) return Promise.resolve(cache);
  if (!inflight || force) {
    inflight = api.get('/pricing').then((r) => { cache = r.data; return cache; })
      .finally(() => { inflight = null; });
  }
  return inflight;
}

export function usePricing() {
  const [pricing, setPricing] = useState(cache);
  const [error, setError] = useState(false);
  useEffect(() => {
    let live = true;
    loadPricing().then((p) => live && setPricing(p)).catch(() => live && setError(true));
    return () => { live = false; };
  }, []);
  return { pricing, error, loading: !pricing && !error };
}

export const fmtUsd = (n) => `$${Number(n).toLocaleString('en-US', { minimumFractionDigits: Number.isInteger(Number(n)) ? 0 : 2, maximumFractionDigits: 2 })}`;
export const fmtInr = (n) => `₹${Number(n).toLocaleString('en-IN')}`;
export const fmtCredits = (n) => Math.floor(Number(n)).toLocaleString('en-US');

// Same rule as the backend (`inr_for_usd`): ceil to the published INR step.
export const inrFor = (usd, pricing) => {
  if (!pricing?.fx_rate) return null;
  const step = pricing.inr_round_step || 50;
  return Math.ceil(Math.round(usd * pricing.fx_rate * 1e6) / 1e6 / step) * step;
};
