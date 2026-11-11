/* Portfolio interactions: language switch, mobile menu, article filters. */
(function () {
  'use strict';

  var root = document.documentElement;

  /* ---------------- language ---------------- */
  var LANG_KEY = 'lu-yi-portfolio-lang';
  var langButton = document.getElementById('lang-toggle');

  function readStoredLang() {
    try {
      var stored = window.localStorage.getItem(LANG_KEY);
      if (stored === 'zh' || stored === 'en') return stored;
    } catch (e) { /* storage may be unavailable */ }
    var param = new URLSearchParams(window.location.search).get('lang');
    if (param === 'zh' || param === 'en') return param;
    return 'zh';
  }

  function applyLanguage(lang) {
    var isZh = lang === 'zh';
    root.setAttribute('lang', isZh ? 'zh-CN' : 'en');
    root.setAttribute('data-lang', lang);

    document.querySelectorAll('[data-zh]').forEach(function (el) {
      var value = el.getAttribute(isZh ? 'data-zh' : 'data-en');
      if (value !== null) el.textContent = value;
    });

    document.querySelectorAll('[data-zh-html]').forEach(function (el) {
      var value = el.getAttribute(isZh ? 'data-zh-html' : 'data-en-html');
      if (value !== null) el.innerHTML = value;
    });

    var title = root.getAttribute(isZh ? 'data-title-zh' : 'data-title-en');
    if (title) document.title = title;

    var description = document.querySelector('meta[name="description"]');
    var desc = root.getAttribute(isZh ? 'data-desc-zh' : 'data-desc-en');
    if (description && desc) description.setAttribute('content', desc);

    if (langButton) {
      langButton.textContent = isZh ? 'EN' : '中文';
      langButton.setAttribute('aria-label', isZh ? 'Switch to English' : '切换到中文');
    }
  }

  if (langButton) {
    langButton.addEventListener('click', function () {
      var next = root.getAttribute('data-lang') === 'zh' ? 'en' : 'zh';
      applyLanguage(next);
      try { window.localStorage.setItem(LANG_KEY, next); } catch (e) { /* ignore */ }
    });
  }
  applyLanguage(readStoredLang());

  /* ---------------- mobile menu ---------------- */
  var menuButton = document.querySelector('.menu-toggle');
  var navLinks = document.getElementById('nav-links');

  function closeMenu() {
    if (!navLinks || !menuButton) return;
    navLinks.classList.remove('is-open');
    menuButton.setAttribute('aria-expanded', 'false');
    menuButton.setAttribute('aria-label', '打开导航 / Open navigation');
    document.body.classList.remove('menu-open');
    var use = menuButton.querySelector('use');
    if (use) use.setAttribute('href', '#i-menu');
  }

  if (menuButton && navLinks) {
    menuButton.addEventListener('click', function () {
      var willOpen = !navLinks.classList.contains('is-open');
      if (willOpen) {
        navLinks.classList.add('is-open');
        menuButton.setAttribute('aria-expanded', 'true');
        menuButton.setAttribute('aria-label', '关闭导航 / Close navigation');
        document.body.classList.add('menu-open');
        var use = menuButton.querySelector('use');
        if (use) use.setAttribute('href', '#i-x');
      } else {
        closeMenu();
      }
    });

    navLinks.querySelectorAll('a').forEach(function (link) {
      link.addEventListener('click', closeMenu);
    });

    window.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') closeMenu();
    });
  }

  /* ---------------- article filters ---------------- */
  var filters = document.querySelectorAll('.filter');
  var publications = document.querySelectorAll('.publication');

  function applyFilter(filter) {
    publications.forEach(function (publication) {
      var categories = (publication.getAttribute('data-category') || '').split(/\s+/);
      publication.hidden = filter !== 'all' && categories.indexOf(filter) === -1;
    });
  }

  filters.forEach(function (button) {
    button.addEventListener('click', function () {
      filters.forEach(function (item) { item.classList.remove('is-active'); });
      button.classList.add('is-active');
      applyFilter(button.getAttribute('data-filter') || 'all');
    });
  });

  /* ---------------- footer year ---------------- */
  var year = document.getElementById('year');
  if (year) year.textContent = String(new Date().getFullYear());
})();
