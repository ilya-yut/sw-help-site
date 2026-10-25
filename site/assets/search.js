(function(){
  var idx = window.SEARCH_INDEX || [];
  var q = (new URLSearchParams(location.search).get('q') || '').trim();
  var input = document.getElementById('site-q');
  var out = document.getElementById('site-results');
  if (!input || !out) return;
  input.value = q;
  function esc(s){return s.replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
  function rx(s){return s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');}
  if (!q) { out.innerHTML = '<p>Enter a search term above.</p>'; return; }
  var tokens = q.toLowerCase().split(/\s+/).filter(Boolean);
  var res = [];
  idx.forEach(function(d){
    var title = d.t.toLowerCase(), text = d.x.toLowerCase(), score = 0, ok = true;
    tokens.forEach(function(t){
      var inT = title.indexOf(t) >= 0, n = 0, p = -1;
      while ((p = text.indexOf(t, p + 1)) >= 0 && n < 20) n++;
      if (!inT && n === 0) ok = false;
      score += (inT ? 20 : 0) + n;
    });
    if (ok) res.push({d:d, s:score});
  });
  res.sort(function(a,b){return b.s - a.s || a.d.t.localeCompare(b.d.t);});
  if (!res.length) { out.innerHTML = '<p>No results for <b>' + esc(q) + '</b>.</p>'; return; }
  var hl = new RegExp('(' + tokens.map(rx).join('|') + ')', 'gi');
  var html = '<p>' + res.length + ' result' + (res.length === 1 ? '' : 's') + ' for <b>' + esc(q) + '</b></p><ul>';
  res.slice(0, 100).forEach(function(r){
    var d = r.d, low = d.x.toLowerCase(), pos = -1;
    for (var i = 0; i < tokens.length && pos < 0; i++) pos = low.indexOf(tokens[i]);
    var start = Math.max(0, pos - 80), snip = d.x.substr(start, 220);
    html += '<li><a href="' + d.u + '"><b>' + esc(d.t).replace(hl, '<mark>$1</mark>') + '</b></a>' +
            (d.c ? '<div class="trail">' + esc(d.c) + '</div>' : '') +
            '<div>' + (start > 0 ? '… ' : '') + esc(snip).replace(hl, '<mark>$1</mark>') + ' …</div></li>';
  });
  out.innerHTML = html + '</ul>';
})();
