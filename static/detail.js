/* Observatory detail panel — injects overlay HTML + all interaction logic */
(function () {
  var overlay = document.createElement('div');
  overlay.id = 'detail-overlay';
  overlay.innerHTML =
    '<div id="detail-backdrop" onclick="closeDetail()"></div>' +
    '<div id="detail-panel">' +
      '<div class="detail-close">' +
        '<span id="detail-panel-title" style="font-size:14px;font-weight:600;color:#8b949e;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:400px"></span>' +
        '<button onclick="closeDetail()" aria-label="Close detail">✕</button>' +
      '</div>' +
      '<div id="detail-content"></div>' +
    '</div>';
  document.body.appendChild(overlay);
})();

// ── Detail panel ─────────────────────────────────────────────────────────────
// ── Detail pane — Supabase-backed ────────────────────────────────────────────

function openDetailOverlay(title) {
  const overlay = document.getElementById('detail-overlay');
  const body = document.getElementById('detail-content');
  document.getElementById('detail-panel-title').textContent = title || '';
  body.innerHTML = `<div style="padding:20px">
    <div class="skeleton" style="height:200px;border-radius:0;margin:-20px -20px 20px"></div>
    <div class="skeleton" style="height:28px;width:65%;margin-bottom:10px"></div>
    <div class="skeleton" style="height:14px;width:40%;margin-bottom:20px"></div>
    <div class="skeleton" style="height:90px;margin-bottom:12px"></div>
    <div class="skeleton" style="height:60px"></div>
  </div>`;
  overlay.classList.add('open');
  document.body.style.overflow = 'hidden';
  return body;
}

// Build item_key from itemId string (handles "imdb:tt...", "netflix:...", etc.)
function itemKeyFromId(itemId, mediaType) {
  // Already a full key like "film:imdb:tt123"
  if (itemId.startsWith('film:') || itemId.startsWith('tv_show:') || itemId.startsWith('book:')) return itemId;
  const mt = mediaType || 'film';
  return `${mt}:${itemId}`;
}

async function showDetail(itemId, mediaType) {
  const body = openDetailOverlay('');
  try {
    const key = itemKeyFromId(itemId, mediaType);
    const r = await fetch(`/api/culture/detail?key=${encodeURIComponent(key)}`);
    if (r.status === 404) {
      // Not enriched yet — show linkouts
      showDetailFallback(body, itemId, null);
      return;
    }
    const d = await r.json();
    document.getElementById('detail-panel-title').textContent = d.title || '';
    body.innerHTML = renderStoryDetail(d, itemId);
    wireDetailInteractions(d, itemId);
  } catch(e) {
    showDetailFallback(body, itemId, null);
  }
}

async function showDirectorDetail(name) {
  const body = openDetailOverlay(name);
  try {
    const key = `director:${name}`;
    const r = await fetch(`/api/culture/detail?key=${encodeURIComponent(key)}`);
    if (r.status === 404) {
      const q = encodeURIComponent(name);
      body.innerHTML = `<div style="padding:24px">
        <div style="font-size:18px;font-weight:700;color:var(--text);margin-bottom:16px">${name}</div>
        <div style="display:flex;flex-direction:column;gap:8px">
          <a class="detail-link" href="https://www.imdb.com/find?q=${q}&s=nm" target="_blank">🎬 IMDB ↗</a>
          <a class="detail-link" href="https://letterboxd.com/director/${name.toLowerCase().replace(/ /g,'-')}/" target="_blank">🎞 Letterboxd ↗</a>
        </div>
        <p class="dim" style="margin-top:16px;font-size:12px">Enrichment not yet run for this director.</p>
      </div>`;
      return;
    }
    const d = await r.json();
    document.getElementById('detail-panel-title').textContent = name;
    body.innerHTML = renderDirectorDetail(d);
  } catch(e) {
    body.innerHTML = `<div style="padding:24px;color:var(--text-dim)">Failed to load details for ${name}.</div>`;
  }
}

async function showArtistDetail(name) {
  const body = openDetailOverlay(name);
  try {
    const key = `artist:${name}`;
    const r = await fetch(`/api/culture/detail?key=${encodeURIComponent(key)}`);
    if (r.status === 404) {
      body.innerHTML = `<div style="padding:24px">
        <div style="font-size:18px;font-weight:700;color:var(--text);margin-bottom:16px">${name}</div>
        <a class="detail-link" href="https://www.last.fm/music/${encodeURIComponent(name)}" target="_blank">🎵 Last.fm ↗</a>
        <p class="dim" style="margin-top:16px;font-size:12px">Enrichment not yet run for this artist.</p>
      </div>`;
      return;
    }
    const d = await r.json();
    document.getElementById('detail-panel-title').textContent = name;
    body.innerHTML = renderArtistDetail(d);
  } catch(e) {
    body.innerHTML = `<div style="padding:24px;color:var(--text-dim)">Failed to load details for ${name}.</div>`;
  }
}

