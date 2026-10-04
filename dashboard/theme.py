"""Monochrome High-Contrast Bento Design System & Theme Injector.

Implements the iDraft Bento Dashboard aesthetic:
- Abstract monochrome silk/smoke blurred gradient background
- Floating frosted-glass outer canvas (radius 32px) with subtle 1px border and diffuse shadow
- Floating white sidebar card with dark pill active states and uppercase section headings
- Top greeting bar with pill action button and circular utility controls
- Bento grid: Dark hero card (#171717) with inner stat tiles (highlighted white tile),
  pure white cards with minimal border, donut progress card, and checklist cards.
- Plus Jakarta Sans / Inter typography with tabular numerals.
- Strictly monochrome palette with functional status-only accents (Emerald, Amber, Coral Red).
"""

from __future__ import annotations

import re

import streamlit as st


def clean_html(html_str: str) -> str:
    """Strip leading whitespace on each line to prevent Markdown pre/code block parsing."""
    return re.sub(r"^[ \t]+", "", html_str, flags=re.MULTILINE)


THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700&display=swap');

:root {
  /* Canvas & Background */
  --canvas-bg: radial-gradient(at 15% 15%, rgba(225, 227, 232, 0.85) 0px, transparent 55%),
               radial-gradient(at 85% 10%, rgba(210, 215, 225, 0.75) 0px, transparent 50%),
               radial-gradient(at 50% 85%, rgba(235, 236, 240, 0.95) 0px, transparent 60%),
               linear-gradient(135deg, #E2E4E9 0%, #D3D6DD 100%);
  --canvas-glass: rgba(247, 248, 250, 0.72);
  --canvas-border: rgba(255, 255, 255, 0.65);
  --canvas-radius: 32px;
  --canvas-shadow: 0 24px 72px -12px rgba(0, 0, 0, 0.12), 0 0 0 1px rgba(255, 255, 255, 0.6) inset;

  /* Card Polarity (Monochrome High Contrast) */
  --card-dark: #171717;
  --card-dark-surface: #222222;
  --card-dark-highlight: #FFFFFF;
  --card-dark-border: rgba(255, 255, 255, 0.10);
  --card-dark-shadow: 0 16px 40px -8px rgba(0, 0, 0, 0.40);

  --card-white: #FFFFFF;
  --card-white-surface: #F8F8FA;
  --card-white-border: rgba(0, 0, 0, 0.06);
  --card-white-shadow: 0 10px 30px -4px rgba(0, 0, 0, 0.04), 0 2px 8px -1px rgba(0, 0, 0, 0.02);

  /* Typography & Ink */
  --ink-primary: #111111;
  --ink-secondary: #737373;
  --ink-tertiary: #8E8E93;
  --ink-white: #FFFFFF;
  --ink-white-muted: #A3A3A3;

  /* Functional Status Accents Only (No decorative colors) */
  --status-low: #10B981;
  --status-low-bg: rgba(16, 185, 129, 0.12);
  --status-med: #F59E0B;
  --status-med-bg: rgba(245, 158, 11, 0.12);
  --status-high: #EF4444;
  --status-high-bg: rgba(239, 68, 68, 0.12);

  /* Geometry & Scaling */
  --radius-card: 24px;
  --radius-tile: 16px;
  --radius-pill: 999px;
  --transition-smooth: all 180ms cubic-bezier(0.16, 1, 0.3, 1);
}

/* -------------------------------------------------------------------------
   Global Document & Typography
   ------------------------------------------------------------------------- */
html, body, [class*="css"], [data-testid="stAppViewContainer"], .stMarkdown,
p, span, div, h1, h2, h3, h4, h5, h6, input, select, button, textarea {
  font-family: 'Plus Jakarta Sans', 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
  -webkit-font-smoothing: antialiased !important;
  text-rendering: optimizeLegibility !important;
}

[data-testid="stAppViewContainer"] {
  background: var(--canvas-bg) !important;
  background-attachment: fixed !important;
  color: var(--ink-primary) !important;
}

[data-testid="stHeader"] {
  background: transparent !important;
}

[data-testid="stDecoration"] {
  display: none !important;
}

/* -------------------------------------------------------------------------
   The Floating Frosted-Glass Canvas Container
   ------------------------------------------------------------------------- */
.main .block-container,
[data-testid="stMainBlockContainer"] {
  max-width: 1580px !important;
  margin: 10px auto 16px auto !important;
  background: var(--canvas-glass) !important;
  backdrop-filter: blur(28px) saturate(170%) !important;
  -webkit-backdrop-filter: blur(28px) saturate(170%) !important;
  border: 1px solid var(--canvas-border) !important;
  border-radius: var(--canvas-radius) !important;
  box-shadow: var(--canvas-shadow) !important;
  padding: 20px 28px !important;
  overflow: visible !important;
}

/* -------------------------------------------------------------------------
   Floating Left White Sidebar Card (High Contrast & Visible Text)
   ------------------------------------------------------------------------- */
[data-testid="stSidebar"] {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
}

[data-testid="stSidebar"] > div:first-child {
  background: #FFFFFF !important;
  border-radius: 26px !important;
  margin: 14px 0 14px 18px !important;
  height: calc(100vh - 28px) !important;
  border: 1px solid rgba(0, 0, 0, 0.08) !important;
  box-shadow: 0 16px 44px -8px rgba(0, 0, 0, 0.08) !important;
  padding: 20px 16px !important;
  overflow-y: auto !important;
}

/* Force dark, crisp ink on all sidebar elements */
[data-testid="stSidebar"],
[data-testid="stSidebar"] * {
  color: #111111 !important;
}

[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
  font-size: 11px !important;
  font-weight: 800 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.08em !important;
  color: #111111 !important;
  margin-top: 14px !important;
  margin-bottom: 6px !important;
}

[data-testid="stSidebar"] label,
[data-testid="stSidebar"] label p,
[data-testid="stSidebar"] label span,
[data-testid="stSidebar"] div[data-testid="stWidgetLabel"],
[data-testid="stSidebar"] div[data-testid="stWidgetLabel"] label,
[data-testid="stSidebar"] div[data-testid="stWidgetLabel"] p,
[data-testid="stSidebar"] div[data-testid="stWidgetLabel"] span {
  color: #111111 !important;
  font-weight: 700 !important;
  font-size: 12.5px !important;
}

[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] .stRadio label,
[data-testid="stSidebar"] .stTextInput label {
  color: #111111 !important;
  font-weight: 700 !important;
}

[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] p {
  color: #111111 !important;
}

[data-testid="stSidebar"] hr {
  border: none !important;
  height: 1px !important;
  background: rgba(0, 0, 0, 0.08) !important;
  margin: 14px 0 !important;
}

/* Sidebar Radio Navigation Items */
[data-testid="stSidebar"] [data-testid="stRadioGroup"],
[data-testid="stSidebar"] [data-testid="stRadio"] div[role="radiogroup"] {
  gap: 6px !important;
  display: flex !important;
  flex-direction: column !important;
}

[data-testid="stSidebar"] [data-testid="stRadioOption"],
[data-testid="stSidebar"] [data-testid="stRadio"] div[role="radiogroup"] > label,
[data-testid="stSidebar"] div[data-testid="stRadioGroup"] div[data-rac] {
  background: #F4F4F6 !important;
  border: 1px solid rgba(0, 0, 0, 0.06) !important;
  border-radius: var(--radius-pill) !important;
  padding: 8px 14px !important;
  transition: var(--transition-smooth) !important;
  cursor: pointer !important;
  display: flex !important;
  align-items: center !important;
}

[data-testid="stSidebar"] [data-testid="stRadioOption"] p,
[data-testid="stSidebar"] [data-testid="stRadioOption"] span,
[data-testid="stSidebar"] [data-testid="stRadio"] div[role="radiogroup"] > label p,
[data-testid="stSidebar"] [data-testid="stRadio"] div[role="radiogroup"] > label span {
  color: #111111 !important;
  font-weight: 600 !important;
  font-size: 13px !important;
}

[data-testid="stSidebar"] [data-testid="stRadioOption"]:hover,
[data-testid="stSidebar"] [data-testid="stRadio"] div[role="radiogroup"] > label:hover {
  background: #EAEBED !important;
  transform: translateY(-1px);
}

/* ACTIVE item: Dark Filled Pill with pure white text */
[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"],
[data-testid="stSidebar"] [data-testid="stRadioOption"][data-checked="true"],
[data-testid="stSidebar"] div[data-selected="true"] [data-testid="stRadioOption"],
[data-testid="stSidebar"] div[data-selected="true"] > [data-testid="stRadioOption"],
[data-testid="stSidebar"] div[data-testid="stRadioGroup"] div[data-selected="true"],
[data-testid="stSidebar"] [data-testid="stRadio"] div[role="radiogroup"] > label:has(input:checked) {
  background: #171717 !important;
  border-color: #171717 !important;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.20) !important;
}

[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] p,
[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] span,
[data-testid="stSidebar"] [data-testid="stRadioOption"][data-checked="true"] p,
[data-testid="stSidebar"] [data-testid="stRadioOption"][data-checked="true"] span,
[data-testid="stSidebar"] div[data-selected="true"] [data-testid="stRadioOption"] p,
[data-testid="stSidebar"] div[data-selected="true"] [data-testid="stRadioOption"] span,
[data-testid="stSidebar"] div[data-testid="stRadioGroup"] div[data-selected="true"] p,
[data-testid="stSidebar"] [data-testid="stRadio"] div[role="radiogroup"] > label:has(input:checked) p,
[data-testid="stSidebar"] [data-testid="stRadio"] div[role="radiogroup"] > label:has(input:checked) span {
  color: #FFFFFF !important;
  font-weight: 700 !important;
}

/* Sidebar Selectboxes & Input Contrast */
[data-testid="stSidebar"] [data-baseweb="select"] > div,
[data-testid="stSidebar"] [data-baseweb="select"] span,
[data-testid="stSidebar"] [data-baseweb="select"] div,
[data-testid="stSidebar"] input {
  color: #111111 !important;
  font-weight: 600 !important;
  background-color: #FFFFFF !important;
}

[data-baseweb="popover"],
[data-baseweb="popover"] *,
[data-baseweb="menu"],
[data-baseweb="menu"] * {
  background-color: #FFFFFF !important;
  color: #111111 !important;
}

[data-baseweb="menu"] li:hover,
[data-baseweb="menu"] [aria-selected="true"] {
  background-color: #F3F4F6 !important;
  color: #000000 !important;
}

/* -------------------------------------------------------------------------
   Tabs Restyling: Segmented Pill Control (Reference Style)
   ------------------------------------------------------------------------- */
[data-testid="stTabs"] div[role="tablist"],
[data-testid="stTabs"] [data-baseweb="tab-list"] {
  background: var(--card-white) !important;
  border: 1px solid var(--card-white-border) !important;
  border-radius: var(--radius-pill) !important;
  padding: 6px !important;
  gap: 6px !important;
  box-shadow: 0 4px 18px rgba(0, 0, 0, 0.04) !important;
  display: inline-flex !important;
  width: auto !important;
  margin-bottom: 24px !important;
  border-bottom: none !important;
}

[data-testid="stTabs"] div[role="tab"],
[data-testid="stTabs"] [data-testid="stTab"],
[data-testid="stTabs"] [data-baseweb="tab"] {
  border-radius: var(--radius-pill) !important;
  border: none !important;
  color: var(--ink-secondary) !important;
  padding: 8px 22px !important;
  font-weight: 600 !important;
  font-size: 13.5px !important;
  background: transparent !important;
  transition: var(--transition-smooth) !important;
  cursor: pointer !important;
  box-shadow: none !important;
}

[data-testid="stTabs"] div[role="tab"]:hover,
[data-testid="stTabs"] [data-testid="stTab"]:hover {
  color: var(--ink-primary) !important;
  background: #F2F2F5 !important;
}

/* Active Tab: Dark Filled Pill */
[data-testid="stTabs"] div[role="tab"][data-selected="true"],
[data-testid="stTabs"] div[role="tab"][aria-selected="true"],
[data-testid="stTabs"] [data-testid="stTab"][data-selected="true"],
[data-testid="stTabs"] [data-testid="stTab"][aria-selected="true"] {
  background: var(--card-dark) !important;
  color: var(--ink-white) !important;
  font-weight: 700 !important;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.18) !important;
}

[data-testid="stTabs"] div[role="tab"][data-selected="true"] p,
[data-testid="stTabs"] [data-testid="stTab"][data-selected="true"] p,
[data-testid="stTabs"] div[role="tab"][data-selected="true"] div,
[data-testid="stTabs"] [data-testid="stTab"][data-selected="true"] div {
  color: var(--ink-white) !important;
}

[data-testid="stTabs"] .react-aria-SelectionIndicator,
[data-testid="stTabs"] [data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-baseweb="tab-border"] {
  display: none !important;
}

/* -------------------------------------------------------------------------
   Card Containers & Panels
   ------------------------------------------------------------------------- */
[data-testid="stVerticalBlockBorderWrapper"] > div {
  background: var(--card-white) !important;
  border: 1px solid var(--card-white-border) !important;
  border-radius: var(--radius-card) !important;
  box-shadow: var(--card-white-shadow) !important;
  padding: 24px !important;
  transition: var(--transition-smooth) !important;
}

[data-testid="stVerticalBlockBorderWrapper"] > div:hover {
  transform: translateY(-2px);
  box-shadow: 0 14px 34px -4px rgba(0, 0, 0, 0.07) !important;
}

[data-testid="stExpander"] {
  background: var(--card-white) !important;
  border: 1px solid var(--card-white-border) !important;
  border-radius: var(--radius-card) !important;
  box-shadow: var(--card-white-shadow) !important;
  overflow: hidden !important;
}

/* -------------------------------------------------------------------------
   Buttons (Dark Pill Action Buttons)
   ------------------------------------------------------------------------- */
button[kind="primary"], [data-testid="stBaseButton-primary"] {
  background: var(--card-dark) !important;
  border-radius: var(--radius-pill) !important;
  border: 1px solid rgba(255, 255, 255, 0.15) !important;
  color: var(--ink-white) !important;
  font-weight: 600 !important;
  padding: 8px 20px !important;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.22) !important;
  transition: var(--transition-smooth) !important;
}

