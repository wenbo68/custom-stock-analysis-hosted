// Currency of the market a ticker trades in — a simplified frontend mirror
// of data_provider/base.py's _market_tag rules, enough for the capital
// field's currency hint. The backend stays the source of truth for the
// actual market routing.
export function tickerCurrency(ticker: string): string {
  const code = ticker.trim().toUpperCase();
  if (code.endsWith('.T')) {
    return 'JPY';
  }
  if (code.endsWith('.KS') || code.endsWith('.KQ')) {
    return 'KRW';
  }
  if (code.endsWith('.TW') || code.endsWith('.TWO')) {
    return 'TWD';
  }
  if (code.endsWith('.HK') || (code.startsWith('HK') && /^\d{1,5}$/.test(code.slice(2)))) {
    return 'HKD';
  }
  if (/^\d{5}$/.test(code)) {
    // bare 5-digit codes are Hong Kong; A-share codes are 6 digits
    return 'HKD';
  }
  if (/^\d{6}(\.(SH|SZ|BJ))?$/.test(code)) {
    return 'CNY';
  }
  return 'USD';
}
