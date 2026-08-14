/**
 * main.js — GBP Monitor frontend utilities
 */

// ── Fetch result notification ─────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
  // Auto-dismiss messages after 6 seconds
  const messages = document.querySelectorAll('[role="alert"]');
  messages.forEach(function (msg) {
    setTimeout(function () {
      msg.style.transition = 'opacity 0.4s ease';
      msg.style.opacity = '0';
      setTimeout(function () { msg.remove(); }, 400);
    }, 6000);
  });

  // Highlight active nav
  const currentPath = window.location.pathname;
  const navLinks = document.querySelectorAll('nav a');
  navLinks.forEach(function (link) {
    const linkPath = link.getAttribute('href').split('?')[0];
    if (currentPath === linkPath && !link.classList.contains('active')) {
      link.classList.add('bg-red-50', 'text-red-700');
    }
  });

  // AJAX fetch trigger (sidebar button)
  const fetchForm = document.getElementById('fetch-form');
  if (fetchForm) {
    fetchForm.addEventListener('submit', function (e) {
      const btn = document.getElementById('btn-fetch-now');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `
          <svg class="animate-spin w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
          </svg>
          Fetching...
        `;
      }
    });
  }
});

// ── Number formatting ─────────────────────────────────────────────
function formatNumber(n) {
  return new Intl.NumberFormat('id-ID').format(n);
}

// ── Tooltip helper ────────────────────────────────────────────────
function initTooltips() {
  document.querySelectorAll('[data-tooltip]').forEach(function (el) {
    el.style.position = 'relative';
    el.addEventListener('mouseenter', function () {
      const tip = document.createElement('div');
      tip.className = 'absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-2 px-2.5 py-1.5 rounded-lg text-xs bg-slate-900 text-white whitespace-nowrap pointer-events-none';
      tip.textContent = el.getAttribute('data-tooltip');
      tip.id = 'active-tooltip';
      el.appendChild(tip);
    });
    el.addEventListener('mouseleave', function () {
      const tip = el.querySelector('#active-tooltip');
      if (tip) tip.remove();
    });
  });
}

document.addEventListener('DOMContentLoaded', initTooltips);
