/* Observatory shared nav — injects #primary-nav + #search-bar into every page */
(function () {
  var LINKS = [
    { href: '/', label: 'Dashboard', path: '/' },
    { href: '/picks', label: 'Picks', path: '/picks' },
    { href: '/brain', label: 'Taste Map', path: '/brain' },
    { href: '/ask', label: '✶ Ask Oracle', path: '/ask', cls: 'oracle' },
  ];

  var pathname = location.pathname.replace(/\/$/, '') || '/';
  var onDashboard = pathname === '/';

  /* ── Primary nav ── */
  var nav = document.createElement('nav');
  nav.id = 'primary-nav';
  nav.setAttribute('aria-label', 'Main navigation');
  nav.className = 'has-search-bar';

  var inner = document.createElement('div');
  inner.className = 'nav-inner';

  var logo = document.createElement('a');
  logo.className = 'pnav-logo';
  logo.href = '/';
  logo.innerHTML = 'Observatory <span aria-hidden="true">✶</span>';
  inner.appendChild(logo);

  LINKS.forEach(function (link) {
    var a = document.createElement('a');
    a.className = 'pnav-link' + (link.cls ? ' ' + link.cls : '');
    a.href = link.href;
    a.textContent = link.label;
    var lp = link.path.replace(/\/$/, '') || '/';
    if (pathname === lp || (lp !== '/' && pathname.startsWith(lp + '/'))) {
      a.classList.add('active');
      a.setAttribute('aria-current', 'page');
    }
    inner.appendChild(a);
  });

  nav.appendChild(inner);

  /* ── Search bar row ── */
  var searchBar = document.createElement('div');
  searchBar.id = 'search-bar';
  searchBar.innerHTML =
    '<div class="search-inner">' +
    '<input id="nav-search-input" type="search" placeholder="Search books, films, series…" autocomplete="off" aria-label="Search" />' +
    '<select id="nav-search-type" aria-label="Media type">' +
    '<option value="">All</option>' +
    '<option value="film">Film</option>' +
    '<option value="tv">TV</option>' +
    '<option value="book">Book</option>' +
    '<option value="music">Music</option>' +
    '<option value="podcast">Podcast</option>' +
    '</select>' +
    '<div class="search-spinner" id="nav-search-spinner"></div>' +
    '<button id="nav-search-btn" type="button">Search</button>' +
    '</div>';

  nav.appendChild(searchBar);
  document.body.insertBefore(nav, document.body.firstChild);

  /* ── Search logic ── */
  function doNavSearch() {
    var q = document.getElementById('nav-search-input').value.trim();
    if (!q) return;
    var type = document.getElementById('nav-search-type').value;
    if (onDashboard && typeof doSearch === 'function') {
      doSearch();
    } else {
      var params = new URLSearchParams({ q: q });
      if (type) params.set('type', type);
      location.href = '/?' + params.toString();
    }
  }

  document.getElementById('nav-search-btn').addEventListener('click', doNavSearch);
  document.getElementById('nav-search-input').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') doNavSearch();
  });
})();
