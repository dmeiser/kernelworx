---
name: "KernelWorx"
category: Brands
surface: web
colors:
  background-gray: "#f7f7f7"
  text-primary: "#4b4b4b"
  primary-blue: "#1976d2"
  white-paper: "#ffffff"
  text-secondary: "#595959"
  border-gray: "#e0e0e0"
---

# KernelWorx

> Category: Brands

> Surface: web

*Built for parents and Units. Use it on your own or with the whole pack.*

KernelWorx helps parents of Scouting America Scouts manage their Scout's popcorn sales. Volunteer-run, open-source (MIT). Live at https://kernelworx.app/

## Color Palette

| Role | Name | Hex | Usage |
| --- | --- | --- | --- |
| background | Background Gray | `#f7f7f7` | page canvas (MUI background.default) |
| foreground | Text Primary | `#4b4b4b` | body text and headings (AAA on white and canvas) |
| accent | Primary Blue | `#1976d2` | brand mark and non-text emphasis only (4.6:1 — not for text). Text links #005a9c (AAA); filled actions with white text #0c57ab (AAA); darkest #00265e, light #3e94de |
| surface | White / Paper | `#ffffff` | cards, panels, dialogs (MUI background.paper) |
| muted | Text Secondary | `#595959` | secondary text and metadata (7:1 on white — AAA) |
| border | Border Gray | `#e0e0e0` | rules, dividers, card outlines |

### Accessibility ramp (WCAG 2.1 AAA)

`#1976d2` is 4.6:1 on white — AA only — so it is reserved for the logo mark, icons, borders, and decorative accents. Anything text-bearing uses the darker ramp:

| Role | Hex | Contrast | Usage |
| --- | --- | --- | --- |
| Link Blue | `#005a9c` | 7.1:1 on white | text links, text-level accents, outlined button labels |
| Action Blue | `#0c57ab` | 7.1:1 with white text | filled primary buttons/chips with white text |
| Deep Navy | `#00265e` | 13.5:1 on `#ebf8ff` | text on accent-tint callouts |
| Accent Tint | `#ebf8ff` | — | callout/alert info backgrounds (pair with `#00265e` text) |
| Error Text | `#9e0036` | 7.1:1 on `#ffe6ea` | error text on error tint; filled danger buttons with white text |
| Success Text | `#15431c` | 7.1:1 on `#c4cfc2` | success text on success tint |
| Warning Text | `#8a4200` | 6.9:1 on `#fff7e6` | warning text on warning tint (AA+; prefer a darker text for strict AAA) |

The saturated status mains (`#dc004e`, `#388e3c`, `#f57c00`) are for icons, borders, and small non-text indicators only — never text.

## Typography
- **Display:** Bricolage Grotesque — weights 600, 700 — fallbacks: Atkinson Hyperlegible, sans-serif
- **Body:** Atkinson Hyperlegible — weights 400, 700 — fallbacks: Lexend, Inter, sans-serif
- **Loading:** Google Fonts hosted only (see `googleFontsUrl` in `brand.json`); font binaries are intentionally not vendored in this repo.

## Voice & Tone

- **Adjectives:** friendly, trustworthy, clear, accessible
- **Tone:** Popcorn Sales Made Easy — warm and plain-spoken for busy parents; accessibility-first (WCAG 2.1 AAA).

### Messaging pillars
- Popcorn Sales Made Easy
- Volunteer-run Scouting America fundraising tool

### Vocabulary
- **Use:** (none yet)
- **Avoid:** (none yet)

## Imagery

- **Style:** Real product/popcorn photography over illustration; light-blue brand tints (#ebf8ff to #c2e9ff) behind the logo lockup.
- **Subjects:** popcorn, Scouting fundraising
- **Treatment:** Popcorn-bucket mark (white heap over a tapered carton with five hairline stripes) in a #1976d2 rounded square; Bricolage Grotesque 700 wordmark, 'Kernel' in #4b4b4b + 'Worx' in #1976d2. On blue or dark backgrounds use the reversed single-color (white) version — two-tone fails contrast there.
- **Avoid:** (none yet)

## Layout

- **Radius:** 4px
- **Border weight:** 1px
- **Spacing:** 8px baseline grid

### Posture rules
- Component kit should cover: Button, Card, Form, Navigation, Dialog, Table.
- Buttons: filled primary #0c57ab with white text (AAA 7:1), outlined secondary (#005a9c border and text on white), filled danger #9e0036 with white text; 4px radius. #1976d2 is reserved for the brand mark and non-text accents — never for text or filled text-bearing controls.
- MUI patterns: white paper cards on a #f7f7f7 canvas, contained elevation, left-border callouts in #ebf8ff with a #1976d2 accent bar.
- Accessibility: WCAG 2.1 AAA is the bar. Text on light surfaces uses #4b4b4b (primary) or #595959 (secondary); text links #005a9c; status text on tints — error #9e0036 on #ffe6ea, success #15431c on #c4cfc2, warning #8a4200 on #fff7e6; the saturated status mains (#dc004e, #388e3c, #f57c00) are for icons and borders only, never text.
- Bricolage Grotesque for H1/app title/hero display headings and the wordmark; Atkinson Hyperlegible everywhere else (body, UI, numbers, small labels).
- Iconography: the locked popcorn-bucket mark (assets/kernelworx-icon.svg) is the source of truth for app icons and favicons; it replaces the legacy standalone kernel mark.
