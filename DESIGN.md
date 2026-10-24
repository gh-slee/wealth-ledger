---
name: "Wealth Ledger"
description: "Existing light and dark investment workbench primitives"
colors:
  light-ink: "#193b51"
  light-accent: "#157f7a"
  light-muted: "#526c7c"
  light-canvas: "#eef3f6"
  light-paper: "#fcfdfe"
  light-border: "#d8e2e9"
  light-input: "#ffffff"
  light-control-border: "#a8bac6"
  light-on-accent: "#ffffff"
  light-accent-hover: "#10645f"
  light-selection: "#e3efee"
  light-selection-ink: "#0d6661"
  light-good-bg: "#e4f2ee"
  light-good-ink: "#16644e"
  light-review-bg: "#fff1de"
  light-review-ink: "#874b1c"
  light-error-bg: "#fff0eb"
  light-error-ink: "#8d3324"
  light-danger: "#a33b2f"
  light-on-danger: "#ffffff"
  dark-ink: "#e2edf3"
  dark-accent: "#74d4c7"
  dark-muted: "#adc0ce"
  dark-canvas: "#10212e"
  dark-paper: "#182b39"
  dark-border: "#3a5263"
  dark-input: "#132632"
  dark-control-border: "#678193"
  dark-on-accent: "#102b2a"
  dark-accent-hover: "#98e4d9"
  dark-selection: "#234943"
  dark-selection-ink: "#9be8da"
  dark-good-bg: "#1a4039"
  dark-good-ink: "#a6e9c6"
  dark-review-bg: "#49371e"
  dark-review-ink: "#f3d29b"
  dark-error-bg: "#4b2a2c"
  dark-error-ink: "#ffc5bb"
  dark-danger: "#a63b35"
  dark-on-danger: "#ffffff"
typography:
  headline:
    fontFamily: "IBM Plex Sans Condensed, system-ui, sans-serif"
    fontSize: "2.4rem"
    fontWeight: 600
    lineHeight: 1.1
  title:
    fontFamily: "IBM Plex Sans Condensed, system-ui, sans-serif"
    fontSize: "1.4rem"
    fontWeight: 600
  body:
    fontFamily: "Atkinson Hyperlegible, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
  label:
    fontSize: "0.9rem"
    fontWeight: 700
  eyebrow:
    fontSize: "0.76rem"
    fontWeight: 700
    letterSpacing: "0.11em"
rounded:
  status: "4px"
  control: "5px"
  panel: "7px"
  dialog: "8px"
spacing:
  button: "0.6rem 1rem"
  input: "0.62rem 0.75rem"
  panel: "1.5rem"
components:
  button-primary:
    backgroundColor: "{colors.light-accent}"
    textColor: "{colors.light-on-accent}"
    rounded: "{rounded.control}"
    padding: "{spacing.button}"
  button-secondary:
    backgroundColor: "{colors.light-input}"
    textColor: "{colors.light-ink}"
    rounded: "{rounded.control}"
    padding: "{spacing.button}"
  button-destructive:
    backgroundColor: "{colors.light-danger}"
    textColor: "{colors.light-on-danger}"
    rounded: "{rounded.control}"
    padding: "{spacing.button}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.light-ink}"
    rounded: "{rounded.control}"
    padding: "{spacing.button}"
  input:
    backgroundColor: "{colors.light-input}"
    textColor: "{colors.light-ink}"
    rounded: "{rounded.control}"
    padding: "{spacing.input}"
  panel:
    backgroundColor: "{colors.light-paper}"
    rounded: "{rounded.panel}"
    padding: "{spacing.panel}"
---

# Design System: Wealth Ledger

## Overview

**Creative North Star: "Clear investment workbench"**

Keep the portfolio summary concise, layer analysis by purpose, and reveal detailed
evidence on demand. The established interface uses cool paper surfaces, navy text,
teal actions and compact typography; dark mode translates the same semantic roles.

This is a record of the incumbent system, not a replacement identity. Authority is
[the stylesheet](frontend/src/styles.css), [font imports](frontend/src/main.tsx),
[UI primitives](frontend/src/components/ui/button.tsx), and the synthetic
[light](assets/readme/web-overview.png) / [dark](assets/readme/web-overview-dark.png)
gallery captures. Keep this document synchronized when those primitives change.

**Key Characteristics:**

- A readable hierarchy of summary, analysis and expandable evidence.
- Flat bordered panels, visible focus and restrained accent use.
- Stable numeric alignment and consistent light/dark semantics.

## Colors

The palette is cool and restrained. Frontmatter records literal values from the
current stylesheet; light/dark prefixes describe themes, not separate identities.
The role mapping below is descriptive; CSS remains the implementation authority.

### Primary

- **Workbench teal** (`accent` / CSS `--teal`): primary action and focus ring;
  `on-accent` supplies readable foreground and `accent-hover` the hover state.
- **Selection wash** (`selection`, `selection-ink`): active navigation with an accent edge.

### Secondary

- **Evidence states** (`good-*`, `review-*`, `error-*`): confirmed scoped status,
  review and error. Keep the implementation's corresponding border tokens.
- **Destructive action** (`danger`, `on-danger`): destructive button treatment.
  Dark mode retains a dark red button with a light foreground.

