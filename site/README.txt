Skywind Knowledge Portal - offline copy
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
