---
name: Saffron & Slate
colors:
  surface: '#10131a'
  surface-dim: '#10131a'
  surface-bright: '#363941'
  surface-container-lowest: '#0b0e15'
  surface-container-low: '#191c23'
  surface-container: '#1d2027'
  surface-container-high: '#272a31'
  surface-container-highest: '#32353c'
  on-surface: '#e0e2ec'
  on-surface-variant: '#d7c3ae'
  inverse-surface: '#e0e2ec'
  inverse-on-surface: '#2d3038'
  outline: '#9f8e7a'
  outline-variant: '#524434'
  surface-tint: '#ffb957'
  primary: '#ffc77f'
  on-primary: '#462b00'
  primary-container: '#f5a524'
  on-primary-container: '#643f00'
  inverse-primary: '#835400'
  secondary: '#a8c8ff'
  on-secondary: '#003061'
  secondary-container: '#114784'
  on-secondary-container: '#8cb6fb'
  tertiary: '#98e1ab'
  on-tertiary: '#00391b'
  tertiary-container: '#7dc591'
  on-tertiary-container: '#00522a'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#ffddb5'
  primary-fixed-dim: '#ffb957'
  on-primary-fixed: '#2a1800'
  on-primary-fixed-variant: '#643f00'
  secondary-fixed: '#d5e3ff'
  secondary-fixed-dim: '#a8c8ff'
  on-secondary-fixed: '#001b3c'
  on-secondary-fixed-variant: '#114784'
  tertiary-fixed: '#a9f3bc'
  tertiary-fixed-dim: '#8ed7a1'
  on-tertiary-fixed: '#00210e'
  on-tertiary-fixed-variant: '#00522a'
  background: '#10131a'
  on-background: '#e0e2ec'
  surface-variant: '#32353c'
typography:
  headline-xl:
    fontFamily: Inter
    fontSize: 36px
    fontWeight: '600'
    lineHeight: 44px
  headline-xl-mobile:
    fontFamily: Inter
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 36px
  headline-lg:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  headline-sm:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
  label-md:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
  label-sm:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '600'
    lineHeight: 14px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1.5rem
  gutter-mobile: 1rem
  margin: 2rem
  margin-mobile: 1rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.75rem
  space-lg: 1rem
  space-xl: 1.5rem
---

## Brand & Style

This design system is tailored for an intelligent culinary discovery platform exploring Bangalore's vibrant dining scene through data-driven synthesis. The aesthetic reflects an analytical, focused, and quiet luxury demeanor: deep charcoal and slate backdrops balanced with a radiant warm saffron accent reminiscent of twilight dining, turmeric spice, and high-performance craft. 

The visual style blends **Modern Minimalist Utility** with **Crisp Tonal Layering**. It eschews photo-heavy clutter and sensory overload in favor of typography, clear geometric structure, and structured typographic monograms. The user experience evokes absolute clarity, speed, and trusted discernment—transforming dense urban culinary datasets into calm, actionable intelligence.

## Colors

The palette operates under a strict dark-mode-first framework, utilizing low-luminance slate surfaces to ensure visual comfort during extended browsing.

- **Base Canvas (`#0F1115`)**: Deep, low-reflection obsidian base representing ground zero.
- **Surface / Card Layer (`#171A21`)**: Medium-dark slate for base cards, navigation headers, and container panels.
- **Raised Surfaces / Inputs (`#1F232C`)**: Elevated interactive fields, segmented pill tracks, and input controls.
- **Structural Outlines (`#2A2F3A`)**: Subtle low-contrast perimeter strokes separating distinct visual areas without heavy visual noise.
- **Primary Accent (`#F5A524`)**: Warm saffron reserved strictly for primary actions, focus indicators, active segment fills, range sliders, and dynamic match highlights.
- **Functional Semantics**:
  - `Success` (`#81C995`): High match percentage, positive sentiment signals, and open venue status.
  - `Info` (`#8AB4F8`): Neighborhood tags, algorithmic metadata, and secondary telemetry.
  - `Warning` (`#FDD663`): Limited availability, peak rush hour indicators.
  - `Error` (`#F28B82`): Filter conflict states, API errors, closed venues.
- **Text Layers**:
  - `Primary` (`#E8EAED`): Primary headers, restaurant names, critical numbers.
  - `Secondary` (`#9AA0A6`): Metadata, distance calculations, cuisine categories, secondary labels.

## Typography

Typography relies entirely on **Inter**, capitalizing on its tall x-height, neutral geometric apertures, and unmatched clarity across digital screens. 

- **Display & Headlines**: Rendered in semi-bold (`600`) weights with tight letter-spacing (`-0.02em`) to provide an editorial, authoritative tone without becoming loud or decorative.
- **Body Text**: Tuned for maximum readability across deep dark canvases using regular (`400`) weight, standard tracking, and generous line-height ratios (1.45–1.5) to avoid eye fatigue.
- **Labels & Badges**: Set in medium (`500`) or semi-bold (`600`) weights with slight positive tracking (`+0.02em`) for small-scale identification, tabular data, and AI badge tags.

## Layout & Spacing

The layout employs a responsive 12-column fluid grid system bounded by a maximum content container of `1280px` to maintain comfortable eye scanning widths. 

- **Grid & Margins**:
  - **Desktop (≥1024px)**: 12-column grid, `24px` (`1.5rem`) gutters, `32px` (`2rem`) outer margin.
  - **Tablet (768px - 1023px)**: 8-column grid, `20px` (`1.25rem`) gutters, `24px` (`1.5rem`) outer margin.
  - **Mobile (<768px)**: 4-column fluid layout, `16px` (`1rem`) gutters, `16px` (`1rem`) outer margin.