### Neutral

- **Ledger ink** (`ink` / CSS `--navy`) and `muted`: main and supporting text.
- **Canvas and paper** (`canvas`, `paper`): application background and panel surface.
- **Field and boundary** (`input`, `border`, `control-border`): controls and separators.

**The Semantic Theme Rule.** Use the corresponding CSS variable in both themes;
never paste a light-theme token into a component that must follow dark mode.

## Typography

**Heading Font:** IBM Plex Sans Condensed, system-ui, sans-serif (weight 600).
**Body Font:** Atkinson Hyperlegible, system-ui, sans-serif (regular and bold).

Fonts are bundled through frontend imports. CJK uses the system fallback; the
report generator's Noto font assets do not establish a Web font dependency.
Frontmatter lists reused roles, not a fabricated complete type scale. Headline maps
to h1; title maps to h2. Existing h3 uses a smaller title (1.12rem). Paragraphs use
relaxed line height (1.55); small annotations use compact text (0.82rem). Labels
are bold; eyebrows add uppercase and tracking. Numeric displays use tabular numerals.

**The Numeric Alignment Rule.** Keep amounts aligned, their units explicit and the
existing tabular numeral treatment in data displays; do not alter financial strings.

## Layout

Desktop uses a sticky navigation column (242px) and a flexible workbench capped
at a generous width (1800px). Workbench padding is responsive through clamp. At the
existing intermediate breakpoint (1100px), the sidebar narrows to 210px, analysis
panels stack and toolbar/heading layouts adapt. At the mobile breakpoint (700px),
the sidebar becomes a static band and navigation scrolls horizontally.

Panels use the frontmatter panel spacing; evidence dates form a wrapping rail.
Tables retain horizontal scrolling where needed. This describes existing behavior,
not a claim that every page has passed a new responsive audit.

## Elevation & Depth

Panels and controls are flat, separated by tone, thin borders and spacing. A modal
alone uses a darkened backdrop and an elevated surface. Its current shadow is
`0 15px 80px #193b5140`; the overlay is `#193b5170`. Both are literal incumbent
values, not a newly introduced shadow scale. No shared animation duration exists;
the stylesheet respects reduced motion by suppressing animations and transitions.

**The Flat Surface Rule.** Retain flat resting panels. Reserve the existing dialog
shadow for modal separation rather than adding it to analysis cards.

## Shapes

Small corner changes communicate component scale: compact status tags, modestly
rounded controls, panels and dialogs use the frontmatter radii. Use thin boundaries;
the active navigation edge and evidence rail provide stronger orientation cues.

## Components

- **Buttons:** primary, secondary, ghost and destructive variants share a minimum
  target height (42px), bold text and control radius. Primary hover changes accent;
  secondary uses canvas and ghost uses the hover surface. The destructive variant
  currently has no separate hover color. Disabled buttons fade and use a wait cursor.
- **Fields:** full-width inputs/selects use the field surface, control border,
  input padding and a minimum height (42px). Labels remain visible above controls.
- **Focus:** keyboard focus uses the existing accent outline (3px, offset 4px).
- **Status tags:** text plus a compact bordered tint, with wrapping allowed.
  Neutral, scoped-good and review variants exist; do not infer financial verification
  from a tint. The current notices component maps both warnings and errors to review.
- **Panels:** paper surface, thin boundary, panel radius and spacing; no resting shadow.
- **Navigation:** muted text at rest, a washed active background with bold text and
  accent edge. Preserve active and hover behavior, horizontal overflow on mobile,
  and semantic links/buttons in the real application.
- **Evidence rail:** dates and scope labels wrap above analysis, with a stronger
  upper border (2px) and a standard lower border (1px). Dates remain source-specific.
- **Evidence status:** a scoped summary, at most three initially visible action
  groups with an explicit full-list control, then native expandable evidence. The
  current-processing area is independent of a frozen edition. Reuse existing panel,
  button and status primitives; avoid a second bordered panel inside evidence.
- **Import stages:** a simple numbered list expresses the actual prepare, review
  and publish sequence. Current-stage text carries emphasis; native disclosures
  hold advanced controls and disabled field groups indicate an active request.
  User-submitted results receive focus; background polling does not steal it.
- **Country distribution:** a focusable native scroll viewport contains all supplied
  country rows, with wrapped labels and no automatic label skipping. Localized help
  names keyboard controls and the complete paginated data table. Unknown and adjustment
  rows keep their own labels and amounts; the table remains available if the chart
  fails. Sector, region and history charts retain their existing layouts.
- **Report checks:** a native expandable section preserves counts, stable codes and
  account contexts. Grouping repeated notices must not erase distinct evidence.

## Do's and Don'ts

### Do:

- Do keep saved dates and numeric units adjacent to the values they qualify.
- Do reuse theme variables, existing controls and visible keyboard focus.
- Do wrap long labels and retain accessible table/chart alternatives.

### Don't:

- Don't use accent or status color as the only explanation of meaning.
- Don't introduce new fonts, decorative shadows or whole-page compositions during a scoped fix.
- Don't hide unknowns or evidence limitations to create a reassuring visual state.