// ── Renderers ─────────────────────────────────────────────────────────────────

function starBar(current, itemId, title, mediaType) {
  return [1,2,3,4,5].map(i => {
    const lit = i <= (current||0);
    return `<span class="star${lit?' lit':''}" style="font-size:24px;padding:4px 6px;cursor:pointer"
      onclick="rateDetailItem('${itemId}','${(title||'').replace(/'/g,\"\\\\'\")}',${i},'${mediaType}')"
      onmouseenter="hoverDetailStars(this,${i})"
      onmouseleave="resetDetailStars(this.parentNode,${current||0})">★</span>`;
  }).join('');
}

function streamingBadges(streaming) {
  if (!streaming) return '';
  const flat = (streaming.flatrate||[]).map(s=>`<span class="streaming-pill flatrate">${s}</span>`).join('');
  const rent = (streaming.rent||[]).slice(0,3).map(s=>`<span class="streaming-pill">${s}</span>`).join('');
  const buy  = (streaming.buy||[]).slice(0,2).map(s=>`<span class="streaming-pill" style="opacity:.7">${s}</span>`).join('');
  return flat || rent || buy
    ? `<div class="detail-section">
        <div class="detail-section-label">Where to watch (DE)</div>
        <div class="streaming-pills">${flat}${rent}${buy}</div>
       </div>` : '';
}

function linkRow(links) {
  if (!links) return '';
  return Object.entries(links)
    .filter(([,url]) => url)
    .map(([label,url]) => `<a class="detail-link" href="${url}" target="_blank" rel="noopener">${label} ↗</a>`)
    .join('');
}

function renderStoryDetail(d, itemId) {
  const isBook = d.media_type === 'book';
  const backdrop = d.backdrop_url
    ? `<img class="detail-backdrop-img" src="${d.backdrop_url}" alt="">`
    : d.poster_url
    ? `<img class="detail-backdrop-img" src="${d.poster_url}" alt="" style="object-position:top">`
    : '';
  const coverImg = isBook && d.cover_url
    ? `<img src="${d.cover_url}" style="width:100px;border-radius:4px;margin-bottom:16px;box-shadow:0 2px 8px rgba(26,22,18,.15)" alt="">` : '';

  const metaParts = isBook
    ? [d.author, d.year, d.page_count ? d.page_count+'p' : '', d.series_name ? (d.series_name+' #'+(d.series_pos||'?')) : ''].filter(Boolean)
    : [d.directors?.join(', '), d.year, d.runtime_min ? d.runtime_min+'min' : ''].filter(Boolean);

  const genreTags = (d.genres||d.subjects||[]).slice(0,5).map(g=>`<span class="detail-genre-tag">${g}</span>`).join('');
  const castHtml = (d.cast||[]).slice(0,5).map(c => {
    const img = c.profile ? `<img class="cast-avatar" src="${c.profile}" alt="${c.name}">` : `<div class="cast-avatar" style="display:flex;align-items:center;justify-content:center;font-size:18px">👤</div>`;
    return `<div class="cast-card">${img}<div class="cast-name">${c.name}<br><span style="opacity:.6">${c.character||''}</span></div></div>`;
  }).join('');
  const tmdbScore = d.vote_average ? `<span style="font-weight:700;color:var(--rust)">${d.vote_average}</span><span style="color:var(--text-dim);font-size:12px"> /10 TMDB</span>` : '';
  const yourRating = d.your_rating;
  const yourDate = d.date_watched || d.date_read;

  // Author bio (books)
  const authorBio = isBook && d.author_bio
    ? `<div class="detail-section">
        ${d.author_photo ? `<img src="${d.author_photo}" style="width:56px;height:56px;border-radius:50%;object-fit:cover;float:left;margin:0 12px 8px 0">` : ''}
        <div class="detail-section-label">About ${d.author||'the author'}</div>
        <p style="font-size:13px;color:var(--text-dim);line-height:1.6">${d.author_bio}</p>
        <div style="clear:both"></div>
       </div>` : '';

  return `
    ${backdrop}
    <div class="detail-body">
      ${coverImg}
      <div class="detail-title">${d.title}</div>
      <div class="detail-meta">${metaParts.join(' · ')} ${tmdbScore}</div>
      ${d.tagline ? `<p style="font-style:italic;color:var(--text-dim);font-size:13px;margin:8px 0 12px">"${d.tagline}"</p>` : ''}
      <div class="detail-genres">${genreTags}</div>

      ${yourRating || yourDate ? `<div class="detail-section" style="background:var(--bg-card);border-radius:4px;padding:12px;border:1px solid var(--border)">
        <div class="detail-section-label">Your history</div>
        ${yourRating ? `<div style="font-size:20px;color:var(--gold)">${'★'.repeat(Math.round(yourRating))}<span style="font-size:13px;color:var(--text-dim);margin-left:6px">${yourRating} stars</span></div>` : ''}
        ${yourDate ? `<div style="font-size:12px;color:var(--text-dim);margin-top:4px">${isBook?'Read':'Watched'}: ${yourDate?.slice(0,10)||''}</div>` : ''}
      </div>` : ''}

      <div class="detail-section">
        <div class="detail-section-label">${isBook ? 'Description' : 'Synopsis'}</div>
        <p style="font-size:13px;color:var(--text-dim);line-height:1.6">${d.overview || d.description || 'No description available.'}</p>
      </div>
      ${authorBio}
      ${castHtml ? `<div class="detail-section"><div class="detail-section-label">Cast</div><div class="detail-cast">${castHtml}</div></div>` : ''}
      ${streamingBadges(d.streaming)}

      <div class="detail-section">
        <div class="detail-section-label">Rate this</div>
        <div id="detail-stars" style="display:flex;gap:2px">${starBar(yourRating, itemId, d.title, d.media_type)}</div>
      </div>

      <div style="margin-top:16px;flex-wrap:wrap;display:flex;gap:8px;align-items:center">
        ${linkRow(d.links)}
      </div>
    </div>`;
}

