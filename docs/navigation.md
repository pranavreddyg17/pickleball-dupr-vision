# Navigation and information hierarchy

## Diagnosis

The old overview mixed retrospective video scores with future playing plans.
"Scored / Playing" required users to infer two unrelated calendar concepts.
A prominent average looked like a calibrated player rating; it is instead an
average of scored days from uploaded clips. A large username took precedence
over the actions people came to perform. Calendar and round-robin entry points
were duplicated and organized around implementation modules rather than tasks.

## Structure

- Analyze: session library, analysis entry, and a secondary Progress view.
- Events: upcoming sessions, calendar view, and saved round-robin events.
- Players: discovery, following, followers, and connections.
- Account: a persistent profile control, outside primary task navigation.

Reviews open with observations and replay. Breakdown contains score components,
coverage and scoring methodology. Organizer settings sit inside an event, apart
from its active matches. Existing sharing and authorization rules are unchanged.

Routes use URL fragments, preserving authenticated report and event deep links.
Browser navigation restores the destination rather than leaving the URL and view
out of sync. Mobile keeps the same three destinations in a bottom navigation bar.

## Score meaning

The profile average weights each scored day equally, excludes duplicate clips,
and uses one scoring version. It is useful for comparing similar recordings;
it is not a DUPR rating, a win probability, or a validated overall skill rating.
The interface explains this distinction instead of making the score the landing
page headline. The scores themselves are not changed by this redesign.

## References

- Apple Human Interface Guidelines, Tab bars:
  https://developer.apple.com/design/human-interface-guidelines/tab-bars
- Apple, Organize your features:
  https://developer.apple.com/tutorials/develop-in-swift/organize-your-features
- Nielsen Norman Group, Progressive Disclosure:
  https://www.nngroup.com/articles/progressive-disclosure/

These inform stable destinations and secondary detail placement. This is a
design interpretation, not an Apple-endorsed design or a completed user study.
