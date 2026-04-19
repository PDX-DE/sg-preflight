# Unleashed Recomp Reference

This note records how the local Unleashed Recomp source is meant to be used in this repo's workflow.

## Role of the reference

The Unleashed Recomp codebase is a local visual/interation reference for a future desktop operator shell.

It is not:

- the product identity
- a license to theme the current SG operator surface as a game menu
- content that should be committed into `sg-preflight`

## Intended use

Use the reference to study:

- container framing
- activity accents
- title hierarchy
- category/tab rhythm
- bottom button-guide rhythm
- static/noise framing ideas

The current desktop shell now applies a translated subset of those patterns in Qt code:

- scanline header bars
- amber title + activity-square rhythm
- category-tab action strip
- grid-framed panels
- static-framed evidence panel
- bottom guide-button strip

The native C++ shell now applies a stronger and more direct pass of the same source ideas:

- animated title-square motion
- deeper container framing instead of flat ImGui children
- category-tab highlight motion driven by the same style of timing math as `DrawCategories`
- a fixed 1280x720 virtual menu canvas instead of a generic resizable table layout
- side-aligned bottom guide placement modeled after `ButtonGuide::Draw`
- selection-card treatment for operator lists
- local cue hooks mapped to cursor / confirm / error actions

The current native port is now intentionally closer to the real source structure:

- `DrawTitle`-style title timing and square animation
- `DrawContainer`-style panel growth and outline timing
- `DrawCategories`-style category strip motion and highlight interpolation
- `ButtonGuide::Draw`-style left/right guide layout at the bottom rail
- runtime DDS-backed chrome from the local `UnleashedRecompResources` bundle:
  - `images/common/general_window.dds`
  - `images/common/select.dds`
  - `images/common/light.dds`
  - `images/options_menu/options_static.dds`
  - `images/options_menu/options_static_flash.dds`

What is still not copied wholesale:

- upstream textures
- fonts as an upstream prebuilt atlas snapshot
- sounds
- menu/game-specific assets or strings

## Current font decision

The local resource pack includes `im_font_atlas.bin` and `im_font_atlas.dds`, but the upstream project loads those through a custom `ImFontAtlasSnapshot` path tied to its generated snapshot data and exact ImGui layout.

For `sg-preflight`, the current safer path is:

- use the real DDS chrome textures now
- use direct OTF loading for the downloaded Seurat / New Rodin fonts when available
- defer atlas-snapshot consumption until there is a concrete reason to port that exact font-snapshot pipeline too

## Repository rule

- keep the reference source external or untracked
- do not commit that source tree into `sg-preflight`
- extract principles, not wholesale imitation
- keep the source tree untracked and outside commits even when the live desktop shell is using translated reference ideas

## Product rule

The current browser UI remains SG QA / evidence / handoff tooling.

If a future desktop shell is built, that is the correct place to apply stronger reference-driven interaction language.
