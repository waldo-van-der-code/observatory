/* Observatory shared nav — injects #primary-nav into every page */
(function () {
  var LINKS = [
    { href: '/', label: 'Dashboard', path: '/' },
    { href: '/picks', label: 'Picks', path: '/picks' },
    { href: '/brain', label: 'Taste Map', path: '/brain' },
    { href: '/ask', label: '✶ Ask Oracle', path: '/ask', cls: 'oracle' },
  ];

  var pathname = location.pathname.replace(/\/$/, '') || '/';

  var nav = document.createElement('nav');
  nav.id = 'primary-nav';
  nav.setAttribute('aria-label', 'Main navigation');

  var inner = document.createElement('div');
  inner.className = 'nav-inner';

  var logo = document.createElement('a');
  logo.className = 'pnav-logo';
  logo.href = '/';
  logo.innerHTML = 'Observatory <span>✶</span>';
  inner.appendChild(logo);

  LINKS.forEach(function (link) {
    var a = document.createElement('a');
    a.className = 'pnav-link' + (link.cls ? ' ' + link.cls : '');
    a.href = link.href;
    a.textContent = link.label;
    var lp = link.path.replace(/\/$/, '') || '/';
    if (pathname === lp || (lp !== '/' && pathname.startsWith(lp + '/'))) {
      a.classList.add('active');
    } else if (lp !== '/' && pathname === lp) {
      a.classList.add('active');
    }
    inner.appendChild(a);
  });

  nav.appendChild(inner);
  document.body.insertBefore(nav, document.body.firstChild);
})();