button[kind="primary"]:hover, [data-testid="stBaseButton-primary"]:hover {
  background: #262626 !important;
  transform: translateY(-1px);
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.28) !important;
}

button[kind="secondary"], [data-testid="stBaseButton-secondary"] {
  background: var(--card-white) !important;
  border-radius: var(--radius-pill) !important;
  border: 1px solid rgba(0, 0, 0, 0.12) !important;
  color: var(--ink-primary) !important;
  font-weight: 600 !important;
  padding: 8px 18px !important;
  transition: var(--transition-smooth) !important;
}

button[kind="secondary"]:hover, [data-testid="stBaseButton-secondary"]:hover {
  background: #F4F4F6 !important;
  border-color: rgba(0, 0, 0, 0.25) !important;
  transform: translateY(-1px);
}

/* -------------------------------------------------------------------------
   Form Inputs & Selectboxes
   ------------------------------------------------------------------------- */
[data-testid="stSelectbox"] > div > div,
[data-testid="stTextInput"] > div > div > input {
  background: var(--card-white) !important;
  border: 1px solid rgba(0, 0, 0, 0.10) !important;
  border-radius: 14px !important;
  color: var(--ink-primary) !important;
  font-size: 13.5px !important;
  transition: var(--transition-smooth) !important;
}

