# News fixtures — synthetic

All text is fabricated. Formats follow real RSS 2.0 (with content:encoded), an HTML listing
page, an article page, and GDELT DOC 2.0 ArtList JSON (fields checked 2026-11-11).

`gobmx-listing.js` mimics a gob.mx archive listing (checked 2026-11-20): the response is
JavaScript whose `$("#prensa").append("...")` string literals carry the article cards, each
with a `<time datetime>` in Mexico City time and an `aria-label` title. Content is synthetic.