function renderDirectorDetail(d) {
  const filmRows = (d.your_films||[]).slice(0,10).map(f => {
    const stars = f.rating ? '★'.repeat(Math.round(f.rating)) : '—';
    return `<tr>
      <td style="cursor:pointer;color:var(--cobalt)" onclick="searchAndShowDetail('${f.title?.replace(/'/g,"\\\\'")}','film')">${f.title||''}</td>
      <td style="color:var(--text-dim)">${f.year||''}</td>
      <td style="color:var(--gold)">${stars}</td>
    </tr>`;
  }).join('');

  return `<div class="detail-body">
    ${d.photo_url ? `<img src="${d.photo_url}" style="width:80px;height:80px;border-radius:50%;object-fit:cover;margin-bottom:16px;border:2px solid var(--border-dark)">` : ''}
    <div class="detail-title">${d.name}</div>
    <div class="detail-meta">${[d.birthday?.slice(0,4), d.place_of_birth].filter(Boolean).join(' · ')}</div>
    ${d.bio ? `<div class="detail-section"><p style="font-size:13px;color:var(--text-dim);line-height:1.6">${d.bio}</p></div>` : ''}
    <div class="detail-section">
      <div class="detail-section-label">Your watch history (${d.your_count} films · avg ${d.your_avg}★)</div>
      <table><tr><th>Film</th><th>Year</th><th>Your rating</th></tr>${filmRows}</table>
    </div>
    <div style="margin-top:16px;display:flex;gap:8px;flex-wrap:wrap">${linkRow(d.links)}</div>
  </div>`;
}

function renderArtistDetail(d) {
  const trackRows = (d.your_top_tracks||[]).map((t,i) =>
    `<tr><td style="color:var(--text-dim)">${i+1}</td><td>${t.title||t.track||''}</td><td style="color:var(--accent-music)">${(t.plays||0).toLocaleString()}</td></tr>`
  ).join('');
  const albumRows = (d.your_top_albums||[]).map(a =>
    `<tr><td>${a.title||a.album||''}</td><td style="color:var(--accent-music)">${(a.plays||0).toLocaleString()}</td></tr>`
  ).join('');

  return `<div class="detail-body">
    <div class="detail-title">${d.name}</div>
    <div class="detail-meta">${d.listeners ? Number(d.listeners).toLocaleString()+' Last.fm listeners' : ''}</div>
    ${d.tags?.length ? `<div style="display:flex;gap:6px;flex-wrap:wrap;margin:10px 0">${d.tags.map(t=>`<span class="detail-genre-tag">${t}</span>`).join('')}</div>` : ''}
    ${d.bio ? `<div class="detail-section"><p style="font-size:13px;color:var(--text-dim);line-height:1.6">${d.bio}</p></div>` : ''}
    <div class="detail-section">
      <div class="detail-section-label">Your listening — ${(d.your_plays||0).toLocaleString()} plays · ${d.your_hours||0}h</div>
    </div>
    ${trackRows ? `<div class="detail-section"><div class="detail-section-label">Your top tracks</div><table><tr><th></th><th>Track</th><th>Plays</th></tr>${trackRows}</table></div>` : ''}
    ${albumRows ? `<div class="detail-section"><div class="detail-section-label">Your top albums</div><table><tr><th>Album</th><th>Plays</th></tr>${albumRows}</table></div>` : ''}
    ${d.similar?.length ? `<div class="detail-section"><div class="detail-section-label">Similar artists</div><div style="font-size:13px;color:var(--cobalt)">${d.similar.map(s=>`<span style="cursor:pointer;margin-right:10px" onclick="showArtistDetail('${s}')">${s}</span>`).join('')}</div></div>` : ''}
    <div style="margin-top:16px;display:flex;gap:8px;flex-wrap:wrap">${linkRow(d.links)}</div>
  </div>`;
}

