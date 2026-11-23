# News fixtures — synthetic

All text is fabricated. Formats follow real RSS 2.0 (with content:encoded), an HTML listing
page, an article page, and GDELT DOC 2.0 ArtList JSON (fields checked 2026-11-11).

`gobmx-listing.js` mimics a gob.mx archive listing (checked 2026-11-20): the response is
JavaScript whose `$("#prensa").append("...")` string literals carry the article cards, each
with a `<time datetime>` in Mexico City time and an `aria-label` title. Content is synthetic.

`fgr-listing.html` mimics the FGR press listing at www.fgr.org.mx (checked 2026-11-22): each
card links twice to `/es/FGR/Prensa/_rid/61/_mod/story`, the release named only by its `suri`
query value, with a `span.fecha` day, `span.numBoletin` number and `span.titBoletin` headline.
The bytes are ISO-8859-1 (the server's header) while the page's meta says UTF-8. Content is
synthetic.