[data-testid="stSelectbox"] > div > div:hover,
[data-testid="stTextInput"] > div > div > input:focus {
  border-color: var(--ink-primary) !important;
  box-shadow: 0 0 0 2px rgba(23, 23, 23, 0.08) !important;
}

/* -------------------------------------------------------------------------
   DataFrames & Tables (Clean Monochrome)
   ------------------------------------------------------------------------- */
[data-testid="stDataFrame"] {
  background: var(--card-white) !important;
  border: 1px solid var(--card-white-border) !important;
  border-radius: var(--radius-card) !important;
  box-shadow: var(--card-white-shadow) !important;
  overflow: hidden !important;
}

/* -------------------------------------------------------------------------
   Custom Bento CSS Utility Classes
   ------------------------------------------------------------------------- */
.bento-topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.bento-greeting {
  font-size: 32px;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: var(--ink-primary);
  margin: 0;
  line-height: 1.15;
}

.bento-greeting-sub {
  font-size: 13.5px;
  color: var(--ink-secondary);
  font-weight: 500;
  margin-top: 4px;
}

.bento-top-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.bento-circle-btn {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  background: var(--card-white);
  border: 1px solid rgba(0, 0, 0, 0.08);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 16px;
  color: var(--ink-primary);
  transition: var(--transition-smooth);
}

