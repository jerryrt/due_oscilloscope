# Writing documents here

`docs/` carries what is **settled and will be needed again**. `CLAUDE.md`
has the split between git and issues; the row it does not spell out is
this one, and these are the rules for filling it.

## The rules

| rule | why |
|---|---|
| **General to detailed, top to bottom** | The first section is read most, so it should be the shortest. A reader who stops after one screen should still have the answer |
| **Detail lives in the code. Point at it** | A copied signature, file list or constant table drifts silently and nothing fails when it does. The tree cannot drift from itself |
| **State what is true, never how it changed** | "This section used to say five minutes" is the document keeping books on itself. That belongs in `git log`, which is durable and is where people look |
| **No issue numbers** | Issues carry what is being argued; `docs/` carries what is settled. A document that says "see #48" tells the reader the answer lives somewhere it does not |
| **Prefer a table** | A cell will not hold a sentence that is acquiring qualifications. The format does the editing |
| **Plain, short, accurate** | Check a claim against the tree before writing it. "Both tracks" was true once and there are three |

## Evidence is not bookkeeping

The distinction is easy to lose, and the rules above kill a document
that loses it in the wrong direction.

| keep - this is evidence for a rule | cut - this is bookkeeping about the document |
|---|---|
| "A guard that could not fail went green six times" | "This section used to claim five minutes" |
| A figure with its bench, commit and instrument | "Re-measured, because the table had drifted" |
| "The counters have lied", and the two cases | "584 collected became 587" |

A number that dates a **finding** is provenance and stays. A number that
dates the **document** is bookkeeping and goes.

## Shape

| prefer | over | because |
|---|---|---|
| a table | a bulleted list | two columns are usually already there: the claim, and what it cost to learn |
| a step column | a numbered list | order survives and the reason gets its own column |
| the command | the number it prints | a number written down is a number that rots |
| a name | a citation | `stream_port.h` outlives "see the framer issue" |

## The failure this prevents

A document written as a plan, then amended in place, becomes a
stratigraphy: finished work in future tense, findings wherever they
landed, and corrections layered over corrections. It reads as history
rather than as instruction, and the reader cannot tell which layer is
current.

The tell is a document that describes itself. When a paragraph explains
why an earlier paragraph was wrong, the rewrite is overdue.
