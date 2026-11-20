# One improvement beyond the brief

## A browser app for quarterly licensing reviews

Adjoa uploads a candidate CSV, runs the recommendation for both release windows, and downloads the results in one ZIP. At the next review, she can open **Compare saved runs** in the same app and upload the earlier and later ZIPs. The app shows the two recommendations side by side and lists the bundles or standalone films that entered the shortlist, left it, or moved in rank.

The brief asks Adjoa to rerun the analysis on her own laptop, sometimes during a meeting. The app gives her one place to run a new list and see what changed since the last review. She can tell Kwame which titles are new negotiation leads and whether the overall advice changed without reading two workbooks line by line.

The comparison uses the results saved in each ZIP, so Adjoa can review earlier decisions even when the movie cache has changed. She only needs to keep the ZIP from each review. [Browser app instructions](../README.md#upload-a-list-in-the-browser)

In a check of the implemented app, we made two runs using the same saved movie data. The first used the sample list. The second removed *Spirited Away*, *Interstellar*, *Inception*, and *The Prestige*. That left four eligible standalones from 2000 onward (8 minus 4), below the five required for a firm comparison. The app showed that the newer result changed to insufficient evidence while the all-years result still favored standalones. It also showed which shortlist entries changed. [Comparison rule](03_questions.md#scoring-and-comparison)

Keep each download intact. The app checks the rankings workbook against the saved run record to catch accidental changes or mismatched files. The check cannot authenticate a download if both files have been edited together. The upload is used for the current run, while saved TMDB responses and lookup outcomes can be reused. [Saved report bundles ADR](03-adr/005-compare-saved-report-bundles.md)
