# Handover: Offline Help Site (Skywind Knowledge Portal)

Status date: 2026-10-25. Written for continuing in Cursor.

## 1. Goal

A WordPress help site (https://help.skywind.com) must be delivered to a client whose environment has **no internet access** and strict security policies. The client wants hierarchical pages with text, images and navigation, hosted inside their network.

**Deliverable:** a zip of static files (HTML/CSS/JS/images) that the client's basis team unzips onto any web server (nginx / Apache / IIS). No installer, no database, no server-side code, no executables.

## 2. Decisions made

| Topic | Decision |
|---|---|
| Architecture | Static site. No backend. |
| Source material | Browser-saved pages ("Save page as, complete"), not a WP export. 126 `.htm` + a `<Title>_files/` folder per page. |
| Packaging | Plain zip + `README.txt`. No installer. Docker only if the client asks. |
| Search | Own small client-side search (JSON index in a `.js` file + `search.html`), works offline and from `file://`. Pagefind was the earlier idea but was replaced. |
| Fonts | Raleway bundled locally (from `@fontsource/raleway`, latin subset) instead of Google Fonts. |
| Video pages | **User instruction: do not include pages that contain videos.** They and their `.mp4` files are skipped. |
| Security | Every page gets a restrictive Content-Security-Policy `<meta>` (self only). Build report self-checks that nothing loads externally. |

## 3. What the scan of the real export showed

`scan_site.py` was run by the user on `help-full.zip` (543 MB zip, 841.9 MB unpacked). Findings:

- 13,204 files. 126 HTML (`.htm`), 0 PHP, no `wp-content`/`wp-json` => not a WP export.
- 6,871 `.jpg` (652.9 MB), 1,647 `.png` (15 MB), 3,036 `.js` (64 MB), 1,390 `.css` (40 MB), 2 `.mp4` (59 MB), 132 `.svg`. **No font files** were saved.
- Every page carries its own copy of jQuery, Bootstrap, theme CSS etc. (massive duplication; images appear in pairs with identical sizes).
- Own domain: `help.skywind.com`, ~32,217 absolute references to it (page links, category links, upload URLs).
- External domains seen: most are only comments/patterns inside JS libraries (jqueryui.com, github.com, getbootstrap.com, popper.js.org, YouTube/Vimeo/Facebook patterns in fancybox/owl). Real external loads: Google Fonts (`@import` in every page), WordPress emoji scripts (`s.w.org`, `cdn.jsdelivr.net`), plus footer links (LinkedIn, YouTube, SAP partner profile on `pf-prod-sapit-partner-prod.cfapps.eu10.hana.ondemand.com`, which is only an `<a href>`, not a request).
- Two video pages exist: "Potential SoD Violations (by SoD Rules) – Video" and "Actual SoD Violations (by SoD Rules) – Video" (each with an mp4 around 30 MB, mediaelement player).

## 4. Structure of the saved pages (from 2 sample pages)

Samples seen: `Administration – Overview.htm`, `Cross Reference Violations – Report Usage.htm`. Video pages were **not** seen.

- Saved **after JS ran** (DOM snapshot). Notable: `owl-carousel` galleries already initialised (`owl-loaded`, `owl-stage-outer > owl-stage > owl-item`, cloned items, generated `owl-nav`/`owl-dots`, generated `.image-caption`).
- `<header>` with menu (Products > 4C / SoDA category links, Contact -> `/submit-a-ticket/`, logout link with `menu-logout`).
- `ul.breadcrumbs`, `h2.post__title`, share box `.post-copy`, PDF button `.pdfprnt-buttons`, search form `.post-search form` (GET `https://help.skywind.com/?s=`).
- **Full table of contents in every page**: `ul.category-list` > `li.cat-item` > `a` (category URL `/category/<a>/<b>/`), `div.posts-list` (post links `/<slug>/`), nested `ul.children`. This is the hierarchy source.
- Content in `.post-right`. Images: `<a data-fancybox href="http://help.skywind.com/wp-content/uploads/..."><img src="<Title>_files/x_002_XXXX.jpg" srcset="... 5 sizes ...">`. The `href` points to the remote original, so it is rewritten to the largest local image.
- Page URL available from `<link rel="canonical">` and from `input.post-copy__input` value (used to name files and resolve links).
- Leftovers from being saved while logged in: `#wpadminbar`, admin-bar CSS/JS (`html{margin-top:32px}`), autologin popup script.
- Footer: logo, `ul.footer-soc` (LinkedIn/YouTube/SAP), product links, contact info (mailto/tel).
- Scripts present: WP jQuery + jquery-migrate + jQuery UI parts, theme jQuery 3.2.1 (loaded twice on the original too), popper, bootstrap, formstyler, clipboard, mask, fancybox, owl.carousel, `scripts*.js` (theme, **contents not yet inspected**), emoji, hoverintent, admin-bar.

## 5. Files delivered so far

| File | Purpose |
|---|---|
| `scan_site.py` | Scans zip/folder, reports file stats, external domains, own-domain refs. Already run. |
| `site_builder.zip` containing `site_builder/build_site.py` + `site_builder/fonts/*.woff2` | The converter. Fonts folder must stay next to the script. |

## 6. How `build_site.py` works

Run:

```
pip install beautifulsoup4
python build_site.py <help-full.zip or folder> --out site
```

Options: `--domain help.skywind.com`, `--single-image` (keep only largest srcset image), `--keep-carousel-dom` (skip carousel reset), `--no-csp`. Refuses to run if `--out` exists. Writes `build_report.txt` next to the script.

Pipeline:

1. **Source** abstraction over zip or folder (normalised lookup, repairs cp437 zip names).
2. **Pass 1 (`analyze`)**: for each page get title, canonical path, `is_video`, TOC size and TOC html. `is_video` = regex `<video|.mp4|mediaelement|wp-video|youtube.com/embed|player.vimeo|<iframe` in the HTML, or filename ending in "– Video". Pages with canonical path `""` are treated as the old home and replaced by a generated `index.html`.
3. **Global tree**: the most complete TOC is parsed (`parse_toc`) into categories/posts, pruned to categories that contain at least one kept page.
4. **Pass 2 (`transform`)** per kept page:
   - strip comments, admin bar, share/PDF, logout, social list, noscript, module/emoji/autologin/contact-form scripts, admin-bar/dashicons/autologin CSS, WP `<link rel=...>` junk, Google Fonts `<style>`/`<link>`, any anchor reading "Submit a ticket";
   - add `assets/fonts.css`, data-URI icon, CSP meta;
   - fancybox `href` -> largest local image from the child `<img>`;
   - optional single-image mode;
   - carousel reset: remove `.owl-item.cloned`, `.owl-nav/.owl-dots`, unwrap `owl-stage-outer/owl-stage/owl-item`, drop owl state classes and inline style, remove generated `.thumbs-left-cont .image-caption` (**assumption**: theme JS regenerates it);
   - rewrite every attribute pointing into `<Title>_files/` (incl. `srcset`, `style`, `<style>` url()) to `assets/<name>-<sha1_10>.<ext>` (content-hash dedupe; CSS files are rewritten first so their `url()` point to sibling assets; remote CSS urls become `url("data:,")`);
   - prune TOC entries (categories/posts that do not exist offline);
   - rewrite internal links: `/` -> `index.html`, `/category/a/b/` -> `cat-a--b.html`, `/<slug>/` -> `<slug>.html`; unresolvable internal links are unwrapped (menu items removed); upload links not in export are left and reported;
   - search form -> `search.html?q=`.
5. **Generated pages** (cloned from the first processed page as a template): `index.html` (tree of categories and pages plus "Other pages" for pages missing from the TOC), `cat-*.html` per category, `search.html`.
6. **Search**: `assets/search-index.js` (`window.SEARCH_INDEX=[{t,u,c,x}]`) and `assets/search.js` (all tokens must match, title weighted, highlighted snippets).
7. **Report** with counts, skipped pages, orphans, unresolved links, missing resources, remote CSS URLs, a **self-check** for external resources still loaded by pages (must be empty), external hyperlinks, and site-specific strings (`help.skywind.com`, `admin-ajax`, `wp-json`) left in bundled JS/CSS.

Output layout is flat: `index.html`, `<slug>.html`, `cat-*.html`, `search.html`, `README.txt`, `assets/` (deduped files, fonts, search files).

## 7. Test status

- Tested only on a **synthetic fixture** built from the 2 sample pages (dummy resource files) plus a fake video page. Result: video page skipped, links and TOC rewritten, admin bar gone, CSP present, self-check clean, carousel markup reset, `search.js` verified under Node with stubs.
- **Not yet done**: run on the real `help-full.zip`; render in a real browser; inspect the real report.

## 8. Known risks and unknowns (check first)

1. **Carousel reset is a guess.** If galleries (left thumbnails, zoom) are broken, rerun with `--keep-carousel-dom`, or inspect the theme `scripts*.js` to see how owl is initialised and whether `.image-caption` is generated.
2. **Theme `scripts*.js` not inspected.** It may call `admin-ajax.php`, `wp-json`, or build markup. The report's last section lists such strings; investigate any hits.
3. **CSP might block something** unexpected (inline handlers, blob/data usage). Remove with `--no-csp` to diagnose, then loosen the policy rather than drop it if possible.
4. **Video page detection is regex plus filename.** Confirm the skipped list is exactly the intended pages. Pages that merely link to a video are kept, with the dead link reported.
5. **Missing upload files** (PDFs or other attachments linked via `/wp-content/uploads/`) will be dead links. Check the report section.
6. **Fonts**: only the latin subset of Raleway is bundled. The `@fontsource` package also has latin-ext files if needed. Icon fonts were not saved by the browser; check for missing icons visually.
7. **Page-internal state**: jQuery loads twice (as on the original). Pages without a canonical link fall back to a slug from the title.
8. Output size is unknown until the real run. `--single-image` reduces it.

## 9. Next steps

1. Place `build_site.py` and `fonts/` in a repo/folder, run on the real zip, read `build_report.txt`.
2. Open `site/index.html` and test: navigation tree, 3 to 5 deep pages, a page with a gallery, a page with tables, image zoom (fancybox), search, mobile width.
3. Fix issues found (likely carousel, CSS gaps, unresolved links).
4. Test served over HTTP (`python -m http.server` in `site/`) and with the browser's network tab open: confirm **zero requests to external hosts**.
5. Write the **basis team checklist** (not done yet). Draft requirements: any web server serving a static folder; storage = size of `site/`; standard MIME types (`.html .css .js .json .woff2 .svg .jpg .png`); index files for folder URLs; modern Chrome/Edge/Firefox with JavaScript enabled; no outbound internet needed; works from root or sub-path (relative links); no server-side runtime.
6. Optional extras if requested: nginx/Apache/IIS config snippets in the README, a Docker image, a small local preview script.
7. Zip `site/` (no executables, no scripts) for delivery; many clients scan incoming archives.

## 10. Useful prompt for Cursor

> I am continuing a project that converts a browser-saved WordPress help site (126 pages with `_files` folders) into a clean offline static site for a client with no internet access. Read `HANDOVER.md` and `build_site.py`. First goal: run it on the real zip, then fix problems from `build_report.txt` and a browser check (carousel/gallery, CSS, search, zero external requests). Do not include pages that contain videos.
