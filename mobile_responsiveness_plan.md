# Mobile Web Readiness Plan

## Goals
- Deliver full chat and voice functionality on handheld browsers without feature degradation.
- Ensure layout adapts smoothly between desktop, tablet, and handset breakpoints (1280px, 1024px, 768px, 480px, 360px).
- Preserve accessibility (ARIA labels, focus order, readable font sizes) across breakpoints.

## Workstream Overview
1. **Audit & Requirements**
   - Capture screenshots on baseline devices (iPhone 14/SE, Pixel 7, iPad Mini) to highlight broken regions (top bar overflow, avatar panel width, composer visibility).
   - Inventory interactive flows (chat send, theme toggle, voice redirect, auth) and mark any that fail on touch screens.

2. **Layout System Updates**
   - Introduce utility classes for header actions, stacked panes, and modal sizing instead of inline styles.
   - Expand CSS grid/flex layouts with tablet (=980), phablet (=768), phone (=480), and compact (=360) treatments.
   - Collapse the dual-column layout to single column below 980px and reflow controls (icons, condensed buttons) below 480px.

3. **Component Adaptations**
   - Top bar: convert "Sign in" to icon+label pair on compact widths, keep voice/theme icons accessible, and expose overflow menu for future items.
   - Avatar pane: constrain video to available width, drop sticky positioning on small viewports, and ensure emotion card stacks below.
   - Composer: pin to bottom with safe-area padding, grow textarea on input, keep send button reachable for touch.
   - Voice page: apply the same breakpoints to mic button, status text, and back navigation.

4. **Touch & Performance Enhancements**
   - Increase hit targets to =44px, add `touch-action` hints, debounce scroll-to-bottom for long transcripts.
   - Verify media autoplay policies (muted video, audio playback via user gestures) continue to work on iOS/Android.

5. **Testing & Verification**
   - Automated: add Playwright viewport suite (1280, 1024, 768, 480, 360) to capture layout screenshots and basic flow (send message stub).
   - Unit-level: lint HTML for `<meta name="viewport">`, assert presence of responsive media queries, and snapshot critical CSS blocks.
   - Manual: smoke test on Safari iOS, Chrome Android, desktop responsive mode; validate orientation changes and PWA install banners (future).

6. **Rollout**
   - Behind the scenes flag in staging, gather feedback, then promote to production once telemetry (Core Web Vitals, UI errors) meets baseline.

