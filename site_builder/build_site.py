#!/usr/bin/env python3
"""
build_site.py - turn a browser-saved copy of the Skywind help site
(126 x "Page.htm" + "Page_files" folders) into one clean, offline static site.

Usage:
    pip install beautifulsoup4
    python build_site.py help-full.zip --out site

Options:
    --domain help.skywind.com   the original site's domain (links to it become local)
    --single-image              keep only the largest image per picture (smaller output)
    --keep-carousel-dom         do not "reset" saved image carousels (use if galleries look broken)
    --no-csp                    do not add the Content-Security-Policy meta tag

What it does:
  * skips pages that contain videos (and never copies the .mp4 files)
  * rewrites links between pages to local files, removes WordPress admin bar,
    share/PDF buttons, login/ticket links, social links, emoji + Google Fonts calls
  * de-duplicates the thousands of identical JS/CSS/image copies into ./assets
  * builds index.html, category pages and an offline search page
  * writes build_report.txt (give this back to Claude) next to the script

Nothing is sent over the network. The input zip is never modified.
"""
import argparse, copy, hashlib, json, os, posixpath, re, shutil, sys, unicodedata, zipfile
from collections import Counter, defaultdict
from urllib.parse import unquote, quote, urlparse

try:
    from bs4 import BeautifulSoup, Comment
except ImportError:
    sys.exit("Missing dependency. Run:  pip install beautifulsoup4")

HERE = os.path.dirname(os.path.abspath(__file__))


# ----------------------------------------------------------------- helpers
def norm(name):
    return unicodedata.normalize("NFC", name.replace("\\", "/")).lower()


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


def path_only(value):
    """Drop ?query and a real #fragment.

    Saved filenames can contain '#', which the browser percent-encodes as %23.
    Unquoting first and then splitting on '#' throws away that filename.
    """
    path = value.split("?", 1)[0]
    if "#" in path:
        path = path.split("#", 1)[0]
    return path


