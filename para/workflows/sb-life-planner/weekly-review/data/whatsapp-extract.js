// WhatsApp Web — Self-Chat Message Extractor
// Usage: Open WhatsApp Web -> select self-chat -> F12 -> Console -> paste and run.
// Extracted messages are copied to the clipboard. Paste into your agent for routing.

(() => {
  const msgs = document.querySelectorAll('.copyable-text[data-pre-plain-text]');
  const results = [];
  msgs.forEach(el => {
    const meta = el.getAttribute('data-pre-plain-text').trim();
    const text = el.querySelector('[data-testid="selectable-text"]')?.innerText || '';
    if (text) results.push(`${meta} ${text}`);
  });
  copy(results.join('\n'));
  console.log(`${results.length} messages copied to clipboard`);
})();