.bento-circle-btn:hover {
  background: #F2F2F5;
  transform: translateY(-1px);
}

.bento-avatar {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  background: var(--card-dark);
  color: #FFFFFF;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 14px;
  border: 2px solid #FFFFFF;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
}

/* -------------------------------------------------------------------------
   Bento Unified Metric Cards (Dark & Light matching structure)
   ------------------------------------------------------------------------- */
.bento-card-dark,
.bento-dark-hero {
  background: #171717 !important;
  border-radius: 20px !important;
  padding: 18px 16px !important;
  color: #FFFFFF !important;
  border: 1px solid rgba(255, 255, 255, 0.12) !important;
  box-shadow: 0 16px 40px -8px rgba(0, 0, 0, 0.35) !important;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  height: 100%;
  min-height: 180px;
  box-sizing: border-box;
  transition: all 180ms cubic-bezier(0.16, 1, 0.3, 1);
}

.bento-card-dark:hover,
.bento-dark-hero:hover {
  transform: translateY(-2px);
  box-shadow: 0 20px 48px -6px rgba(0, 0, 0, 0.45) !important;
}

.bento-card-light {
  background: #FFFFFF !important;
  border-radius: 20px !important;
  padding: 18px 16px !important;
  color: #111111 !important;
  border: 1px solid rgba(0, 0, 0, 0.08) !important;
  box-shadow: 0 8px 24px -4px rgba(0, 0, 0, 0.04), 0 2px 6px -1px rgba(0, 0, 0, 0.02) !important;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  height: 100%;
  min-height: 180px;
  box-sizing: border-box;
  transition: all 180ms cubic-bezier(0.16, 1, 0.3, 1);
}