- **Spatial Rhythm**:
  - Content components rely on an uncompromising `4px`/`8px` vertical base grid. 
  - Standard spacing between logical groups uses `1.5rem` (`24px`). Internal component padding favors generous breathing room (`space-md` to `space-lg`) to offset the dense data tables and listing items.

## Elevation & Depth

Visual hierarchy does not rely on heavy drop shadows or blurred glass layers. Instead, depth is constructed via **pure tonal stepping** coupled with crisp, low-contrast structural outlines:

1. **Canvas (Level 0 - `#0F1115`)**: Base window background.
2. **Container/Card (Level 1 - `#171A21`)**: Base container level. Framed by a 1px solid stroke of `#2A2F3A`. Zero drop shadow.
3. **Floating/Active (Level 2 - `#1F232C`)**: Active inputs, interactive elements, hovered cards, and dropdown flyouts. Framed with `#2A2F3A` and an optional ambient diffusion: `0 8px 24px -4px rgba(0, 0, 0, 0.45)`.
4. **Tooltips & Overlays (Level 3 - `#242934`)**: Slider value flags and context tooltips elevated above interactive planes with subtle directional shadow: `0 4px 12px rgba(0, 0, 0, 0.5)`.

## Shapes

The design system enforces a precise, systematic **12px (`0.75rem`) border radius** across primary containers, interactive cards, input fields, and segmented controls, translating to a balanced, contemporary feel that softens the analytical dark theme.

- **Primary Radius (`12px`)**: Used for cards, search surfaces, modal containers, and text fields.
- **Inner Child Radius (`8px`)**: Used for inner elements nested within `12px` parent containers (such as individual segmented control segments and sub-item highlights) to ensure concentric harmony.
- **Full Pill (`9999px`)**: Reserved for filter chips, action pills, dismiss tags, live tooltips, and AI match tags.
- **Circular Monograms (`50%` round)**: Strict circular containers reserved exclusively for restaurant entity icons.

## Components

### 1. Restaurant Monogram (No-Image Policy)
- **Geometry**: Strict `40px` or `48px` circle (`border-radius: 50%`).
- **Surface**: Subtle warm tint (`rgba(245, 165, 36, 0.08)`) or neutral slate (`#1F232C`) with a `1px` border of `#2A2F3A`.
- **Content**: 2-letter uppercase initials in `Inter SemiBold` using `#F5A524` or `#E8EAED`. No imagery, photographs, or illustrative icons.

### 2. Primary & Ghost Buttons
- **Primary Button**: Solid saffron `#F5A524`, text color `#0F1115` (`fontWeight: 600`), 12px border radius, `0 2px 8px rgba(245, 165, 36, 0.25)` resting glow. Focus ring: `2px` offset saffron outline.
- **Ghost/Secondary Button**: Background transparent or `#1F232C`, border `1px solid #2A2F3A`, text `#E8EAED`. Hover creates background shift to `#2A2F3A`.

### 3. Chips & Dismissibles
- **Geometry**: Full pill shape (`height: 32px`), padding `0 12px`.
- **States**:
  - *Inactive*: `#1F232C` background, `#9AA0A6` label, `1px solid #2A2F3A`.
  - *Active*: Border tinted `#F5A524`, background `rgba(245, 165, 36, 0.12)`, text `#F5A524`.
  - *Dismiss Icon*: Trailing `14px` cross icon with `#F5A524` fill on hover, removing the filter on trigger.

### 4. Segmented Control
- **Container**: Background `#1F232C`, `padding: 4px`, `border-radius: 12px`, border `1px solid #2A2F3A`.
- **Item**: `border-radius: 8px`, `padding: 6px 14px`, text `#9AA0A6`.
- **Selected Item**: Background `#F5A524`, text `#0F1115` (`fontWeight: 600`), smooth sliding transition (`200ms cubic-bezier(0.2, 0, 0, 1)`).

### 5. Range Slider with Value Badge
- **Track**: `4px` height, `#2A2F3A` background.
- **Filled Track**: `#F5A524`.
- **Thumb**: `18px` circle, background `#F5A524`, border `2px solid #0F1115`, shadow `0 0 0 4px rgba(245, 165, 36, 0.2)` on active drag.
- **Live Tooltip Badge**: Floating pill pinned directly above the thumb, background `#242934`, border `1px solid #2A2F3A`, text `#E8EAED` (`11px`, `fontWeight: 600`).

### 6. AI Explanation Badges
- **Visual Design**: Subtle horizontal pill with background `rgba(245, 165, 36, 0.08)`, border `1px solid rgba(245, 165, 36, 0.25)`.
- **Content**: Small leading sparkle glyph (`#F5A524`), followed by concise reasoning text (e.g., *"Top-rated for Craft Beer in Indiranagar"*), text color `#E8EAED`, label typography `body-sm`.

### 7. Form Inputs & Search Fields
- **Container**: Background `#1F232C`, `12px` border radius, `1px solid #2A2F3A`, text `#E8EAED`, placeholder `#9AA0A6`.
- **Focus State**: Border color `#F5A524`, box-shadow `0 0 0 1px #F5A524`.
- **Iconography**: Clean neutral search glyph left-aligned, right-aligned keyboard shortcut or clear indicator.

### 8. Restaurant Listing Cards
- **Container**: Surface `#171A21`, `12px` radius, `1px solid #2A2F3A`, padding `16px`.
- **Layout**: Top row monospaced or monogram emblem aligned with restaurant title, locality badge (`#8AB4F8`), and ratings badge (`#81C995`).
- **Middle Row**: AI narrative snippet formatted inside an AI Explanation Badge.
- **Footer**: Key cuisine tags, pricing indicator (e.g., `₹₹₹`), and real-time distance data in `#9AA0A6`.