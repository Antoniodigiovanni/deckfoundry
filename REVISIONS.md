# Incremental revision CLI

`src/project.py` manages local HTML-source projects without a server or database. Standard operations (from the engine root):

```
.venv/bin/python src/project.py init projects/NAME input.html --deck input.pptx
.venv/bin/python src/project.py build projects/NAME
.venv/bin/python src/project.py inspect projects/NAME
.venv/bin/python src/project.py inspect projects/NAME --slide 8
.venv/bin/python src/project.py patch projects/NAME patch.json
.venv/bin/python src/project.py build projects/NAME
```

A patch is `{"base":"v0001","message":"Update status","ops":[{"slide":8,"old":"exact old source literal","new":"new source literal"}]}`. Old must match exactly once in that slide. Stale bases and no-match patches fail without advancing the current version. For insertion/reordering, global CSS, or PPTX-authority edits, use a separate future migration path; those are not supported by this CLI.

Each `versions/vNNNN/` preserves source.html, index.json, changes.json, patch.json (when applicable), deck.pptx, html-source/spec.json, render/deck.pdf and slide PNGs, validation.json, regression.json and review.json. Builds may rerun in the same version; prior versions are not modified by new patches. project.json points to latest source, not approved output. If building fails, repair/rebuild that version; do not present it as delivered.

Token efficiency: read the title index then just requested slides. Use compact exact-match patch payloads rather than retransmitting the deck. Local full rendering remains mandatory; visually review changed slides and the contact sheet when unchanged geometry regression passes. If no baseline or global changes exist, inspect all slides. Neither model tokens nor API costs have been benchmarked.

Regression checks compare untouched source fragments and extracted text, geometry, styling and notes. They do not certify pixel-perfect equivalence, PowerPoint compatibility or factual accuracy. Templates and project content are excluded from Git by default. This CLI is for serial personal use, not concurrent writes.

Execution verification: tests exercise baseline build, exact targeted patch, second build with unchanged-slide geometry regression, stale-base rejection, match failure, and retained original source. Run `.venv/bin/python -m pytest tests -q`.
