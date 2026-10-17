# Report fonts

`NotoSansTC-Regular.ttf` is the bundled Traditional Chinese font for PDF and PNG,
independent of operating-system fonts. It is instantiated from the Google Fonts
Noto Sans TC variable font at `wght=400`, with the PostScript name set to
`NotoSansTC-Regular`. The actual weight has been verified as 400.

Upstream: [Google Fonts Noto Sans TC](https://github.com/google/fonts/tree/main/ofl/notosanstc).
It uses SIL Open Font License 1.1; complete terms are in `OFL.txt` in this directory.
Production reports use this Regular asset.

ODS embeds the same font and license and specifies Latin and Asian text styles.
Reader support for embedded fonts varies. Formulas remain editable. Charts are
embedded PNGs: their series are not editable and they do not redraw when cells
change. PDF embeds the font; PNG contains rendered pixels.

## Simplified Chinese

`NotoSansSC-Regular.ttf` is unmodified Noto Sans SC Regular (Version 2.004-H2) for
zh-CN. It contains TrueType outlines; its metadata identifies Adobe 2014-2021 and
SIL OFL 1.1. Full terms are in `OFL-SC.txt`. Version, SHA-256 and source are recorded
in `NotoSansSC-provenance.json`; upstream is [Noto CJK](https://github.com/notofonts/noto-cjk).
This bundled asset does not require a user's local applications or system fonts.

en-CA and zh-TW select TC; zh-CN selects SC. Acceptance checks include cmap coverage
for all catalog Han characters and text extraction/font-registration isolation
when multiple PDF languages are generated in one process. Font licenses are separate
from the project's MIT license. Additional languages require glyph/license review.
