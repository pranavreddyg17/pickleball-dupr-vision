# Round robins

Open **Events -> New event -> Round robin**. Create an event using the venue picker, date/time controls, and game rules. Court labels are optional; the number of courts determines capacity. The organizer is not a player unless **I'm playing** is selected.

Organizers can use **Edit event** before generating the first round to change its venue, dates, title, or rules. Discard an unstarted first preview to edit those details. Once play begins, game rules and fixed-team membership are locked; court capacity and attendance can still change for future rounds.

## Running an event

1. Open Players to add guests by name or find existing members. Invite players with the joining link. The link requires sign-in and can be replaced by the organizer. An event supports up to 32 roster entries and eight courts.
2. Check in players who are present. Expected, resting, and withdrawn players are not scheduled. Add co-organizers through Find a member -> Add as -> Co-organizer; they need not play.
3. For fixed teams, give both partners the same team name. Each team must have exactly two players. Teams lock when the first preview is generated.
4. Generate a round and review the draw. Rotating-partner previews support player swaps, including available players resting that round. Discard a preview before changing attendance or courts.
5. Start the round. Players see their own assignment and can submit scores for their matches. A member of the opposing team confirms or disputes the score; an organizer can enter or resolve it directly. The original submitter can revise an unconfirmed score. Every accepted change is recorded.
6. Resolve all matches before generating another round. Unplayed matches and forfeits require an organizer and reason. The next round never silently abandons a pending result.
7. Add rotating-partner rounds while time permits, up to 50 per event. Fixed-team play ends when every team has met every other team; completed competitions do not silently acquire extra ranked rematches.
8. Open the event's Settings tab to finish after resolving matches. Results become read-only. Finished events remain accessible from Events -> Your events.

## Rules and standings

- Games to 11, 15, or 21 support win-by-one or win-by-two validation. Side-out and rally are rule labels for on-court scoring; the app records final scores, not individual rally scoring or server positions.
- Timed games support 10- or 15-minute presets in the UI. The clock runs from the server's recorded start timestamp. After time expires, finish the rally and enter the score; equal scores count as draws. Timers do not auto-submit results.
- Rotating partners rank by `(wins + draws / 2) / games`, then average point differential from scored games. Fixed teams rank by wins plus half a win per draw, then average point differential. Remaining ties share a place. These are published recreational rules, not an implementation of sanctioned tournament regulations.
- The minimum qualifying game count is chosen at creation. Players or teams below it are provisional. Games played is always visible. A forfeit counts toward the win/loss record and qualifying count but contributes no invented points or differential. Unplayed matches and rests do not affect standings.
- Pausing prevents new rounds from being generated or started. It does not interrupt active games or stop their clocks. Court and attendance changes made during play affect future rounds; active assignments remain intact.
- Scores do not change Vision scores or official DUPR ratings. There is no automatic DUPR submission.

## Implementation

`competition.py` owns event membership, role checks, lifecycle rules, score validation, and API commands. It exposes an authenticated router under `/api/competitions`. `round_robin.py` schedules on CPU with OR-Tools CP-SAT. `competition.js` and `competition.css` contain the event interface.

Competition metadata links one-to-one to an existing calendar event. Separate tables store organizers, players, rounds, matches, command receipts, and audit entries. Membership grants access even when a member does not follow the organizer; personal calendar privacy rules continue to apply to ordinary plans. Calendar deletion/edit routes cannot silently remove a competition or its history.

Each mutation runs in a database transaction, checks the event version, and requires a request UUID. A replay of the same UUID and payload returns current state without repeating the action. Reusing a UUID for different input is rejected. An old event version returns 409. Two concurrent round-generation requests cannot create two rounds. The UI retains unsent score payloads, including their UUID, in local storage per user/event/match and supports explicit retry. A stale edit refreshes the event and requires another submission.

The event view polls every five seconds while visible and not editing. A changed version triggers a redraw. No polling occurs while a score form is open. Score drafts survive closing and reopening the form; full offline event operation is not implemented.

Rotating play prioritizes fewer games and least recent participation before optimizing partner/opponent repetition. The solver has a one-second search budget; if it returns no solution in time, a valid assignment from the same participation-prioritized roster is used. The fallback preserves court capacity and prevents duplicate players, but may repeat partners. Fixed-team play chooses a maximum set of unplayed pairings that fits the available courts. There is no guarantee of globally optimal partner diversity over an unknown number of future rounds.

Measured locally over five successive rounds per roster size: scheduling took at most 0.003 s for 4 players, 0.011 s for 9, 0.053 s for 13, 0.266 s for 24, and 0.519 s for 32. These are development-machine measurements, not hosted latency guarantees. SQLite serializes writes; use PostgreSQL with event-row locking and run optimization outside the write transaction before scaling concurrent events across servers.

## Validation and scope

Tests cover 13-player rest balance, fixed-team opponent coverage, host-only and co-organizer roles, private invitation access, late additions, duplicate commands, concurrent generation, stale versions, disputes, forfeits, timed draws, and completed-event locking. Browser tests cover creation, guest check-in, scores, extra rounds, invitation joining, retained network-failure drafts, completion, and 320-1440 px layouts.

This release uses synchronized rounds. Continuous court-by-court dispatch, ranking-aware matchmaking, divisions, recurring leagues, waitlists, payments, spectator links, native push notifications, tournament brackets, and post-completion reopening are not implemented. They should extend this event model rather than share the video-analysis worker.

Research: [Swish recreational play](https://swishsportsapp.com/recreational-play/), [Pickleheads round robins](https://www.pickleheads.com/round-robin), [OR-Tools](https://github.com/google/or-tools), [social golfers problem](https://www.csplib.org/Problems/prob010/), [asynchronous round-robin scheduling](https://arxiv.org/abs/1804.04504).