.bento-card-light:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 30px -4px rgba(0, 0, 0, 0.08) !important;
}

.bento-card-header,
.bento-dark-hero-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.bento-card-title,
.bento-dark-hero-title {
  font-size: 13.5px;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.bento-card-dark .bento-card-title,
.bento-dark-hero-title {
  color: #FFFFFF;
}

.bento-card-light .bento-card-title {
  color: #111111;
}

.bento-card-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.bento-card-big-num,
.bento-dark-hero-big-num {
  font-size: 36px;
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1;
  font-variant-numeric: tabular-nums;
  margin-top: 2px;
}

.bento-card-dark .bento-card-big-num,
.bento-dark-hero-big-num {
  color: #FFFFFF;
}

.bento-card-light .bento-card-big-num {
  color: #111111;
}

.bento-card-label,
.bento-dark-hero-label {
  font-size: 11.5px;
  font-weight: 500;
  margin-top: 4px;
  line-height: 1.3;
}

.bento-card-dark .bento-card-label,
.bento-dark-hero-label {
  color: #A3A3A3;
}

.bento-card-light .bento-card-label {
  color: #6B7280;
}

.bento-subtiles-row,
.bento-tiles-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
  margin-top: 14px;
}

.bento-subtile,
.bento-tile {
  border-radius: 10px;
  padding: 8px 4px;
  text-align: center;
}

.bento-card-dark .bento-subtile,
.bento-dark-hero .bento-tile {
  background: #242424;
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.bento-card-dark .bento-subtile-val,
.bento-dark-hero .bento-tile-val {
  font-size: 15px;
  font-weight: 800;
  color: #FFFFFF;
  font-variant-numeric: tabular-nums;
}

.bento-card-dark .bento-subtile-lbl,
.bento-dark-hero .bento-tile-lbl {
  font-size: 9px;
  color: #9CA3AF;
  text-transform: uppercase;
  font-weight: 600;
  margin-top: 2px;
}

.bento-card-dark .bento-subtile-highlight,
.bento-dark-hero .bento-tile-highlight {
  background: #FFFFFF !important;
}

.bento-card-dark .bento-subtile-highlight .bento-subtile-val,
.bento-dark-hero .bento-tile-highlight .bento-tile-val {
  color: #111111 !important;
}

.bento-card-dark .bento-subtile-highlight .bento-subtile-lbl,
.bento-dark-hero .bento-tile-highlight .bento-tile-lbl {
  color: #4B5563 !important;
}

/* Light Card Subtiles */
.bento-card-light .bento-subtile {
  background: #F4F4F6;
  border: 1px solid rgba(0, 0, 0, 0.04);
}

.bento-card-light .bento-subtile-val {
  font-size: 15px;
  font-weight: 800;
  color: #111111;
  font-variant-numeric: tabular-nums;
}

.bento-card-light .bento-subtile-lbl {
  font-size: 9px;
  color: #6B7280;
  text-transform: uppercase;
  font-weight: 600;
  margin-top: 2px;
}

.bento-card-light .bento-subtile-highlight {
  background: #171717 !important;
}

.bento-card-light .bento-subtile-highlight .bento-subtile-val {
  color: #FFFFFF !important;
}

.bento-card-light .bento-subtile-highlight .bento-subtile-lbl {
  color: #D1D5DB !important;
}

/* Internal Scrollable Panels for Zero-Page-Scroll UX */
.bento-scroll-panel {
  max-height: 540px;
  overflow-y: auto;
  padding-right: 6px;
}

.bento-scroll-panel::-webkit-scrollbar {
  width: 5px;
}

.bento-scroll-panel::-webkit-scrollbar-track {
  background: transparent;
}

.bento-scroll-panel::-webkit-scrollbar-thumb {
  background: #D1D5DB;
  border-radius: 999px;
}

.bento-scroll-panel::-webkit-scrollbar-thumb:hover {
  background: #9CA3AF;
}

/* White Card Containers */
.bento-white-card {
  background: var(--card-white);
  border-radius: var(--radius-card);
  padding: 24px;
  border: 1px solid var(--card-white-border);
  box-shadow: var(--card-white-shadow);
  height: 100%;
}

.bento-card-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--ink-primary);
  letter-spacing: -0.01em;
  margin-bottom: 4px;
}

