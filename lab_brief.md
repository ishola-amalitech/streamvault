Instructions
A client hands you a list of films under consideration for licensing and a decision worth $14M. Nobody hands you the data: you pull it yourself from a live public API, and it isn't clean.

The work is not "compute these numbers." It's deciding what the numbers should be, finding what's wrong with the source, and defending both to someone whose job depends on the answer.

Background
StreamVault is a streaming service that licenses older films from studios alongside its own productions, the back catalog. Studios sell two ways: a franchise arrives as a bundle (take all six Space Raider films or none), while standalone hits are priced one at a time.

Candidate list: 127 titles this year, assembled over about four years from three sources: Adjoa's evaluation tracker, a spreadsheet inherited from Kwame's predecessor, and a batch a studio's licensing desk emailed over. Nobody has gone through it properly.

Next year's list is expected to be closer to 500 titles.

Kwame's analyst, Adjoa, will re-run this analysis every quarter, on her own laptop, sometimes live in a meeting.

Yaw in Finance distrusts anything released before 2000 (inflation, currency reporting, how box office used to be reported) and will say so in the room.

Problem Statement
Kwame Boateng, VP of Content Acquisition, has $14M to commit at the board's licensing review on 31 October, and no evidence to commit it with. His team argues constantly about how to spend it: half think franchise bundles are the safer buy, built-in audience, people binge the series, the marketing writes itself; the other half think StreamVault overpays for the weak middle entries and would do better cherry-picking standalone hits. Nobody brings numbers.

The stakes are personal. Two years ago Kwame championed a trilogy bundle on instinct; it underperformed, and the board remembers. Last quarter StreamVault passed on a five-film bundle that a competitor picked up and is now promoting; he doesn't know whether that was a bullet dodged or a miss. He's been told, politely, that without evidence this cycle the money moves to originals.

He wants:

A recommendation he can defend in the room: franchise bundles or standalone hits, with the reasoning behind it.

A shortlist to negotiate from: his three strongest franchise targets and five strongest standalones, each with the reason it made the cut.

A read on which directors and lead actors reliably signal a title worth licensing; his negotiators use talent as a lever.

A one-paragraph deal note on the single strongest franchise candidate: what to pay for it relative to everything else, and the one number that most drove your view.

To be told plainly what you couldn't verify, and what that costs him. He'd rather hear it from you in October than from Finance in November.

Resources Given
id_list.csv: the candidate list, one column of TMDb movie ids, nothing else. You fetch everything yourself, live, from the public TMDb API: movie details (GET /movie/{id}) and credits (GET /movie/{id}/credits) for every title you use, both returned as nested JSON. Register your own free TMDb key. The data will contain problems this brief doesn't name; not everything that looks wrong is wrong.

Constraints
Present the franchise-versus-standalone comparison both ways, all years and 2000-onward, and if the recommendation changes between them, say so loudly rather than footnoting it.

The solution has to scale: next year's list is expected to be closer to 500 titles, and Adjoa will run it herself, on her own laptop, without you. It shouldn't mean starting over.

Kwame has no view on how you do any of this; the approach is yours to choose.

Kwame is not available for follow-up questions before the review. Where the brief doesn't settle something, decide it, and say what you decided.

Deliverables
Data diagnosis: every problem found, how you detected it, and what it does to Kwame's recommendation, ranked by risk. A full account of the candidate list itself: how many titles made your final analysis, where the rest went, and what that gap costs him.

Working analysis: runs top to bottom from a clean clone, no manual edits, and answers both time windows.

Decision notes: every judgement call you made where the brief left something open: what you assumed, why, and what it costs him if you're wrong. State what survives when Adjoa reruns this next year against 500 titles without you.

Client memo: one page, business language, no tool names or jargon. His recommendation, his shortlist, the two-window comparison, the deal note, and what you couldn't stand behind.

One improvement beyond the brief: justified in terms of what it's worth to Kwame or Adjoa.

Rubric
Your work is graded against these weighted criteria.

Criterion	Description	Weight
Analyze	What's Assessed: Data diagnosis · What "Good" Looks Like: Finds the problems that actually move the recommendation, quantifies their effect, and ranks them by risk. Not a flat list of everything untidy, or a fix applied to nothing broken.	20%
Apply	What's Assessed: Acquisition · What "Good" Looks Like: Pulls the full list without crashing or losing track of anything, without abusing a shared API; every id is accounted for and totals reconcile against what you were given.	20%
Apply / Create	What's Assessed: Analysis · What "Good" Looks Like: Nested responses turned into a sound analytical shape, the join proven not to drop or duplicate a film, results computed without looping over rows, and inside the client's time budget, measured.	20%
Evaluate	What's Assessed: Reasoning · What "Good" Looks Like: Every judgement call named, decided, and defended, with what it costs if you're wrong; rejected alternatives are real, and you can say what the recommendation looks like under them.	20%
Evaluate / Create	What's Assessed: What reaches the client · What "Good" Looks Like: A memo Kwame could act on without a follow-up meeting, with the caveats a negotiator needs, plus one improvement beyond the brief that genuinely helps him or Adjoa, reasoned in terms of their problem.