def slugify(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "page"


def clean_stem(filename):
    stem, _ = os.path.splitext(filename)
    stem = re.sub(r"(_\d{3})?_[A-Za-z0-9]{4}$", "", stem)  # browser-added suffixes
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "file"
    return stem[:60]


class Source:
    """Read-only view over a zip file or a folder."""

    def __init__(self, path):
        self.index = {}  # normalized name -> real name
        self.zf = None
        self.root = None
        if os.path.isdir(path):
            self.root = path
            for dp, _, fs in os.walk(path):
                for f in fs:
                    real = os.path.relpath(os.path.join(dp, f), path).replace("\\", "/")
                    self.index[norm(real)] = real
        else:
            self.zf = zipfile.ZipFile(path)
            for info in self.zf.infolist():
                if info.is_dir():
                    continue
                real = info.filename
                if not (info.flag_bits & 0x800):  # not flagged UTF-8: try to repair cp437 mojibake
                    try:
                        real = real.encode("cp437").decode("utf-8")
                    except Exception:
                        pass
                self.index[norm(real)] = info.filename

    def names(self):
        return list(self.index.values())

    def find(self, name):
        return self.index.get(norm(name))

    def read(self, real):
        if self.zf:
            return self.zf.read(real)
        with open(os.path.join(self.root, real), "rb") as fh:
            return fh.read()


class Assets:
    def __init__(self, outdir):
        self.dir = os.path.join(outdir, "assets")
        os.makedirs(self.dir, exist_ok=True)
        self.by_hash = {}
        self.bytes_written = 0

    def add(self, data, orig_name):
        ext = os.path.splitext(orig_name)[1].lower()
        key = hashlib.sha1(data).hexdigest() + ext
        if key in self.by_hash:
            return self.by_hash[key]
        fname = f"{clean_stem(os.path.basename(orig_name))}-{key[:10]}{ext}"
        with open(os.path.join(self.dir, fname), "wb") as fh:
            fh.write(data)
        self.bytes_written += len(data)
        self.by_hash[key] = fname
        return fname


VIDEO_PAT = re.compile(r"<video\b|\.mp4|mediaelement|wp-video|youtube\.com/embed|player\.vimeo|<iframe\b", re.I)
REMOVE_SCRIPT_SRC = re.compile(r"admin-bar|hoverintent|wp-emoji|autologin|contact-form|recaptcha|gtag|analytics", re.I)
REMOVE_CSS_HREF = re.compile(r"admin-bar|dashicons|autologin", re.I)
DROP_LINK_RELS = {"alternate", "canonical", "shortlink", "edituri", "https://api.w.org/", "pingback",
                  "dns-prefetch", "preconnect", "profile", "prev", "next", "icon", "shortcut", "apple-touch-icon"}
CSP = ("default-src 'self'; img-src 'self' data: blob:; media-src 'self'; font-src 'self' data:; "
       "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; "
       "frame-src 'none'; object-src 'none'; base-uri 'self'; form-action 'self'")


# ------------------------------------------------------------------- pages
class Page:
    pass


def discover_pages(src):
    pages = []
    for real in src.names():
        low = real.lower()
        if not low.endswith((".htm", ".html")):
            continue
        if "_files/" in low.replace("\\", "/"):
            continue
        p = Page()
        p.real = real
        p.base = posixpath.dirname(real.replace("\\", "/"))
        p.stem = posixpath.splitext(posixpath.basename(real.replace("\\", "/")))[0]
        pages.append(p)
    pages.sort(key=lambda p: p.real.lower())
    return pages


def read_text(src, real):
    data = src.read(real)
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def canonical_path(soup, own_hosts):
    cand = []
    link = soup.find("link", rel=lambda r: r and "canonical" in (r if isinstance(r, list) else [r]))
    if link and link.get("href"):
        cand.append(link["href"])
    inp = soup.select_one("input.post-copy__input")
    if inp and inp.get("value"):
        cand.append(inp["value"])
    link = soup.find("link", rel=lambda r: r and "shortlink" in (r if isinstance(r, list) else [r]))
    for c in cand:
        u = urlparse(c)
        if u.netloc.lower() in own_hosts or not u.netloc:
            return unquote(u.path).strip("/")
    return None


def analyze(src, pages, own_hosts):
    for p in pages:
        html = read_text(src, p.real)
        soup = BeautifulSoup(html, "html.parser")
        t = soup.select_one("h2.post__title")
        p.title = (t.get_text(" ", strip=True) if t else (soup.title.get_text(strip=True) if soup.title else p.stem))
        p.url_path = canonical_path(soup, own_hosts)
        p.is_video = bool(VIDEO_PAT.search(html)) or bool(re.search(r"[–\-]\s*video\s*$", p.stem, re.I))
        p.has_content = soup.select_one(".post-right") is not None
        toc = soup.select_one("ul.category-list")
        p.toc_size = len(toc.select("li.cat-item")) + len(toc.select(".posts-list a")) if toc else 0
        p.toc_html = str(toc) if toc else ""
        del soup


def parse_toc(toc_html):
    """Return {cat_path: {name, parent, posts[], children[]}}, top-level cat paths (in order)."""
    soup = BeautifulSoup(toc_html, "html.parser")
    root = soup.find("ul")
    cats, top = {}, []

    def cat_key(href):
        path = unquote(urlparse(href).path).strip("/")
        return path[len("category/"):] if path.startswith("category/") else path

    def walk(li, parent):
        a = li.find("a", recursive=False)
        if not a:
            return None
        key = cat_key(a.get("href", ""))
        span = a.find("span")
        node = {"name": (span or a).get_text(" ", strip=True), "parent": parent, "posts": [], "children": []}
        cats[key] = node
        pl = li.find("div", class_="posts-list", recursive=False)
        if pl:
            for pa in pl.find_all("a"):
                path = unquote(urlparse(pa.get("href", "")).path).strip("/")
                if path:
                    node["posts"].append((path, pa.get_text(" ", strip=True)))
        ul = li.find("ul", class_="children", recursive=False)
        if ul:
            for child in ul.find_all("li", class_="cat-item", recursive=False):
                ck = walk(child, key)
                if ck is not None:
                    node["children"].append(ck)
        return key

    if root:
        for li in root.find_all("li", class_="cat-item", recursive=False):
            k = walk(li, None)
            if k is not None:
                top.append(k)
    return cats, top


def open_current_branch(soup, filename):
    """Mark only the table-of-contents branch that contains this page.

    The theme stylesheet shows a nested list when the parent <li> has
    current-cat-ancestor, and the page list when the <li> is current-cat
    or current-cat-parent. Everything else stays collapsed.
    """
    side = soup.select_one(".post-categoryes")
    if side is None or not filename:
        return
    target = None
    for a in side.select("a[href]"):
        if a.get("href") == filename:
            target = a
            break
    if target is None:
        return
    li = target.find_parent("li", class_="cat-item")
    if li is None:
        return
    classes = list(li.get("class") or [])
    if "current-cat" not in classes:
        li["class"] = classes + ["current-cat"]
    parent = target.parent
    parent_classes = parent.get("class") or [] if parent else []
    if "posts-list" in parent_classes:
        tcls = list(target.get("class") or [])
        if "this" not in tcls:
            target["class"] = tcls + ["this"]
    else:
        acls = list(target.get("class") or [])
        if "active" not in acls:
            target["class"] = acls + ["active"]
        target["aria-current"] = "page"
    node = li
    first = True
    while True:
        parent_li = node.find_parent("li", class_="cat-item")
        if parent_li is None:
            break
        pcls = list(parent_li.get("class") or [])
        for name in ("current-cat-ancestor",) + (("current-cat-parent",) if first else ()):
            if name not in pcls:
                pcls.append(name)
        parent_li["class"] = pcls
        first = False
        node = parent_li


# ------------------------------------------------------------------ builder
class Builder:
    def __init__(self, args):
        self.args = args
        self.own_hosts = {args.domain.lower(), "www." + args.domain.lower()}
        self.src = Source(args.input)
        self.out = args.out
        self.stats = Counter()
        self.missing_res = Counter()
        self.unresolved = Counter()
        self.remote_css = Counter()
        self.missing_uploads = Counter()
        self.res_cache = {}
        self.fonts_ok = os.path.isdir(os.path.join(HERE, "fonts"))
        self.search = []
        self.template = None

    # ----- resources
    def asset_for(self, page_base, rel):
        rel = unquote(path_only(rel))
        full = posixpath.normpath(posixpath.join(page_base, rel)) if page_base else posixpath.normpath(rel)
        key = norm(full)
        if key in self.res_cache:
            return self.res_cache[key]
        real = self.src.find(full)
        if not real:
            self.res_cache[key] = None
            self.missing_res[full] += 1
            return None
        data = self.src.read(real)
        if real.lower().endswith(".css"):
            text = data.decode("utf-8-sig", errors="replace")
            text = self.process_css(text, posixpath.dirname(real), prefix="")
            data = text.encode("utf-8")
        name = self.assets.add(data, real)
        self.res_cache[key] = name
        return name

    CSS_URL = re.compile(r"""url\(\s*(['"]?)(.*?)\1\s*\)""", re.I | re.S)
    CSS_IMPORT_STR = re.compile(r"""@import\s+(['"])(?:https?:)?//[^'"]*\1[^;]*;""", re.I)

    def process_css(self, text, base, prefix):
        text = self.CSS_IMPORT_STR.sub("", text)

        def repl(m):
            val = m.group(2).strip()
            if not val or val.startswith("data:") or val.startswith("#"):
                return m.group(0)
            if re.match(r"(https?:)?//", val, re.I):
                self.remote_css[urlparse(val if not val.startswith("//") else "http:" + val).netloc] += 1
                return 'url("data:,")'
            name = self.asset_for(base, val)
            if not name:
                return m.group(0)
            frag = ""
            if "#" in val:
                frag = "#" + val.split("#", 1)[1]
            return f'url("{prefix}{quote(name)}{frag}")'

        return self.CSS_URL.sub(repl, text)

    def local_ref(self, page, value):
        """If value points into this page's *_files folder, return rewritten 'assets/...' or None."""
        raw = path_only(value)
        unq = unquote(raw)
        pref = page.stem + "_files/"
        if not norm(unq).startswith(norm(pref)):
            return None
        name = self.asset_for(page.base, raw)
        return ("assets/" + quote(name)) if name else None

    # ----- links
    def map_href(self, href):
        h = href.strip()
        if not h or h.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            return "keep", None
        u = urlparse(h)
        internal = (u.scheme in ("http", "https") and u.netloc.lower() in self.own_hosts) or \
                   (not u.scheme and not u.netloc and h.startswith("/"))
        if not internal:
            return "keep", None
        path = unquote(u.path).strip("/")
        frag = ("#" + u.fragment) if u.fragment else ""
        if path == "":
            return "new", "index.html" + frag
        if path.startswith("category/"):
            key = path[len("category/"):]
            if key in self.cats:
                return "new", self.cat_file(key) + frag
            return "drop", "category"
        if path in self.slugmap:
            return "new", self.slugmap[path] + frag
        if path.startswith("wp-content/"):
            return "upload", path
        return "drop", path

    @staticmethod
    def cat_file(key):
        return "cat-" + key.replace("/", "--") + ".html"

    # ----- page transformation
    def transform(self, soup, page):
        args = self.args
        for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
            c.extract()

        # --- remove WordPress/admin/third-party bits
        for sel in ("#wpadminbar", ".pdfprnt-buttons", ".post-copy", "li.menu-logout", "ul.footer-soc",
                    "style#admin-bar-inline-css", "script#wp-emoji-settings", "script[type=module]",
                    "noscript"):
            for el in soup.select(sel):
                el.decompose()
        for s in soup.find_all("script"):
            src = s.get("src")
            sid = s.get("id", "")
            if src and REMOVE_SCRIPT_SRC.search(unquote(src)):
                s.decompose()
            elif not src and re.search(r"contact-form-7|autologin|wp-emoji", sid):
                s.decompose()
        for l in soup.find_all("link"):
            rel = {r.lower() for r in (l.get("rel") or [])}
            href = unquote(l.get("href", ""))
            if "stylesheet" in rel:
                if REMOVE_CSS_HREF.search(href) or "fonts.googleapis" in href:
                    l.decompose()
            elif rel & DROP_LINK_RELS:
                l.decompose()
        for st in soup.find_all("style"):
            if "fonts.googleapis" in (st.string or st.get_text()):
                st.decompose()
        for a in soup.find_all("a"):
            if re.search(r"submit a ticket", a.get_text(" ", strip=True), re.I):
                a.decompose()

        head = soup.head
        if head is not None:
            if self.fonts_ok:
                head.append(BeautifulSoup('<link rel="stylesheet" href="assets/fonts.css">', "html.parser"))
            head.append(BeautifulSoup('<link rel="icon" href="data:,">', "html.parser"))
            if not args.no_csp:
                head.insert(0, BeautifulSoup(f'<meta http-equiv="Content-Security-Policy" content="{CSP}">',
                                             "html.parser"))

        # --- fancybox: full-size link -> best local picture
        for a in soup.select("a[data-fancybox]"):
            img = a.find("img")
            if not img:
                continue
            best = img.get("src")
            ss = img.get("srcset")
            if ss:
                bw = -1
                for cand in ss.split(","):
                    bits = cand.strip().split()
                    if not bits:
                        continue
                    w = int(bits[1][:-1]) if len(bits) > 1 and bits[1].endswith("w") and bits[1][:-1].isdigit() else 0
                    if w > bw:
                        bw, best = w, bits[0]
            if best:
                a["href"] = best
        # --- single image mode
        if args.single_image:
            for img in soup.find_all("img", srcset=True):
                best, bw = img.get("src"), -1
                for cand in img["srcset"].split(","):
                    bits = cand.strip().split()
                    if not bits:
                        continue
                    w = int(bits[1][:-1]) if len(bits) > 1 and bits[1].endswith("w") and bits[1][:-1].isdigit() else 0
                    if w > bw:
                        bw, best = w, bits[0]
                if best:
                    img["src"] = best
                del img["srcset"]
                if img.has_attr("sizes"):
                    del img["sizes"]

        # --- reset saved carousels to their pre-JS markup
        if not args.keep_carousel_dom:
            for g in soup.select(".owl-carousel"):
                for c in g.select(".owl-item.cloned"):
                    c.decompose()
                for n in g.select(".owl-nav, .owl-dots"):
                    n.decompose()
                so = g.find(class_="owl-stage-outer")
                if so:
                    for it in so.select(".owl-item"):
                        it.unwrap()
                    stage = so.find(class_="owl-stage")
                    if stage:
                        stage.unwrap()
                    so.unwrap()
                g["class"] = [c for c in g.get("class", []) if c == "owl-carousel" or not c.startswith("owl-")]
                g.attrs.pop("style", None)
            # Theme scripts.js fills an existing .image-caption next to the carousel.
            # It does not create that element, so the saved caption has to stay.

        # --- local files (images, css, js)
        for tag in soup.find_all(True):
            for attr, val in list(tag.attrs.items()):
                if isinstance(val, str):
                    if attr in ("srcset", "data-srcset"):
                        parts = []
                        for cand in val.split(","):
                            bits = cand.strip().split()
                            if not bits:
                                continue
                            new = self.local_ref(page, bits[0])
                            bits[0] = new or bits[0]
                            parts.append(" ".join(bits))
                        tag[attr] = ", ".join(parts)
                    elif attr == "style":
                        tag[attr] = self.process_css(val, page.base, prefix="assets/")
                    else:
                        new = self.local_ref(page, val)
                        if new:
                            tag[attr] = new
        for st in soup.find_all("style"):
            txt = st.string if st.string is not None else st.get_text()
            if "url(" in txt or "@import" in txt:
                st.string = self.process_css(txt, page.base, prefix="assets/")

        # --- table of contents: drop entries that do not exist offline
        for li in soup.select("li.cat-item"):
            a = li.find("a", recursive=False)
            if a is None:
                continue
            path = unquote(urlparse(a.get("href", "")).path).strip("/")
            key = path[len("category/"):] if path.startswith("category/") else path
            if key not in self.cats:
                li.decompose()
        for a in soup.select(".posts-list a"):
            kind, _ = self.map_href(a.get("href", ""))
            if kind != "new":
                a.decompose()

        # --- links between pages
        for a in soup.find_all("a", href=True):
            kind, val = self.map_href(a["href"])
            if kind == "new":
                a["href"] = val
            elif kind == "drop":
                self.unresolved[val] += 1
                li = a.find_parent("li", class_="menu-item")
                if li is not None:
                    li.decompose()
                else:
                    a.unwrap()
            elif kind == "upload":
                self.missing_uploads[val] += 1
            elif a.get("target") == "_blank":
                a["rel"] = "noopener noreferrer"

        # --- search form -> local search page
        for form in soup.select(".post-search form, .questions form"):
            form["action"] = "search.html"
            form["method"] = "get"
            inp = form.find("input")
            if inp:
                inp["name"] = "q"
        return soup

    # ----- generated pages
    def make_page(self, title, crumbs, content_html, filename):
        soup = copy.deepcopy(self.template)
        for el in soup.select("li.cat-item, .category-list a, .posts-list a"):
            el["class"] = [c for c in el.get("class", []) if c not in
                           ("active", "current-cat", "current-cat-parent", "current-cat-ancestor", "this")]
            el.attrs.pop("aria-current", None)
        open_current_branch(soup, filename)
        if soup.title:
            soup.title.string = title
        bc = soup.select_one("ul.breadcrumbs")
        if bc:
            bc.clear()
            items = [("Home", "index.html")] + crumbs
            for i, (txt, href) in enumerate(items):
                li = soup.new_tag("li")
                if href and i < len(items) - 1:
                    a = soup.new_tag("a", href=href)
                    a.string = txt
                    li.append(a)
                else:
                    li.string = txt
                bc.append(li)
        h = soup.select_one("h2.post__title")
        if h:
            h.string = title
        pr = soup.select_one(".post-right")
        if pr:
            pr.clear()
            pr.append(BeautifulSoup(content_html, "html.parser"))
        with open(os.path.join(self.out, filename), "w", encoding="utf-8") as fh:
            fh.write(str(soup))

    def tree_html(self, keys, depth=0):
        out = ["<ul>"]
        for k in keys:
            c = self.cats[k]
            out.append(f'<li><a href="{self.cat_file(k)}"><strong>{esc(c["name"])}</strong></a>')
            posts = [(p, t) for p, t in c["posts"] if p in self.slugmap]
            if posts:
                out.append("<ul>" + "".join(f'<li><a href="{self.slugmap[p]}">{esc(self.titles.get(p, t))}</a></li>'
                                            for p, t in posts) + "</ul>")
            if c["children"]:
                out.append(self.tree_html(c["children"], depth + 1))
            out.append("</li>")
        out.append("</ul>")
        return "".join(out)

    # ----- main
    def run(self):
        args = self.args
        os.makedirs(self.out, exist_ok=True)
        self.assets = Assets(self.out)
        pages = discover_pages(self.src)
        if not pages:
            sys.exit("No .htm pages found in the input.")
        print(f"Found {len(pages)} pages. Analyzing...")
        analyze(self.src, pages, self.own_hosts)

        excluded = [p for p in pages if p.is_video]
        home = [p for p in pages if p.url_path == "" and not p.is_video]
        kept = [p for p in pages if not p.is_video and p not in home]

        # file names / url map
        self.slugmap, used = {}, set()
        for p in kept:
            path = p.url_path or slugify(p.title)
            fn = path.replace("/", "--") + ".html"
            i = 2
            while fn.lower() in used or fn in ("index.html", "search.html"):
                fn = f"{path.replace('/', '--')}-{i}.html"
                i += 1
            used.add(fn.lower())
            p.out_name = fn
            self.slugmap[path] = fn
        self.titles = {(p.url_path or slugify(p.title)): p.title for p in kept}

        # category tree (from the most complete TOC), pruned to what exists
        best = max(pages, key=lambda p: p.toc_size)
        cats, top = parse_toc(best.toc_html) if best.toc_html else ({}, [])

        def has_pages(k):
            c = cats[k]
            return any(p in self.slugmap for p, _ in c["posts"]) or any(has_pages(ch) for ch in c["children"])

        live = {k for k in cats if has_pages(k)}
        self.cats = {k: dict(v, children=[c for c in v["children"] if c in live]) for k, v in cats.items() if k in live}
        top = [k for k in top if k in live]
        in_toc = {p for c in self.cats.values() for p, _ in c["posts"]}

        # transform every kept page
        for i, p in enumerate(kept, 1):
            if i % 10 == 0 or i == len(kept):
                print(f"  page {i}/{len(kept)}")
            soup = BeautifulSoup(read_text(self.src, p.real), "html.parser")
            self.transform(soup, p)
            pr = soup.select_one(".post-right")
            text = ""
            if pr:
                tmp = copy.copy(pr)
                for bad in tmp.select("script, style"):
                    bad.decompose()
                text = re.sub(r"\s+", " ", tmp.get_text(" ", strip=True))[:25000]
            trail = " > ".join(li.get_text(" ", strip=True) for li in soup.select("ul.breadcrumbs li")[1:])
            self.search.append({"t": p.title, "u": p.out_name, "c": trail, "x": text})
            if self.template is None and pr is not None:
                self.template = copy.deepcopy(soup)
            with open(os.path.join(self.out, p.out_name), "w", encoding="utf-8") as fh:
                fh.write(str(soup))
            p.written = True
            del soup

        if self.template is None:
            sys.exit("No page with a content area was found; cannot build index/search pages.")

        # The saved home page is the product-card layout. Keep it as index.html.
        self.wrote_home = False
        if home:
            p = next((h for h in home if h.stem.lower() == "main"), home[0])
            p.out_name = "index.html"
            soup = BeautifulSoup(read_text(self.src, p.real), "html.parser")
            self.transform(soup, p)
            for card in soup.select(".main-categorys .category_coming-soon"):
                card.decompose()
            for a in list(soup.select(".main-categorys a.category-top")):
                href = (a.get("href") or "").replace("\\", "/").lower()
                if href.endswith("cat-skyaps.html") or href.rstrip("/").endswith("/skyaps"):
                    card = a.find_parent("div", class_="category")
                    if card is not None:
                        card.decompose()
            for block in soup.select(".main-categorys .articles-wr"):
                heading = block.find_previous_sibling("h2")
                if heading and "latest articles" in heading.get_text(" ", strip=True).lower():
                    heading.decompose()
                block.decompose()
            area = soup.select_one(".main-categorys") or soup.body
            text = ""
            if area is not None:
                tmp = copy.copy(area)
                for bad in tmp.select("script, style"):
                    bad.decompose()
                text = re.sub(r"\s+", " ", tmp.get_text(" ", strip=True))[:25000]
            self.search.append({"t": "Home", "u": "index.html", "c": "", "x": text})
            with open(os.path.join(self.out, "index.html"), "w", encoding="utf-8") as fh:
                fh.write(str(soup))
            self.wrote_home = True
            del soup

        # generated pages: index (only if the export had no home page), categories, search
        orphans = [p for p in kept if (p.url_path or slugify(p.title)) not in in_toc]
        if not self.wrote_home:
            body = "<p>Browse the knowledge base by topic, or use the search.</p>" + self.tree_html(top)
            if orphans:
                body += "<h4>Other pages</h4><ul>" + "".join(
                    f'<li><a href="{p.out_name}">{esc(p.title)}</a></li>' for p in orphans) + "</ul>"
            self.make_page("Skywind Knowledge Portal", [], body, "index.html")
        for k, c in self.cats.items():
            chain, cur = [], k
            while cur is not None:
                chain.append(cur)
                par = self.cats[cur]["parent"]
                cur = par if par in self.cats else None
            crumbs = [(self.cats[x]["name"], self.cat_file(x)) for x in reversed(chain)]
            body = ""
            if c["children"]:
                body += "<h4>Sections</h4>" + self.tree_html(c["children"])
            posts = [(p, t) for p, t in c["posts"] if p in self.slugmap]
            if posts:
                body += "<h4>Pages</h4><ul>" + "".join(
                    f'<li><a href="{self.slugmap[p]}">{esc(self.titles.get(p, t))}</a></li>' for p, t in posts) + "</ul>"
            self.make_page(c["name"], crumbs, body, self.cat_file(k))
        search_body = SEARCH_BODY
        self.make_page("Search", [("Search", None)], search_body, "search.html")

        # search assets
        idx = json.dumps(self.search, ensure_ascii=False).replace("</", "<\\/")
        with open(os.path.join(self.assets.dir, "search-index.js"), "w", encoding="utf-8") as fh:
            fh.write("window.SEARCH_INDEX=" + idx + ";")
        with open(os.path.join(self.assets.dir, "search.js"), "w", encoding="utf-8") as fh:
            fh.write(SEARCH_JS)
        # fonts
        if self.fonts_ok:
            self.write_fonts()
        with open(os.path.join(self.out, "README.txt"), "w", encoding="utf-8") as fh:
            fh.write(README)

        self.report(pages, kept, excluded, home, orphans)

    def write_fonts(self):
        fdir = os.path.join(HERE, "fonts")
        dst = os.path.join(self.assets.dir, "fonts")
        os.makedirs(dst, exist_ok=True)
        css = []
        for f in sorted(os.listdir(fdir)):
            m = re.match(r"raleway-latin-(\d+)-normal\.woff2$", f)
            if not m:
                continue
            shutil.copy(os.path.join(fdir, f), os.path.join(dst, f))
            css.append("@font-face{font-family:'Raleway';font-style:normal;font-display:swap;"
                       f"font-weight:{m.group(1)};src:url('fonts/{f}') format('woff2');}}")
        # Arrow images (img/slide-left.png, img/slide-right.png) were not in the browser save.
        css.append(ARROW_CSS)
        with open(os.path.join(self.assets.dir, "fonts.css"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(css))

    # ----- report
    def report(self, pages, kept, excluded, home, orphans):
        out = self.out
        L = []
        w = L.append
        total = 0
        nfiles = 0
        for dp, _, fs in os.walk(out):
            for f in fs:
                total += os.path.getsize(os.path.join(dp, f))
                nfiles += 1
        w("=== BUILD REPORT ===")
        home_note = "original product cards" if self.wrote_home else f"generated ({len(home)} saved home page(s) unused)"
        w(f"Input pages: {len(pages)}   Built pages: {len(kept)}   Skipped (video): {len(excluded)}   Home page: {home_note}")
        w(f"Output: {nfiles} files, {human(total)}   (assets: {len(self.assets.by_hash)} unique files, {human(self.assets.bytes_written)})")
        w(f"Options: single_image={self.args.single_image} keep_carousel_dom={self.args.keep_carousel_dom} csp={not self.args.no_csp} fonts={'bundled' if self.fonts_ok else 'MISSING (fonts/ folder not found next to script)'}")
        w("")
        w("--- Skipped pages (contain video) ---")
        for p in excluded:
            w("  " + p.stem)
        if not excluded:
            w("  none")
        w("")
        w(f"--- Pages not listed in the category tree (shown under 'Other pages'): {len(orphans)} ---")
        for p in orphans[:25]:
            w("  " + p.title)
        w("")
        w(f"--- Categories built: {len(self.cats)} ---")
        w("")
        w("--- Internal links that point to pages not in this build (links removed, text kept) ---")
        tot = sum(self.unresolved.values())
        w(f"  total: {tot}")
        for k, v in self.unresolved.most_common(25):
            w(f"  {v:5}x  /{k}")
        w("")
        w("--- Links to uploaded files (PDF/images) that are NOT in the export (will be dead) ---")
        w(f"  total: {sum(self.missing_uploads.values())}")
        for k, v in self.missing_uploads.most_common(15):
            w(f"  {v:5}x  /{k}")
        w("")
        w("--- Files referenced by pages but missing from the zip ---")
        w(f"  distinct: {len(self.missing_res)}")
        for k, v in self.missing_res.most_common(15):
            w(f"  {v:5}x  {k}")
        w("")
        w("--- Remote URLs found inside CSS (neutralised) ---")
        for k, v in self.remote_css.most_common(15):
            w(f"  {v:5}x  {k}")
        if not self.remote_css:
            w("  none")
        w("")

        # self-check of the output
        bad = Counter()
        ext_links = Counter()
        res_re = re.compile(r"""<(?:script|img|source|iframe|video|audio|embed|object|link)\b[^>]*?\b(?:src|srcset|href)=["']\s*((?:https?:)?//[^"'\s]+)""", re.I)
        a_re = re.compile(r"""<a\b[^>]*?\bhref=["'](https?://[^"']+)""", re.I)
        css_re = re.compile(r"""url\(\s*["']?((?:https?:)?//[^)"']+)""", re.I)
        for f in os.listdir(out):
            if not f.endswith(".html"):
                continue
            t = open(os.path.join(out, f), encoding="utf-8").read()
            for m in res_re.finditer(t):
                bad[urlparse(m.group(1) if not m.group(1).startswith("//") else "http:" + m.group(1)).netloc] += 1
            for m in css_re.finditer(t):
                bad["(css) " + urlparse(m.group(1)).netloc] += 1
            for m in a_re.finditer(t):
                ext_links[urlparse(m.group(1)).netloc] += 1
        w("--- SELF-CHECK: external resources still loaded by pages (must be empty) ---")
        if bad:
            for k, v in bad.most_common(20):
                w(f"  {v:5}x  {k}")
        else:
            w("  none - pages load nothing from the internet")
        w("")
        w("--- External hyperlinks (clickable only, no automatic requests; will not open offline) ---")
        for k, v in ext_links.most_common(15):
            w(f"  {v:5}x  {k}")
        w("")
        w("--- Site-specific strings inside bundled JS/CSS (may hide online calls) ---")
        found = False
        for f in sorted(os.listdir(self.assets.dir)):
            if f.endswith((".js", ".css")) and f not in ("search.js", "search-index.js", "fonts.css"):
                t = open(os.path.join(self.assets.dir, f), encoding="utf-8", errors="ignore").read()
                hits = {s: t.count(s) for s in (self.args.domain, "admin-ajax", "wp-json") if s in t}
                if hits:
                    found = True
                    w(f"  {f}: {hits}")
        if not found:
            w("  none")
        report = "\n".join(L)
        with open(os.path.join(HERE, "build_report.txt"), "w", encoding="utf-8") as fh:
            fh.write(report)
        print("\n" + report)
        print(f"\nSite written to: {os.path.abspath(out)}")
        print(f"Report saved to: {os.path.join(HERE, 'build_report.txt')}  <- paste this back to Claude")


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


SEARCH_BODY = """
<form method="get" action="search.html" style="margin:0 0 24px">
  <input id="site-q" name="q" type="text" placeholder="Type your search terms here" autofocus
         style="width:70%;max-width:520px;padding:8px 12px;border:1px solid #ccc;border-radius:4px">
  <button type="submit" style="padding:8px 18px;border:0;border-radius:4px;background:#1a73e8;color:#fff;cursor:pointer">Search</button>
</form>
<div id="site-results"></div>
<style>
 #site-results li{margin:0 0 18px;list-style:none} #site-results ul{padding:0}
 #site-results .trail{color:#777;font-size:13px} #site-results mark{background:#ffe58a}
</style>
<script src="assets/search-index.js"></script>
<script src="assets/search.js"></script>
"""

SEARCH_JS = r"""(function(){
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
"""

ARROW_CSS = """
.owl-carousel .owl-prev, .owl-carousel .owl-next {
  background: rgba(30, 26, 22, 0.55);
}
.owl-carousel .owl-prev:after, .owl-carousel .owl-next:after {
  content: "";
  position: absolute;
  top: 50%;
  left: 50%;
  width: 12px;
  height: 12px;
  border-top: 3px solid #fff;
  border-right: 3px solid #fff;
}
.owl-carousel .owl-prev:after { transform: translate(-30%, -50%) rotate(-135deg); }
.owl-carousel .owl-next:after { transform: translate(-70%, -50%) rotate(45deg); }

/* The saved arrow image (img/category-list_img1.png) was not in the export.
   Point right when collapsed, down when this branch is open. */
.category-list_css li > a::before {
  background: none !important;
  width: 7px;
  height: 7px;
  border-top: 2px solid #1e1a16;
  border-right: 2px solid #1e1a16;
  box-sizing: border-box;
  transform: rotate(45deg);
}
.category-list_css li.current-cat-ancestor > a::before,
.category-list_css li > a.active::before {
  transform: rotate(135deg);
}
/* Card photos (pic1.jpg and the others) were not in the export. */
.main-categorys .category-top { background-color: #efefef; }
"""

README = """Skywind Knowledge Portal - offline copy
=======================================

This folder is a static website. There is nothing to install.

1. Copy the whole folder to a web server (nginx, Apache, IIS or any static file host),
   for example into the server's document root, or into a sub-folder.
2. Open  http://<server>/index.html  in Chrome, Edge or Firefox (JavaScript enabled).
3. Test: open index.html, click through the menu, and try the search page.

Notes
- All links are relative, so the folder can be served from the root or from a sub-path.
- No internet access is required. The pages load no external fonts, scripts or images.
- Every page carries a Content-Security-Policy that only allows files from this site.
- Needs only standard MIME types: .html .css .js .jpg .png .svg .woff2
- No server-side code, no database, no executables.
- Quick local test without a web server: double-click index.html (search also works this way).
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="help-full.zip or the extracted folder")
    ap.add_argument("--out", default="site")
    ap.add_argument("--domain", default="help.skywind.com")
    ap.add_argument("--single-image", action="store_true")
    ap.add_argument("--keep-carousel-dom", action="store_true")
    ap.add_argument("--no-csp", action="store_true")
    args = ap.parse_args()
    if os.path.exists(args.out):
        sys.exit(f"Output folder '{args.out}' already exists. Delete it or choose another with --out.")
    Builder(args).run()


if __name__ == "__main__":
    main()