.bento-card-caption {
  font-size: 12px;
  color: var(--ink-secondary);
  margin-bottom: 16px;
}

/* Checklist Card (Reference: Month goals) */
.bento-checklist-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid rgba(0, 0, 0, 0.04);
}

.bento-check-circle {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
}

.bento-check-circle.checked {
  background: var(--card-dark);
  color: #FFFFFF;
}

.bento-check-circle.pending {
  border: 2px solid #D1D5DB;
  background: transparent;
}

.bento-check-text {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-primary);
}

.bento-check-text.struck {
  text-decoration: line-through;
  color: var(--ink-secondary);
}

/* Day Selector Row (M T W T F S S) */
.bento-day-row {
  display: flex;
  justify-content: space-between;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid rgba(0, 0, 0, 0.05);
}

.bento-day-item {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
  color: var(--ink-secondary);
}

.bento-day-item.active {
  background: var(--card-dark);
  color: #FFFFFF;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2);
}

/* Responsive adjustments */
@media (max-width: 1280px) {
  .main .block-container, [data-testid="stMainBlockContainer"] {
    padding: 20px !important;
    margin: 12px auto !important;
  }
}
</style>
"""


def inject_theme() -> None:
    """Inject centralized monochrome glassmorphism CSS theme tokens into Streamlit DOM."""
    st.markdown(THEME_CSS, unsafe_allow_html=True)


def get_hero_svg_markup() -> str:
    """Return inline SVG representation of monochrome shield / agent trace node-graph."""
    svg = """<svg width="300" height="190" viewBox="0 0 300 190" fill="none" xmlns="http://www.w3.org/2000/svg">