function showDetailFallback(body, itemId, title) {
  const q = encodeURIComponent((title || itemId.split(':').pop() || ''));
  body.innerHTML = `<div style="padding:24px">
    <div style="font-size:16px;font-weight:700;color:var(--text);margin-bottom:8px">${title || itemId}</div>
    <p style="font-size:13px;color:var(--text-dim);margin-bottom:16px;line-height:1.6">Not yet enriched — search directly:</p>
    <div style="display:flex;flex-direction:column;gap:8px">
      <a class="detail-link" href="https://www.imdb.com/find?q=${q}" target="_blank">🎬 IMDB ↗</a>
      <a class="detail-link" href="https://letterboxd.com/search/${q}/" target="_blank">🎞 Letterboxd ↗</a>
      <a class="detail-link" href="https://www.goodreads.com/search?q=${q}" target="_blank">📖 Goodreads ↗</a>
    </div>
  </div>`;
}

function wireDetailInteractions(d, itemId) {
  // nothing extra needed — stars are wired inline
}

async function rateDetailItem(itemId, title, stars, mediaType) {
  // Optimistic UI
  const container = document.getElementById('detail-stars');
  if (container) {
    container.querySelectorAll('.star').forEach((s,i) => {
      s.classList.toggle('lit', i < stars);
    });
  }
  await fetch('/api/culture/interact', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ item_key: itemKeyFromId(itemId, mediaType), media_type: mediaType, title, interact: 'rating', value: String(stars) }),
  });
}

function hoverDetailStars(el, n) {
  const container = el.closest('[id="detail-stars"]') || el.parentNode;
  container.querySelectorAll('.star').forEach((s,i) => { s.style.color = i < n ? 'var(--gold)' : 'var(--border-dark)'; });
}
function resetDetailStars(container, saved) {
  container.querySelectorAll('.star').forEach((s,i) => { s.style.color = i < saved ? 'var(--gold)' : 'var(--border-dark)'; });
}

function closeDetail() {
  document.getElementById('detail-overlay').classList.remove('open');
  document.body.style.overflow='';
  setTimeout(()=>{ document.getElementById('detail-content').innerHTML=''; }, 260);
}

document.addEventListener('keydown', e=>{ if(e.key==='Escape') closeDetail(); });

// ── Search-then-detail (rec cards click title) ────────────────────────────────
async function searchAndShowDetail(title, mediaType) {
  const body = openDetailOverlay(title);
  // Derive a key to try
  const mt = mediaType === 'tv' ? 'tv_show' : (mediaType === 'book' ? 'book' : 'film');
  // Try local API first with a title search
  try {
    const r = await fetch(`/api/culture/detail?key=${encodeURIComponent(mt+':title:'+title)}`);
    // 404 = not found by that key, try full search
    if (r.status === 404) {
      // Fall back to TMDB search via local server if running, else show fallback
      const sr = await fetch(`${API}/api/search?q=${encodeURIComponent(title)}&type=${mediaType}`)
        .catch(() => null);
      if (sr && sr.ok) {
        const results = await sr.json();
        if (results.length) {
          _lastResults.push(...results.filter(r=>!_lastResults.find(x=>x.id===r.id)));
          await showDetail(results[0].id, mt);
          return;
        }
      }
      showDetailFallback(body, title, title);
      return;
    }
    const d = await r.json();
    document.getElementById('detail-panel-title').textContent = d.title || title;
    body.innerHTML = renderStoryDetail(d, title);
  } catch(e) {
    showDetailFallback(body, title, title);
  }
}