<defs>
<linearGradient id="monoShieldFill" x1="150" y1="10" x2="150" y2="180" gradientUnits="userSpaceOnUse">
<stop offset="0%" stop-color="#FFFFFF" stop-opacity="0.25"/>
<stop offset="100%" stop-color="#E5E7EB" stop-opacity="0.10"/>
</linearGradient>
<linearGradient id="monoStroke" x1="50" y1="20" x2="250" y2="170" gradientUnits="userSpaceOnUse">
<stop offset="0%" stop-color="#FFFFFF" stop-opacity="0.8"/>
<stop offset="100%" stop-color="#9CA3AF" stop-opacity="0.5"/>
</linearGradient>
<filter id="softGlow" x="-20%" y="-20%" width="140%" height="140%">
<feGaussianBlur stdDeviation="3" result="blur"/>
<feComposite in="SourceGraphic" in2="blur" operator="over"/>
</filter>
</defs>
<circle cx="150" cy="90" r="70" fill="#171717" fill-opacity="0.04" filter="url(#softGlow)"/>
<path d="M150 16 C192 16, 230 26, 242 54 C242 114, 192 154, 150 174 C108 154, 58 114, 58 54 C70 26, 108 16, 150 16 Z" fill="url(#monoShieldFill)" stroke="url(#monoStroke)" stroke-width="1.8" stroke-linecap="round"/>
<path d="M150 88 Q118 70, 85 52" stroke="#171717" stroke-width="1.8" stroke-linecap="round"/>
<path d="M150 88 Q182 70, 215 52" stroke="#171717" stroke-width="1.8" stroke-linecap="round"/>
<path d="M150 88 Q115 110, 75 130" stroke="#737373" stroke-width="1.6" stroke-linecap="round"/>
<path d="M150 88 Q185 110, 225 130" stroke="#737373" stroke-width="1.6" stroke-linecap="round"/>
<circle cx="85" cy="52" r="14" fill="#FFFFFF" stroke="rgba(0,0,0,0.08)"/>
<circle cx="85" cy="52" r="5" fill="#171717"/>
<text x="85" y="38" font-family="'Plus Jakarta Sans', sans-serif" font-size="8.5" font-weight="700" fill="#171717" text-anchor="middle">SCOPE</text>
<circle cx="215" cy="52" r="14" fill="#FFFFFF" stroke="rgba(0,0,0,0.08)"/>
<circle cx="215" cy="52" r="5" fill="#171717"/>
<text x="215" y="38" font-family="'Plus Jakarta Sans', sans-serif" font-size="8.5" font-weight="700" fill="#171717" text-anchor="middle">TOOL</text>
<circle cx="75" cy="130" r="14" fill="#FFFFFF" stroke="rgba(0,0,0,0.08)"/>
<circle cx="75" cy="130" r="5" fill="#737373"/>
<text x="75" y="148" font-family="'Plus Jakarta Sans', sans-serif" font-size="8.5" font-weight="700" fill="#171717" text-anchor="middle">PII</text>
<circle cx="225" cy="130" r="14" fill="#FFFFFF" stroke="rgba(0,0,0,0.08)"/>
<circle cx="225" cy="130" r="5" fill="#737373"/>
<text x="225" y="148" font-family="'Plus Jakarta Sans', sans-serif" font-size="8.5" font-weight="700" fill="#171717" text-anchor="middle">NLI</text>
<circle cx="150" cy="88" r="20" fill="#171717" filter="url(#softGlow)"/>
<circle cx="150" cy="88" r="8" fill="#FFFFFF"/>
<text x="150" y="74" font-family="'Plus Jakarta Sans', sans-serif" font-size="9" font-weight="800" fill="#171717" text-anchor="middle">CORE</text>
</svg>"""
    return svg


def render_hero_panel() -> None:
    """Render the top hero panel with monochrome vector graphic."""
    svg_code = get_hero_svg_markup()
    html = f"""<div style="background: #FFFFFF; border-radius: 24px; padding: 24px 28px; border: 1px solid rgba(0,0,0,0.06); box-shadow: 0 10px 30px -4px rgba(0,0,0,0.04); display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px;">
<div>
<div style="display: inline-block; background: #F4F4F6; color: #171717; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; padding: 4px 12px; border-radius: 999px; margin-bottom: 10px;">
🛡️ Deterministic Multi-Control Governance
</div>
<div style="font-size: 24px; font-weight: 800; letter-spacing: -0.02em; color: #111111; margin-bottom: 8px;">
Operational Audit & Risk Explorer
</div>
<p style="font-size: 13.5px; color: #737373; margin: 0 0 14px 0; max-width: 580px; line-height: 1.5;">
Continuous verification of agent execution trajectories against task policies. Cross-examines tool authorization limits, sensitive PII redaction, and factual NLI entailment.
</p>
<div style="display: flex; gap: 8px; flex-wrap: wrap;">
<span style="background: #F8F8FA; border: 1px solid rgba(0,0,0,0.06); color: #171717; font-size: 11.5px; font-weight: 600; padding: 4px 12px; border-radius: 999px;">⚡ Tool Authorization</span>
<span style="background: #F8F8FA; border: 1px solid rgba(0,0,0,0.06); color: #171717; font-size: 11.5px; font-weight: 600; padding: 4px 12px; border-radius: 999px;">🔒 Context PII Redaction</span>
<span style="background: #F8F8FA; border: 1px solid rgba(0,0,0,0.06); color: #171717; font-size: 11.5px; font-weight: 600; padding: 4px 12px; border-radius: 999px;">📑 NLI Entailment</span>
<span style="background: #F8F8FA; border: 1px solid rgba(0,0,0,0.06); color: #171717; font-size: 11.5px; font-weight: 600; padding: 4px 12px; border-radius: 999px;">🛡️ Composite Risk</span>
</div>
</div>
<div>
{svg_code}
</div>
</div>"""
    st.markdown(html, unsafe_allow_html=True)
